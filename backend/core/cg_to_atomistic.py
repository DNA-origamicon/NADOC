"""
CG-to-atomistic bridge: read a relaxed oxDNA configuration and produce
an AtomisticModel whose helix axes are fitted to the CG backbone positions.

Approach: per-helix axis fit
-----------------------------
Individual CG nucleotide positions have local positional disorder (up to
~0.5 nm from oxDNA MC fluctuations) that would corrupt the all-atom template
placement if used directly as backbone positions.  Instead, we fit a smooth
helix axis per-helix using PCA of the CG backbone centroids, then rebuild the
ideal B-DNA atomistic model along those fitted axes.

This captures the key benefit of CG pre-relaxation — the helices settle to
their correct global positions relative to each other, which resolves crossover
terminal atom clashes — while avoiding the local-disorder problem.

Pipeline
--------
1. Export oxDNA package from the current design.
2. Run oxDNA relaxation (``oxDNA input.txt`` → ``last_conf.dat``).
3. Call ``build_atomistic_model_from_cg(design, last_conf.dat)`` which:
   a. Reads relaxed backbone positions from the .dat file.
   b. For each helix, fits a line (PCA) through the CG backbone centroids.
   c. Builds a modified Design with updated helix axis_start/axis_end.
   d. Calls ``build_atomistic_model(modified_design)`` for regular ideal-B-DNA
      template placement along the CG-fitted axes.
4. Pass the returned AtomisticModel to ``build_gromacs_package``.
"""

from __future__ import annotations

import copy
from pathlib import Path

import numpy as np

from backend.core.models import Design, Helix, Direction, Vec3
from backend.core.atomistic import AtomisticModel, build_atomistic_model
from backend.physics.oxdna_interface import read_configuration
from backend.core.constants import BDNA_RISE_PER_BP


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
    configuration rather than the original ideal B-DNA axes.

    Parameters
    ----------
    design    : Design — must match the topology used to generate the conf.
    conf_path : Path to a relaxed oxDNA .dat file (e.g. ``last_conf.dat``).

    Returns
    -------
    AtomisticModel with ideal B-DNA geometry placed along the CG-fitted axes.
    Crossover terminal atom clashes are resolved because the helices are now
    at their equilibrium relative positions.
    """
    cg_positions = read_configuration(conf_path, design)
    design_cg = _refit_helix_axes(design, cg_positions)
    return build_atomistic_model(design_cg)
