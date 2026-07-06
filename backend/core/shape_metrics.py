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

import numpy as np

from backend.core.constants import BDNA_BP_PER_TURN, BDNA_RISE_PER_BP
from backend.core.oxdna_health import (
    _bundle_axis_frame,
    _chord_sagitta_bend,
    _kabsch_superpose,
    bundle_slab_centreline,
    measure_bundle_twist,
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
