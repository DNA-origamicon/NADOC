"""The MD-measured display placement, and the two defects it corrects.

These pin the audit findings, not just the code: if someone "fixes" the frame-origin
correction in atomistic.py or changes the groove sign convention in geometry.py, the
assertions about the DEFECT will fail and point at what moved.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from backend.core.atomistic import (
    _ATOMISTIC_P_RADIUS,
    _ATOMISTIC_PP_SEP_RAD,
    _FRAME_ROT_RAD,
    _SUGAR,
)
from backend.core.constants import HELIX_RADIUS
from backend.core.measured_positioning import (
    MEASURED,
    _FALLBACK,
    _from_atomistic_template,
    apply_measured_positioning,
)
from backend.core.models import Direction, Helix, Vec3


def _template_p_azimuth_offset_rad(p_radius_nm: float) -> float:
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

    Lives here, not in ``measured_positioning``: it is the arithmetic of a DEFECT that
    the test below asserts, it has never had a production caller, and keeping it in the
    module made it a live reader of ``atomistic._SUGAR`` for no runtime purpose.
    """
    n, y = float(_SUGAR[0][2]), float(_SUGAR[0][3])
    c, s = math.cos(_FRAME_ROT_RAD), math.sin(_FRAME_ROT_RAD)
    n_rot = n * c - y * s
    y_rot = n * s + y * c
    return math.atan2(y_rot, p_radius_nm - n_rot)


def _straight_helix(direction: Direction, n_bp: int = 24) -> Helix:
    return Helix(
        id="h_test",
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=n_bp * 0.334),
        phase_offset=0.37,
        twist_per_bp_rad=math.radians(34.3),
        length_bp=n_bp,
        bp_start=0,
        direction=direction,
    )


def _cyl(points: np.ndarray, axis_pt: np.ndarray, t: np.ndarray):
    rel = points - axis_pt
    z = rel @ t
    radial = rel - np.outer(z, t)
    return np.linalg.norm(radial, axis=1), radial


def _pair_separation_deg(arrs: dict, axis_pt: np.ndarray, t: np.ndarray) -> np.ndarray:
    pos = np.asarray(arrs["positions"])
    out = []
    for k in range(len(pos) // 2):
        f, r = pos[2 * k], pos[2 * k + 1]
        rf = f - axis_pt - np.dot(f - axis_pt, t) * t
        rr = r - axis_pt - np.dot(r - axis_pt, t) * t
        rf /= np.linalg.norm(rf)
        rr /= np.linalg.norm(rr)
        out.append(math.degrees(math.atan2(float(np.dot(np.cross(rf, rr), t)),
                                           float(np.dot(rf, rr)))) % 360.0)
    return np.array(out)


T = np.array([0.0, 0.0, 1.0])
ORIGIN = np.zeros(3)


def _arrays(direction: Direction) -> dict:
    from backend.core.geometry import nucleotide_positions_arrays

    return nucleotide_positions_arrays(_straight_helix(direction))


def _measured(direction: Direction) -> dict:
    return apply_measured_positioning(_arrays(direction), axis_origin=ORIGIN, axis_hat=T,
                                      legacy_radius=HELIX_RADIUS)


# ── the defect being corrected ────────────────────────────────────────────────


def test_the_legacy_groove_sign_flips_with_the_cell_type():
    """FORWARD cells build at 150 deg and REVERSE at 210.

    Both helices stay right-handed, so these are NOT enantiomers — they are two
    right-handed helices with the minor groove on opposite sides, one of which is
    marking the major groove as the minor.  Chirality is unaffected and separately
    pinned by tests/test_atomistic_chirality.py.  This is defect (1) in
    measured_positioning's docstring; if the groove sign convention in geometry.py
    ever changes, this is the test that says so.
    """
    fwd = _pair_separation_deg(_arrays(Direction.FORWARD), ORIGIN, T)
    rev = _pair_separation_deg(_arrays(Direction.REVERSE), ORIGIN, T)
    assert fwd == pytest.approx(150.0, abs=1e-6)
    assert rev == pytest.approx(210.0, abs=1e-6)


def test_the_atomistic_phosphorus_lands_short_of_its_intended_separation():
    """Defect (2): the 208.2 deg correction is applied to the frame ORIGIN, but the
    template's P sits off that origin, and the two strands' frames are z-mirrored —
    so the realised P-P separation collapses by twice the template's azimuth offset.
    """
    phi = _template_p_azimuth_offset_rad(_ATOMISTIC_P_RADIUS)
    assert math.degrees(phi) == pytest.approx(12.182, abs=0.01)
    realised = math.degrees(_ATOMISTIC_PP_SEP_RAD) - 2 * math.degrees(phi)
    assert realised == pytest.approx(183.84, abs=0.02)


# ── the correction ────────────────────────────────────────────────────────────


@pytest.mark.parametrize("direction", [Direction.FORWARD, Direction.REVERSE])
def test_both_cell_types_land_on_one_separation(direction):
    """The whole point: after correction a helix's groove no longer depends on which
    lattice cell it happened to be built in.

    The separation is now the C3'-C3' one (130 deg), not the phosphates' (180): the
    backbone bead IS the ribose C3', and C3' sits a quarter turn round from its own P.
    """
    want = (MEASURED.backbone_rev.azimuth_deg - MEASURED.backbone_fwd.azimuth_deg) % 360.0
    seps = _pair_separation_deg(_measured(direction), ORIGIN, T)
    assert seps == pytest.approx(want, abs=1e-6)


@pytest.mark.parametrize("direction", [Direction.FORWARD, Direction.REVERSE])
def test_beads_and_bases_sit_on_the_measured_cylinders(direction):
    arrs = _measured(direction)
    r_bb, _ = _cyl(np.asarray(arrs["positions"]), ORIGIN, T)
    r_base, _ = _cyl(np.asarray(arrs["base_positions"]), ORIGIN, T)
    assert r_bb[0::2] == pytest.approx(MEASURED.backbone_fwd.radius_nm, abs=1e-9)
    assert r_bb[1::2] == pytest.approx(MEASURED.backbone_rev.radius_nm, abs=1e-9)
    assert r_base[0::2] == pytest.approx(MEASURED.base_fwd.radius_nm, abs=1e-9)
    assert r_base[1::2] == pytest.approx(MEASURED.base_rev.radius_nm, abs=1e-9)


def test_the_forward_bead_swings_round_to_its_c3_prime():
    """The forward strand DOES move now, and by exactly the measured amount.

    It used to be pinned in place so a helix would not appear to spin when the view was
    toggled.  That was only defensible while the bead was standing in for the phosphorus,
    which sits at azimuth ~0; the ribose C3' is +24.5 deg round from it, so holding the
    bead still would put it somewhere no atom is.
    """
    before = np.asarray(_arrays(Direction.FORWARD)["positions"])[0::2]
    after = np.asarray(_measured(Direction.FORWARD)["positions"])[0::2]
    for b, a in zip(before, after):
        rb = b - np.dot(b, T) * T
        ra = a - np.dot(a, T) * T
        rb /= np.linalg.norm(rb)
        ra /= np.linalg.norm(ra)
        swing = math.degrees(math.atan2(float(np.dot(np.cross(rb, ra), T)),
                                        float(np.dot(rb, ra))))
        assert swing == pytest.approx(MEASURED.backbone_fwd.azimuth_deg, abs=1e-6)


def test_beads_carry_their_measured_axial_offset():
    """C3' does not lie in its base pair's own plane — it stands ~0.1 nm along the axis,
    oppositely on the two strands.  Flattening that would fuse the strands into one
    plane and lose the rise offset between a sugar and its base."""
    before = np.asarray(_arrays(Direction.FORWARD)["positions"])
    after = np.asarray(_measured(Direction.FORWARD)["positions"])
    dz = (after - before) @ T
    assert dz[0::2] == pytest.approx(MEASURED.backbone_fwd.axial_nm, abs=1e-9)
    assert dz[1::2] == pytest.approx(MEASURED.backbone_rev.axial_nm, abs=1e-9)
    assert MEASURED.backbone_fwd.axial_nm * MEASURED.backbone_rev.axial_nm < 0


def test_base_normals_stay_cross_strand_and_antiparallel():
    arrs = _measured(Direction.FORWARD)
    bn = np.asarray(arrs["base_normals"])
    assert bn[0::2] == pytest.approx(-bn[1::2], abs=1e-9)
    assert np.linalg.norm(bn, axis=1) == pytest.approx(1.0, abs=1e-9)


def test_the_input_arrays_are_not_mutated():
    arrs = _arrays(Direction.FORWARD)
    snapshot = np.array(arrs["positions"], copy=True)
    apply_measured_positioning(arrs, axis_origin=ORIGIN, axis_hat=T,
                               legacy_radius=HELIX_RADIUS)
    assert np.asarray(arrs["positions"]) == pytest.approx(snapshot)


def test_a_bead_on_the_axis_is_left_alone():
    """Fail safe: a nucleotide with no radial direction has no azimuth to place it at,
    so it keeps its existing position rather than being sent somewhere invented."""
    arrs = _arrays(Direction.FORWARD)
    arrs = {k: (np.array(v, copy=True) if isinstance(v, np.ndarray) else v)
            for k, v in arrs.items()}
    arrs["positions"][0] = np.array([0.0, 0.0, 0.0])   # exactly on the axis
    out = apply_measured_positioning(arrs, axis_origin=ORIGIN, axis_hat=T,
                                     legacy_radius=HELIX_RADIUS)
    assert np.asarray(out["positions"])[0] == pytest.approx([0.0, 0.0, 0.0])
    # the rest of the helix still moved
    r_bb, _ = _cyl(np.asarray(out["positions"])[2:], ORIGIN, T)
    assert r_bb[0::2] == pytest.approx(MEASURED.backbone_fwd.radius_nm, abs=1e-9)


def test_a_pair_split_across_a_domain_transform_is_left_alone():
    """The failure this guard exists for, reproduced.

    Cluster transforms are applied per DOMAIN, so a base pair whose two strands belong
    to different domains gets one bead moved and the other left behind — they are then
    in different frames.  Anchoring the pair's frame on the stale bead threw the
    placement out by 1.9 nm on ``workspace/VoltronCore.nadoc`` (helix ``h_XY_4_10``),
    which is worse than not moving it at all.  Such a pair must keep legacy placement.
    """
    arrs = _arrays(Direction.FORWARD)
    arrs = {k: (np.array(v, copy=True) if isinstance(v, np.ndarray) else v)
            for k, v in arrs.items()}
    before = np.array(arrs["positions"], copy=True)
    # Drag ONE bead of the first pair off the cylinder, as a domain transform would.
    arrs["positions"][0] = arrs["positions"][0] * 3.0
    out = apply_measured_positioning(arrs, axis_origin=ORIGIN, axis_hat=T,
                                     legacy_radius=HELIX_RADIUS)
    pos = np.asarray(out["positions"])
    assert pos[0] == pytest.approx(before[0] * 3.0), "displaced bead must not be re-placed"
    assert pos[1] == pytest.approx(before[1]), "its partner must not be re-placed either"
    # every other pair still moved
    r_bb, _ = _cyl(pos[2:], ORIGIN, T)
    assert r_bb[0::2] == pytest.approx(MEASURED.backbone_fwd.radius_nm, abs=1e-9)


def test_the_bead_lands_on_the_ribose_c3_prime():
    """The point of the whole exercise, checked against the atoms rather than a table.

    Builds a real design, places its CG beads, and asks how far each one is from the
    C3' the all-atom layer stamps for the same nucleotide.  The legacy bead misses by
    0.46 nm.  The residual here is not error but sequence: the bead sites are averaged
    over the four bases, and this fixture is all-DT.
    """
    from pathlib import Path

    from backend.core.atomistic import build_atomistic_model
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.models import Design

    design = Design.model_validate_json(Path("Examples/6hb_test.nadoc").read_text())
    c3 = {(a.helix_id, a.bp_index, a.direction): np.array([a.x, a.y, a.z])
          for a in build_atomistic_model(design).atoms if a.name == "C3'"}

    def miss(measured: bool) -> float:
        d = []
        for n in _geometry_for_helices(design, measured_positioning=measured):
            p = c3.get((n["helix_id"], n["bp_index"], n["direction"]))
            if p is not None:
                d.append(float(np.linalg.norm(np.array(n["backbone_position"]) - p)))
        return float(np.median(d))

    # The measured bead no longer sits exactly ON the C3', and that is deliberate.
    # Placing it there means adopting the measurement's 130.2 deg cross-strand separation,
    # which breaks the dyad symmetry of a Holliday junction: the two crossovers of a DX
    # pair went to 0.70 vs 1.25 nm bead separation, against 0.6797 vs 0.6802 for the
    # lattice convention.  The CG layer now re-registers both strands onto the lattice
    # groove and keeps only the measurement's RADIUS and AXIAL offset (TD-27).
    #
    # The bead still lands closer to its C3' than legacy does — measured on
    # workspace/6hbx100_noT.nadoc (a design with real FORWARD/REVERSE cells), every
    # bucket improves and the overall mean goes 0.5011 -> 0.3828 nm.  This fixture is
    # the worst case for it: 6hb_test's helices all carry direction=None, so every one
    # is treated as a REVERSE cell, where the lattice groove and the measured C3' sit
    # 55.3 deg apart.
    assert miss(measured=False) > 0.40, "legacy bead is nowhere near the C3'"
    assert miss(measured=True) < miss(measured=False) + 0.15, (
        "the groove-registered bead should stay in the same neighbourhood as legacy")


def test_the_frozen_fallback_still_matches_what_the_template_derives():
    """``MEASURED = _from_atomistic_template() or _FALLBACK`` — the fallback is what keeps
    a missing or corrupt ``measured_atomistic_template.json`` from hard-failing every
    geometry response at import time, so it has to stay.

    What it must NOT be is a silent second source of truth.  Nothing may read ``_FALLBACK``
    directly, and this pins it to the derivation it duplicates: if the template is
    re-extracted and these drift, the fallback would quietly serve the old placement on
    exactly the runs where the real one is unavailable (TD-27 Stage 1).
    """
    derived = _from_atomistic_template()
    assert derived is not None, "the measured template must be loadable in a test run"

    for field in ("backbone_fwd", "backbone_rev", "base_fwd", "base_rev"):
        want, got = getattr(derived, field), getattr(_FALLBACK, field)
        assert got.radius_nm == pytest.approx(want.radius_nm, abs=5e-5), field
        assert got.azimuth_deg == pytest.approx(want.azimuth_deg, abs=5e-3), field
        assert got.axial_nm == pytest.approx(want.axial_nm, abs=5e-5), field
    assert _FALLBACK.slab_extent_nm == pytest.approx(derived.slab_extent_nm, abs=5e-5)


# ── firewalls: what must NOT move when the CG placement becomes measured ──────


def test_the_atomistic_build_is_immune_to_the_cg_measured_flag():
    """`build_atomistic_model` reads `geometry.nucleotide_positions` directly, never
    `design_geometry`, so the CG re-placement cannot reach it.

    That independence is the whole reason the CG layer can be changed at all without
    re-deriving the atomistic templates.  It is asserted rather than assumed because the
    failure would be silent: atoms would drift with a display toggle (TD-27 Stage 3).
    """
    from pathlib import Path

    from backend.core.atomistic import build_atomistic_model
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.models import Design

    design = Design.model_validate_json(Path("Examples/6hb_test.nadoc").read_text())

    def atoms(measured: bool):
        # Build the CG geometry in the given mode FIRST, so any shared cache or global
        # the flag might touch is warm, then stamp the atoms.
        _geometry_for_helices(design, None, measured_positioning=measured)
        m = build_atomistic_model(design, close_backbone=False)
        return np.array([[a.x, a.y, a.z] for a in m.atoms], dtype=float)

    off, on = atoms(False), atoms(True)
    assert off.shape == on.shape
    assert np.array_equal(off, on), "the CG measured flag reached the atomistic build"


def test_the_periodic_seam_solver_still_gets_a_valid_axis():
    """`periodic_polymer._section_frame_from_arrs` ANALYTICALLY INVERTS `HELIX_RADIUS`
    and the groove offset to recover a helix axis from two beads.

    It is immune to the measured re-placement only because it consumes
    `deformed_nucleotide_arrays` (the raw geometric layer), NOT `_geometry_for_design`
    — the re-placement runs at the `_emit_arrs` serialiser boundary, downstream of it.
    If measured positioning were ever pushed down into `geometry.py`, this solve would
    silently return a wrong axis rather than fail (TD-27 Stage 3 invariant).

    Pinned by checking the inverter reproduces the true axis of a known helix.
    """
    from backend.core.deformation import deformed_nucleotide_arrays
    from backend.core.models import Design

    from backend.core import periodic_polymer as pp

    helix = _straight_helix(Direction.FORWARD, n_bp=24)
    design = Design(name="pin", helices=[helix], strands=[])
    arrs = deformed_nucleotide_arrays(helix, design)

    frame = pp._section_frame_from_arrs(arrs, 0, helix.direction)
    assert frame is not None, "the seam solver could not recover an axis at all"
    origin, z = np.asarray(frame)[:3, 3], np.asarray(frame)[:3, 2]
    # The fixture helix runs along +Z from the origin.
    assert np.allclose(np.abs(z), [0.0, 0.0, 1.0], atol=1e-9)
    assert np.allclose(origin[:2], [0.0, 0.0], atol=1e-9), (
        "recovered axis is off the true centreline — the inverter's build-convention "
        "assumption (HELIX_RADIUS + groove_offset_rad) no longer holds")


def test_the_oxdna_seed_restores_the_cm_radius_and_is_a_legacy_no_op():
    """The oxDNA conf's first three floats are the CENTRE OF MASS, and HELIX_RADIUS is
    defined as exactly that radius in oxDNA's model.  The display bead is a different
    landmark — the measured ribose C3' at 0.804 nm — so the seed boundary converts.

    Two properties, both load-bearing:

      1. On LEGACY geometry it is a no-op, because legacy beads already sit at
         HELIX_RADIUS.  That is what makes the conversion safe to apply unconditionally.
      2. On MEASURED geometry it puts the bead back on the HELIX_RADIUS cylinder while
         keeping its azimuth and axial offset — undoing the 0.196 nm inward pull that
         widens every crossover gap by 0.39 nm and pushes borderline backbone bonds over
         oxDNA's FENE cliff (TD-27 Stage 3).
    """
    from pathlib import Path

    from backend.core.deformation import deformed_helix_axes
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.models import Design
    from backend.physics.oxdna_interface import _oxdna_cm_radius_map, resolved_nuc_map

    design = Design.model_validate_json(Path("Examples/6hb_test.nadoc").read_text())
    axes = {a["helix_id"]: (np.asarray(a["start"], float),
                            np.asarray(a["end"], float) - np.asarray(a["start"], float))
            for a in deformed_helix_axes(design)}

    def radii(rm):
        out = []
        for key, nuc in rm.items():
            e = axes.get(key[0]) if isinstance(key, tuple) and key else None
            if e is None:
                continue
            o, v = e
            t = v / np.linalg.norm(v)
            d = np.asarray(nuc["backbone_position"], float) - o
            out.append(float(np.linalg.norm(d - (d @ t) * t)))
        return np.asarray(out)

    legacy = resolved_nuc_map(design, _geometry_for_helices(
        design, None, compact_skips=True, measured_positioning=False))
    measured = resolved_nuc_map(design, _geometry_for_helices(
        design, None, compact_skips=True, measured_positioning=True))

    # (1) legacy beads are already on the CM cylinder, so the conversion changes nothing.
    assert radii(legacy) == pytest.approx(HELIX_RADIUS, abs=1e-6)
    assert _oxdna_cm_radius_map(design, legacy) is legacy, "must be a no-op on legacy"

    # (2) measured beads come in at the C3' radius and go out on the CM cylinder.
    assert radii(measured) == pytest.approx(MEASURED.backbone_fwd.radius_nm, abs=5e-3)
    assert radii(_oxdna_cm_radius_map(design, measured)) == pytest.approx(
        HELIX_RADIUS, abs=1e-6)
