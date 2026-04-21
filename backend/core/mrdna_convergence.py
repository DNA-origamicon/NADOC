"""
Generalised convergence metric for mrdna coarse-grained simulations.

FTT — Fraction to Target
    FTT = 1 − d_chamfer(current_beads, target_axis_points)
              / d_chamfer(initial_beads, target_axis_points)

    where d_chamfer is the mean nearest-neighbour distance (Chamfer distance)
    from each CG bead to the closest point on any deformed helix axis.

    FTT = 0  →  simulation is at the initial (undeformed) geometry
    FTT = 1  →  simulation has reached the deformed target geometry

Target axis points come from NADOC's own deformation model via
`deformed_helix_axes(design)`, so no manual parameter tuning is needed.
For designs with no deformations the function returns None (no meaningful
target exists).

This Chamfer-based metric is robust to large conformational changes
(e.g. 180° U-shape folding) where helix-centroid metrics fail because CG
beads are mis-assigned to helices after the structure folds.

Typical usage
─────────────
    from backend.core.mrdna_convergence import ConvergenceTracker

    tracker = ConvergenceTracker(design, psf_path, pdb_path, output_every=200_000)
    steps, ftts = tracker.read_dcd(dcd_path)
    fit = tracker.fit(steps, ftts)
    print(f"FTT={ftts[-1]:.2%}  projected crossing: {fit.crossing_steps/1e6:.0f}M steps")
"""

from __future__ import annotations
import math
import warnings
from dataclasses import dataclass
from typing import Optional

import numpy as np


# ── Target geometry ────────────────────────────────────────────────────────────

def _target_axis_points_nm(design) -> Optional[np.ndarray]:
    """
    Return (M, 3) array of sampled points along all deformed helix axes in nm.
    Returns None if the design has no deformations.
    """
    from backend.core.deformation import deformed_helix_axes
    if not design.deformations and not design.cluster_transforms:
        return None

    axes = deformed_helix_axes(design)
    pts  = []
    for ax in axes:
        pts.append(np.array(ax['samples'], dtype=float))
    return np.concatenate(pts, axis=0)   # (M, 3) in nm


def _target_helix_centroids_nm(design) -> Optional[np.ndarray]:
    """
    Return (N_helices, 3) centroid positions in nm from deformed helix axes.
    Kept for backward-compat / diagnostics; not used in FTT computation.
    """
    from backend.core.deformation import deformed_helix_axes
    if not design.deformations and not design.cluster_transforms:
        return None

    axes = deformed_helix_axes(design)
    return np.array([np.array(ax['samples'], dtype=float).mean(axis=0)
                     for ax in axes])


def _initial_helix_centroids_nm(design) -> np.ndarray:
    """
    Return (N_helices, 3) straight-geometry centroid positions in nm.
    Midpoint of each helix's axis_start / axis_end.
    """
    centroids = []
    for h in design.helices:
        s = h.axis_start.to_array()
        e = h.axis_end.to_array()
        centroids.append((s + e) / 2.0)
    return np.array(centroids)


# ── Chamfer (mean nearest-neighbour) distance ──────────────────────────────────

def _chamfer_dist_nm(bead_pos_ang: np.ndarray, target_nm: np.ndarray) -> float:
    """
    Mean distance (nm) from each CG bead to its nearest target axis point.

    bead_pos_ang : (N_beads, 3) in Å (MDAnalysis convention)
    target_nm    : (M, 3) in nm
    Returns      : scalar mean distance in nm
    """
    bead_nm  = bead_pos_ang / 10.0                              # Å → nm
    diff     = bead_nm[:, None, :] - target_nm[None, :, :]     # (N, M, 3)
    dists    = np.linalg.norm(diff, axis=2)                     # (N, M)
    min_dist = dists.min(axis=1)                                # (N,)
    return float(min_dist.mean())


def fraction_to_target_chamfer(
    current_ang: np.ndarray,
    initial_ang: np.ndarray,
    target_nm:   np.ndarray,
) -> float:
    """
    FTT ∈ [0, 1] via Chamfer distance.

    current_ang, initial_ang : (N_beads, 3) bead positions in Å
    target_nm                : (M, 3) deformed axis sample points in nm
    """
    d_init = _chamfer_dist_nm(initial_ang, target_nm)
    if d_init < 1e-6:
        return 1.0
    d_curr = _chamfer_dist_nm(current_ang, target_nm)
    return float(np.clip(1.0 - d_curr / d_init, 0.0, 1.0))


# ── Legacy helpers (kept for external callers / diagnostics) ──────────────────

def _bead_helix_assignments(bead_pos_ang: np.ndarray, design) -> np.ndarray:
    """
    Assign each CG bead to the nearest helix by 3-D axis-line distance.
    Not used in FTT computation; kept for diagnostics and backward compat.
    """
    origins  = np.array([h.axis_start.to_array() * 10.0 for h in design.helices])
    ends     = np.array([h.axis_end.to_array()   * 10.0 for h in design.helices])
    dirs     = ends - origins
    len2     = (dirs ** 2).sum(axis=1, keepdims=True)
    dirs_hat = dirs / np.maximum(len2, 1e-12)

    diff  = bead_pos_ang[:, None, :] - origins[None, :, :]
    proj  = (diff * dirs_hat[None, :, :]).sum(axis=2, keepdims=True)
    perp  = diff - proj * dirs_hat[None, :, :]
    dists = np.linalg.norm(perp, axis=2)
    return dists.argmin(axis=1)


def _helix_centroids_from_beads(
    bead_pos_ang: np.ndarray,
    assignments:  np.ndarray,
    n_helices:    int,
) -> np.ndarray:
    """Return (N_helices, 3) centroid positions in nm. Kept for diagnostics."""
    centroids = np.zeros((n_helices, 3), dtype=float)
    for i in range(n_helices):
        mask = assignments == i
        if mask.any():
            centroids[i] = bead_pos_ang[mask].mean(axis=0) / 10.0
    return centroids


def _rmsd(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(((a - b) ** 2).sum(axis=1).mean()))


def fraction_to_target(
    current:  np.ndarray,
    initial:  np.ndarray,
    target:   np.ndarray,
) -> float:
    """Legacy centroid-RMSD FTT. Prefer fraction_to_target_chamfer for folding designs."""
    d_init = _rmsd(initial, target)
    if d_init < 1e-6:
        return 1.0
    d_curr = _rmsd(current, target)
    return float(np.clip(1.0 - d_curr / d_init, 0.0, 1.0))


# ── Exponential fit ────────────────────────────────────────────────────────────

@dataclass
class FTTFit:
    ftt_max:        float
    tau:            float
    crossing_steps: Optional[float]
    plateau:        bool
    threshold:      float


def _ftt_model(t, ftt_max, tau):
    return ftt_max * (1.0 - np.exp(-t / tau))


def fit_ftt(
    steps:     list[int],
    ftts:      list[float],
    threshold: float = 0.85,
) -> Optional[FTTFit]:
    """
    Fit FTT(t) = ftt_max * (1 − exp(−t/τ)).
    Returns None if fewer than 6 data points.
    """
    from scipy.optimize import curve_fit

    if len(steps) < 6:
        return None

    t = np.array(steps, dtype=float)
    f = np.array(ftts,  dtype=float)

    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            popt, _ = curve_fit(
                _ftt_model, t, f,
                p0=[min(1.0, f[-1] * 1.5), t[-1] * 2.0],
                bounds=([0.1, t[1] if len(t) > 1 else 1.0], [2.0, 1e11]),
                maxfev=20_000,
            )
        ftt_max, tau = popt

        crossing = None
        if ftt_max > threshold:
            arg = 1.0 - threshold / ftt_max
            if 0 < arg < 1:
                crossing = -tau * math.log(arg)

        slope_now = ftt_max / tau * math.exp(-t[-1] / tau)
        plateau   = slope_now < 1e-8

        return FTTFit(
            ftt_max=float(ftt_max),
            tau=float(tau),
            crossing_steps=crossing,
            plateau=plateau,
            threshold=threshold,
        )
    except Exception:
        return None


# ── ConvergenceTracker ────────────────────────────────────────────────────────

class ConvergenceTracker:
    """
    Stateful helper that computes FTT for each DCD frame using the Chamfer
    distance from CG beads to deformed helix axis sample points.

    The Chamfer metric is robust to large conformational changes (e.g. 180°
    U-shape folding) where centroid-based metrics fail due to bead mis-assignment.

    Parameters
    ----------
    design          : loaded NADOC Design
    psf_path        : coarse ARBD .psf file (first stage that started at ideal geometry)
    pdb_path        : coarse ARBD .pdb file (initial coordinates)
    output_every    : steps between DCD frames (= coarse_output_period)
    threshold       : FTT value considered "converged" (default 0.90)
    """

    def __init__(
        self,
        design,
        psf_path:     str,
        pdb_path:     str,
        output_every: int   = 200_000,
        threshold:    float = 0.90,
    ):
        self.design       = design
        self.psf_path     = psf_path
        self.output_every = output_every
        self.threshold    = threshold

        import MDAnalysis as mda

        ref      = mda.Universe(psf_path, pdb_path)
        init_pos = ref.atoms.positions     # Å

        self.target_pts = _target_axis_points_nm(design)  # (M, 3) nm or None
        if self.target_pts is None:
            raise ValueError(
                "Design has no deformations — FTT metric requires a target geometry."
            )

        self.initial_pos = init_pos.copy()  # Å — reference for d_init
        self.d_init = _chamfer_dist_nm(init_pos, self.target_pts)

        print(
            f"[convergence] {len(design.helices)} helices | "
            f"{len(self.target_pts)} target pts | "
            f"initial Chamfer dist = {self.d_init:.2f} nm",
            flush=True,
        )

    def read_dcd(
        self,
        dcd_path: str,
        step_offset: int = 0,
    ) -> tuple[list[int], list[float]]:
        """
        Read all available DCD frames and return (steps, ftts).
        step_offset allows concatenating multiple stage DCDs.
        """
        import MDAnalysis as mda

        try:
            u     = mda.Universe(self.psf_path, dcd_path)
            atoms = u.select_atoms('all')
            steps, ftts = [], []
            for ts in u.trajectory:
                pos = atoms.positions
                d_curr = _chamfer_dist_nm(pos, self.target_pts)
                ftt    = float(np.clip(1.0 - d_curr / self.d_init, 0.0, 1.0))
                steps.append(step_offset + ts.frame * self.output_every)
                ftts.append(ftt)
            return steps, ftts
        except Exception:
            return [], []

    def fit(
        self,
        steps: list[int],
        ftts:  list[float],
    ) -> Optional[FTTFit]:
        return fit_ftt(steps, ftts, self.threshold)

    def projected_steps(
        self,
        steps: list[int],
        ftts:  list[float],
    ) -> Optional[float]:
        """Convenience: return projected crossing step count, or None."""
        result = self.fit(steps, ftts)
        return result.crossing_steps if result else None
