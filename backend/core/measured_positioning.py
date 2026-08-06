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
class Site:
    """One landmark's cylindrical place in the base-pair frame: (radius, azimuth, rise)."""

    radius_nm: float
    azimuth_deg: float
    axial_nm: float
    """Offset along the helix axis from the base pair's own plane.  Small but real
    (~0.1 nm for C3'), and dropping it would flatten the two strands into one plane."""

    def azimuth_rad(self) -> float:
        return math.radians(self.azimuth_deg)


@dataclass(frozen=True)
class MeasuredPositioning:
    """Where the CG beads go, all measured about the local helix axis.

    Every field is DERIVED from the all-atom template in ``measured_atomistic.py`` (see
    :func:`_from_atomistic_template`) rather than measured separately.  That is the point:
    the backbone bead is meant to BE the ribose C3' and the base bead its base-ring
    centroid, so reading them off the same atoms the atomistic layer stamps is the only
    way the two representations can be guaranteed to agree.  A bead placed from an
    independent fit lands near the atom, not on it — the previous parameter set targeted
    the phosphorus and still missed it by 0.13 nm.
    """

    backbone_fwd: Site
    backbone_rev: Site
    """The ribose C3' of each strand.  MD: r = 0.804 nm at +24.5 deg on FORWARD and
    +154.7 deg on REVERSE, i.e. a C3'-C3' separation of 130.2 deg — nothing like the
    180 deg the phosphates take, because C3' sits a quarter-turn round from its own P."""

    base_fwd: Site
    base_rev: Site
    """Base-ring centroid.  MD r = 0.314 nm; the legacy CG base bead is at 0.714 nm,
    more than twice too far out — the single largest placement error found."""

    slab_extent_nm: float
    """Long extent of the base slab, along the bead->base axis (NOT the cross-strand
    direction).  Sized to run from the nucleotide's own backbone bead inward to just
    past its Watson-Crick atom, so the slab visibly joins the base to its own sugar."""


def _site(vals: "list[tuple[float, float, float]]") -> Site:
    """Sequence-average a landmark: mean radius/rise, CIRCULAR mean azimuth."""
    r = float(np.mean([v[0] for v in vals]))
    z = float(np.mean([v[2] for v in vals]))
    ang = np.radians([v[1] for v in vals])
    az = math.degrees(math.atan2(float(np.sin(ang).mean()), float(np.cos(ang).mean())))
    return Site(radius_nm=round(r, 4), azimuth_deg=round(az, 2), axial_nm=round(z, 4))


def _from_atomistic_template() -> "MeasuredPositioning | None":
    """Read the bead sites straight off the measured all-atom template.

    Returns ``None`` if that data file is unavailable, so the caller can fall back to
    the frozen numbers below rather than fail a view.
    """
    from backend.core import measured_atomistic as _ma

    PURINE_RING = ("N9", "C8", "N7", "C5", "C6", "N1", "C2", "N3", "C4")
    PYRIMIDINE_RING = ("N1", "C2", "N3", "C4", "C5", "C6")
    try:
        tmpl = _ma.measured_templates()
    except _ma.MeasuredTemplateUnavailable:
        return None

    def landmark(role: str, which: str) -> Site:
        vals = []
        for residue in ("DA", "DT", "DG", "DC"):
            sugar, base = tmpl[(role, residue)]
            pos = {n: np.array([x, y, z]) for n, _e, x, y, z in (*sugar, *base)}
            if which == "C3'":
                v = pos["C3'"]
            elif which == "RING":
                ring = PURINE_RING if residue in ("DA", "DG") else PYRIMIDINE_RING
                v = np.mean([pos[a] for a in ring], axis=0)
            else:  # the Watson-Crick donor/acceptor
                v = pos["N1"] if residue in ("DA", "DG") else pos["N3"]
            vals.append((float(math.hypot(v[0], v[1])),
                         math.degrees(math.atan2(v[1], v[0])), float(v[2])))
        return _site(vals)

    bb_f, bb_r = landmark("FORWARD", "C3'"), landmark("REVERSE", "C3'")
    ba_f, ba_r = landmark("FORWARD", "RING"), landmark("REVERSE", "RING")
    wc_f = landmark("FORWARD", "WC")

    # Slab length = bead -> own Watson-Crick atom, so the plate spans the whole base and
    # its OUTER end lands on the bead.  Measured straight-line, not a radial difference:
    # the bead sits 0.29 nm off the base's cross-strand line, so a slab merely lengthened
    # radially reaches the right radius and still misses the bead entirely.
    def xyz(s: Site) -> np.ndarray:
        return np.array([s.radius_nm * math.cos(s.azimuth_rad()),
                         s.radius_nm * math.sin(s.azimuth_rad()), s.axial_nm])

    extent = float(np.linalg.norm(xyz(wc_f) - xyz(bb_f)))
    return MeasuredPositioning(backbone_fwd=bb_f, backbone_rev=bb_r,
                               base_fwd=ba_f, base_rev=ba_r,
                               slab_extent_nm=round(extent, 4))


# Frozen fallback, and the documentation of what the derivation produces today.
_FALLBACK = MeasuredPositioning(
    backbone_fwd=Site(0.8040, 24.52, 0.0992),
    backbone_rev=Site(0.8032, 154.70, -0.0997),
    base_fwd=Site(0.3136, 7.87, 0.0326),
    base_rev=Site(0.3127, 171.35, -0.0320),
    slab_extent_nm=0.6568,
)

MEASURED = _from_atomistic_template() or _FALLBACK


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


# ── The atomistic re-placement lives in measured_atomistic.py ─────────────────
# RESOLVED 2026-08-06.  The audit below concluded that the atomistic rep could not be
# fixed by moving nucleotides, because measured against the free MD the 1ZEW-derived
# template is wrong INTERNALLY, and not by a common factor:
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
# So the templates were re-extracted, which is what that conclusion called for:
# ``scripts/measure_atomistic_template.py`` measures every heavy atom of both strands
# in one base-pair frame from five free NAMD trajectories, and
# ``backend/core/measured_atomistic.py`` stamps the result.  FORWARD and REVERSE are
# measured separately — no z-mirrored templates, no per-strand frame flip — so the
# frame-origin defect ``template_p_azimuth_offset_rad`` describes cannot arise: there
# is no correction applied to an origin, because both nucleotides of a pair share one
# frame.  ``template_p_azimuth_offset_rad`` is kept as the proof of what went wrong on
# the legacy path, which is still what the view shows with the toggle OFF.


def _axis_point_for(
    bead: np.ndarray,
    axis_origin: np.ndarray,
    axis_hat: np.ndarray,
) -> np.ndarray:
    """The point on the helix axis level with this nucleotide — the foot of the
    perpendicular from its backbone bead.

    The axis is passed in rather than recovered from the beads, because it CANNOT be
    recovered from them.  Two beads on a circle of known radius admit two circumcentres,
    mirror images across their chord and ``2h`` = 0.52 nm apart, and nothing else in the
    nucleotide arrays breaks the tie: the base beads are offset along the CROSS-STRAND
    direction, so the pair's base midpoint coincides with its backbone midpoint exactly
    (verified: |base_mid − bead_mid| = 0).

    The previous code chose by reproducing the CCW angle the legacy groove was built
    with, which depends on the sign convention of ``axis_tangent`` relative to the
    helix's lattice cell type — and silently picked the MIRRORED circumcentre for one of
    the two cell types.  Measured on ``6hb_test``: mean displacement 0.2588 nm = h, max
    0.5176 = 2h, i.e. exactly half the base pairs were placed about a phantom axis.  The
    caller has the real helix in hand, so it simply hands it over.
    """
    d = bead - axis_origin
    return axis_origin + float(np.dot(d, axis_hat)) * axis_hat


def apply_measured_positioning(
    arrs: dict,
    *,
    axis_origin: np.ndarray,
    axis_hat: np.ndarray,
    legacy_radius: float,
    params: MeasuredPositioning = MEASURED,
) -> dict:
    """Re-place the backbone beads and base beads of one helix's nucleotide arrays.

    ``arrs`` is a ``nucleotide_positions_arrays`` block: FORWARD/REVERSE interleaved,
    index ``2k`` and ``2k+1`` being the two strands of base pair ``k``.  Returns a new
    dict; the input is not mutated, and ``bp_indices`` / ``directions`` /
    ``axis_tangents`` are carried through untouched.

    The frame is anchored on the FORWARD strand's EXISTING bead direction (azimuth 0),
    which is also the frame the all-atom template's coordinates are quoted in — verified
    on a built design, where the atomistic C3' lands at exactly the tabulated
    (r, azimuth, z) with zero scatter.  So placing a bead at ``backbone_fwd`` puts it ON
    the C3' atom rather than merely near it.

    Both strands are placed from their own measured site.  Earlier this held FORWARD
    fixed and swung REVERSE by a single separation angle; that cannot express the
    measurement now, because the backbone site is the C3' and the base site is the ring
    centroid, and those two land at different azimuthal separations (130.2 deg vs
    163.5 deg).  Deriving one from the other would put the base beads in the wrong place.

    ``axis_origin`` / ``axis_hat`` are the helix's own centreline, cluster transforms and
    all (``deformation.deformed_helix_axes``).

    A base pair is re-placed only when BOTH of its beads are ``legacy_radius`` from that
    centreline.  That check is not paranoia — cluster transforms are applied per DOMAIN,
    so a base pair whose two strands belong to different domains has one bead moved and
    the other left behind, and the two are then in different frames.  Measured on
    ``workspace/VoltronCore.nadoc``: on ``h_XY_4_10`` only the reverse strand is covered
    by a domain, leaving its forward partner 3.07 nm off the axis; anchoring the frame on
    that stale bead threw the pair's placement out by 1.9 nm — worse than not moving it.
    Such pairs keep their legacy placement, which is coherent even if not measured.
    """
    positions = np.array(arrs["positions"], dtype=float, copy=True)
    base_positions = np.array(arrs["base_positions"], dtype=float, copy=True)
    base_normals = np.array(arrs["base_normals"], dtype=float, copy=True)
    tangents = np.asarray(arrs["axis_tangents"], dtype=float)

    n_pairs = len(positions) // 2

    for k in range(n_pairs):
        i, j = 2 * k, 2 * k + 1
        t = tangents[i]
        nt = np.linalg.norm(t)
        if nt < 1e-12:
            continue
        t = t / nt

        axis_pt = _axis_point_for(positions[i], axis_origin, axis_hat)

        radial_f = positions[i] - axis_pt
        radial_f = radial_f - np.dot(radial_f, t) * t
        n = np.linalg.norm(radial_f)
        if n < 1e-9:
            continue
        # Both beads must actually belong to this centreline — see the docstring.
        radial_r = positions[j] - axis_pt
        radial_r = radial_r - np.dot(radial_r, t) * t
        if (abs(n - legacy_radius) > 1e-3
                or abs(float(np.linalg.norm(radial_r)) - legacy_radius) > 1e-3):
            continue
        radial_f = radial_f / n
        perp_f = np.cross(t, radial_f)   # +90° CCW about t, completing the frame

        def at(site: Site) -> np.ndarray:
            a = site.azimuth_rad()
            return (axis_pt
                    + site.radius_nm * (math.cos(a) * radial_f + math.sin(a) * perp_f)
                    + site.axial_nm * t)

        # Backbone bead = the ribose C3'; base bead = the base-ring centroid.  Each
        # strand from its own measured site, neither derived from the other.
        positions[i] = at(params.backbone_fwd)
        positions[j] = at(params.backbone_rev)
        base_positions[i] = at(params.base_fwd)
        base_positions[j] = at(params.base_rev)

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
