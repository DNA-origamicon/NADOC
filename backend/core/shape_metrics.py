"""Engine-agnostic shape descriptors from a display-position map.

Every structure-prediction engine here (oxDNA ``/display``, CanDo ``deformed_positions``,
mrDNA ``_display_positions``, NAMD md frame) already emits the SAME substrate for its
overlay: a per-nucleotide list of ``{helix_id, bp_index, direction, backbone_position, …}``
dicts keyed by ``(helix, bp, dir, copy)``.  This module composes the locked
``oxdna_health`` bundle estimators into ONE comparable descriptor set so the engines can
be cross-validated on identical numbers (the shared-metric track; S1).

It is a pure read-over-positions layer — **Physical/display only, it never touches
topology** (Three-Layer Law).  Each descriptor is computed independently and set to
``None`` when the input can't define it (e.g. global twist needs ≥2 helices for a
cross-section), so a partial/degenerate frame yields a partial descriptor set rather
than crashing.

Like the ``oxdna_health`` estimators it wraps, the twist/bend descriptors are meant
for the rigid duplex CORE (ssDNA ends have ill-defined cross-sections); filtering the
frame to the core is the CALLER's responsibility — this entry point is engine-agnostic
and reads whatever map it is handed.

Descriptor set (all lengths nm, angles degrees):
    twist_total_deg        signed global twist end-to-end (right-handed +)
    twist_per_turn_deg     twist_total normalised by axial length / B-DNA pitch
    bend_angle_deg         realised arc-span of the centreline (chord+sagitta)
    bend_radius_nm         radius of curvature of that arc (inf ≈ straight)
    radius_of_gyration_nm  overall compactness, sqrt(mean |r−r_cm|²)
    end_to_end_nm          3-D chord between the two axial-end cross-section centroids
    axial_span_nm          length of the fitted bundle axis
    n_nucleotides          size of the input map
"""
from __future__ import annotations

import math

import numpy as np
from scipy.stats import pearsonr, spearmanr

from backend.core.constants import BDNA_BP_PER_TURN, BDNA_RISE_PER_BP
from backend.core.oxdna_health import (
    _bundle_axis_frame,
    _chord_sagitta_bend,
    _kabsch_superpose,
    bundle_slab_centreline,
    measure_bundle_twist,
    measure_bundle_twist_profile,
    measure_radius_of_gyration,
)

# B-DNA helical pitch (nm per full turn) — the denominator for twist-per-turn.
BDNA_PITCH_NM: float = BDNA_RISE_PER_BP * BDNA_BP_PER_TURN  # ≈ 3.505 nm/turn


def _bp_midpoints(positions) -> np.ndarray:
    """Collapse each ``(helix, bp)`` column to its base-pair midpoint (averaging the two
    complementary backbone sites lands ON the helix axis) — the same on-axis point set the
    bundle estimators fit their frame to."""
    bp_pts: dict = {}
    for p in positions:
        bp_pts.setdefault((p["helix_id"], int(p["bp_index"])), []).append(
            np.asarray(p["backbone_position"], dtype=float))
    return np.array([np.mean(v, axis=0) for v in bp_pts.values()])


def _axial_span_and_end_chord(positions) -> tuple[float | None, float | None]:
    """(axial_span_nm, end_to_end_nm).  Axial span = extent along the fitted bundle axis.
    End-to-end = 3-D distance between the cross-section centroids of the two axial-end
    bands (a 5%-of-span band at each end, averaged so ragged ends don't pick one stray
    nucleotide).  Returns ``(None, None)`` on a degenerate axis."""
    pts = _bp_midpoints(positions)
    if len(pts) < 2:
        return None, None
    try:
        C, L, _e1, _e2 = _bundle_axis_frame(pts)
    except Exception:
        return None, None
    t = (pts - C) @ L
    span = float(t.max() - t.min())
    if span < 1e-9:
        return 0.0, 0.0
    band = max(BDNA_RISE_PER_BP, 0.05 * span)
    lo = pts[t <= t.min() + band].mean(axis=0)
    hi = pts[t >= t.max() - band].mean(axis=0)
    return span, float(np.linalg.norm(hi - lo))


def _safe(fn, *args, **kwargs):
    """Call an estimator, returning ``None`` when it raises on a degenerate frame (too
    few helices/points) rather than propagating — keeps the descriptor set partial-safe."""
    try:
        return fn(*args, **kwargs)
    except Exception:
        return None


def compute_shape_descriptors(positions, *, n_slices: int = 0) -> dict:
    """Unified shape descriptors for one display-position frame.  See the module docstring
    for the field list.  ``n_slices`` overrides the ~1-turn axial slabbing used by the
    twist/centreline estimators (0 = auto).  Every field is present; undefined ones are
    ``None``."""
    n = len(positions)
    twist_total = _safe(measure_bundle_twist, positions, n_slices=n_slices) if n else None
    rg = _safe(measure_radius_of_gyration, positions) if n else None
    axial_span, end_to_end = _axial_span_and_end_chord(positions) if n else (None, None)

    bend_angle = None
    bend_radius = None
    centreline = _safe(bundle_slab_centreline, positions, n_slices=n_slices) if n else None
    if centreline is not None and len(centreline) >= 5:
        bend_angle, bend_radius = _chord_sagitta_bend(centreline)

    twist_per_turn = None
    if twist_total is not None and axial_span and axial_span > 1e-9:
        n_turns = axial_span / BDNA_PITCH_NM
        if n_turns > 1e-9:
            twist_per_turn = twist_total / n_turns

    return {
        "twist_total_deg": twist_total,
        "twist_per_turn_deg": twist_per_turn,
        "bend_angle_deg": bend_angle,
        "bend_radius_nm": bend_radius,
        "radius_of_gyration_nm": rg,
        "end_to_end_nm": end_to_end,
        "axial_span_nm": axial_span,
        "n_nucleotides": n,
    }


def twist_profile(positions, *, n_slices: int = 0) -> list[tuple[float, float]]:
    """The spatially-resolved twist descriptor: ``[(axial_nm, cumulative_twist_deg), …]``
    from the bundle start, whose LAST y equals the scalar ``twist_total_deg``.  Wraps the
    locked ``oxdna_health.measure_bundle_twist_profile`` estimator and shifts the x-axis so
    the profile starts at 0 nm (each engine fits its own axis origin — the common
    quantity is axial DISTANCE from the bundle start, so the curves overlay).  Engine-
    agnostic like :func:`compute_shape_descriptors`; a degenerate frame (<2 helices, zero
    span) → ``[]`` rather than raising."""
    prof = _safe(measure_bundle_twist_profile, positions, n_slices=n_slices) if positions else None
    if not prof:
        return []
    x0 = prof[0][0]
    return [(float(t) - float(x0), float(v)) for t, v in prof]


# ── Deviation + RMSF profiles (S2) ─────────────────────────────────────────────────
#
# These are the engine-agnostic per-nucleotide profiles S3's ``compare_descriptors``
# consumes.  They generalise the two engine-specific implementations already in the
# codebase into one home that reads any display-position map:
#   * ``deviation_profile``      generalises ``cando_deviation.compute_deviation`` (which
#     diffs against the design's deformed geometry with NO alignment) and
#     ``oxdna_health.geometry_deviation_map`` (Kabsch-aligned) — one function, an
#     ``align`` switch, plus the global RMSD scalar.
#   * ``rmsf_from_ensemble``     generalises the variance core of
#     ``oxdna_health.production_rmsf`` (per-site RMS fluctuation about the mean over a
#     frame set), stripped of the oxDNA trajectory-file I/O so NAMD/mrDNA/any ensemble
#     can feed it.  CanDo instead supplies its NMA RMSF directly (``predict_shape``).
#   * ``normalize_rmsf_profile`` generalises ``fem_solver.normalize_rmsf`` (mesh-keyed)
#     to a keyed [0,1] map from any ``{helix_id, bp_index, direction?, rmsf_nm}`` list.
#
# All read-only over the Physical layer (Three-Layer Law) — never touch topology.


def _dev_key(p) -> tuple:
    """Copy-aware key ``(helix, bp, direction, copy)`` — loop-insertion copies stay
    distinct (copy defaults 0) so each inserted base matches its own reference base
    instead of collapsing onto the last one."""
    return (p["helix_id"], int(p["bp_index"]),
            getattr(p["direction"], "value", p["direction"]), int(p.get("copy", 0)))


def deviation_profile(positions, reference_positions, *, align: bool = True) -> dict:
    """Per-nucleotide deviation (nm) of a candidate frame from a reference frame, plus
    the global RMSD — engine-agnostic.

    ``positions`` and ``reference_positions`` are display-position maps (lists of
    ``{helix_id, bp_index, direction, backbone_position}`` dicts).  The deviation is
    computed over the nucleotides present in BOTH (copy-aware keys), so a core-only
    reference restricts the comparison to the rigid duplex core.

    ``align=True`` (default): optimal rigid (Kabsch) superposition of the candidate onto
    the reference first, so only intrinsic SHAPE mismatch survives — where a frame floats
    in its engine's box, and its overall orientation, are irrelevant (a residual global
    twist/bend is not a rigid motion and DOES survive).  This is the cross-engine mode.
    ``align=False``: direct key-matched distance, for two frames already in a common frame
    (e.g. a prediction vs the design geometry it was aligned to) — reports the exact
    positional residual.

    Returns ``{"positions": [{helix_id, bp_index, direction, copy, backbone_position (the
    candidate site, aligned into the reference frame when align=True), deviation}],
    "rmsd_nm", "min_deviation", "max_deviation", "mean_deviation", "n"}``.

    Raises ``ValueError`` on an empty map, or (align=True) fewer than three shared
    nucleotides — a rigid superposition is undetermined below three non-collinear points.
    """
    if not positions:
        raise ValueError("deviation_profile: empty candidate map")
    if not reference_positions:
        raise ValueError("deviation_profile: empty reference map")
    cand = {_dev_key(p): np.asarray(p["backbone_position"], float) for p in positions}
    ref = {_dev_key(p): np.asarray(p["backbone_position"], float)
           for p in reference_positions}
    shared = sorted(set(cand) & set(ref))
    if align and len(shared) < 3:
        raise ValueError(
            f"deviation_profile: only {len(shared)} shared nucleotide(s) — need >= 3 to "
            "superpose (align=True); pass align=False for a direct key-matched diff")
    if not shared:
        raise ValueError("deviation_profile: no shared nucleotides between the maps")

    P = np.array([cand[k] for k in shared])
    Q = np.array([ref[k] for k in shared])
    if align:
        _R, Pa, Qc, Qmean = _kabsch_superpose(P, Q)
        dev = np.linalg.norm(Pa - Qc, axis=1)
        aligned = Pa + Qmean                     # candidate placed in the reference frame
    else:
        dev = np.linalg.norm(P - Q, axis=1)
        aligned = P

    out = [{"helix_id": k[0], "bp_index": k[1], "direction": k[2], "copy": k[3],
            "backbone_position": aligned[i].tolist(), "deviation": float(dev[i])}
           for i, k in enumerate(shared)]
    return {
        "positions": out,
        "rmsd_nm": float(np.sqrt((dev ** 2).mean())),
        "min_deviation": float(dev.min()),
        "max_deviation": float(dev.max()),
        "mean_deviation": float(dev.mean()),
        "n": len(shared),
    }


def rmsf_from_ensemble(frames, *, align: bool = True) -> dict:
    """Per-nucleotide RMSF (root-mean-square fluctuation, nm) over a frame ensemble —
    the trajectory-variance flexibility source for any engine that samples an ensemble
    (oxDNA / NAMD / mrDNA); CanDo supplies its NMA RMSF directly instead.

    ``frames`` is a list of display-position maps (one per trajectory frame / NMA sample).
    Every frame is (optionally) Kabsch-aligned to the first frame to strip rigid diffusion
    /tumbling, then each nucleotide's RMSF is the RMS of its distance from its own mean
    position across frames.  Only nucleotides present in EVERY frame are reported.

    ``align=True`` (default) removes whole-body motion — correct for a trajectory that
    diffuses/tumbles in a box.  ``align=False`` skips it — correct when the frames are
    already in a common frame (site fluctuations only), or when the bundle is too small
    for a stable global fit (Kabsch would fold local motion into a spurious rotation).

    Returns ``{"positions": [{helix_id, bp_index, direction, copy, backbone_position
    (mean site), rmsf_nm}], "min_rmsf", "max_rmsf", "mean_rmsf", "n_frames", "n"}``.
    """
    frames = [f for f in frames if f]
    if len(frames) < 2:
        raise ValueError("rmsf_from_ensemble: need >= 2 non-empty frames")

    keyed = [{_dev_key(p): np.asarray(p["backbone_position"], float) for p in fr}
             for fr in frames]
    shared = sorted(set.intersection(*(set(k) for k in keyed)))
    if not shared:
        raise ValueError("rmsf_from_ensemble: no nucleotide is present in every frame")

    stacks = [np.array([kf[k] for k in shared]) for kf in keyed]  # each (N, 3)
    if align:
        ref = stacks[0]
        aligned = [ref]
        for S in stacks[1:]:
            _R, Pa, _Qc, Qmean = _kabsch_superpose(S, ref)
            aligned.append(Pa + Qmean)
        stacks = aligned

    A = np.stack(stacks, axis=0)                 # (F, N, 3)
    mean_pos = A.mean(axis=0)                     # (N, 3)
    rmsf = np.sqrt(((A - mean_pos) ** 2).sum(axis=2).mean(axis=0))  # (N,)

    out = [{"helix_id": k[0], "bp_index": k[1], "direction": k[2], "copy": k[3],
            "backbone_position": mean_pos[i].tolist(), "rmsf_nm": float(rmsf[i])}
           for i, k in enumerate(shared)]
    return {
        "positions": out,
        "min_rmsf": float(rmsf.min()),
        "max_rmsf": float(rmsf.max()),
        "mean_rmsf": float(rmsf.mean()),
        "n_frames": len(frames),
        "n": len(shared),
    }


def normalize_rmsf_profile(profile) -> dict:
    """Normalise a per-node RMSF profile to [0, 1], keyed ``"{helix}:{bp}:{direction}"``.

    ``profile`` is any list of ``{helix_id, bp_index, rmsf_nm, direction?}`` dicts — a
    CanDo ``predict_shape`` RMSF list, or an ``rmsf_from_ensemble`` result's positions.
    Entries without a ``direction`` are emitted for BOTH strands (mirrors the CanDo
    axis-node convention where RMSF is direction-independent).  All-zero input maps to 0
    (no divide-by-zero).  The [0,1] scale is the display colour ramp; multiplying back by
    the max recovers the physical values."""
    vals = [float(e["rmsf_nm"]) for e in profile]
    rmax = max(vals) if vals and max(vals) > 0 else 1.0
    result: dict = {}
    for e in profile:
        v = float(e["rmsf_nm"]) / rmax
        d = e.get("direction")
        dirs = [getattr(d, "value", d)] if d is not None else ["forward", "reverse"]
        for direction in dirs:
            result[f"{e['helix_id']}:{int(e['bp_index'])}:{direction}"] = v
    return result


# ── Cross-engine agreement (S3) ────────────────────────────────────────────────────
#
# ``compare_descriptors`` scores how well a CANDIDATE engine's shape prediction agrees
# with a REFERENCE engine's, on the three comparable observable classes S1/S2 produce:
#   * scalar shape descriptors  -> signed percent delta vs the reference
#   * per-nt RMSF profile        -> Pearson (linear) + Spearman (rank) correlation
#   * relaxed shape frame        -> aligned-shape RMSD (reuses deviation_profile align=True,
#                                   i.e. Kabsch — rigid pose is irrelevant, intrinsic shape
#                                   mismatch survives)
# ``reference_for`` applies the per-observable reference POLICY (oxDNA=shape/field,
# CanDo=RMSF/flexibility) with NAMD overriding every observable once a NAMD run exists.
# Pure comparison layer over Physical-layer outputs — never touches topology.

#: The engine-agnostic scalar descriptors compared as signed percent deltas.  (Counts
#: like ``n_nucleotides`` are excluded — they describe the map, they aren't observables.)
COMPARABLE_SCALARS: tuple[str, ...] = (
    "twist_total_deg", "twist_per_turn_deg", "bend_angle_deg", "bend_radius_nm",
    "radius_of_gyration_nm", "end_to_end_nm", "axial_span_nm",
)

#: Per-observable reference engine (lower-case).  NAMD (:data:`_GOLD_ENGINE`) overrides
#: all of these when present.  ``field`` shares oxDNA with ``shape`` (both geometric).
_REFERENCE_POLICY: dict[str, str] = {"shape": "oxdna", "field": "oxdna", "rmsf": "cando"}
_GOLD_ENGINE = "namd"


def reference_for(engines, observable: str) -> str | None:
    """Which engine is the reference for ``observable`` given the ones present.

    ``engines`` is any iterable of engine names; ``observable`` is one of ``"shape"``,
    ``"field"``, ``"rmsf"``.  NAMD wins every observable when present (gold override);
    otherwise the policy engine wins if present.  Returns ``None`` when neither the gold
    engine nor the policy engine is available (or the observable is unknown) — a missing
    reference is reported, never silently mis-assigned.
    """
    avail = {str(e).lower() for e in engines}
    if _GOLD_ENGINE in avail:
        return _GOLD_ENGINE
    pref = _REFERENCE_POLICY.get(observable)
    return pref if pref in avail else None


def _finite_or_none(x) -> float | None:
    """Coerce to a plain float, mapping NaN/inf (degenerate correlation) to ``None``."""
    x = float(x)
    return x if math.isfinite(x) else None


def _signed_pct(cand, ref) -> tuple[float | None, float | None]:
    """``(abs_delta, signed_percent_delta)`` of a candidate scalar vs its reference.
    ``None`` scalars -> both ``None`` (incomparable); a zero reference -> the absolute
    delta but a ``None`` percent (no divide-by-zero)."""
    if cand is None or ref is None:
        return None, None
    abs_delta = float(cand) - float(ref)
    if ref == 0:
        return abs_delta, None
    return abs_delta, abs_delta / abs(float(ref)) * 100.0


def _rmsf_per_bp(profile) -> dict:
    """Collapse a per-nucleotide RMSF profile to a per-base-pair ``(helix, bp, copy)`` map,
    averaging over strand direction.

    This is the reconciliation the cross-engine comparison needs: an ensemble profile
    (``rmsf_from_ensemble``) carries a ``direction`` per strand — two entries per bp —
    while CanDo's NMA RMSF (the policy RMSF *reference*) is an axis-node value with NO
    direction — one entry per bp.  Keying on ``direction`` would leave those two key-sets
    disjoint (nothing shared), so the correlation between the very pair the policy exists
    to compare would silently be undefined.  Reducing both sides to the per-bp mean puts
    them on the SAME sites (mirrors the strand-agnostic collapse in
    ``normalize_rmsf_profile``)."""
    acc: dict = {}
    for e in profile:
        k = (e["helix_id"], int(e["bp_index"]), int(e.get("copy", 0)))
        acc.setdefault(k, []).append(float(e["rmsf_nm"]))
    return {k: float(np.mean(v)) for k, v in acc.items()}


def _rmsf_agreement(cand_rmsf, ref_rmsf) -> dict | None:
    """Pearson + Spearman correlation between two RMSF profiles over the base pairs they
    share (each collapsed to per-bp by :func:`_rmsf_per_bp`, so a direction-less CanDo
    profile still matches a per-strand ensemble profile).  ``None`` if either profile is
    missing, fewer than two base pairs overlap, or a profile is constant (correlation
    undefined -> ``None`` coefficient, not NaN)."""
    if not cand_rmsf or not ref_rmsf:
        return None
    c = _rmsf_per_bp(cand_rmsf)
    r = _rmsf_per_bp(ref_rmsf)
    shared = sorted(set(c) & set(r))
    if len(shared) < 2:
        return None
    cv = np.array([c[k] for k in shared])
    rv = np.array([r[k] for k in shared])
    degenerate = cv.std() < 1e-12 or rv.std() < 1e-12
    pear = None if degenerate else _finite_or_none(pearsonr(cv, rv)[0])
    spear = None if degenerate else _finite_or_none(spearmanr(cv, rv).correlation)
    return {
        "pearson": pear,
        "spearman": spear,
        "n": len(shared),
        "candidate_mean_rmsf_nm": float(cv.mean()),
        "reference_mean_rmsf_nm": float(rv.mean()),
    }


def _shape_rmsd(cand_frame, ref_frame, align: bool) -> float | None:
    """Aligned-shape RMSD (nm) between two display-position frames — reuses
    :func:`deviation_profile`.  ``None`` if either frame is absent or too small/degenerate
    to superpose."""
    if not cand_frame or not ref_frame:
        return None
    try:
        return deviation_profile(cand_frame, ref_frame, align=align)["rmsd_nm"]
    except ValueError:
        return None


def compare_descriptors(candidate, reference, *, align_shape: bool = True) -> dict:
    """Agreement between a candidate engine's prediction and a reference engine's.

    Each argument is a source bundle::

        {"engine": str,
         "descriptors": <compute_shape_descriptors output> | None,
         "rmsf": [{helix_id, bp_index, rmsf_nm, direction?, copy?}, …] | None,
         "shape_frame": <display-position map> | None}

    ``reference`` is the denominator for the scalar percent deltas (pick it with
    :func:`reference_for`).  Returns::

        {"candidate", "reference",             # engine names
         "scalars": {name: {candidate, reference, abs_delta, signed_pct_delta}},
         "rmsf": {pearson, spearman, n, candidate_mean_rmsf_nm, reference_mean_rmsf_nm} | None,
         "shape_rmsd_nm": float | None}         # Kabsch-aligned when align_shape (default)

    Any observable a source doesn't carry is reported as ``None`` — a partial bundle
    yields a partial comparison, never a crash.
    """
    cd = candidate.get("descriptors") or {}
    rd = reference.get("descriptors") or {}
    scalars: dict = {}
    for name in COMPARABLE_SCALARS:
        c, r = cd.get(name), rd.get(name)
        abs_delta, pct = _signed_pct(c, r)
        scalars[name] = {"candidate": c, "reference": r,
                         "abs_delta": abs_delta, "signed_pct_delta": pct}
    return {
        "candidate": candidate.get("engine"),
        "reference": reference.get("engine"),
        "scalars": scalars,
        "rmsf": _rmsf_agreement(candidate.get("rmsf"), reference.get("rmsf")),
        "shape_rmsd_nm": _shape_rmsd(
            candidate.get("shape_frame"), reference.get("shape_frame"), align_shape),
    }


# ── Field-response descriptor (S4) ──────────────────────────────────────────────────
#
# The engine-agnostic E-field oracle + descriptor.  Generalises
# ``oxdna_health.measure_field_response`` (oxDNA-only, one aggregate verdict) into a
# reusable primitive every engine's field flow feeds: it adds a copy-aware PER-NT
# deflection map so two engines' field responses can be compared directionally, while
# keeping the physical verdict (anchors held + free deflected along the field).
#
# Positions are NOT Kabsch-aligned: the anchored region IS the common frame between the
# field-on and field-off structures, and aligning would remove the very field-driven
# motion being measured (mirrors ``field_response_from_confs``' note).  All read-only
# over the Physical layer (Three-Layer Law) — never touches topology.


def _pos_lookup(positions) -> dict:
    """Copy-aware ``{(helix, bp, dir, copy): np.array(xyz)}`` map (same key as
    :func:`_dev_key`) so inserted-base copies stay distinct."""
    return {_dev_key(p): np.asarray(p["backbone_position"], dtype=float)
            for p in positions}


def _anchor_key_set(anchor_keys) -> set:
    """Normalise anchor landmarks to their ``(helix, bp, dir)`` triple (copy-agnostic —
    an anchored base pins all of its inserted copies)."""
    out = set()
    for k in anchor_keys:
        h, bp, direction = tuple(k)[:3]
        out.add((h, int(bp), getattr(direction, "value", direction)))
    return out


def field_response_profile(
    field_positions,
    reference_positions,
    field_dir,
    anchor_keys=(),
    *,
    anchor_tol_nm: float = 1.0,
    min_free_proj_nm: float = 0.5,
) -> dict:
    """Per-nucleotide + aggregate response of a structure to an E-field stage vs its
    field-off reference — engine-agnostic (generalises
    ``oxdna_health.measure_field_response``).

    ``field_positions`` / ``reference_positions`` are display-position maps (lists of
    ``{helix_id, bp_index, direction, backbone_position, copy?}`` dicts).  ``anchor_keys``
    is the iterable of anchored ``(helix, bp, direction)`` landmarks (the parts pinned by
    traps/restraints); ``field_dir`` is the applied field direction.

    ``passed`` asserts a *physical property*, not a run status: the anchored nucleotides
    barely moved (≤ ``anchor_tol_nm``) AND the free nucleotides displaced, on average,
    ALONG the field (≥ ``min_free_proj_nm``).  Returns the aggregates
    (``anchored_max_drift_nm``, ``anchored_mean_drift_nm``, ``free_mean_disp_nm``,
    ``free_proj_along_field_nm``, ``n_anchored``, ``n_free``, ``passed``, ``reason``), the
    unit ``field_dir``, the mean free ``deflection_vec_nm`` (for cross-engine cosine), and
    a copy-aware ``per_nt`` deflection map ``[{helix_id, bp_index, direction, copy,
    disp_vec_nm, disp_nm, proj_along_field_nm, anchored}, …]``.

    Raises ``ValueError`` on a zero field direction or no free nucleotides to measure."""
    fdir = np.asarray(field_dir, dtype=float)
    fnorm = float(np.linalg.norm(fdir))
    if fnorm <= 1e-9:
        raise ValueError("field_response_profile: field_dir is ~zero")
    fdir = fdir / fnorm

    fmap = _pos_lookup(field_positions)
    rmap = _pos_lookup(reference_positions)
    anchor_set = _anchor_key_set(anchor_keys)

    per_nt: list = []
    anchored_drifts: list[float] = []
    free_disps: list[float] = []
    free_projs: list[float] = []
    free_vecs: list = []
    for key, fpos in fmap.items():
        if key not in rmap:
            continue
        h, bp, direction, copy = key
        disp = fpos - rmap[key]
        dist = float(np.linalg.norm(disp))
        proj = float(np.dot(disp, fdir))
        is_anchor = (h, bp, direction) in anchor_set
        per_nt.append({
            "helix_id": h, "bp_index": bp, "direction": direction, "copy": copy,
            "disp_vec_nm": [float(x) for x in disp],
            "disp_nm": dist, "proj_along_field_nm": proj, "anchored": is_anchor,
        })
        if is_anchor:
            anchored_drifts.append(dist)
        else:
            free_disps.append(dist)
            free_projs.append(proj)
            free_vecs.append(disp)

    if not free_disps:
        raise ValueError("field_response_profile: no free (non-anchored) nucleotides to measure")

    anchored_max = max(anchored_drifts) if anchored_drifts else 0.0
    anchored_mean = float(np.mean(anchored_drifts)) if anchored_drifts else 0.0
    free_mean = float(np.mean(free_disps))
    free_proj = float(np.mean(free_projs))
    deflection_vec = np.mean(np.asarray(free_vecs), axis=0)

    held = anchored_max <= anchor_tol_nm
    deflected = free_proj >= min_free_proj_nm
    reasons = []
    if not held:
        reasons.append(f"anchors drifted {anchored_max:.2f} nm > {anchor_tol_nm} nm tol")
    if not deflected:
        reasons.append(f"free motion along field {free_proj:.2f} nm < {min_free_proj_nm} nm min")
    return {
        "field_dir": [float(x) for x in fdir],
        "per_nt": per_nt,
        "deflection_vec_nm": [float(x) for x in deflection_vec],
        "anchored_max_drift_nm": anchored_max,
        "anchored_mean_drift_nm": anchored_mean,
        "free_mean_disp_nm": free_mean,
        "free_proj_along_field_nm": free_proj,
        "n_anchored": len(anchored_drifts),
        "n_free": len(free_disps),
        "passed": held and deflected,
        "reason": "; ".join(reasons) or "anchors held; structure deflected along the field",
    }


def _free_vec_map(profile) -> dict:
    """``{(helix, bp, dir, copy): np.array(disp_vec)}`` over the FREE nucleotides of a
    :func:`field_response_profile` result — the substrate the cross-engine comparison
    correlates."""
    return {(e["helix_id"], e["bp_index"], e["direction"], e["copy"]):
            np.asarray(e["disp_vec_nm"], dtype=float)
            for e in profile.get("per_nt", []) if not e["anchored"]}


def compare_field_response(candidate_profile, reference_profile) -> dict:
    """Cross-engine agreement of two :func:`field_response_profile` deflection fields.

    Over the FREE nucleotides both engines share, the per-nt displacement vectors are
    concatenated into one long vector per engine; ``cosine_similarity`` is the cosine of
    those (do both engines deflect the structure the same way? +1 identical, 0 orthogonal,
    −1 opposite) and ``magnitude_ratio`` is ‖candidate‖/‖reference‖ (one engine more
    compliant than the other).  Returns ``{cosine_similarity, magnitude_ratio,
    n_shared_free}`` — the scalars are ``None`` when no free nucleotides overlap or a
    deflection field is degenerate (zero-length -> cosine undefined, no divide-by-zero)."""
    c = _free_vec_map(candidate_profile)
    r = _free_vec_map(reference_profile)
    shared = sorted(set(c) & set(r))
    if not shared:
        return {"cosine_similarity": None, "magnitude_ratio": None, "n_shared_free": 0}
    cv = np.concatenate([c[k] for k in shared])
    rv = np.concatenate([r[k] for k in shared])
    cn = float(np.linalg.norm(cv))
    rn = float(np.linalg.norm(rv))
    cosine = None if cn < 1e-12 or rn < 1e-12 else _finite_or_none(float(np.dot(cv, rv)) / (cn * rn))
    ratio = None if rn < 1e-12 else _finite_or_none(cn / rn)
    return {"cosine_similarity": cosine, "magnitude_ratio": ratio, "n_shared_free": len(shared)}
