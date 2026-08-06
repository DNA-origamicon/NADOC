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
from backend.core.constants import BDNA_MINOR_GROOVE_ANGLE_RAD, HELIX_RADIUS
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
    groove = (BDNA_MINOR_GROOVE_ANGLE_RAD if direction == Direction.FORWARD
              else -BDNA_MINOR_GROOVE_ANGLE_RAD)
    return apply_measured_positioning(
        _arrays(direction), legacy_radius=HELIX_RADIUS, legacy_groove_rad=groove)


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
    lattice cell it happened to be built in."""
    seps = _pair_separation_deg(_measured(direction), ORIGIN, T)
    assert seps == pytest.approx(MEASURED.pp_separation_deg, abs=1e-6)


@pytest.mark.parametrize("direction", [Direction.FORWARD, Direction.REVERSE])
def test_beads_and_bases_sit_on_the_measured_cylinders(direction):
    arrs = _measured(direction)
    r_bb, _ = _cyl(np.asarray(arrs["positions"]), ORIGIN, T)
    r_base, _ = _cyl(np.asarray(arrs["base_positions"]), ORIGIN, T)
    assert r_bb == pytest.approx(MEASURED.backbone_radius_nm, abs=1e-9)
    assert r_base == pytest.approx(MEASURED.base_radius_nm, abs=1e-9)


def test_the_forward_strand_does_not_move_azimuthally():
    """A helix must not appear to spin when the view is toggled — only the strand
    that is demonstrably misplaced moves."""
    before = np.asarray(_arrays(Direction.FORWARD)["positions"])[0::2]
    after = np.asarray(_measured(Direction.FORWARD)["positions"])[0::2]
    for b, a in zip(before, after):
        rb = b - np.dot(b, T) * T
        ra = a - np.dot(a, T) * T
        cosang = float(np.dot(rb, ra) / (np.linalg.norm(rb) * np.linalg.norm(ra)))
        assert math.degrees(math.acos(min(1.0, cosang))) == pytest.approx(0.0, abs=1e-6)


def test_axial_positions_are_untouched():
    """Only the cross-section is re-placed; rise and phase along the axis stay put."""
    before = np.asarray(_arrays(Direction.FORWARD)["positions"])
    after = np.asarray(_measured(Direction.FORWARD)["positions"])
    assert (after @ T) == pytest.approx(before @ T, abs=1e-9)


def test_base_normals_stay_cross_strand_and_antiparallel():
    arrs = _measured(Direction.FORWARD)
    bn = np.asarray(arrs["base_normals"])
    assert bn[0::2] == pytest.approx(-bn[1::2], abs=1e-9)
    assert np.linalg.norm(bn, axis=1) == pytest.approx(1.0, abs=1e-9)


def test_the_input_arrays_are_not_mutated():
    arrs = _arrays(Direction.FORWARD)
    snapshot = np.array(arrs["positions"], copy=True)
    apply_measured_positioning(
        arrs, legacy_radius=HELIX_RADIUS, legacy_groove_rad=BDNA_MINOR_GROOVE_ANGLE_RAD)
    assert np.asarray(arrs["positions"]) == pytest.approx(snapshot)


def test_a_pair_that_cannot_be_reconciled_is_left_alone():
    """Fail safe: a base pair whose axis point cannot be recovered keeps its legacy
    placement rather than being displaced by a bad reconstruction."""
    arrs = _arrays(Direction.FORWARD)
    arrs = {k: (np.array(v, copy=True) if isinstance(v, np.ndarray) else v)
            for k, v in arrs.items()}
    arrs["positions"][0] = np.array([5.0, 5.0, 0.0])   # nowhere near the cylinder
    out = apply_measured_positioning(
        arrs, legacy_radius=HELIX_RADIUS, legacy_groove_rad=BDNA_MINOR_GROOVE_ANGLE_RAD)
    assert np.asarray(out["positions"])[0] == pytest.approx([5.0, 5.0, 0.0])
    # the rest of the helix still moved
    r_bb, _ = _cyl(np.asarray(out["positions"])[2:], ORIGIN, T)
    assert r_bb == pytest.approx(MEASURED.backbone_radius_nm, abs=1e-9)
