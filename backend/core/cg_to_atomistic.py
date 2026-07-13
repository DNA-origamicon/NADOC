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

from pathlib import Path

import numpy as np
from scipy.ndimage import gaussian_filter1d

from backend.core.models import Design, Helix, Vec3
from backend.core.atomistic import AtomisticModel, build_atomistic_model
from backend.physics.oxdna_interface import (
    read_configuration,
    read_configuration_full_unwrapped,
    oxdna_backbone_site,
)
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


def deformed_helix_axes(
    design: Design,
    full_map: dict[tuple[str, int, str], dict],
    sigma: float = 2.0,
) -> dict[tuple[str, int], tuple[np.ndarray, np.ndarray]]:
    """Per-(helix, bp) deformed centerline point + local tangent from a relaxed CG map.

    The atomistic placer derives each nucleotide's radial direction (hence its
    helical phase) from ``backbone - axis_point``.  By default ``axis_point`` is the
    helix's IDEAL straight axis; once a helix has bent/shifted in the relaxed CG
    structure, that straight reference makes the global displacement swamp the true
    radial — the twist collapses and adjacent nucleotides pile up (the seed-clash
    bug).  This returns the BENT centerline so the radial is measured correctly.

    Centerline per bp = midpoint of the two paired strands' centres of mass (which
    straddle the helix axis); built only from base-paired bps (a single strand's CM
    sits off-axis), then linearly filled across the helix's bp span, Gaussian
    smoothed, and differentiated for the local tangent.  The tangent is sign-aligned
    to the helix's original axis direction so FORWARD/REVERSE polarity is preserved.
    Helices with fewer than two paired bps are omitted (fall back to the straight
    axis).  Physical-layer only — never written back into topology.
    """
    axis_dir = {}
    for h in design.helices:
        d = np.array([h.axis_end.x - h.axis_start.x,
                      h.axis_end.y - h.axis_start.y,
                      h.axis_end.z - h.axis_start.z], dtype=float)
        n = np.linalg.norm(d)
        axis_dir[h.id] = d / n if n > 1e-9 else np.array([0.0, 0.0, 1.0])

    by_helix: dict[str, dict[int, dict[str, np.ndarray]]] = {}
    for (h_id, bp, dr), rec in full_map.items():
        by_helix.setdefault(h_id, {}).setdefault(bp, {})[dr] = np.asarray(
            rec["backbone_position"], dtype=float)

    out: dict[tuple[str, int], tuple[np.ndarray, np.ndarray]] = {}
    for h_id, bpmap in by_helix.items():
        paired_bp: list[int] = []
        paired_pt: list[np.ndarray] = []
        for bp in sorted(bpmap):
            dd = bpmap[bp]
            if "FORWARD" in dd and "REVERSE" in dd:
                paired_bp.append(bp)
                paired_pt.append(0.5 * (dd["FORWARD"] + dd["REVERSE"]))
        if len(paired_bp) < 2:
            continue
        kb = np.array(paired_bp)
        kp = np.array(paired_pt)
        core_bps = np.arange(paired_bp[0], paired_bp[-1] + 1)
        axis = np.stack([np.interp(core_bps, kb, kp[:, c]) for c in range(3)], axis=1)
        if sigma > 0 and len(core_bps) >= 3:
            axis = gaussian_filter1d(axis, sigma=sigma, axis=0, mode="nearest")
        tang = np.gradient(axis, axis=0)
        tn = np.linalg.norm(tang, axis=1, keepdims=True)
        tang = tang / np.where(tn < 1e-9, 1.0, tn)
        # Sign-align to the helix's original axis direction (no FWD/REV flip).
        if axis_dir.get(h_id) is not None and float(np.dot(tang.mean(axis=0), axis_dir[h_id])) < 0:
            tang = -tang

        # Cover EVERY bp present on the helix — single-stranded overhang ends sit
        # OUTSIDE the paired range, and without an axis there they fall back to the
        # straight ideal axis and re-clash.  Extrapolate the smoothed centerline
        # straight along its end tangent (an overhang continues the helix), one
        # centerline-rise step per bp.
        step0 = axis[1] - axis[0]
        stepN = axis[-1] - axis[-2]
        lo = min(bpmap)
        hi = max(bpmap)
        for bp in range(lo, hi + 1):
            if bp < paired_bp[0]:
                pt, tg = axis[0] + (bp - paired_bp[0]) * step0, tang[0]
            elif bp > paired_bp[-1]:
                pt, tg = axis[-1] + (bp - paired_bp[-1]) * stepN, tang[-1]
            else:
                idx = bp - paired_bp[0]
                pt, tg = axis[idx], tang[idx]
            out[(h_id, int(bp))] = (pt, tg)
    return out


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

    The oxDNA ``.dat`` stores each nucleotide's CENTRE OF MASS, which sits
    ~0.34 units inward of the backbone.  Using the raw CM (as ``read_configuration``
    returns) makes the seeded atomistic duplex too THIN (paired backbones ~1.0 nm
    apart instead of ~1.6 nm) → backbone atoms of paired strands clash at NAMD
    startup — the very thing the relaxation is meant to prevent.  So we reconstruct
    the true backbone site (``oxdna_backbone_site``) from the CM + a1/a3 before
    smoothing.

    Parameters
    ----------
    design    : Design — must match the topology used to generate the conf.
    conf_path : Path to a relaxed oxDNA .dat file (e.g. ``last_conf.dat``).
    sigma     : Gaussian smoothing width in nucleotides (default 2.0).

    Returns
    -------
    AtomisticModel with CG-informed backbone positions.
    """
    # PBC make-whole: DEFENSIVE — an E-field/surface run can stream the structure
    # across a box face; a wrapped strand would make the backbone spline overshoot.
    # No-op for a structure already whole in [0,L) (the common case).
    full_map = read_configuration_full_unwrapped(conf_path, design)
    # RAW backbone sites (no per-nucleotide smoothing): the override supplies each
    # nucleotide's radial DIRECTION (its helical phase) relative to the deformed
    # axis below; Gaussian-smoothing the per-nucleotide positions flattens the
    # spiral and collapses the ~34°/bp twist, stacking adjacent nucleotides (clash).
    # The axis (not the per-nucleotide phase) is what gets smoothed.
    pos_override = {
        key: oxdna_backbone_site(rec["backbone_position"], rec["a1"], rec["a3"])
        for key, rec in full_map.items()
    }
    # Deformed centerline so the placer measures each nucleotide's radial (helical
    # phase) against the BENT axis, not the ideal straight one — without this a
    # displaced helix collapses the twist and piles atoms together (seed clashes).
    axis_override = deformed_helix_axes(design, full_map, sigma=sigma)
    # apply_design_geometry=False: the CG override already gives each nucleotide's FINAL
    # world position (deformed + cluster-transformed, then oxDNA-relaxed).  Letting
    # build_atomistic_model re-apply the design's deformations/cluster transforms on top
    # would DOUBLE them — the ~N× explosion when seeding copy-pasted, rotated clusters.
    # The seed is a pure function of the oxDNA positions; pre-oxDNA transforms don't apply.
    model = build_atomistic_model(
        design, nuc_pos_override=pos_override, axis_override=axis_override,
        apply_design_geometry=False)

    # Safety net: the reconstruction must preserve the CG structure's extent.  If a
    # future seed still blows up (e.g. an unwrapped/torn conf), fail with an actionable
    # message rather than writing a corrupt PDB whose overflowing coordinates crash NAMD
    # downstream with a cryptic error.  (A correct reconstruction reconstructs at ~1×.)
    if model.atoms and full_map:
        cg = np.asarray([r["backbone_position"] for r in full_map.values()])
        at = np.asarray([[a.x, a.y, a.z] for a in model.atoms])
        cg_span = float(np.ptp(cg, axis=0).max())
        at_span = float(np.ptp(at, axis=0).max())
        if cg_span > 1.0 and at_span > 2.0 * cg_span:
            raise ValueError(
                f"oxDNA→atomistic reconstruction exploded the structure "
                f"({cg_span:.0f} nm CG → {at_span:.0f} nm all-atom, {at_span/cg_span:.1f}×). "
                f"The relaxed conf could not be reconstructed cleanly — re-run the oxDNA "
                f"relaxation, or seed from a conformation that fits within one box."
            )
    return model


def read_backbone_positions(
    conf_path: str | Path,
    design:    Design,
) -> dict[tuple[str, int, str], np.ndarray]:
    """
    Read a relaxed oxDNA configuration and return the reconstructed true
    BACKBONE position per nucleotide (nm), not the raw centre of mass.

    oxDNA's ``.dat`` position is the centre of mass; the backbone phosphate sits
    ~0.34 units outward along a1/a2 (oxDNA2, ``model.h`` POS_MM_BACK1/2).  This
    helper applies ``oxdna_backbone_site`` per nucleotide so downstream
    atomistic seeding gets a ~1.6 nm cross-pair duplex (near B-DNA) instead of
    the ~1.0 nm CM-to-CM separation that causes startup clashes.

    Returns
    -------
    dict mapping (helix_id, bp_index, direction_str) → backbone position (nm).
    """
    full = read_configuration_full_unwrapped(conf_path, design)
    return {
        key: oxdna_backbone_site(rec["backbone_position"], rec["a1"], rec["a3"])
        for key, rec in full.items()
    }


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
