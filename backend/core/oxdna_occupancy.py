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
    _kabsch_superpose,
    _strain_index,
    twist_series_stats,
)
from backend.physics.oxdna_interface import (
    _EXT_PREFIX,
    _XB_SENTINEL,
    _walk_strand_nucleotides,
    is_extension_key,
    is_synthetic_nuc_key,
    oxdna_backbone_sites,
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


# ── Scope: which nucleotides the clustering is allowed to see ─────────────────────
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
    """
    X = np.asarray(X, dtype=float)
    if X.shape[0] < 2 or X.shape[1] < 9:      # < 3 points: no rotation to speak of
        return X
    n = X.shape[1] // 3
    P = X.reshape(X.shape[0], n, 3)
    ref = P.mean(axis=0)
    out = np.empty_like(P)
    for i in range(P.shape[0]):
        _R, Pa, _Qc, Qmean = _kabsch_superpose(P[i], ref)
        out[i] = Pa + Qmean
    return out.reshape(X.shape[0], -1)


# ── Feature vectors ───────────────────────────────────────────────────────────────
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
