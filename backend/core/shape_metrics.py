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
