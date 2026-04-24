"""
CG-to-atomistic bridge: read a relaxed oxDNA configuration and produce
an AtomisticModel whose backbone positions are informed by the CG trajectory.

Two approaches are implemented:

Phase 3a — per-helix PCA axis refitting (build_atomistic_model_from_cg)
------------------------------------------------------------------------
Fits a PCA line through all CG backbone positions per helix and rebuilds
ideal B-DNA along those axes.  VALIDATED AS INSUFFICIENT: 9,656 EM steps
(CG path) vs 9,787 steps (ideal) — 1.3% difference, within run noise.
Root cause: PCA averages 420+ bp, diluting crossover signal; 0.05-0.10 nm
axis shifts don't change relative helix spacing at crossovers.  Kept for
reference; do NOT use for EM acceleration.

Phase 3b — per-domain Gaussian-smoothed position override (build_atomistic_model_from_cg_spline)
-------------------------------------------------------------------------------------------------
Uses CG backbone positions directly as per-nucleotide position overrides
(MrDNA methodology).  Gaussian smoothing (sigma=2 nt) removes MC positional
noise (~0.3-0.5 nm/nt) within each helix domain without crossing crossover
boundaries.  At crossover junctions, the CG equilibrium positions are used
directly — these are ~0.6-1.4 nm apart vs ~0.05 nm in ideal B-DNA,
eliminating the 10^13 kJ/mol LJ spike.

Pipeline
--------
1. Export oxDNA package from the current design.
2. Run oxDNA relaxation (``oxDNA input.txt`` → ``last_conf.dat``).
3. Call ``build_atomistic_model_from_cg_spline(design, last_conf.dat)`` which:
   a. Reads relaxed backbone positions from the .dat file.
   b. Groups nucleotides by strand domain (helix segment).
   c. Applies Gaussian smoothing within each domain (not across crossovers).
   d. Passes smoothed positions as nuc_pos_override to build_atomistic_model.
4. Pass the returned AtomisticModel to ``build_gromacs_package``.
"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

from backend.core.models import Design, Helix, Direction, Vec3
from backend.core.atomistic import AtomisticModel, build_atomistic_model
from backend.physics.oxdna_interface import read_configuration
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.sequences import domain_bp_range


# ── Phase 3b: per-domain smoothed position override ──────────────────────────


def _smooth_cg_positions_per_domain(
    design: Design,
    cg_positions: dict[tuple[str, int, str], np.ndarray],
    sigma: float = 2.0,
) -> dict[tuple[str, int, str], np.ndarray]:
    """
    Smooth CG backbone positions within each helix domain independently.

    Per-domain Gaussian smoothing (sigma nucleotides) removes MC positional
    noise (~0.3-0.5 nm/nt) while preserving crossover junction geometry.
    Smoothing is applied independently per domain so that positions from
    adjacent helices are never blended together at crossover boundaries.

    Parameters
    ----------
    design       : Design matching the CG configuration.
    cg_positions : Output of read_configuration — (helix_id, bp, dir) → pos nm.
    sigma        : Gaussian smoothing width in nucleotides.  2.0 is recommended:
                   smooths noise while keeping crossover positions close to CG.

    Returns
    -------
    dict mapping (helix_id, bp_index, direction_str) → smoothed position (nm),
    suitable for use as nuc_pos_override in build_atomistic_model.
    """
    smoothed: dict[tuple[str, int, str], np.ndarray] = {}

    for strand in design.strands:
        for domain in strand.domains:
            h_id    = domain.helix_id
            dir_str = domain.direction.value  # "FORWARD" or "REVERSE"

            # Collect bp indices in 5'→3' order for this domain.
            bps = list(domain_bp_range(domain))
            keys = [(h_id, bp, dir_str) for bp in bps]

            # Gather the CG positions that exist for this domain.
            raw_pos: list[np.ndarray] = []
            valid_keys: list[tuple[str, int, str]] = []
            for key in keys:
                pos = cg_positions.get(key)
                if pos is not None:
                    raw_pos.append(pos)
                    valid_keys.append(key)

            if not valid_keys:
                continue

            if len(valid_keys) < 3 or sigma <= 0.0:
                # Too short to smooth meaningfully; use raw CG positions.
                for key, pos in zip(valid_keys, raw_pos):
                    smoothed[key] = pos.copy()
                continue

            pts = np.array(raw_pos)  # shape (N, 3)

            # Gaussian smooth each coordinate axis independently.
            # mode='nearest' avoids edge ringing by clamping boundary values.
            smoothed_pts = gaussian_filter1d(pts, sigma=sigma, axis=0, mode='nearest')

            for key, pos in zip(valid_keys, smoothed_pts):
                smoothed[key] = pos

    return smoothed


def build_atomistic_model_from_cg_spline(
    design: Design,
    conf_path: str | Path,
    sigma: float = 2.0,
) -> AtomisticModel:
    """
    Build an all-atom model using per-domain smoothed CG backbone positions
    as position overrides — the MrDNA-inspired Phase 3b approach.

    CG backbone positions at crossover junctions are ~0.6-1.4 nm apart
    (compared to ~0.05 nm in ideal B-DNA), eliminating the O5'/O1P LJ spike.
    Gaussian smoothing within each helix domain removes MC positional noise
    before the override so backbone bond lengths remain physically correct.

    Parameters
    ----------
    design    : Design — must match the topology used to generate the conf.
    conf_path : Path to a relaxed oxDNA .dat file (e.g. ``last_conf.dat``).
    sigma     : Gaussian smoothing width in nucleotides (default 2.0).

    Returns
    -------
    AtomisticModel with CG-informed backbone positions.
    """
    cg_positions = read_configuration(conf_path, design)
    pos_override = _smooth_cg_positions_per_domain(design, cg_positions, sigma=sigma)
    return build_atomistic_model(design, nuc_pos_override=pos_override)


# ── Phase 3a: per-helix PCA axis refitting (kept for reference) ───────────────


def _fit_helix_axis(
    positions: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """
    Fit a line through a set of 3D points using PCA.

    Returns (centroid, unit_direction) where direction is the first principal
    component (longest variance axis).
    """
    centroid = positions.mean(axis=0)
    _, _, Vt = np.linalg.svd(positions - centroid, full_matrices=False)
    direction = Vt[0]  # first principal component
    direction /= np.linalg.norm(direction) + 1e-14
    return centroid, direction


def _project_onto_axis(
    point: np.ndarray,
    centroid: np.ndarray,
    direction: np.ndarray,
) -> float:
    """Scalar projection of point onto the axis defined by (centroid, direction)."""
    return float(np.dot(point - centroid, direction))


def _refit_helix_axes(
    design: Design,
    cg_positions: dict[tuple[str, int, str], np.ndarray],
) -> Design:
    """
    Return a copy of *design* with each helix's axis_start/axis_end replaced
    by the axis fitted to the CG backbone positions for that helix.

    For helices with no CG positions (none of their nucleotides appear in
    cg_positions), the original axis is kept.
    """
    # Group CG backbone positions by helix_id.
    helix_pts: dict[str, list[np.ndarray]] = {}
    for (h_id, bp, direction), pos in cg_positions.items():
        helix_pts.setdefault(h_id, []).append(pos)

    new_helices: list[Helix] = []
    for helix in design.helices:
        pts_list = helix_pts.get(helix.id)
        if pts_list is None or len(pts_list) < 2:
            new_helices.append(helix)
            continue

        pts = np.array(pts_list)
        centroid, fitted_dir = _fit_helix_axis(pts)

        # Ensure fitted direction points in the same half-space as the original
        # helix axis (avoid axis flip).
        orig_start = np.array([helix.axis_start.x, helix.axis_start.y, helix.axis_start.z])
        orig_end   = np.array([helix.axis_end.x,   helix.axis_end.y,   helix.axis_end.z])
        orig_dir   = orig_end - orig_start
        orig_dir  /= np.linalg.norm(orig_dir) + 1e-14
        if np.dot(fitted_dir, orig_dir) < 0:
            fitted_dir = -fitted_dir

        # Project the original axis_start and axis_end onto the fitted line to
        # get new start/end that preserve the bp_start/bp_end mapping.
        new_start = centroid + _project_onto_axis(orig_start, centroid, fitted_dir) * fitted_dir
        new_end   = centroid + _project_onto_axis(orig_end,   centroid, fitted_dir) * fitted_dir

        new_helix = helix.model_copy(update={
            "axis_start": Vec3(x=float(new_start[0]), y=float(new_start[1]), z=float(new_start[2])),
            "axis_end":   Vec3(x=float(new_end[0]),   y=float(new_end[1]),   z=float(new_end[2])),
        })
        new_helices.append(new_helix)

    return design.model_copy(update={"helices": new_helices})


def build_atomistic_model_from_cg(
    design: Design,
    conf_path: str | Path,
) -> AtomisticModel:
    """
    Build an all-atom model using helix axes fitted to a relaxed oxDNA
    configuration (Phase 3a — per-helix PCA axis refitting).

    NOTE: Validated 2026-04-20 as providing no EM benefit vs ideal B-DNA
    (9,656 steps CG vs 9,787 steps ideal — 1.3% difference, within noise).
    Use build_atomistic_model_from_cg_spline (Phase 3b) instead.
    """
    cg_positions = read_configuration(conf_path, design)
    design_cg = _refit_helix_axes(design, cg_positions)
    return build_atomistic_model(design_cg)
