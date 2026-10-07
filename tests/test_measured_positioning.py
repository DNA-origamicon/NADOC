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
    FULL_REP,
    _from_atomistic_template,
)
from backend.core.models import Direction, Helix, Vec3
from backend.core.native_full_placement import place_native_full, NativePlacementError


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
        out.append(
            math.degrees(
                math.atan2(float(np.dot(np.cross(rf, rr), t)), float(np.dot(rf, rr)))
            )
            % 360.0
        )
    return np.array(out)


T = np.array([0.0, 0.0, 1.0])
ORIGIN = np.zeros(3)


def _arrays(direction: Direction) -> dict:
    from backend.core.geometry import nucleotide_positions_arrays

    return nucleotide_positions_arrays(_straight_helix(direction))


def _measured(direction: Direction) -> dict:
    return place_native_full(_arrays(direction))


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

    The full-representation separation is the O5'-O5' one, not the phosphate groove.
    """
    want = (
        FULL_REP.backbone_rev.azimuth_deg - FULL_REP.backbone_fwd.azimuth_deg
    ) % 360.0
    seps = _pair_separation_deg(_measured(direction), ORIGIN, T)
    assert seps == pytest.approx(want, abs=1e-6)


@pytest.mark.parametrize("direction", [Direction.FORWARD, Direction.REVERSE])
def test_beads_and_bases_sit_on_the_measured_cylinders(direction):
    arrs = _measured(direction)
    r_bb, _ = _cyl(np.asarray(arrs["positions"]), ORIGIN, T)
    r_base, _ = _cyl(np.asarray(arrs["base_positions"]), ORIGIN, T)
    assert r_bb[0::2] == pytest.approx(FULL_REP.backbone_fwd.radius_nm, abs=1e-9)
    assert r_bb[1::2] == pytest.approx(FULL_REP.backbone_rev.radius_nm, abs=1e-9)
    assert r_base[0::2] == pytest.approx(FULL_REP.base_fwd.radius_nm, abs=1e-9)
    assert r_base[1::2] == pytest.approx(FULL_REP.base_rev.radius_nm, abs=1e-9)


def test_the_forward_bead_swings_round_to_its_c3_prime():
    """The forward strand DOES move now, and by exactly the measured amount.

    It used to be pinned in place so a helix would not appear to spin when the view was
    toggled.  That was only defensible while the bead was standing in for the phosphorus,
    which sits at azimuth ~0; O5' is +8.23 deg round from it, so holding the
    bead still would put it somewhere no atom is.
    """
    before = np.asarray(_arrays(Direction.FORWARD)["positions"])[0::2]
    after = np.asarray(_measured(Direction.FORWARD)["positions"])[0::2]
    for b, a in zip(before, after):
        rb = b - np.dot(b, T) * T
        ra = a - np.dot(a, T) * T
        rb /= np.linalg.norm(rb)
        ra /= np.linalg.norm(ra)
        swing = math.degrees(
            math.atan2(float(np.dot(np.cross(rb, ra), T)), float(np.dot(rb, ra)))
        )
        assert swing == pytest.approx(FULL_REP.backbone_fwd.azimuth_deg, abs=1e-6)


def test_beads_carry_their_measured_axial_offset():
    """O5' carries a small but real axial offset from its base pair's own plane,
    oppositely on the two strands.  Flattening that would fuse the strands into one
    plane and lose the rise offset between a sugar and its base."""
    before = np.asarray(_arrays(Direction.FORWARD)["positions"])
    after = np.asarray(_measured(Direction.FORWARD)["positions"])
    dz = (after - before) @ T
    assert dz[0::2] == pytest.approx(FULL_REP.backbone_fwd.axial_nm, abs=1e-9)
    assert dz[1::2] == pytest.approx(FULL_REP.backbone_rev.axial_nm, abs=1e-9)
    assert FULL_REP.backbone_fwd.axial_nm * FULL_REP.backbone_rev.axial_nm < 0


def test_base_normals_stay_cross_strand_and_antiparallel():
    arrs = _measured(Direction.FORWARD)
    bn = np.asarray(arrs["base_normals"])
    assert bn[0::2] == pytest.approx(-bn[1::2], abs=1e-9)
    assert np.linalg.norm(bn, axis=1) == pytest.approx(1.0, abs=1e-9)


def test_the_input_arrays_are_not_mutated():
    arrs = _arrays(Direction.FORWARD)
    snapshot = np.array(arrs["positions"], copy=True)
    place_native_full(arrs)
    assert np.asarray(arrs["positions"]) == pytest.approx(snapshot)


def test_invalid_frame_fails_instead_of_retaining_provisional_bead_positions():
    arrs = _arrays(Direction.FORWARD)
    arrs["radial_hats"][0] = 0
    with pytest.raises(NativePlacementError, match="not orthonormal"):
        place_native_full(arrs)


def test_partner_displacement_does_not_change_native_internal_placement():
    arrs = _arrays(Direction.FORWARD)
    before = place_native_full(arrs)
    shift = np.array([3.0, -1.0, 2.0])
    arrs["axis_points"][0] += shift
    # Provisional construction beads do not influence the authoritative result.
    arrs["positions"][0] = 1000
    out = place_native_full(arrs)
    np.testing.assert_allclose(out["positions"][0], before["positions"][0] + shift)
    np.testing.assert_array_equal(out["positions"][1:], before["positions"][1:])


def test_the_bead_lands_on_the_atomistic_o5_prime():
    """The point of the whole exercise, checked against the atoms rather than a table.

    Builds a real design, places its CG beads, and asks how far each one is from the
    O5' the all-atom layer stamps for the same nucleotide.  The residual is sequence:
    the bead sites are averaged
    over the four bases, and this fixture is all-DT.
    """
    from pathlib import Path

    from backend.core.atomistic import build_atomistic_model
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.models import Design

    design = Design.model_validate_json(Path("Examples/6hb_test.nadoc").read_text())
    o5 = {
        (a.helix_id, a.bp_index, a.direction): np.array([a.x, a.y, a.z])
        for a in build_atomistic_model(design).atoms
        if a.name == "O5'"
    }

    def miss(measured: bool) -> float:
        d = []
        for n in _geometry_for_helices(design, measured_positioning=measured):
            p = o5.get((n["helix_id"], n["bp_index"], n["direction"]))
            if p is not None:
                d.append(float(np.linalg.norm(np.array(n["backbone_position"]) - p)))
        return float(np.median(d))

    # The remaining ~0.025 nm is sequence specificity: the display site is averaged over
    # all four residues while this fixture stamps one concrete residue at each site.
    # Lattice-groove registration used to leave this at 0.545 nm on REVERSE/None cells.
    with pytest.raises(NativePlacementError, match="Legacy bead/slab placement has been removed"):
        miss(measured=False)
    assert miss(measured=True) < 0.027


def test_both_lattice_cell_types_overlay_the_atomistic_o5_prime():
    """A lattice-cell label must not select a different physical duplex geometry."""
    from pathlib import Path

    from backend.core.atomistic import build_atomistic_model
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.models import Design

    fixture = Path("workspace/2hbx1.nadoc")
    if not fixture.exists():
        pytest.skip(f"fixture {fixture} not present on this machine")
    design = Design.model_validate_json(fixture.read_text())
    cells = {h.id: h.direction for h in design.helices}
    atoms_by_name = {
        (a.helix_id, a.bp_index, a.direction, a.name): np.array([a.x, a.y, a.z])
        for a in build_atomistic_model(design).atoms
        if a.name in {"O5'", "C5'", "C3'"}
    }
    misses = {Direction.FORWARD: [], Direction.REVERSE: []}
    wrong_landmark_misses = {"C5'": [], "C3'": []}
    for n in _geometry_for_helices(
        design, measured_positioning=True, junction_balance=True
    ):
        key = (n["helix_id"], n["bp_index"], n["direction"])
        bead = np.asarray(n["backbone_position"])
        misses[cells[n["helix_id"]]].append(
            float(np.linalg.norm(bead - atoms_by_name[(*key, "O5'")]))
        )
        for atom_name in wrong_landmark_misses:
            wrong_landmark_misses[atom_name].append(
                float(np.linalg.norm(bead - atoms_by_name[(*key, atom_name)]))
            )

    assert max(misses[Direction.FORWARD]) < 0.027
    assert max(misses[Direction.REVERSE]) < 0.027
    assert min(wrong_landmark_misses["C5'"]) > 0.10
    assert min(wrong_landmark_misses["C3'"]) > 0.20


def test_template_is_the_only_source_and_missing_data_fails(monkeypatch):
    from backend.core import measured_atomistic, measured_positioning
    assert _from_atomistic_template("O5'") == FULL_REP
    assert not hasattr(measured_positioning, "_FALLBACK")
    assert not hasattr(measured_positioning, "_FULL_REP_FALLBACK")
    assert not hasattr(measured_positioning, "apply_measured_positioning")

    def unavailable():
        raise measured_atomistic.MeasuredTemplateUnavailable("deliberately missing test source")
    monkeypatch.setattr(measured_atomistic, "measured_templates", unavailable)
    with pytest.raises(measured_atomistic.MeasuredTemplateUnavailable):
        _from_atomistic_template("O5'")


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

    def atoms():
        m = build_atomistic_model(design, close_backbone=False)
        return np.array([[a.x, a.y, a.z] for a in m.atoms], dtype=float)

    before = atoms()
    _geometry_for_helices(design)
    after = atoms()
    np.testing.assert_array_equal(before, after)


def test_the_periodic_seam_solver_still_gets_a_valid_axis():
    """`periodic_polymer._section_frame_from_arrs` recovers a helix's cross-section frame.

    ⚠ Premise changed 2026-08-07 (helical-site Phase 3). It used to ANALYTICALLY INVERT
    `HELIX_RADIUS` and the groove offset to recover the axis from the two strands' beads,
    which is why it carried a TD-27 warning that pushing the measured re-placement down
    into `geometry.py` would make it return a WRONG axis rather than fail. It now READS
    the forward nucleotide's own carried axis point and radial, so that failure mode is
    gone: a re-placed bead brings its own site or none.

    Still pinned the same way — the recovered frame must be the known helix's true axis.
    """
    from backend.core.deformation import deformed_nucleotide_arrays
    from backend.core.models import Design

    from backend.core import periodic_polymer as pp

    helix = _straight_helix(Direction.FORWARD, n_bp=24)
    design = Design(name="pin", helices=[helix], strands=[])
    arrs = deformed_nucleotide_arrays(helix, design)

    frame = pp._section_frame_from_arrs(arrs, 0)
    assert frame is not None, "the seam solver could not recover an axis at all"
    origin, z = np.asarray(frame)[:3, 3], np.asarray(frame)[:3, 2]
    # The fixture helix runs along +Z from the origin.
    assert np.allclose(np.abs(z), [0.0, 0.0, 1.0], atol=1e-9)
    assert np.allclose(origin[:2], [0.0, 0.0], atol=1e-9), (
        "recovered axis is off the true centreline — the inverter's build-convention "
        "assumption (HELIX_RADIUS + groove_offset_rad) no longer holds"
    )


def test_oxdna_converts_canonical_o5_to_its_named_centre_of_mass_landmark():
    """The oxDNA conversion is a chemical export boundary, not a display option."""
    from pathlib import Path

    from backend.core.deformation import deformed_helix_axes
    from backend.core.design_geometry import _geometry_for_helices
    from backend.core.models import Design
    from backend.physics.oxdna_interface import _oxdna_cm_radius_map, resolved_nuc_map

    design = Design.model_validate_json(Path("Examples/6hb_test.nadoc").read_text())
    axes = {
        a["helix_id"]: (
            np.asarray(a["start"], float),
            np.asarray(a["end"], float) - np.asarray(a["start"], float),
        )
        for a in deformed_helix_axes(design)
    }

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

    native = _geometry_for_helices(design, None, compact_skips=True)
    measured = {(n["helix_id"], n["bp_index"], n["direction"]): n for n in native}
    # The shared resolver now performs the conversion before any writer can
    # mistake an O5′ landmark for a particle CM. Inspect both sides explicitly.
    assert radii(measured) == pytest.approx(FULL_REP.backbone_fwd.radius_nm, abs=5e-3)
    physical = resolved_nuc_map(design, native)
    assert radii(physical) == pytest.approx(HELIX_RADIUS, abs=1e-6)
    assert _oxdna_cm_radius_map(design, physical) is physical


def test_rotated_oh7_keeps_the_same_measured_bead_to_base_geometry():
    """Rigid overhang rotation must happen after measured native placement.

    VoltronCoreArm OH7 used to fail the measured-placement axis guard after it had
    already been rotated, leaving its slabs in legacy placement beside measured slabs.
    """
    from pathlib import Path

    from backend.core.design_geometry import _geometry_for_design
    from backend.core.models import Design

    path = Path("workspace/VoltronCoreArm.nadoc")
    if not path.exists():
        pytest.skip("requires local workspace fixture VoltronCoreArm.nadoc")
    design = Design.model_validate_json(path.read_text())
    geometry = _geometry_for_design(
        design, junction_balance=True, measured_positioning=True
    )

    def slab_local_center_offset(helix_id, bp_index, strand_id):
        pair = [
            n for n in geometry
            if n["helix_id"] == helix_id and n["bp_index"] == bp_index
        ]
        nuc = next(n for n in pair if n["strand_id"] == strand_id)
        mate = next(n for n in pair if n["direction"] != nuc["direction"])
        bead = np.asarray(nuc["backbone_position"], dtype=float)
        center = np.asarray(nuc["base_position"], dtype=float).copy()
        tangent = np.asarray(nuc["axis_tangent"], dtype=float)
        tangent /= np.linalg.norm(tangent)
        normal = np.asarray(nuc["base_normal"], dtype=float)
        local_z = normal - tangent * np.dot(normal, tangent)
        local_z /= np.linalg.norm(local_z)
        local_x = np.cross(tangent, local_z)
        local_x /= np.linalg.norm(local_x)
        mate_base = np.asarray(mate["base_position"], dtype=float)
        center += tangent * (np.dot(mate_base, tangent) - np.dot(center, tangent)) * 0.5
        radial = bead - center
        radial -= tangent * np.dot(radial, tangent)
        distance = np.linalg.norm(radial)
        radial /= distance
        support = abs(np.dot(radial, local_x)) * 0.15 + abs(np.dot(radial, local_z)) * 0.35
        center += radial * max(0.0, distance - support + 0.02)
        offset = center - bead
        return np.array([
            np.dot(offset, local_x), np.dot(offset, tangent), np.dot(offset, local_z)
        ])

    oh7 = slab_local_center_offset("h_sc_55", 40, "sc_strand_167")
    ordinary_duplex = slab_local_center_offset("h_sc_44", 72, "sc_strand_205")
    assert oh7 == pytest.approx(ordinary_duplex, abs=1e-12)
    assert oh7 == pytest.approx([0.053483996701, 0.0155, 0.344734740832], abs=1e-12)
