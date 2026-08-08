"""
mrDNA curvature report — compares a design's ANALYTIC (Dietz continuum) curvature
against the curvature mrDNA/ARBD actually produced.

The main purpose of the mrDNA CG panel is quick-checking designs with curvature.
Curvature in DNA origami is programmed with loop (insertion) / skip (deletion)
marks (Dietz, Douglas & Shih, Science 2009); NADOC's own continuum model
(``loop_skip_calculator.predict_radius_nm``) gives the *designed* radius of
curvature from that mark pattern.  This module pairs that analytic prediction with
the radius measured from the mrDNA-relaxed structure, so the panel can show
"designed vs simulated" curvature at a glance.

IMPORTANT — twist coupling: Dietz curvature is a twist-coupled effect (a skip
overtwists and bends inward, a loop undertwists and bends outward).  mrDNA's
COARSE stage is generated without twist, so it does NOT develop the bend — only
the FINE stage (with orientation/twist) does.  A curvature check therefore needs a
FINE run; a coarse-only run reads ~straight regardless of the marks.

Physical-layer / read-only: measures display positions, never mutates topology.
"""

from __future__ import annotations

import math
from typing import Optional

import numpy as np

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import Design


def _loop_skip_modifications(design: Design) -> tuple[dict, list, int, int]:
    """Return (modifications, segment_helices, n_loops, n_skips) from the design's
    loop/skip marks — the input to the analytic Dietz model."""
    mods = {h.id: list(h.loop_skips or []) for h in design.helices}
    n_loops = sum(
        ls.delta for h in design.helices for ls in (h.loop_skips or []) if ls.delta > 0
    )
    n_skips = sum(
        -ls.delta for h in design.helices for ls in (h.loop_skips or []) if ls.delta < 0
    )
    return mods, list(design.helices), n_loops, n_skips


def analytic_curvature(
    design: Design, *, direction_deg: Optional[float] = None
) -> dict:
    """Designed curvature from the loop/skip pattern via NADOC's continuum model.

    Scans the bend direction for the maximum curvature when ``direction_deg`` is
    None (the pattern's own bend axis).  Returns radius_nm=inf / kappa=0 when the
    design has no curvature-inducing marks.
    """
    from backend.core.loop_skip_calculator import _cell_boundaries, predict_radius_nm

    mods, helices, n_loops, n_skips = _loop_skip_modifications(design)
    all_bp = [ls.bp_index for h in design.helices for ls in (h.loop_skips or [])]
    out = {
        "radius_nm": math.inf,
        "kappa_deg_per_nm": 0.0,
        "bend_deg": 0.0,
        "direction_deg": 0.0,
        "n_loops": n_loops,
        "n_skips": n_skips,
        "has_marks": bool(all_bp),
    }
    if not all_bp:
        return out
    pa, pb = min(all_bp), max(all_bp)

    dirs = [direction_deg] if direction_deg is not None else range(0, 360, 5)
    best_r, best_dir = math.inf, 0.0
    for dd in dirs:
        r = predict_radius_nm(helices, mods, pa, pb, direction_deg=float(dd))
        if r < best_r:
            best_r, best_dir = r, float(dd)
    n_cells = len(_cell_boundaries(pa, pb))
    seg_len_nm = n_cells * 7 * BDNA_RISE_PER_BP
    if math.isfinite(best_r) and best_r > 1e-6:
        out["radius_nm"] = best_r
        out["kappa_deg_per_nm"] = math.degrees(1.0 / best_r)
        out["bend_deg"] = math.degrees(seg_len_nm / best_r)
        out["direction_deg"] = best_dir
    return out


def _slab_centroids(positions: list[dict], n_slices: int = 15) -> "np.ndarray | None":
    """Base-pair-midpoint slab centroids along the bundle axis (the centreline)."""
    from backend.core.oxdna_health import _bundle_axis_frame

    bp_pts: dict = {}
    for p in positions:
        bp_pts.setdefault((p["helix_id"], int(p["bp_index"])), []).append(
            np.asarray(p["backbone_position"], dtype=float)
        )
    pts = np.array([np.mean(v, axis=0) for v in bp_pts.values()])
    if len(pts) < n_slices:
        return None
    C, L, _e1, _e2 = _bundle_axis_frame(pts)
    t = (pts - C) @ L
    if float(t.max() - t.min()) < 1e-6:
        return None
    edges = np.linspace(t.min(), t.max(), n_slices + 1)
    slab = np.clip(np.digitize(t, edges[1:-1]), 0, n_slices - 1)
    cen = [pts[slab == k].mean(axis=0) for k in range(n_slices) if np.any(slab == k)]
    return np.array(cen) if len(cen) >= 3 else None


def measured_curvature(positions: list[dict]) -> dict:
    """Curvature measured from the mrDNA-relaxed display positions.

    ``bend_deg`` is the end-to-end deflection of the bundle centreline (the stable
    primary metric); ``radius_nm`` / ``kappa_deg_per_nm`` are DERIVED from it over
    the centreline arc length.  We deliberately do NOT use a circular-arc fit as the
    primary radius — for the short, thermally-noisy CG structures these checks run
    on, the circle fit is noise-dominated (swings wildly run-to-run).  A straight
    (or too-small) structure returns radius_nm=inf / kappa=0.
    """
    from backend.core.oxdna_health import measure_bundle_bend

    out = {"radius_nm": math.inf, "kappa_deg_per_nm": 0.0, "bend_deg": 0.0}
    if not positions:
        return out
    cen = _slab_centroids(positions)
    if cen is None:
        return out
    arc_len = float(np.linalg.norm(np.diff(cen, axis=0), axis=1).sum())
    try:
        bend = float(measure_bundle_bend(positions))
    except Exception:  # noqa: BLE001
        bend = 0.0
    out["bend_deg"] = bend
    if bend > 1e-3 and arc_len > 1e-6:
        out["kappa_deg_per_nm"] = bend / arc_len
        out["radius_nm"] = arc_len / math.radians(bend)
    return out


def curvature_report(design: Design, positions: Optional[list[dict]]) -> dict:
    """Designed (analytic) vs simulated (mrDNA) curvature, plus an agreement ratio.

    ``ratio`` = simulated κ / analytic κ (1.0 = perfect); None when either side has
    no curvature.  ``positions`` None → analytic only (available before a run).
    """
    analytic = analytic_curvature(design)
    measured = measured_curvature(positions) if positions else None
    ratio = None
    if (
        measured
        and analytic["kappa_deg_per_nm"] > 1e-6
        and measured["kappa_deg_per_nm"] > 1e-6
    ):
        ratio = measured["kappa_deg_per_nm"] / analytic["kappa_deg_per_nm"]
    return {"analytic": analytic, "measured": measured, "ratio": ratio}
