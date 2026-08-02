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

from backend.core.oxdna_health import (
    _STRAIN_FRAME_REJECT_FRAC,
    _aligned_cache_key,
    _aligned_downsampled_frames,
    _fene_violation_fraction,
    _flatten_cg_frame,
    _strain_index,
    twist_series_stats,
)
from backend.physics.oxdna_interface import oxdna_backbone_sites

# ── Tunables ──────────────────────────────────────────────────────────────────────
_OCC_SEED = 0                  # fixed → deterministic clustering (the tests rely on it)
_OCC_RESTARTS = 5              # kmeans2 does no restarts of its own
_OCC_KMAX = 6
_OCC_MIN_FRAMES = 20           # below this, clustering is not meaningful
_OCC_VAR_TARGET = 0.90         # cumulative variance retained by the kept PCs
_OCC_MAX_PCS = 10
_OCC_SILHOUETTE_MIN = 0.25     # below → unimodal (invariant 3)
_OCC_MIN_VISITS = 2            # each state must be ENTERED this many times (invariant 2)
_OCC_MIN_BP_COLUMNS = 10       # below this, "bp" basis is meaningless → fall back to "nt"

# n_eff below which populations are flagged preliminary. At p=0.5 the relative error
# sqrt(p(1-p)/N_eff)/p is 0.20 here — the same "one significant figure" threshold
# RMSF_PRELIM_FRAMES encodes for the flexibility map.
OCCUPANCY_PRELIM_NEFF = 25.0

_OCCUPANCY_CACHE = None
_OCCUPANCY_CACHE_MAX = 6


# ── Feature vectors ───────────────────────────────────────────────────────────────
def occupancy_features(frames, keys, design, *, basis: str = "nt"):
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
    ia_bb, ib_bb = _strain_index(design, key_list, "backbone")
    if basis == "bp":
        ia_wc, ib_wc = _strain_index(design, key_list, "wc")
        if len(ia_wc) < _OCC_MIN_BP_COLUMNS:
            basis = "nt"

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
        v = sites if basis == "nt" else 0.5 * (sites[ia_wc] + sites[ib_wc])
        rows.append(np.asarray(v, dtype=float).ravel())
        kept.append(i)

    feature_keys = key_list if basis == "nt" else [key_list[i] for i in ia_wc]
    if not rows:
        return np.zeros((0, 0)), feature_keys, [], basis
    return np.array(rows, dtype=float), feature_keys, kept, basis


# ── Clustering primitives ─────────────────────────────────────────────────────────
def _pca_scores(X, *, var_target: float = _OCC_VAR_TARGET):
    """Truncated PC scores via the Gram trick.

    ``F`` (≤ a few hundred frames) is far smaller than ``D`` (3 × nucleotides ≈ 10^4), so
    eigendecomposing the ``F×F`` Gram matrix is both cheaper and better conditioned than
    an SVD of the wide matrix — and its eigenvectors ARE the scores, so the loadings are
    never needed.

    Centring here is for the PCA only.  It never touches the coordinates that get
    rendered: those come from the untouched frame dict of the medoid.

    Note the frames arrive Kabsch-aligned to the DESIGN reference and are deliberately not
    re-aligned to the ensemble mean.  A second alignment would sharpen the modes slightly
    but would put the medoids in a different pose from every other overlay
    (``/display``, ``/rmsf``, ``/trajectory``), which is the one thing they must share.
    """
    Xc = X - X.mean(axis=0)
    w, V = np.linalg.eigh(Xc @ Xc.T)
    w = np.clip(w[::-1], 0.0, None)
    V = V[:, ::-1]
    total = float(w.sum())
    if total <= 0.0:                        # every frame identical
        return np.zeros((X.shape[0], 2)), np.zeros(w.size), 2
    var = w / total
    n_pcs = int(np.clip(np.searchsorted(np.cumsum(var), var_target) + 1, 2, min(_OCC_MAX_PCS, max(2, X.shape[0] - 1))))
    scores = V[:, :n_pcs] * np.sqrt(w[:n_pcs])
    return scores, var, n_pcs


def _silhouette(D, labels) -> float:
    """Mean silhouette over a precomputed distance matrix. Singletons score 0."""
    uniq = np.unique(labels)
    if uniq.size < 2:
        return -1.0
    s = np.zeros(labels.size, dtype=float)
    for i in range(labels.size):
        same = labels == labels[i]
        n_same = int(same.sum()) - 1
        if n_same <= 0:
            continue
        a = float(D[i, same].sum()) / n_same
        b = min(float(D[i, labels == c].mean()) for c in uniq if c != labels[i])
        denom = max(a, b)
        s[i] = 0.0 if denom <= 0 else (b - a) / denom
    return float(s.mean())


def _kmeans_best(scores, k, *, seed=_OCC_SEED, restarts=_OCC_RESTARTS):
    """k-means with explicit restarts, keeping the lowest inertia. Deterministic."""
    from scipy.cluster.vq import ClusterError, kmeans2

    best = None
    for r in range(restarts):
        try:
            cent, lab = kmeans2(scores, k, minit="++",
                                rng=np.random.default_rng(seed + r), missing="raise")
        except ClusterError:
            continue                        # an empty cluster — this restart failed
        inertia = float(((scores - cent[lab]) ** 2).sum())
        if best is None or inertia < best[0]:
            best = (inertia, np.asarray(lab, dtype=int))
    return (None, None) if best is None else (best[1], best[0])


def state_recurrence(labels, k: int) -> dict:
    """Does the trajectory REVISIT each state, or does it pass through once?

    This is the discriminator a silhouette cannot make.  Cutting a monotone drift in half
    yields two tight, well-separated clusters and a high silhouette — but each "state" is
    entered exactly once, and calling their frame counts "populations" is meaningless.
    Genuine bistability recurs: the object leaves a state and comes back.

    Returns ``{transitions, visits, min_visits, recurrent}`` where ``visits[c]`` counts
    maximal contiguous runs of label ``c`` in composite frame order.
    """
    lab = np.asarray(labels, dtype=int)
    if lab.size == 0:
        return {"transitions": 0, "visits": [], "min_visits": 0, "recurrent": False}
    visits = [0] * k
    prev = None
    for v in lab:
        if v != prev:
            visits[int(v)] += 1
        prev = v
    transitions = int((np.diff(lab) != 0).sum())
    min_visits = min(visits) if visits else 0
    return {"transitions": transitions, "visits": visits,
            "min_visits": int(min_visits),
            "recurrent": bool(min_visits >= _OCC_MIN_VISITS)}


def occupancy_confidence(n_frames: int, n_eff: float) -> dict:
    """Sampling confidence in the POPULATIONS (not the shapes).

    ``rel_error`` is the relative error of a p=0.5 population at this effective sample
    size.  Mirrors :func:`backend.core.oxdna_health.rmsf_confidence`'s contract.
    """
    n_eff = float(max(n_eff, 1e-9))
    rel = float(np.sqrt(0.25 / n_eff) / 0.5)
    return {"n_frames": int(n_frames), "n_eff": round(n_eff, 2),
            "rel_error": round(rel, 4), "preliminary": bool(n_eff < OCCUPANCY_PRELIM_NEFF)}


# ── The pure clustering entry point ───────────────────────────────────────────────
def occupancy_clusters(X, *, n_clusters: int = 0, k_max: int = _OCC_KMAX,
                       seed: int = _OCC_SEED, var_target: float = _OCC_VAR_TARGET,
                       min_silhouette: float = _OCC_SILHOUETTE_MIN) -> dict:
    """Cluster an ``(F, D)`` ensemble in truncated PC space. Pure — no I/O, no oxDNA.

    ``X`` rows MUST be in trajectory order; the recurrence test depends on it.
    ``n_clusters=0`` selects k automatically by silhouette.

    Returns a dict with ``verdict`` ∈ ``{"switching", "drift", "unimodal"}``:

    * ``"switching"`` — separated AND recurrent. Populations are meaningful (check
      ``confidence.preliminary`` for whether they are converged).
    * ``"drift"`` — separated but each state entered ≤ once. The k-means split is cutting
      a one-way path in two; the clusters are "early" and "late", not configurations in
      equilibrium. Callers must NOT present these as likelihoods.
    * ``"unimodal"`` — not separated. The flexibility map already describes this ensemble.

    Distances are Euclidean in score space, which relates to RMSD by
    ``d = sqrt(n_points) * rmsd`` — that is what lets spreads be reported in nanometres.
    """
    X = np.asarray(X, dtype=float)
    n_frames = int(X.shape[0])
    n_points = max(1, int(X.shape[1]) // 3)

    if n_frames < _OCC_MIN_FRAMES:
        return {"ready": False,
                "reason": f"need at least {_OCC_MIN_FRAMES} frames to cluster (have {n_frames})",
                "n_frames": n_frames}

    scores, var, n_pcs = _pca_scores(X, var_target=var_target)

    from scipy.spatial.distance import pdist, squareform
    D = squareform(pdist(scores))

    def _to_rmsd(d):
        return float(d) / float(np.sqrt(n_points))

    # ── choose k ────────────────────────────────────────────────────────────────
    auto_k = n_clusters <= 0
    sweep: dict[int, tuple[float, np.ndarray]] = {}
    hi = int(min(k_max, max(2, n_frames // 2)))

    def _fit(k):
        lab, _ = _kmeans_best(scores, k, seed=seed)
        if lab is not None:
            sweep[k] = (_silhouette(D, lab), lab)

    if auto_k:
        for k in range(2, hi + 1):
            _fit(k)
        best_k = max(sweep, key=lambda k: sweep[k][0]) if sweep else None
    else:
        # Only fit the k that was asked for — sweeping and discarding costs an O(F²)
        # silhouette per unused k.
        best_k = int(np.clip(n_clusters, 1, k_max))
        if best_k >= 2:
            _fit(best_k)

    silhouette = float(sweep[best_k][0]) if best_k in sweep else -1.0
    labels = sweep[best_k][1] if best_k in sweep else np.zeros(n_frames, dtype=int)

    # ── verdict: separated? recurrent? ──────────────────────────────────────────
    separated = best_k is not None and best_k >= 2 and silhouette >= min_silhouette
    rec = state_recurrence(labels, best_k) if separated else \
        {"transitions": 0, "visits": [], "min_visits": 0, "recurrent": False}

    if auto_k and not separated:
        verdict, k = "unimodal", 1
    elif separated and not rec["recurrent"]:
        verdict, k = "drift", int(best_k)
    elif separated:
        verdict, k = "switching", int(best_k)
    else:
        # forced k on an unseparated ensemble — honour it, but say so
        verdict, k = "unimodal", int(best_k or 1)

    if verdict == "unimodal" and k == 1:
        labels = np.zeros(n_frames, dtype=int)

    # PC1 smoothness: ≈ +1.0 means a continuous path, not hopping between basins.
    pc1 = scores[:, 0]
    pc1_lag1 = float(np.corrcoef(pc1[:-1], pc1[1:])[0, 1]) if n_frames > 2 and pc1.std() > 0 else 0.0

    # ── per-cluster medoids, populations, spreads ───────────────────────────────
    clusters = []
    for c in range(k):
        members = np.flatnonzero(labels == c)
        if members.size == 0:
            continue
        sub = D[np.ix_(members, members)]
        medoid = int(members[int(np.argmin(sub.sum(axis=1)))])
        spread = _to_rmsd(sub[int(np.argmin(sub.sum(axis=1)))].mean())

        stats = twist_series_stats((labels == c).astype(float))
        clusters.append({
            "population": float(stats["mean"]),
            "population_sem": float(stats["sem"]),
            "n_frames": int(members.size),
            "tau_int": float(stats["tau_int"]),
            "n_eff": float(stats["n_eff"]),
            "medoid_index": medoid,
            "rmsd_spread_nm": round(spread, 4),
            "visits": int(rec["visits"][c]) if c < len(rec["visits"]) else 0,
            "frames": members.tolist(),
            "pc_scores": [round(float(v), 4) for v in scores[medoid, :min(3, n_pcs)]],
        })

    clusters.sort(key=lambda d: -d["population"])
    for rank, cl in enumerate(clusters):
        cl["rank"] = rank
    if clusters:
        top = clusters[0]["medoid_index"]
        for cl in clusters:
            cl["rmsd_to_top_nm"] = round(_to_rmsd(D[top, cl["medoid_index"]]), 4)

    n_eff_overall = min((c["n_eff"] for c in clusters), default=float(n_frames))

    return {
        "ready": True,
        "n_frames": n_frames,
        "n_features": int(X.shape[1]),
        "n_pcs": int(n_pcs),
        "variance_explained": [round(float(v), 4) for v in var[:5]],
        "k": int(k),
        "auto_k": bool(auto_k),
        "silhouette": round(silhouette, 4),
        "verdict": verdict,
        "multimodal": verdict == "switching",
        "transitions": int(rec["transitions"]),
        "pc1_lag1": round(pc1_lag1, 4),
        "pc1_series": [round(float(v), 4) for v in pc1],
        "clusters": clusters,
        "confidence": occupancy_confidence(n_frames, n_eff_overall),
    }


# ── I/O shell ─────────────────────────────────────────────────────────────────────
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
                         align: bool = True, progress=None,
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
    X, _feature_keys, kept_rows, basis_used = occupancy_features(
        samples, key_list, design, basis=basis)
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
           int(n_clusters), str(method), str(basis))

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
        method=method, basis=basis, align=align, progress=progress,
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
