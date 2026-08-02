"""Occupancy clouds — the top-N most likely CONFIGURATIONS of an oxDNA ensemble.

The flexibility map (:func:`backend.core.oxdna_health.production_rmsf`) reports one
mean structure plus a per-nucleotide spread.  For a bistable object that is the wrong
estimator: a plate alternating between the two saddle senses of a hyperbolic paraboloid
has a MEAN that is flat — a shape it never occupies.  RMSF draws that fictitious flat
mean and paints high fluctuation at the corners, telling you something moves but not
*what states it moves between*.

This module answers the other question.  Frames (already PBC-unwrapped and Kabsch-aligned
upstream) are projected onto their dominant collective modes by PCA, clustered in that
mode space, and each cluster contributes its MEDOID — a real frame — as a representative
configuration, with a population weight.

Three invariants, each of which cost a measurement to learn:

**1. The representative is a medoid, never a within-cluster average.**  Averaging
positions collapses bond lengths (measured -26 %/-67 % vs -1.8 %/+0.9 % per-frame on the
strain work; see ``memory/project_md_viz_tools.md``).  A cluster mean would be exactly as
physically unreal as the flat RMSF mean this module exists to replace.  The medoid is a
real frame by construction.

**2. Separation is NOT switching.**  A monotone DRIFT along one collective mode gets cut
in half by k-means and scores a high silhouette while never revisiting a state.  Measured
on ``exp35_.../oxdna_jobs/14b896dab3c2``: silhouette +0.58 at k=2, but the label sequence
was ``1111111111111111111111111 0000000000000000000000000`` — exactly ONE transition, PC1
lag-1 autocorrelation +1.000.  Those two "states" were "early in the run" and "late in the
run".  Reporting them as two configurations with 50/50 populations would have been a
confident lie.  So a multimodal verdict additionally requires RECURRENCE: every retained
state must be entered at least :data:`_OCC_MIN_VISITS` times.  Otherwise the verdict is
``"drift"`` and the caller must not speak of populations.

**3. Unimodal is a legitimate answer.**  A rigid, well-designed origami *is* unimodal.
Manufacturing two states out of one Gaussian basin is worse than drawing nothing, so below
:data:`_OCC_SILHOUETTE_MIN` this returns k=1 and says the flexibility map is the right view.

Populations carry autocorrelation-aware error bars via
:func:`backend.core.oxdna_health.twist_series_stats` — frames are not independent, and a
naive ``sqrt(p(1-p)/N)`` overstates confidence by an order of magnitude when the states
interconvert slowly.

Layer 3 (Physical / display-only).  Nothing here is ever written back to topology.

Private helpers are imported from :mod:`backend.core.oxdna_health` deliberately, rather
than duplicated — the same cross-module reuse ``backend/api/routes_oxdna_metrics.py``
already does with ``routes_oxdna``'s helpers.  Sharing ``_aligned_downsampled_frames``
also shares its ``_ALIGNED_CACHE``, so an occupancy request for a job whose trajectory has
already been scrubbed costs linear algebra rather than a re-parse.
"""

from __future__ import annotations

import numpy as np

from backend.core.occupancy_core import (  # noqa: F401  (re-exported for callers/tests)
    OCCUPANCY_PRELIM_NEFF,
    _OCC_MIN_BP_COLUMNS,
    _OCC_MIN_FRAMES,
    _OCC_SILHOUETTE_MIN,
    _OCC_MIN_VISITS,
    _selection_sig,
    _superpose_on_subset,
    occupancy_clusters,
    occupancy_confidence,
    resolve_selection_keys,
    state_recurrence,
)
from backend.core.oxdna_health import (
    _STRAIN_FRAME_REJECT_FRAC,
    _aligned_cache_key,
    _aligned_downsampled_frames,
    _fene_violation_fraction,
    _flatten_cg_frame,
    _strain_index,
)
from backend.physics.oxdna_interface import oxdna_backbone_sites


# ── Scope: which nucleotides the clustering is allowed to see ─────────────────────
def occupancy_features(frames, keys, design, *, basis: str = "nt", selection=None):
    """Build the ``(F, D)`` feature matrix from aligned per-nucleotide frame dicts.

    ``basis="nt"`` uses every nucleotide's backbone site — the same atom set the
    flexibility map uses, so the two views describe the same object.
    ``basis="bp"`` uses the midpoint of each designed Watson-Crick pair, which sits
    essentially on the duplex axis.  That rejects two things ``"nt"`` keeps: the ~10.5-bp
    helical-phase orbit of the backbone site about the axis, and every unpaired
    nucleotide (overhangs, ssDNA loops, frayed termini), whose RMSF is several times the
    duplex value.  Since PCA maximises VARIANCE, those can outweigh a global shape mode
    and bury it.  ``"bp"`` is the sharper instrument; ``"nt"`` is the comparable one.

    Frames whose bonded-neighbour distances leave the FENE window are DROPPED, not
    clustered.  Late frames of long or resumed runs get torn by the PBC unwrap (violation
    fraction measured rising 0.0000 → 0.3861 across resumes).  A torn frame carries
    box-scale bonds, making it maximally distant from every real frame — k-means would
    hand it its own cluster and this module would render it as a "configuration".

    Returns ``(X, feature_keys, kept, basis_used)``.  ``kept`` lists the indices INTO
    ``frames`` that survived the gate, so the caller can map a medoid row back to its real
    frame without re-deriving the rejections.  ``basis_used`` is the basis ACTUALLY used —
    a construct with fewer than :data:`_OCC_MIN_BP_COLUMNS` duplex columns has no duplex
    axis worth speaking of and falls back to ``"nt"``.  That fallback is returned rather
    than applied silently, so a payload can never claim ``basis="bp"`` while carrying
    per-nucleotide data.

    ``X`` rows are in composite frame order; that ordering is load-bearing for the
    recurrence test in :func:`occupancy_clusters`.
    """
    if basis not in ("nt", "bp"):
        raise ValueError(f"basis must be 'nt' or 'bp', got {basis!r}")

    key_list = list(keys)
    # The FENE gate stays on the WHOLE structure even for a scoped run: a tear anywhere
    # means the PBC unwrap failed, which invalidates the frame's alignment and therefore
    # the selected region's coordinates too.
    ia_bb, ib_bb = _strain_index(design, key_list, "backbone")

    scoped = resolve_selection_keys(design, key_list, selection)
    if selection and not scoped:
        raise ValueError("the selection matched no nucleotides")
    is_scoped = bool(selection) and len(scoped) < len(key_list)
    if basis == "bp":
        ia_wc, ib_wc = _strain_index(design, key_list, "wc")
        if len(ia_wc) < _OCC_MIN_BP_COLUMNS:
            basis = "nt"

    # Index into whatever the basis produces: nucleotide rows for "nt", duplex columns
    # for "bp" (a column is selected when EITHER of its two strands was picked).
    sel_idx = None
    if is_scoped:
        want = set(scoped)
        if basis == "nt":
            sel_idx = [i for i, k in enumerate(key_list) if k in want]
        else:
            sel_idx = [c for c, (a, b) in enumerate(zip(ia_wc, ib_wc))
                       if key_list[a] in want or key_list[b] in want]
        if not sel_idx:
            raise ValueError("the selection matched no nucleotides in this basis")

    rows: list[np.ndarray] = []
    kept: list[int] = []
    for i, fr in enumerate(frames):
        try:
            cm = np.array([fr[k]["backbone_position"] for k in key_list], dtype=float)
            a1 = np.array([fr[k]["a1"] for k in key_list], dtype=float)
            a3 = np.array([fr[k]["a3"] for k in key_list], dtype=float)
        except KeyError:
            continue                        # a half-written frame missing a nucleotide
        if len(ia_bb) and _fene_violation_fraction(cm, a1, a3, ia_bb, ib_bb) > _STRAIN_FRAME_REJECT_FRAC:
            continue
        sites = oxdna_backbone_sites(cm, a1, a3)
        if basis == "nt":
            v = sites[sel_idx] if sel_idx is not None else sites
        else:
            mid = 0.5 * (sites[ia_wc] + sites[ib_wc])
            v = mid[sel_idx] if sel_idx is not None else mid
        rows.append(np.asarray(v, dtype=float).ravel())
        kept.append(i)

    if basis == "nt":
        feature_keys = [key_list[i] for i in sel_idx] if sel_idx is not None else key_list
    else:
        cols = [key_list[i] for i in ia_wc]
        feature_keys = [cols[i] for i in sel_idx] if sel_idx is not None else cols
    if not rows:
        return np.zeros((0, 0)), feature_keys, [], basis
    return np.array(rows, dtype=float), feature_keys, kept, basis


# ── Clustering primitives ─────────────────────────────────────────────────────────
def _sampling_indices(out_stages) -> list[int]:
    """Composite indices belonging to production/field stages, seed frame excluded.

    Two traps live here, both silent:

    * The lineage stage list includes relaxation stages. Those are a transient, not an
      equilibrium sample, and including them guarantees a spurious "drift" split.
    * ``_aligned_downsampled_frames`` PREPENDS the design-reference seed at composite
      index 0 of the first non-empty stage. For a field/production child job that index
      is the design pose, not a sampled configuration — at F ≈ 60 it steals a cluster.
    """
    keep: list[int] = []
    at = 0
    for st in out_stages:
        n = int(st.get("n_frames", 0))
        if st.get("kind") in ("production", "field"):
            keep.extend(range(at, at + n))
        at += n
    if keep and keep[0] == 0:
        keep = keep[1:]
    return keep


def production_occupancy(design, stages, reference_conf_path, *, max_frames: int = 200,
                         n_clusters: int = 0, method: str = "pca", basis: str = "nt",
                         align: bool = True, progress=None, selection=None,
                         n_trailing_extra: int = 0,
                         trailing_extra_strand_length: int = 0) -> dict:
    """Occupancy states for a job's sampling stages — the route payload.

    ``max_frames``/``copies`` must match what ``/trajectory`` passes (200 / True) for the
    shared ``_ALIGNED_CACHE`` to hit; a different budget silently re-reads the trajectory.

    Emits ``keys`` and each medoid ``frame`` in exactly ``composite_trajectory``'s wire
    shape, so the frontend reuses ``framesToUpdates`` with no new mapping code.
    """
    if method != "pca":
        raise ValueError("method must be 'pca'")

    key_list, ordered, out_stages, _markers = _aligned_downsampled_frames(
        design, stages, reference_conf_path, max_frames, copies=True,
        progress=progress, align=align, n_trailing_extra=n_trailing_extra,
        trailing_extra_strand_length=trailing_extra_strand_length)

    if not ordered:
        return {"ready": False, "reason": "sampling starting — no frames yet"}

    idx = _sampling_indices(out_stages)
    if not idx:
        return {"ready": False, "reason": "no production or field run yet"}

    samples = [ordered[i] for i in idx]
    try:
        X, feature_keys, kept_rows, basis_used = occupancy_features(
            samples, key_list, design, basis=basis, selection=selection)
    except ValueError as e:
        return {"ready": False, "reason": str(e)}
    n_torn = len(samples) - len(kept_rows)
    if X.shape[0] < _OCC_MIN_FRAMES:
        return {"ready": False,
                "reason": f"need at least {_OCC_MIN_FRAMES} frames to cluster (have {int(X.shape[0])})",
                "n_frames": int(X.shape[0]), "n_frames_torn": n_torn}

    # Row r of X is sample kept_rows[r], which is composite frame idx[kept_rows[r]].
    kept = [idx[r] for r in kept_rows]

    res = occupancy_clusters(X, n_clusters=n_clusters)
    if not res.get("ready"):
        res["n_frames_torn"] = n_torn
        return res

    res["method"] = method
    res["basis"] = basis_used           # what was actually used, not what was asked for
    res["basis_requested"] = basis
    res["scoped"] = bool(selection) and len(feature_keys) < len(key_list)
    res["n_selected"] = len(feature_keys)
    res["n_total"] = len(key_list)
    res["n_frames_total"] = len(ordered)
    res["n_frames_torn"] = n_torn
    res["keys"] = [list(k) for k in key_list]
    for cl in res["clusters"]:
        composite = kept[cl["medoid_index"]]
        cl["medoid_frame"] = int(composite)
        cl["frames"] = [int(kept[r]) for r in cl["frames"]]
        cl["frame"] = _flatten_cg_frame(ordered[composite], key_list)
    return res


def production_occupancy_cached(design, stages, reference_conf_path, *, max_frames: int = 200,
                                n_clusters: int = 0, method: str = "pca", basis: str = "nt",
                                align: bool = True, progress=None, refetch: bool = False,
                                selection=None,
                                n_trailing_extra: int = 0,
                                trailing_extra_strand_length: int = 0) -> dict:
    """LRU over :func:`production_occupancy`, keyed on the full parameter set.

    The ``_aligned_cache_key`` component carries each trajectory's size+mtime, so a
    GROWING trajectory self-invalidates — the same property ``production_rmsf_cached``
    relies on.
    """
    global _OCCUPANCY_CACHE
    from collections import OrderedDict

    if _OCCUPANCY_CACHE is None:
        _OCCUPANCY_CACHE = OrderedDict()

    key = (_aligned_cache_key(stages, reference_conf_path, max_frames, True),
           bool(align), int(n_trailing_extra), int(trailing_extra_strand_length),
           int(n_clusters), str(method), str(basis), _selection_sig(selection))

    if refetch:
        _OCCUPANCY_CACHE.pop(key, None)
    else:
        hit = _OCCUPANCY_CACHE.get(key)
        if hit is not None:
            try:
                _OCCUPANCY_CACHE.move_to_end(key)
            except KeyError:
                pass
            return hit

    res = production_occupancy(
        design, stages, reference_conf_path, max_frames=max_frames, n_clusters=n_clusters,
        method=method, basis=basis, align=align, progress=progress, selection=selection,
        n_trailing_extra=n_trailing_extra,
        trailing_extra_strand_length=trailing_extra_strand_length)

    _OCCUPANCY_CACHE[key] = res
    while len(_OCCUPANCY_CACHE) > _OCCUPANCY_CACHE_MAX:
        _OCCUPANCY_CACHE.popitem(last=False)
    return res


def occupancy_cache_clear() -> None:
    """Drop every cached occupancy result (tests, and a design edit)."""
    global _OCCUPANCY_CACHE
    _OCCUPANCY_CACHE = None
#: Parameter-keyed LRU over production_occupancy. Module-level so a re-toggle of the
#: same view is free; the key carries each trajectory's size+mtime so a growing run
#: self-invalidates.
_OCCUPANCY_CACHE = None
_OCCUPANCY_CACHE_MAX = 6
