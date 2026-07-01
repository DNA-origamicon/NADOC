"""Spatially-resolved twist profile for one exp31 run — cumulative twist vs position.

The scalar `twist_diff` says HOW MUCH a bundle is twisted; this says WHERE. The cumulative
twist (cross-section rotation accumulated from one end) is plotted against position along the
bundle at ~24-bp resolution. A straight line 0→total means UNIFORM twist (a uniform skip
density corrects it); a kinked profile localises over/under-wound regions where a LOCAL skip
edit is needed — the actionable signal for local twist correction.

Position is the **axial projection** (then expressed as a bp coordinate), NOT bp-index: square-
lattice helices alternate polarity, so a given bp-index sits at opposite ends on FORWARD vs
REVERSE helices — only the axis projection is a consistent cross-bundle position coordinate
(the same reason `measure_bundle_twist` projects onto the fitted axis).

Differential (sim − analytic) like the scalar twist, so the measurement's small fixed offset
cancels and the straight analytic design reads ~flat-zero.
"""
from __future__ import annotations

import csv
import pathlib

import numpy as np

from backend.core.oxdna_health import (
    measure_bundle_curvature_profile, measure_bundle_twist_profile)

_PROFILE_FIELDS = ["position_bp", "position_frac", "cum_twist_sim",
                   "cum_twist_analytic", "cum_twist_diff"]
_CURV_FIELDS = ["position_bp", "position_frac", "cum_curv_sim",
                "cum_curv_analytic", "cum_curv_diff"]


def compute_twist_profile(core, ref, *, length_bp: int, bp_per_bin: int = 24) -> list[dict]:
    """Per-bin cumulative twist (deg) vs fractional/bp position for one run.

    ``core`` = simulated-mean core positions, ``ref`` = the design's analytic core geometry
    (both from the SAME design).  Bins the bundle axis into ~``bp_per_bin``-wide slabs, takes
    the cumulative cross-section rotation at each, and returns the differential profile
    (sim − analytic, compared at the same fractional position along the bundle).
    """
    n = max(3, round(length_bp / bp_per_bin))
    sim = measure_bundle_twist_profile(core, n_slices=n)
    ana = measure_bundle_twist_profile(ref, n_slices=n)
    st = np.array([p[0] for p in sim]); sv = np.array([p[1] for p in sim])
    at = np.array([p[0] for p in ana]); av = np.array([p[1] for p in ana])

    def _frac(t):
        return (t - t.min()) / (t.max() - t.min()) if t.max() > t.min() else t * 0.0

    sfrac, afrac = _frac(st), _frac(at)
    ana_on_sim = np.interp(sfrac, afrac, av)          # compare at the same fractional position
    diff = sv - ana_on_sim
    pos_bp = sfrac * length_bp
    return [{"position_bp": round(float(b), 1), "position_frac": round(float(f), 4),
             "cum_twist_sim": round(float(s), 2), "cum_twist_analytic": round(float(a), 2),
             "cum_twist_diff": round(float(d), 2)}
            for b, f, s, a, d in zip(pos_bp, sfrac, sv, ana_on_sim, diff)]


def compute_curvature_profile(core, ref, *, length_bp: int, bp_per_bin: int = 24) -> list[dict]:
    """Per-bin cumulative bending (deg) vs position — the curvature analogue of
    :func:`compute_twist_profile`.  Differential (sim − analytic) cumulative turning along the
    centreline; flat ⇒ straight there, a ramp ⇒ a bend, slope ⇒ local curvature."""
    n = max(3, round(length_bp / bp_per_bin))
    sim = measure_bundle_curvature_profile(core, n_slices=n)
    ana = measure_bundle_curvature_profile(ref, n_slices=n)
    if not sim or not ana:
        return []
    st = np.array([p[0] for p in sim]); sv = np.array([p[1] for p in sim])
    at = np.array([p[0] for p in ana]); av = np.array([p[1] for p in ana])

    def _frac(t):
        return (t - t.min()) / (t.max() - t.min()) if t.max() > t.min() else t * 0.0

    sfrac, afrac = _frac(st), _frac(at)
    ana_on_sim = np.interp(sfrac, afrac, av)
    diff = sv - ana_on_sim
    pos_bp = sfrac * length_bp
    return [{"position_bp": round(float(b), 1), "position_frac": round(float(f), 4),
             "cum_curv_sim": round(float(s), 2), "cum_curv_analytic": round(float(a), 2),
             "cum_curv_diff": round(float(d), 2)}
            for b, f, s, a, d in zip(pos_bp, sfrac, sv, ana_on_sim, diff)]


def save_profile_csv(profile: list[dict], path, fields=None) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields or _PROFILE_FIELDS)
        w.writeheader()
        w.writerows(profile)


def plot_twist_profile(profile: list[dict], png_path, *, label: str) -> None:
    """Cumulative twist vs position with the uniform-twist (linear) reference overlaid, so a
    kink (local over/under-wind = a local correction site) is visible against it."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    xs = [p["position_bp"] for p in profile]
    ys = [p["cum_twist_diff"] for p in profile]
    fig, ax = plt.subplots(figsize=(8, 5))
    ax.plot(xs, ys, "-o", color="#1f77b4", markersize=4,
            label="cumulative twist (sim − analytic)")
    if len(xs) >= 2:
        ax.plot([xs[0], xs[-1]], [ys[0], ys[-1]], "--", color="0.6",
                label="uniform-twist reference (linear)")
    ax.axhline(0.0, color="0.85", lw=0.7)
    ax.set_xlabel("position along bundle (bp, axis-projected)")
    ax.set_ylabel("cumulative twist (deg)")
    ax.set_title(f"exp31 twist profile — {label}")
    ax.grid(True, alpha=0.25)
    ax.legend(fontsize=8, loc="best")
    fig.tight_layout()
    pathlib.Path(png_path).parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(png_path, dpi=150)
    plt.close(fig)


def run_label(strategy: str, delta: int) -> str:
    return f"{strategy}_d{delta:+d}"
