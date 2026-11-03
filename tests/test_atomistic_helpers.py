"""
Unit tests for the helpers used by atomistic construction and extra-base placement.

The unused cost/gradient extraction is outside this suite. The active bridge
objective is covered in test_atomistic_minimisers.py.

Each helper class targets one extracted function with synthetic numeric inputs
and pure-output assertions — no Design / Atom / topology objects involved.
"""

from __future__ import annotations

import math

import numpy as np
import pytest

from backend.core.atomistic_helpers import (
    _BOW_FRAC_3D,
    _CANON_C3O3,
    _CANON_C3O3P,
    _CANON_O3P,
    _CANON_O3PO5,
    _CANON_O5C5,
    _CANON_PO5,
    _CANON_PO5C5,
    _DEG2RAD,
    _arc_bow_dir,
    _arc_ctrl_pt,
    _bezier_pt,
    _bezier_tan,
    _lerp,
    _make_spin_rotation,
    _normalise,
)


# ── Constants sanity ──────────────────────────────────────────────────────────


class TestConstants:
    def test_canonical_bond_lengths_in_nm(self) -> None:
        # B-DNA / AMBER ff14SB: 0.14–0.16 nm range
        for L in (_CANON_C3O3, _CANON_O3P, _CANON_PO5, _CANON_O5C5):
            assert 0.13 < L < 0.17

    def test_canonical_bond_angles_in_degrees(self) -> None:
        for A in (_CANON_C3O3P, _CANON_O3PO5, _CANON_PO5C5):
            assert 90.0 < A < 130.0

    def test_deg2rad_matches_math(self) -> None:
        assert _DEG2RAD == pytest.approx(math.pi / 180.0)

    def test_bow_frac_3d_value(self) -> None:
        assert _BOW_FRAC_3D == pytest.approx(0.3)


# ── Pure-math primitives ──────────────────────────────────────────────────────


class TestNormalise:
    def test_unit_vector_unchanged(self) -> None:
        v = np.array([1.0, 0.0, 0.0])
        n = _normalise(v)
        assert np.allclose(n, v)

    def test_long_vector_normalised(self) -> None:
        v = np.array([3.0, 4.0, 0.0])
        n = _normalise(v)
        assert n == pytest.approx(np.array([0.6, 0.8, 0.0]))
        assert float(np.linalg.norm(n)) == pytest.approx(1.0)

    def test_zero_vector_returned_unchanged(self) -> None:
        v = np.zeros(3)
        n = _normalise(v)
        assert np.allclose(n, v)


class TestLerp:
    def test_endpoints(self) -> None:
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([2.0, 4.0, 6.0])
        assert np.allclose(_lerp(a, b, 0.0), a)
        assert np.allclose(_lerp(a, b, 1.0), b)

    def test_midpoint(self) -> None:
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([2.0, 4.0, 6.0])
        assert np.allclose(_lerp(a, b, 0.5), np.array([1.0, 2.0, 3.0]))

    def test_extrapolation(self) -> None:
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])
        assert np.allclose(_lerp(a, b, 2.0), np.array([2.0, 0.0, 0.0]))


class TestMakeSpinRotation:
    def test_zero_angle_identity(self) -> None:
        axis = np.array([0.0, 0.0, 1.0])
        R = _make_spin_rotation(axis, 0.0)
        assert np.allclose(R, np.eye(3))

    def test_90_degree_z_axis(self) -> None:
        axis = np.array([0.0, 0.0, 1.0])
        R = _make_spin_rotation(axis, math.pi / 2)
        v = np.array([1.0, 0.0, 0.0])
        rotated = R @ v
        assert np.allclose(rotated, np.array([0.0, 1.0, 0.0]), atol=1e-10)

    def test_180_about_x_flips_y(self) -> None:
        axis = np.array([1.0, 0.0, 0.0])
        R = _make_spin_rotation(axis, math.pi)
        v = np.array([0.0, 1.0, 0.0])
        rotated = R @ v
        assert np.allclose(rotated, np.array([0.0, -1.0, 0.0]), atol=1e-10)


# ── Extra-base arc helpers ────────────────────────────────────────────────────


class TestBezierPt:
    def test_endpoints(self) -> None:
        a = np.array([0.0, 0.0, 0.0])
        c = np.array([0.5, 1.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])
        assert np.allclose(_bezier_pt(a, c, b, 0.0), a)
        assert np.allclose(_bezier_pt(a, c, b, 1.0), b)

    def test_midpoint(self) -> None:
        a = np.array([0.0, 0.0, 0.0])
        c = np.array([0.5, 1.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])
        # mid = 0.25 a + 0.5 c + 0.25 b = (0.25 + 0.5*0.5 + 0.25, 0.5*1.0, 0)
        # x = 0.25 + 0.25 + 0.25 = 0.5; y = 0.5
        mid = _bezier_pt(a, c, b, 0.5)
        assert mid == pytest.approx(np.array([0.5, 0.5, 0.0]))


class TestBezierTan:
    def test_unit_norm(self) -> None:
        a = np.array([0.0, 0.0, 0.0])
        c = np.array([0.5, 1.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])
        for t in (0.0, 0.25, 0.5, 0.75, 1.0):
            tan = _bezier_tan(a, c, b, t)
            assert float(np.linalg.norm(tan)) == pytest.approx(1.0)

    def test_at_start_points_toward_ctrl(self) -> None:
        a = np.array([0.0, 0.0, 0.0])
        c = np.array([1.0, 0.0, 0.0])
        b = np.array([2.0, 1.0, 0.0])
        tan = _bezier_tan(a, c, b, 0.0)
        # Tangent at t=0 is 2(C-A) — direction points toward (1, 0, 0) → +x
        assert tan[0] > 0.0
        assert tan[1] == pytest.approx(0.0)


def test_crossover_extra_base_placement_contract():
    from backend.core.atomistic_helpers import crossover_extra_base_placements

    a = np.array([0.0, 0.0, 0.0])
    b = np.array([2.0, 0.0, 0.0])
    axis = np.array([0.0, 0.0, 1.0])
    placements = crossover_extra_base_placements(a, b, axis, axis, 3)
    assert [p["geometric_index"] for p in placements] == [0, 1, 2]
    assert [p["t"] for p in placements] == pytest.approx([0.25, 0.5, 0.75])
    for p in placements:
        assert float(np.linalg.norm(p["tangent"])) == pytest.approx(1.0)
        assert p["center"].shape == (3,)
        assert p["bow"].shape == (3,)

    reversed_placements = crossover_extra_base_placements(
        a, b, axis, axis, 3, sim_reversed=True
    )
    assert [p["sim_k"] for p in reversed_placements] == [2, 1, 0]
    for p in reversed_placements:
        assert p["chain_tangent"] == pytest.approx(-p["tangent"])


@pytest.mark.parametrize(
    ("sim_reversed", "expected_center", "expected_quaternion"),
    [
        (
            False,
            np.array([1.0350126516288711, -0.07173220248105638, -0.11421214332034445]),
            np.array(
                [
                    -0.10871135764025318,
                    0.05191393506416845,
                    -0.3845073158890162,
                    0.9152272439640281,
                ]
            ),
        ),
        (
            True,
            np.array([0.9294409122891801, -0.16297393786874226, 0.154884325969625]),
            np.array(
                [
                    -0.0653133319390967,
                    -0.08778461219542308,
                    -0.20145497692027542,
                    0.9733673113510458,
                ]
            ),
        ),
    ],
)
def test_one_base_default_uses_measured_junction_local_pose(
    sim_reversed, expected_center, expected_quaternion
):
    """1xT is deliberately off the Bezier; both traversal cases are pinned."""
    from backend.core.atomistic_helpers import crossover_extra_base_placements

    a = np.array([0.0, 0.0, 0.0])
    b = np.array([2.0, 0.0, 0.0])
    axis = np.array([0.0, 0.0, 1.0])
    [placement] = crossover_extra_base_placements(
        a, b, axis, axis, 1, sim_reversed=sim_reversed
    )
    assert placement["geometric_center"] == pytest.approx([1.0, -0.3, 0.0])
    assert placement["center"] == pytest.approx(expected_center, abs=1e-12)
    assert placement["default_local_quaternion"] == pytest.approx(
        expected_quaternion, abs=1e-15
    )
    assert np.linalg.norm(placement["center"] - placement["geometric_center"]) > 0.2


@pytest.mark.parametrize("sim_reversed", [False, True])
def test_one_base_local_frame_tracks_independent_half_a_polarity(sim_reversed):
    """Opposite 2HB polarity rotates the calibrated frame without changing its arc."""
    from backend.core.atomistic_helpers import crossover_extra_base_placements

    a = np.array([0.0, 0.0, 0.0])
    b = np.array([2.0, 0.0, 0.0])
    axis = np.array([0.0, 0.0, 1.0])
    [forward] = crossover_extra_base_placements(
        a, b, axis, axis, 1, sim_reversed=sim_reversed
    )
    [reverse] = crossover_extra_base_placements(
        a, b, axis, axis, 1,
        sim_reversed=sim_reversed,
        local_frame_reversed=True,
    )

    assert reverse["geometric_center"] == pytest.approx(forward["geometric_center"])
    assert reverse["bow"] == pytest.approx(-forward["bow"])
    assert reverse["center"] != pytest.approx(forward["center"])
    # The promoted v6 2xT default has its own pair of polarity-specific poses.
    ordinary_two = crossover_extra_base_placements(a, b, axis, axis, 2)
    reversed_two = crossover_extra_base_placements(
        a, b, axis, axis, 2, local_frame_reversed=True
    )
    for ordinary, reversed_frame in zip(ordinary_two, reversed_two):
        assert reversed_frame["center"] != pytest.approx(ordinary["center"])
        assert reversed_frame["frame_rotation"] != pytest.approx(
            ordinary["frame_rotation"]
        )


class TestArcBowDir:
    def test_perpendicular_chord_axis(self) -> None:
        posA = np.array([0.0, 0.0, 0.0])
        posB = np.array([1.0, 0.0, 0.0])
        ax_a = np.array([0.0, 0.0, 1.0])
        ax_b = np.array([0.0, 0.0, 1.0])
        bow = _arc_bow_dir(posA, posB, ax_a, ax_b)
        # cross([1,0,0], [0,0,1]) = [0,-1,0] — bow direction
        assert np.allclose(bow, np.array([0.0, -1.0, 0.0]), atol=1e-9)
        assert float(np.linalg.norm(bow)) == pytest.approx(1.0)

    def test_zero_chord_returns_z(self) -> None:
        posA = np.array([1.0, 2.0, 3.0])
        posB = posA.copy()
        ax_a = np.array([1.0, 0.0, 0.0])
        ax_b = np.array([0.0, 1.0, 0.0])
        bow = _arc_bow_dir(posA, posB, ax_a, ax_b)
        assert np.allclose(bow, np.array([0.0, 0.0, 1.0]))

    def test_chord_parallel_axis_falls_back_to_axis(self) -> None:
        posA = np.array([0.0, 0.0, 0.0])
        posB = np.array([0.0, 0.0, 1.0])
        ax_a = np.array([0.0, 0.0, 1.0])
        ax_b = np.array([0.0, 0.0, 1.0])
        bow = _arc_bow_dir(posA, posB, ax_a, ax_b)
        # avg_axis = z-hat — fallback path
        assert np.allclose(bow, np.array([0.0, 0.0, 1.0]))


class TestArcCtrlPt:
    def test_midpoint_offset(self) -> None:
        posA = np.array([0.0, 0.0, 0.0])
        posB = np.array([1.0, 0.0, 0.0])
        bow = np.array([0.0, 1.0, 0.0])
        ctrl = _arc_ctrl_pt(posA, posB, bow)
        # mid (0.5, 0, 0) + bow * (1 * BOW_FRAC_3D)
        assert ctrl == pytest.approx(np.array([0.5, _BOW_FRAC_3D, 0.0]))

    def test_zero_chord_collapses_to_mid(self) -> None:
        posA = np.array([1.0, 2.0, 3.0])
        posB = posA.copy()
        bow = np.array([0.0, 1.0, 0.0])
        ctrl = _arc_ctrl_pt(posA, posB, bow)
        assert np.allclose(ctrl, posA)
