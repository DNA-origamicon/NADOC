"""The MD-measured display placement, and the two defects it corrects.

These pin the audit findings, not just the code: if someone "fixes" the frame-origin
correction in atomistic.py or changes the groove sign convention in geometry.py, the
assertions about the DEFECT will fail and point at what moved.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from backend.core.atomistic import _ATOMISTIC_P_RADIUS, _ATOMISTIC_PP_SEP_RAD
from backend.core.constants import HELIX_RADIUS
from backend.core.measured_positioning import (
    MEASURED,
    apply_measured_positioning,
    template_p_azimuth_offset_rad,
)
from backend.core.models import Direction, Helix, Vec3


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
    phi = template_p_azimuth_offset_rad(_ATOMISTIC_P_RADIUS)
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

    assert miss(measured=False) > 0.40, "legacy bead is nowhere near the C3'"
    assert miss(measured=True) < 0.05, "measured bead must sit ON the C3'"
