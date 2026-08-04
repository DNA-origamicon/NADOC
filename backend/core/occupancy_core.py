"""Occupancy clouds — the engine-agnostic core.

PCA → k-means → medoids over a frame ensemble, plus the selection-scoping and sampling
statistics that go with it. Nothing here knows what produced the frames: it works on a
plain ``(F, D)`` feature matrix and on nucleotide KEY tuples, both of which oxDNA and NAMD
already speak. The per-engine modules (:mod:`backend.core.oxdna_occupancy`,
:func:`backend.core.md_trajectory.md_occupancy`) own only the frame acquisition and the
feature assembly for their own file formats.

The three invariants this core enforces are written up in ``oxdna_occupancy``'s docstring;
the load-bearing one lives here, in :func:`occupancy_clusters`: separation is NOT switching.
A monotone drift scores a high silhouette while never revisiting a state, so a multimodal
verdict additionally requires recurrence.
"""

from __future__ import annotations

import numpy as np

from backend.core.oxdna_health import _kabsch_superpose, twist_series_stats
from backend.physics.oxdna_interface import (
    _EXT_PREFIX,
    _XB_SENTINEL,
    _walk_strand_nucleotides,
    is_extension_key,
    is_synthetic_nuc_key,
)

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



def _synthetic_selected(key, xb_exact, xb_whole, ext_exact, ext_whole) -> bool:
    """Does this synthetic bead key match one of the two synthetic scopes?

    ``("__xb__", crossover_id, k)`` → extra_bases; ``("__ext_<id>", k, direction)`` →
    extensions. Element [1] is a crossover-id STRING for one and a bead-index INT for the
    other — the asymmetry ``is_synthetic_nuc_key`` exists to paper over — so each form is
    matched explicitly rather than by a shared index rule.
    """
    if is_extension_key(key):
        ext_id = str(key[0])[len(_EXT_PREFIX):]
        if ext_id in ext_whole:
            return True
        return len(key) >= 2 and (ext_id, int(key[1])) in ext_exact
    if key[0] == _XB_SENTINEL and len(key) >= 3:
        xo_id = str(key[1])
        if xo_id in xb_whole:
            return True
        return (xo_id, int(key[2])) in xb_exact
    return False

def resolve_selection_keys(design, keys, selection) -> list:
    """Filter the frame key list down to a user selection. Pure.

    ``selection`` is a union of optional criteria — a key is kept if it matches
    ANY of them, which is what "pick these things" means to a user::

        {"cluster_ids":  [...],   # expanded to their member helices
         "helix_ids":    [...],
         "strand_ids":   [...],
         "overhang_ids": [...],
         "domains":      [[strand_id, domain_index], ...],
         "bases":        [[helix_id, bp_index, direction], ...],
         "extra_bases":  [[crossover_id, k?], ...],   # k omitted → the whole run
         "extensions":   [[extension_id, k?], ...]}   # k omitted → the whole tail

    Every criterion mirrors a kind the shared anchor picker emits, so a selection made
    with that widget maps across without a lossy translation step.

    A base is matched on its first three elements, so selecting a position picks up all
    of its loop-insertion copies rather than an arbitrary one.

    SYNTHETIC beads — crossover extra-base inserts (``("__xb__", xo_id, k)``) and
    extension tail beads (``("__ext_<id>", k, direction)``) — are addressed by the last
    two criteria and by those ONLY. Note the asymmetry this fixes: an *unscoped* run has
    always included them (``key_list`` comes from ``_strand_nucleotide_order``, which
    emits them), so they were in the feature basis by default yet impossible to name when
    scoping. They stay excluded from a scoped selection that does not ask for them, which
    keeps every coordinate-based criterion above meaning exactly what it did before.

    An empty/absent selection means the whole structure — the caller gets ``keys`` back
    unchanged, and no re-alignment happens.
    """
    if not selection:
        return list(keys)

    helix_ids = set(selection.get("helix_ids") or [])
    strand_ids = set(str(s) for s in (selection.get("strand_ids") or []))
    want_clusters = set(selection.get("cluster_ids") or [])
    overhang_ids = set(str(o) for o in (selection.get("overhang_ids") or []))
    domains = {(str(d[0]), int(d[1])) for d in (selection.get("domains") or []) if len(d) >= 2}
    bases = {tuple(b)[:3] for b in (selection.get("bases") or [])}

    # Synthetic scopes match on the key tuple directly, so they need no strand walk:
    # element [0] carries the owner (crossover sentinel / "__ext_<id>") and element
    # [1]/[2] the index. `whole` = the ids selected without a specific index.
    def _split(entries):
        exact, whole = set(), set()
        for e in entries or []:
            t = tuple(e)
            if not t:
                continue
            if len(t) >= 2 and t[1] is not None:
                exact.add((str(t[0]), int(t[1])))
            else:
                whole.add(str(t[0]))
        return exact, whole

    xb_exact, xb_whole = _split(selection.get("extra_bases"))
    ext_exact, ext_whole = _split(selection.get("extensions"))

    # A cluster IS a named set of helices (ClusterRigidTransform.helix_ids), so it
    # expands rather than needing a parallel code path.
    if want_clusters:
        for ct in (getattr(design, "cluster_transforms", None) or []):
            if getattr(ct, "id", None) in want_clusters:
                helix_ids.update(getattr(ct, "helix_ids", None) or [])

    # One walk serves strand / domain / overhang — they are all properties of the same
    # step, and walking three times would be three full strand traversals.
    strand_of, domain_of, overhang_of = {}, {}, {}
    if strand_ids or domains or overhang_ids:
        try:
            for step in _walk_strand_nucleotides(design):
                sid = str(getattr(step.strand, "id", ""))
                strand_of[step.key] = sid
                # getattr rather than attribute access: one missing field must not take
                # the whole selection down with it via the except below.
                di = getattr(step, "domain_index", None)
                if di is not None:
                    domain_of[step.key] = (sid, int(di))
                oid = getattr(step, "overhang_id", None)
                if oid is not None:
                    overhang_of[step.key] = str(oid)
        except Exception:
            strand_of, domain_of, overhang_of = {}, {}, {}

    out = []
    for k in keys:
        # Synthetic beads carry no (helix, bp, direction), so they can only ever match
        # their own two criteria — never the coordinate-based ones above, whose fields
        # are all None on these rows.
        if is_synthetic_nuc_key(k):
            if _synthetic_selected(k, xb_exact, xb_whole, ext_exact, ext_whole):
                out.append(k)
            continue
        if helix_ids and k[0] in helix_ids:
            out.append(k)
        elif bases and tuple(k)[:3] in bases:
            out.append(k)
        elif strand_ids and strand_of.get(k) in strand_ids:
            out.append(k)
        elif domains and domain_of.get(k) in domains:
            out.append(k)
        elif overhang_ids and overhang_of.get(k) in overhang_ids:
            out.append(k)
    return out


def _superpose_on_subset(X):
    """Re-superpose every frame onto the ensemble mean using ONLY these coordinates.

    This is what makes a SCOPED run mean anything. The frames arrive Kabsch-fitted on the
    whole structure, so a selected sub-region still carries its rigid-body motion inside
    that fit — swinging on a hinge, or riding a global bend. PCA would then report that
    motion as the region's dominant "mode" and cluster on where the region WAS rather than
    what shape it took. Fitting on the selection removes the rigid part and leaves the
    internal conformational change, which is the whole reason to scope an analysis.

    Feature-space only: the medoid frames handed back for rendering are the untouched,
    globally-aligned ones, so the drawn states stay in the same pose as every other
    overlay. Same discipline as the mean-centring in :func:`_pca_scores`.

    This is the ``fit="selection"`` mode with every selected point in the fit set; the
    production path reaches it through :func:`occupancy_fit_plan` + :func:`apply_fit_plan`,
    which additionally know how to fit on the RIGID members only.
    """
    X = np.asarray(X, dtype=float)
    if X.shape[0] < 2 or X.shape[1] < 3 * _OCC_MIN_FIT_POINTS:
        return X                              # < 3 points: no rotation to speak of
    n = X.shape[1] // 3
    P = X.reshape(X.shape[0], n, 3)
    every = list(range(n))
    return _refit(P, every, every, P.copy(), every).reshape(X.shape[0], -1)


# ── Fit frames for a scoped run ───────────────────────────────────────────────────
#
# A scoped analysis is only as meaningful as the frame its coordinates are expressed in.
# Three, and the right one depends on WHAT was picked:
#
#   "global"    — leave the whole-structure Kabsch fit alone. The region's own rigid-body
#                 motion (hinge swing, riding a global bend) stays in the features, so PCA
#                 can report where the region WAS rather than what shape it took. Correct
#                 when that placement is the question.
#   "selection" — fit on the picked points themselves, which removes exactly that rigid
#                 part. The default for a scoped run, and what every docstring in this
#                 module claimed was happening long before anything called it.
#   "local"     — for crossover extra bases: fit each insert on ITS OWN junction (the
#                 flanking duplex, ±_OCC_LOCAL_FLANK bp on both helices, both strands) and
#                 cluster the insert coordinates in that frame. Answers "what does this T
#                 do relative to its crossover", with the structure's global bending and
#                 the junction's own placement both divided out.
#
# MIXED selections (rigid duplex + floppy inserts or an ssDNA tail) fit on the DUPLEX-PAIRED
# members only. Kabsch weights every point equally and an unpaired bead's RMSF is several
# times the duplex value, so including the floppy points lets them drag the frame around
# and smear the very motion the duplex part was picked to show.

OCC_FIT_MODES = ("global", "selection", "local")
_OCC_LOCAL_FLANK = 3           # bp either side of a junction that define its local frame
_OCC_MIN_FIT_POINTS = 3        # below 3 points a Kabsch fit has no rotation to remove


def _refit(P, fit_pos, out_pos, Q, slots):
    """Superpose frames on ``P[:, fit_pos]`` and write the transformed ``P[:, out_pos]``
    into ``Q[:, slots]``. Helper for :func:`apply_fit_plan`; mutates and returns ``Q``."""
    F = P[:, fit_pos, :]
    ref = F.mean(axis=0)
    for i in range(P.shape[0]):
        R, _Pa, _Qc, Qmean = _kabsch_superpose(F[i], ref)
        Q[i, slots, :] = (P[i, out_pos, :] - F[i].mean(axis=0)) @ R.T + Qmean
    return Q


def _local_flank_keys(crossover, flank: int):
    """The duplex keys that define a crossover's local frame — both halves, both strands,
    ``±flank`` bp. Directions are the KEY spelling (``"FORWARD"``/``"REVERSE"``), not the
    ``Direction`` enum the model stores, which is the trap here."""
    out = []
    for half in (crossover.half_a, crossover.half_b):
        hid = getattr(half, "helix_id", None)
        idx = getattr(half, "index", None)
        if hid is None or idx is None:
            continue
        for direction in ("FORWARD", "REVERSE"):
            for off in range(-flank, flank + 1):
                out.append((hid, int(idx) + off, direction))
    return out


def occupancy_fit_plan(design, key_list, sel_idx, *, fit: str = "selection",
                       flank: int = _OCC_LOCAL_FLANK) -> dict:
    """Plan the re-superposition of a scoped feature set. Pure; no frame data needed.

    ``key_list`` is the key per FEATURE COLUMN of whatever basis is in play (nucleotide
    keys for ``"nt"``, the forward key of each duplex column for ``"bp"``); ``sel_idx``
    indexes into it, or is ``None``/all for an unscoped run.

    Returns ``{fit, fit_requested, note, need_idx, sel_pos, groups, n_fit_points}``:

    * ``need_idx`` — the columns a caller must retain per frame. For ``"local"`` this is
      WIDER than the selection, because a junction's frame is defined by duplex that was
      not picked.
    * ``sel_pos`` — where each selected column sits inside ``need_idx``, in ``sel_idx``
      order, so the feature ordering still matches ``feature_keys``.
    * ``groups`` — ``[(fit_pos, out_pos, slots)]``, positions within ``need_idx`` and
      slots within the emitted feature vector. Empty ⇒ nothing to re-superpose.

    ``fit`` is what will ACTUALLY be used, which is not always what was asked: a mode
    degrades (with a ``note``) rather than lying, exactly as ``basis`` already does. An
    unscoped run is always ``"global"`` — there is no sub-region to remove motion from.
    """
    n = len(key_list)
    requested = fit if fit in OCC_FIT_MODES else "selection"
    sel = list(range(n)) if sel_idx is None else list(sel_idx)
    plain = {"fit": "global", "fit_requested": requested, "note": None,
             "need_idx": sel, "sel_pos": list(range(len(sel))), "groups": [],
             "n_fit_points": 0}
    # A "local" run is NOT subject to the point-count floor: its fit set comes from the
    # junction, not the selection, so picking a single crossover's one or two inserts —
    # the most natural extra-base question there is — must still re-fit.
    if requested == "global" or sel_idx is None:
        return plain
    if requested == "selection" and len(sel) < _OCC_MIN_FIT_POINTS:
        plain["note"] = (f"fewer than {_OCC_MIN_FIT_POINTS} points selected — a Kabsch fit "
                         "has no rotation to remove, so the whole-structure alignment is "
                         "kept")
        return plain

    # Which of the picked columns are duplex-paired.  These are the stable fit set for a
    # MIXED selection; `_strain_index` already refuses to pair synthetic beads.
    from backend.core.oxdna_health import _strain_index

    try:
        ia_wc, ib_wc = _strain_index(design, list(key_list), "wc")
        paired = set(int(i) for i in ia_wc) | set(int(i) for i in ib_wc)
    except Exception:                          # noqa: BLE001 — a design we cannot walk
        paired = set()
    pos_of = {c: p for p, c in enumerate(sel)}
    rigid = [c for c in sel if c in paired]
    mixed = 0 < len(rigid) < len(sel)

    if requested == "local":
        by_col = {}
        for c in sel:
            k = key_list[c]
            if len(k) >= 3 and k[0] == _XB_SENTINEL:
                by_col.setdefault(str(k[1]), []).append(c)
        if by_col:
            key_pos = {tuple(k): i for i, k in enumerate(key_list)}
            need = list(sel)
            need_pos = dict(pos_of)

            def _need(col):
                if col not in need_pos:
                    need_pos[col] = len(need)
                    need.append(col)
                return need_pos[col]

            groups, done, skipped = [], set(), 0
            for xo in (getattr(design, "crossovers", None) or []):
                cols = by_col.get(str(getattr(xo, "id", "")))
                if not cols:
                    continue
                fl = sorted({key_pos[k] for k in _local_flank_keys(xo, flank)
                             if k in key_pos} - set(cols))
                if len(fl) < _OCC_MIN_FIT_POINTS:
                    skipped += 1               # junction not in the basis (e.g. "bp")
                    continue
                groups.append(([_need(c) for c in fl], [_need(c) for c in cols],
                               [pos_of[c] for c in cols]))
                done.update(cols)
            if groups:
                # Anything picked that has no junction of its own — ordinary duplex, an
                # extension tail — still gets the "selection" treatment rather than being
                # left in a different (global) frame from its neighbours.
                rest = [c for c in sel if c not in done]
                rest_fit = [c for c in rest if c in paired] or rest
                if len(rest) >= 1 and len(rest_fit) >= _OCC_MIN_FIT_POINTS:
                    groups.append(([need_pos[c] for c in rest_fit],
                                   [need_pos[c] for c in rest], [pos_of[c] for c in rest]))
                note = None
                if skipped:
                    note = (f"{skipped} selected junction(s) had no flanking duplex in this "
                            "basis and kept the whole-structure alignment")
                return {"fit": "local", "fit_requested": requested, "note": note,
                        "need_idx": need, "sel_pos": [need_pos[c] for c in sel],
                        "groups": groups,
                        "n_fit_points": sum(len(g[0]) for g in groups)}
        # No extra bases picked (or none resolvable) → the local frame is undefined.
        fit_cols = rigid if (mixed and len(rigid) >= _OCC_MIN_FIT_POINTS) else sel
        if len(fit_cols) < _OCC_MIN_FIT_POINTS:
            plain["note"] = ("no crossover extra bases in the selection and too few points "
                             "for a fit of its own — the whole-structure alignment is kept")
            return plain
        return {"fit": "selection", "fit_requested": requested,
                "note": "no crossover extra bases in the selection — a junction frame is "
                        "undefined, so the fit is on the selection itself",
                "need_idx": sel, "sel_pos": list(range(len(sel))),
                "groups": [([pos_of[c] for c in fit_cols], list(range(len(sel))),
                            list(range(len(sel))))],
                "n_fit_points": len(fit_cols)}

    # fit == "selection"
    note = None
    if mixed and len(rigid) >= _OCC_MIN_FIT_POINTS:
        fit_cols = rigid
        note = (f"mixed selection — fitted on the {len(rigid)} duplex-paired point(s) only, "
                f"so the {len(sel) - len(rigid)} unpaired one(s) cannot drag the frame")
    else:
        fit_cols = sel
        if mixed:
            note = (f"only {len(rigid)} duplex-paired point(s) in the selection — too few "
                    "for their own frame, so every selected point is in the fit")
    return {"fit": "selection", "fit_requested": requested, "note": note,
            "need_idx": sel, "sel_pos": list(range(len(sel))),
            "groups": [([pos_of[c] for c in fit_cols], list(range(len(sel))),
                        list(range(len(sel))))],
            "n_fit_points": len(fit_cols)}


def apply_fit_plan(P, plan) -> np.ndarray:
    """``(F, len(need_idx), 3)`` retained coordinates → the ``(F, D)`` feature matrix.

    Feature-space ONLY. The medoid frames handed back for rendering are the untouched,
    globally-aligned ones, so a re-fitted analysis still draws its states in the same pose
    as ``/trajectory`` and ``/rmsf``. Same discipline as the mean-centring in
    :func:`_pca_scores`.
    """
    P = np.asarray(P, dtype=float)
    if P.ndim != 3 or P.shape[0] == 0:
        return P.reshape(P.shape[0] if P.ndim else 0, -1)
    sel_pos = plan.get("sel_pos") or list(range(P.shape[1]))
    groups = plan.get("groups") or []
    if not groups and len(sel_pos) == P.shape[1]:
        # The unscoped path, which is every whole-structure run: no re-fit, no reordering,
        # so don't pay a full (F, N, 3) copy of a 15 k-nucleotide ensemble to say so.
        return P.reshape(P.shape[0], -1)
    Q = P[:, sel_pos, :].copy()
    if P.shape[0] < 2:
        return Q.reshape(P.shape[0], -1)
    for fit_pos, out_pos, slots in groups:
        if len(fit_pos) < _OCC_MIN_FIT_POINTS or not out_pos:
            continue
        _refit(P, list(fit_pos), list(out_pos), Q, list(slots))
    return Q.reshape(P.shape[0], -1)


# ── Feature vectors ───────────────────────────────────────────────────────────────


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


def _selection_sig(selection) -> str:
    """Stable cache signature for a selection. Order must not matter — the same set of
    picks made in a different order is the same analysis."""
    if not selection:
        return ""
    parts = []
    for field in ("cluster_ids", "helix_ids", "strand_ids", "overhang_ids"):
        parts.append(",".join(sorted(str(v) for v in (selection.get(field) or []))))
    for field, width in (("domains", 2), ("bases", 3),
                         ("extra_bases", 2), ("extensions", 2)):
        parts.append(",".join(sorted("/".join(str(x) for x in tuple(v)[:width])
                                     for v in (selection.get(field) or []))))
    return "|".join(parts)
