"""MD-measured placement of the coarse-grained backbone bead and base slab.

Display-only.  Nothing here is a build constant: the topology and the geometric
layer are untouched, and every consumer that is not the "new positioning" view
keeps the legacy numbers in ``constants.py``.  See ``apply_measured_positioning``.

What was wrong (audit, 2026-08-05)
──────────────────────────────────
Three layers disagreed about where a nucleotide is, and none of them had ever been
checked against a simulation:

  quantity              CG "full" rep        atomistic (realised)   free MD
  backbone radius       1.000 nm             0.900                  0.925
  P–P azimuthal sep     150° FORWARD cell    183.8° (both cells)    183.9°
                        210° REVERSE cell
  base bead / centroid   0.714 nm             —                      0.324
  C1'–C1'               —                    0.967 nm               1.074

Two separate defects:

1. ``geometry.py`` flips the sign of ``BDNA_MINOR_GROOVE_ANGLE_RAD`` with the helix's
   lattice cell type, so FORWARD-cell helices are built at 150° and REVERSE-cell at
   210°.  Both helices are right-handed — the twist is NOT flipped — so these are not
   enantiomers of each other; they are two right-handed helices with the minor groove
   on OPPOSITE SIDES, one of which is labelling the major groove as the minor.  This
   is a wrong-side-marker defect, not a wrong-molecule one, and it does not reach the
   atoms (see below).  Against the 183.9° the phosphates actually take, FORWARD cells
   are 33.9° out and REVERSE cells 26.1° out — in opposite directions.

2. ``atomistic.py`` corrects for that (``_ATOMISTIC_PP_SEP_RAD``, 208.2°, from the
   1ZEW crystal) but applies the correction to the template *frame origin*.  The
   template's phosphorus sits 0.1887 nm off that origin in-plane, and the two strands'
   frames are z-mirrored, so the offset rotates the two P atoms in OPPOSITE azimuthal
   directions.  Verified exactly, at every bp and in both cell types: frame-origin
   separation 208.20°, realised P-atom separation 183.84° — 2 × 12.18° of collapse.
   The same mirror shrinks C1'–C1' to 0.967 nm against 1.061 nm in 1ZEW.

Together those account for the ~5 Å bead-to-phosphorus offset recorded in
``project_extra_base_spacing.md``: ~0.1 nm radial plus 26–34° of azimuth at r ≈ 0.93.

Defect (1) is confined to the CG bead layer.  ``atomistic.py``'s per-cell correction
(+58.2° on FORWARD cells, −1.8° on REVERSE) equalises both cell types onto ONE
separation, so the all-atom model does not inherit the cell-type split.

CHIRALITY IS NOT AFFECTED, and this was checked rather than assumed.  Every stamping
frame is a proper rotation (det(R) = +1.000000000000 over 1396 frames, min = max); the
strand z-flip is a physical 180° end-over-end rotation, since ``e_y = e_z × e_n``
co-flips and keeps ``[e_n | e_y | e_z]`` right-handed.  Sugar stereocentre signed
volumes match 1ZEW (C1' +, C3' −, C4' −) in all four cell-type × strand buckets, and
fitting every built residue onto a same-base forward reference WITHOUT a reflection
guard gives det = +1 for all 1284.  The REVERSE base templates fit their FORWARD
counterparts at det = −1, but that is a coplanarity degeneracy — the rings are planar
to 1.2–2.8 pm and a forced proper rotation fits equally well (sub-pm difference) — a
planar molecule being achiral.  Pinned by ``tests/test_atomistic_chirality.py``.

Where the numbers come from
───────────────────────────
``scripts/measure_cg_registration.py`` over the free (``MGHH_only``, unrestrained)
stage of job ``dbd8ad3b7d4f`` — ``propagator_20bp_long``, a 20 bp duplex, 7500 frames,
600 sampled, 3 terminal bp excluded each end.  Radii and azimuths are measured about a
local helix axis fitted as the axis of the cylinder the phosphates lie on; the
C1'–C1'-midpoint line fit that preceded it was not accurate enough (see that script).
The estimator reproduces 1ZEW at 208.5° / 0.881 nm, matching the constants
``atomistic.py`` took from that same structure, and two independent axis fits
(phosphate cylinder, C1' cylinder) agree to 0.1°.

Sanity of the source trajectory: rise 0.347 ± 0.005 nm, twist 34.21 ± 0.83°,
C1'–C1' 1.074 ± 0.023 nm, WC N1–N3 0.296 ± 0.011 nm — B-form on every axis.

⚠ ``PP_SEPARATION_DEG`` IS PROVISIONAL
──────────────────────────────────────
Every trajectory in this repo was seeded from NADOC's own build, i.e. started at
183.84°.  The 20 bp duplex drifts 186.6 → 179.7° over its run and plateaus — *away*
from the 208.5° crystal value, not toward it.  C1'–C1' in the same run does relax
correctly (0.967 → 1.074 nm), so local geometry is equilibrating; but that is not
enough to separate "≈184° is the CHARMM36 solution equilibrium" from "the groove is a
soft, slowly-reorganising DOF still holding its seed".

Settling it needs MD seeded from deliberately different groove angles, converging (or
not) on a common value.  Until that lands this value is the measured-but-contaminated
one, and it is the ONLY number here that the seed sweep can move: the radii and the
base-centroid placement all relaxed demonstrably away from the seed.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class MeasuredPositioning:
    """One coherent placement parameter set, all measured about the local helix axis."""

    backbone_radius_nm: float
    """Where the phosphorus actually sits.  MD 0.925 ± 0.039 nm; the CG layer draws
    the bead at 1.000 and the atomistic layer stamps P at 0.900."""

    base_radius_nm: float
    """Base-ring centroid, MD 0.324 ± 0.052 nm.  The CG base bead is currently at
    0.714 nm — more than twice too far out, the single largest placement error found."""

    pp_separation_deg: float
    """Azimuthal separation, CCW about the axis, from the FORWARD strand's phosphorus
    to the REVERSE strand's at the same base pair.  PROVISIONAL — see module docstring."""

    base_azimuth_offset_deg: float
    """Azimuth of the base-ring centroid relative to its OWN phosphorus, signed toward
    the partner strand.  MD puts them within a degree of each other (fwd 177.8° vs
    178.6°, rev 2.60° vs 2.50°): the nucleotide runs essentially straight inward, so
    the base bead is the backbone bead pulled in along the same radial."""

    slab_extent_nm: float
    """Long in-plane extent of the base slab, along the cross-strand direction.  Sized
    to span its own base: from that strand's C1' (MD r = 0.566 nm) inward to just past
    the Watson-Crick atom (r = 0.165 nm)."""

    def pp_separation_rad(self) -> float:
        return math.radians(self.pp_separation_deg)


MEASURED = MeasuredPositioning(
    backbone_radius_nm=0.925,
    base_radius_nm=0.324,
    pp_separation_deg=183.9,      # PROVISIONAL — pending the seed-sweep MD
    base_azimuth_offset_deg=-0.8,
    slab_extent_nm=0.45,
)


def template_p_azimuth_offset_rad(p_radius_nm: float) -> float:
    """Azimuth by which the template's phosphorus misses its own frame origin.

    ``_atom_frame`` places the frame origin on the circle of radius ``p_radius_nm``
    and treats that as the phosphorus.  It is not: the sugar template's P sits at
    ``(n, y)`` in the frame plane, which after the ``_FRAME_ROT_RAD`` pre-compensation
    cancel becomes a radial shift of ``-n'`` and a TANGENTIAL shift of ``y'``.  The
    tangential part is an azimuth error of ``atan2(y', r - n')``.

    It matters because the two strands' frames are z-mirrored (``e_z`` is
    ``-axis_tangent`` on FORWARD and ``+axis_tangent`` on REVERSE), which flips the
    sign of ``e_y`` and therefore of this offset.  The two phosphates rotate toward
    each other and the realised P-P separation comes out 2x this angle short of the
    intended one.  Computed from the template rather than hardcoded so it stays
    correct if the template is ever re-extracted.
    """
    from backend.core.atomistic import _FRAME_ROT_RAD, _SUGAR

    n, y = float(_SUGAR[0][2]), float(_SUGAR[0][3])
    c, s = math.cos(_FRAME_ROT_RAD), math.sin(_FRAME_ROT_RAD)
    n_rot = n * c - y * s
    y_rot = n * s + y * c
    return math.atan2(y_rot, p_radius_nm - n_rot)


# ── Why there is no atomistic re-placement here ───────────────────────────────
# The atomistic rep cannot be corrected by moving nucleotides.  Measured against the
# free MD, the 1ZEW-derived template is wrong INTERNALLY, and not by a common factor:
#
#     landmark            built      free MD    error
#     P                   0.902 nm   0.925      -0.023
#     C1'                 0.493 nm   0.566      -0.073
#     base-ring centroid  0.351 nm   0.324      +0.027
#
# A rigid per-nucleotide move onto the measured P cylinder was tried and rejected: it
# lands r_P exactly but drags the base out with it, opening Watson-Crick pairs from
# 0.309 to 0.355 nm and stretching inter-residue O3'-P linkers by up to 0.34 nm.  A
# radial affine map r' = a*r + b was tried and rejected too: fitting P and C1'
# simultaneously (a = 0.877, b = 0.134) throws the base centroid to 0.442 nm against a
# measured 0.324.  The three landmarks are mutually inconsistent under every whole-body
# transform, which is the signature of a template defect rather than a placement one.
#
# The real fix is to re-extract the sugar and base templates against measured geometry
# — the recipe specified but never executed in project_o3prime_investigation.md, which
# also records the known-wrong residual C3'-O3'-P angle (93.6 deg vs a 119.35 target)
# in this same template.  ``pdb_import.analyze_duplex`` already averages per-residue
# template coordinates in the NADOC frame and is the tool for it.
#
# ``template_p_azimuth_offset_rad`` above stays because it is the proof of the separate
# frame-origin defect, and because a re-extraction has to account for it.


def _reconstruct_axis_point(
    fwd: np.ndarray,
    rev: np.ndarray,
    tangent: np.ndarray,
    legacy_radius: float,
    legacy_groove_rad: float,
) -> np.ndarray | None:
    """Recover the helix-axis point for one base pair from its two backbone beads.

    Both legacy beads sit at ``legacy_radius`` from the axis, so in the plane
    perpendicular to ``tangent`` the axis point is a circumcentre: on the perpendicular
    bisector of the bead chord, ``sqrt(r² − (d/2)²)`` from its midpoint.  Two solutions
    exist; the correct one is the side for which the CCW angle from FORWARD to REVERSE
    reproduces the legacy groove the beads were built with.

    Returns ``None`` when the pair cannot be reconciled with that groove — a deformed
    or otherwise non-circular pair — so the caller can leave it on legacy placement
    rather than move it somewhere invented.
    """
    t = tangent / np.linalg.norm(tangent)
    mid = (fwd + rev) / 2.0
    chord = rev - fwd
    chord = chord - np.dot(chord, t) * t
    d = float(np.linalg.norm(chord))
    if d < 1e-9 or d > 2.0 * legacy_radius:
        return None
    chord_hat = chord / d
    perp = np.cross(t, chord_hat)
    h = math.sqrt(max(0.0, legacy_radius**2 - (d / 2.0) ** 2))

    want = legacy_groove_rad % (2.0 * math.pi)
    best: np.ndarray | None = None
    best_err = float("inf")
    for sign in (+1.0, -1.0):
        cand = mid + sign * h * perp
        rf = fwd - cand
        rf = rf - np.dot(rf, t) * t
        rr = rev - cand
        rr = rr - np.dot(rr, t) * t
        nf, nr = np.linalg.norm(rf), np.linalg.norm(rr)
        if nf < 1e-9 or nr < 1e-9:
            continue
        rf, rr = rf / nf, rr / nr
        ang = math.atan2(float(np.dot(np.cross(rf, rr), t)), float(np.dot(rf, rr)))
        err = abs(((ang - want + math.pi) % (2.0 * math.pi)) - math.pi)
        if err < best_err:
            best_err, best = err, cand
    # 3° of slack absorbs float noise without accepting a genuinely wrong circumcentre.
    return best if best_err < math.radians(3.0) else None


def apply_measured_positioning(
    arrs: dict,
    *,
    legacy_radius: float,
    legacy_groove_rad: float,
    params: MeasuredPositioning = MEASURED,
) -> dict:
    """Re-place the backbone beads and base beads of one helix's nucleotide arrays.

    ``arrs`` is a ``nucleotide_positions_arrays`` block: FORWARD/REVERSE interleaved,
    index ``2k`` and ``2k+1`` being the two strands of base pair ``k``.  Returns a new
    dict; the input is not mutated, and ``bp_indices`` / ``directions`` /
    ``axis_tangents`` are carried through untouched.

    The FORWARD strand's azimuth is held fixed and the REVERSE strand is moved to
    ``pp_separation_deg`` from it.  Holding FORWARD still means a helix does not appear
    to spin when the view is toggled; only the strand that is demonstrably in the wrong
    place moves.

    Base pairs whose axis point cannot be recovered (see ``_reconstruct_axis_point``)
    are left exactly as they were, so a deformed helix degrades to legacy placement
    per base pair instead of being displaced by a bad reconstruction.
    """
    positions = np.array(arrs["positions"], dtype=float, copy=True)
    base_positions = np.array(arrs["base_positions"], dtype=float, copy=True)
    base_normals = np.array(arrs["base_normals"], dtype=float, copy=True)
    tangents = np.asarray(arrs["axis_tangents"], dtype=float)

    sep = params.pp_separation_rad()
    base_off = math.radians(params.base_azimuth_offset_deg)
    n_pairs = len(positions) // 2

    for k in range(n_pairs):
        i, j = 2 * k, 2 * k + 1
        t = tangents[i]
        nt = np.linalg.norm(t)
        if nt < 1e-12:
            continue
        t = t / nt

        axis_pt = _reconstruct_axis_point(
            positions[i], positions[j], t, legacy_radius, legacy_groove_rad
        )
        if axis_pt is None:
            continue

        radial_f = positions[i] - axis_pt
        radial_f = radial_f - np.dot(radial_f, t) * t
        n = np.linalg.norm(radial_f)
        if n < 1e-9:
            continue
        radial_f = radial_f / n
        perp_f = np.cross(t, radial_f)   # +90° CCW about t, completing the frame

        def at(angle: float, radius: float) -> np.ndarray:
            return axis_pt + radius * (math.cos(angle) * radial_f + math.sin(angle) * perp_f)

        # FORWARD holds azimuth 0 in this frame; REVERSE moves to the measured separation.
        positions[i] = at(0.0, params.backbone_radius_nm)
        positions[j] = at(sep, params.backbone_radius_nm)
        # The base centroid sits on its own strand's radial, pulled in toward the axis.
        base_positions[i] = at(+base_off, params.base_radius_nm)
        base_positions[j] = at(sep - base_off, params.base_radius_nm)

        cross = base_positions[j] - base_positions[i]
        nc = np.linalg.norm(cross)
        if nc > 1e-9:
            base_normals[i] = cross / nc
            base_normals[j] = -base_normals[i]

    out = dict(arrs)
    out["positions"] = positions
    out["base_positions"] = base_positions
    out["base_normals"] = base_normals
    return out
