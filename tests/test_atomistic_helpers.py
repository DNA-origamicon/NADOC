"""
Unit tests for backend/core/atomistic_helpers.py (Pass 11-A pure-helper extract).

Coverage target: ≥90% on the helpers module per precondition #21
(matches Pass 9-B gromacs_helpers + Pass 10-A namd_helpers precedent).

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
    _COS_C3O3P,
    _COS_O3PO5,
    _COS_PO5C5,
    _DEG2RAD,
    _FRAC_O3_F,
    _FRAC_O5_B,
    _FRAC_O5_F,
    _FRAC_P_B,
    _FRAC_P_F,
    _PHOSPHATE_ATOMS,
    _R_REPULSION,
    _TOTAL_LINKER_B,
    _TOTAL_LINKER_F,
    _W_GLYCOSIDIC,
    _W_REPULSION,
    _arc_bow_dir,
    _arc_ctrl_pt,
    _backbone_bridge_cost,
    _backbone_bridge_cost_grad,
    _bezier_pt,
    _bezier_tan,
    _bwd_bridge_x0,
    _cos_angle_3pt,
    _cos_angle_grad,
    _fwd_bridge_x0,
    _glycosidic_cost,
    _glycosidic_cost_grad,
    _lerp,
    _make_spin_rotation,
    _normalise,
    _rb_grad_propagate,
    _rb_pair_repulsion,
    _rb_pair_repulsion_grad,
    _repulsion_cost,
    _repulsion_cost_grad,
    _spin_rotation_deriv,
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

    def test_cos_constants_match_canonical_angles(self) -> None:
        assert _COS_C3O3P == pytest.approx(math.cos(_CANON_C3O3P * _DEG2RAD))
        assert _COS_O3PO5 == pytest.approx(math.cos(_CANON_O3PO5 * _DEG2RAD))
        assert _COS_PO5C5 == pytest.approx(math.cos(_CANON_PO5C5 * _DEG2RAD))

    def test_phosphate_atoms_set(self) -> None:
        assert _PHOSPHATE_ATOMS == frozenset({"P", "OP1", "OP2", "O5'"})

    def test_weights_positive(self) -> None:
        assert _W_GLYCOSIDIC > 0
        assert _W_REPULSION  > 0
        assert 0.0 < _R_REPULSION < 1.0   # nm

    def test_linker_fractions_in_unit_interval(self) -> None:
        for f in (_FRAC_O3_F, _FRAC_P_F, _FRAC_O5_F, _FRAC_P_B, _FRAC_O5_B):
            assert 0.0 < f < 1.0

    def test_total_linker_lengths_consistent(self) -> None:
        # Total fwd/bwd linker lengths derived from canonical bond lengths
        assert _TOTAL_LINKER_F == pytest.approx(
            _CANON_C3O3 + _CANON_O3P + _CANON_PO5 + _CANON_O5C5
        )
        assert _TOTAL_LINKER_B == pytest.approx(
            _CANON_O3P + _CANON_PO5 + _CANON_O5C5
        )

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


class TestCosAngle3pt:
    def test_right_angle(self) -> None:
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])
        c = np.array([0.0, 1.0, 0.0])
        assert _cos_angle_3pt(a, b, c) == pytest.approx(0.0)

    def test_collinear_zero_angle(self) -> None:
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])
        c = np.array([2.0, 0.0, 0.0])
        assert _cos_angle_3pt(a, b, c) == pytest.approx(1.0)

    def test_collinear_180(self) -> None:
        a = np.array([1.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])
        c = np.array([-1.0, 0.0, 0.0])
        assert _cos_angle_3pt(a, b, c) == pytest.approx(-1.0)

    def test_degenerate_arm_returns_one(self) -> None:
        # Both A and B at the same position → degenerate
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([0.0, 0.0, 0.0])
        c = np.array([1.0, 0.0, 0.0])
        assert _cos_angle_3pt(a, b, c) == 1.0


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


class TestSpinRotationDeriv:
    def test_zero_angle_yields_skew(self) -> None:
        axis = np.array([0.0, 0.0, 1.0])
        dR = _spin_rotation_deriv(axis, 0.0)
        # at θ=0: dR/dθ = K (the skew-symmetric matrix)
        K = np.array([
            [0.0, -1.0, 0.0],
            [1.0,  0.0, 0.0],
            [0.0,  0.0, 0.0],
        ])
        assert np.allclose(dR, K)

    def test_finite_difference(self) -> None:
        axis = np.array([0.0, 0.0, 1.0])
        theta = 0.5
        eps = 1e-6
        R_plus  = _make_spin_rotation(axis, theta + eps)
        R_minus = _make_spin_rotation(axis, theta - eps)
        dR_fd   = (R_plus - R_minus) / (2 * eps)
        dR_an   = _spin_rotation_deriv(axis, theta)
        assert np.allclose(dR_an, dR_fd, atol=1e-6)


# ── Cost / gradient leaves ───────────────────────────────────────────────────


def _canonical_chain() -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Construct a perfect canonical-geometry C3'–O3'–P–O5'–C5' chain.

    Bond lengths match _CANON_* values; bond angles match _CANON_*P/_O3PO5/_PO5C5
    so _backbone_bridge_cost evaluates to exactly zero. Built iteratively in 2D:
    each successive atom is placed so that the previous bond and the new bond
    subtend the canonical angle. Specifically, the new direction is the previous
    bond's direction rotated by (π − angle), which gives interior angle = angle.
    """
    def _rotz(v: np.ndarray, theta: float) -> np.ndarray:
        c, s = math.cos(theta), math.sin(theta)
        return np.array([c * v[0] - s * v[1], s * v[0] + c * v[1], v[2]])

    angle_c3o3p = _CANON_C3O3P * _DEG2RAD
    angle_o3po5 = _CANON_O3PO5 * _DEG2RAD
    angle_po5c5 = _CANON_PO5C5 * _DEG2RAD

    c3 = np.array([0.0, 0.0, 0.0])
    # First bond direction: along +x
    d1 = np.array([1.0, 0.0, 0.0])
    o3 = c3 + _CANON_C3O3 * d1
    # Next direction: prev rotated by (π − angle_c3o3p)
    d2 = _rotz(d1, math.pi - angle_c3o3p)
    p = o3 + _CANON_O3P * d2
    d3 = _rotz(d2, math.pi - angle_o3po5)
    o5 = p + _CANON_PO5 * d3
    d4 = _rotz(d3, math.pi - angle_po5c5)
    c5 = o5 + _CANON_O5C5 * d4
    return c3, o3, p, o5, c5


class TestBackboneBridgeCost:
    def test_canonical_geometry_zero_cost(self) -> None:
        c3, o3, p, o5, c5 = _canonical_chain()
        cost = _backbone_bridge_cost(c3, o3, p, o5, c5)
        assert cost == pytest.approx(0.0, abs=1e-10)

    def test_stretched_bond_increases_cost(self) -> None:
        c3, o3, p, o5, c5 = _canonical_chain()
        # Stretch O3 away by 0.1 nm
        o3_stretched = o3 + np.array([0.1, 0.0, 0.0])
        cost = _backbone_bridge_cost(c3, o3_stretched, p, o5, c5)
        assert cost > 0.0

    def test_cost_nonnegative(self) -> None:
        c3 = np.array([0.0, 0.0, 0.0])
        o3 = np.array([0.5, 0.0, 0.0])
        p  = np.array([0.5, 0.5, 0.0])
        o5 = np.array([0.5, 1.0, 0.0])
        c5 = np.array([0.0, 1.0, 0.0])
        assert _backbone_bridge_cost(c3, o3, p, o5, c5) >= 0.0


class TestCosAngleGrad:
    def test_finite_difference_perpendicular(self) -> None:
        A = np.array([1.0, 0.0, 0.0])
        B = np.array([0.0, 0.0, 0.0])
        C = np.array([0.0, 1.0, 0.0])
        cos_t, dA, dB, dC = _cos_angle_grad(A, B, C)
        assert cos_t == pytest.approx(0.0)
        # finite-difference dA[0] (perturb A in x)
        eps = 1e-6
        A_p = A + np.array([eps, 0.0, 0.0])
        A_m = A - np.array([eps, 0.0, 0.0])
        fd = (_cos_angle_3pt(A_p, B, C) - _cos_angle_3pt(A_m, B, C)) / (2 * eps)
        assert dA[0] == pytest.approx(fd, abs=1e-6)

    def test_degenerate_zeros(self) -> None:
        A = np.zeros(3)
        B = np.zeros(3)
        C = np.array([1.0, 0.0, 0.0])
        cos_t, dA, dB, dC = _cos_angle_grad(A, B, C)
        assert cos_t == 1.0
        assert np.allclose(dA, 0.0)
        assert np.allclose(dB, 0.0)
        assert np.allclose(dC, 0.0)


class TestBackboneBridgeCostGrad:
    def test_finite_difference_match(self) -> None:
        # Off-canonical chain; verify analytic grad matches finite-difference
        rng = np.random.default_rng(42)
        c3 = rng.normal(size=3)
        o3 = c3 + np.array([_CANON_C3O3, 0.0, 0.0]) + 0.02 * rng.normal(size=3)
        p  = o3 + np.array([0.0, _CANON_O3P, 0.0])  + 0.02 * rng.normal(size=3)
        o5 = p  + np.array([_CANON_PO5, 0.0, 0.0]) + 0.02 * rng.normal(size=3)
        c5 = o5 + np.array([0.0, _CANON_O5C5, 0.0]) + 0.02 * rng.normal(size=3)

        cost, g_c3, g_o3, g_p, g_o5, g_c5 = _backbone_bridge_cost_grad(
            c3, o3, p, o5, c5
        )

        # Spot-check ∂/∂o3[1] via finite difference
        eps = 1e-6
        o3_p = o3.copy()
        o3_p[1] += eps
        o3_m = o3.copy()
        o3_m[1] -= eps
        fd = (_backbone_bridge_cost(c3, o3_p, p, o5, c5)
              - _backbone_bridge_cost(c3, o3_m, p, o5, c5)) / (2 * eps)
        assert g_o3[1] == pytest.approx(fd, abs=1e-5)

        # Cost matches plain function
        plain = _backbone_bridge_cost(c3, o3, p, o5, c5)
        assert cost == pytest.approx(plain, abs=1e-12)

    def test_canonical_zero_grad(self) -> None:
        c3, o3, p, o5, c5 = _canonical_chain()
        cost, g_c3, g_o3, g_p, g_o5, g_c5 = _backbone_bridge_cost_grad(
            c3, o3, p, o5, c5
        )
        assert cost == pytest.approx(0.0, abs=1e-10)
        for g in (g_c3, g_o3, g_p, g_o5, g_c5):
            assert np.allclose(g, 0.0, atol=1e-6)


class TestGlycosidicCost:
    def test_aligned_returns_zero(self) -> None:
        w = {"C1'": np.array([0.0, 0.0, 0.0]),
             "N1":  np.array([1.0, 0.0, 0.0])}
        target = np.array([1.0, 0.0, 0.0])
        assert _glycosidic_cost(w, "N1", target) == pytest.approx(0.0)

    def test_anti_aligned_returns_two(self) -> None:
        w = {"C1'": np.array([0.0, 0.0, 0.0]),
             "N1":  np.array([1.0, 0.0, 0.0])}
        target = np.array([-1.0, 0.0, 0.0])
        assert _glycosidic_cost(w, "N1", target) == pytest.approx(2.0)

    def test_missing_n_returns_zero(self) -> None:
        w = {"C1'": np.array([0.0, 0.0, 0.0])}
        target = np.array([1.0, 0.0, 0.0])
        assert _glycosidic_cost(w, "N9", target) == 0.0

    def test_missing_c1_returns_zero(self) -> None:
        w = {"N1": np.array([1.0, 0.0, 0.0])}
        target = np.array([1.0, 0.0, 0.0])
        assert _glycosidic_cost(w, "N1", target) == 0.0

    def test_zero_length_c1n_returns_zero(self) -> None:
        w = {"C1'": np.array([0.0, 0.0, 0.0]),
             "N1":  np.array([0.0, 0.0, 0.0])}
        target = np.array([1.0, 0.0, 0.0])
        assert _glycosidic_cost(w, "N1", target) == 0.0


class TestGlycosidicCostGrad:
    def test_finite_difference(self) -> None:
        c1 = np.array([0.0, 0.0, 0.0])
        n  = np.array([0.7, 0.3, 0.1])
        target = np.array([1.0, 0.0, 0.0])
        cost, g_c1, g_n = _glycosidic_cost_grad(c1, n, target)

        # ∂/∂n[1]
        eps = 1e-6
        n_p = n.copy()
        n_p[1] += eps
        n_m = n.copy()
        n_m[1] -= eps
        c_p = 1.0 - float(np.dot((n_p - c1) / np.linalg.norm(n_p - c1), target))
        c_m = 1.0 - float(np.dot((n_m - c1) / np.linalg.norm(n_m - c1), target))
        fd = (c_p - c_m) / (2 * eps)
        assert g_n[1] == pytest.approx(fd, abs=1e-6)

    def test_zero_length_returns_zeros(self) -> None:
        c1 = np.array([1.0, 0.0, 0.0])
        n  = np.array([1.0, 0.0, 0.0])
        target = np.array([1.0, 0.0, 0.0])
        cost, g_c1, g_n = _glycosidic_cost_grad(c1, n, target)
        assert cost == 0.0
        assert np.allclose(g_c1, 0.0)
        assert np.allclose(g_n, 0.0)


class TestRepulsionCost:
    def test_no_clash_zero_cost(self) -> None:
        w = {"C1'": np.array([0.0, 0.0, 0.0])}
        repel = [np.array([10.0, 0.0, 0.0])]   # far away
        assert _repulsion_cost(w, repel) == 0.0

    def test_clash_increases_cost(self) -> None:
        w = {"C1'": np.array([0.0, 0.0, 0.0])}
        repel = [np.array([0.1, 0.0, 0.0])]    # well inside _R_REPULSION
        cost = _repulsion_cost(w, repel)
        assert cost > 0.0

    def test_missing_atom_skipped(self) -> None:
        w = {"P": np.array([0.0, 0.0, 0.0])}   # not C1/C3/C4
        repel = [np.array([0.1, 0.0, 0.0])]
        assert _repulsion_cost(w, repel) == 0.0


class TestRepulsionCostGrad:
    def test_finite_difference(self) -> None:
        w = {"C1'": np.array([0.05, 0.05, 0.0])}
        repel = [np.array([0.0, 0.0, 0.0])]
        cost, g_dict = _repulsion_cost_grad(w, repel)
        assert cost > 0.0
        # ∂/∂C1'[0] via finite difference
        eps = 1e-7
        wp = {"C1'": w["C1'"] + np.array([eps, 0.0, 0.0])}
        wm = {"C1'": w["C1'"] - np.array([eps, 0.0, 0.0])}
        fd = (_repulsion_cost(wp, repel) - _repulsion_cost(wm, repel)) / (2 * eps)
        assert g_dict["C1'"][0] == pytest.approx(fd, abs=1e-4)

    def test_no_clash_zero_grad(self) -> None:
        w = {"C1'": np.array([0.0, 0.0, 0.0])}
        repel = [np.array([10.0, 0.0, 0.0])]
        cost, g_dict = _repulsion_cost_grad(w, repel)
        assert cost == 0.0
        assert np.allclose(g_dict["C1'"], 0.0)


class TestRBPairRepulsion:
    def test_no_clash(self) -> None:
        w1 = {"C1'": np.array([0.0, 0.0, 0.0])}
        w2 = {"C1'": np.array([1.0, 0.0, 0.0])}
        assert _rb_pair_repulsion(w1, w2) == 0.0

    def test_clash_positive(self) -> None:
        w1 = {"C1'": np.array([0.0, 0.0, 0.0])}
        w2 = {"C1'": np.array([0.1, 0.0, 0.0])}
        assert _rb_pair_repulsion(w1, w2) > 0.0


class TestRBPairRepulsionGrad:
    def test_finite_difference(self) -> None:
        w1 = {"C1'": np.array([0.0, 0.0, 0.0])}
        w2 = {"C1'": np.array([0.15, 0.0, 0.0])}
        cost, g1, g2 = _rb_pair_repulsion_grad(w1, w2)
        assert cost > 0.0
        # ∂/∂w2["C1'"][0]
        eps = 1e-7
        w2p = {"C1'": w2["C1'"] + np.array([eps, 0.0, 0.0])}
        w2m = {"C1'": w2["C1'"] - np.array([eps, 0.0, 0.0])}
        fd = (_rb_pair_repulsion(w1, w2p) - _rb_pair_repulsion(w1, w2m)) / (2 * eps)
        assert g2["C1'"][0] == pytest.approx(fd, abs=1e-4)

    def test_no_atoms_zero(self) -> None:
        w1: dict[str, np.ndarray] = {}
        w2: dict[str, np.ndarray] = {}
        cost, g1, g2 = _rb_pair_repulsion_grad(w1, w2)
        assert cost == 0.0
        assert g1 == {}
        assert g2 == {}


class TestRBGradPropagate:
    def test_translation_gradient(self) -> None:
        # Translation only: ∂f/∂delta = Σ g_w
        names = ("C1'", "C2'")
        mat = np.array([[1.0, 0.0, 0.0], [0.0, 1.0, 0.0]])
        g_w = {"C1'": np.array([1.0, 2.0, 3.0]),
               "C2'": np.array([4.0, 5.0, 6.0])}
        dR = np.zeros((3, 3))
        g_delta, g_theta = _rb_grad_propagate(g_w, names, mat, dR)
        assert np.allclose(g_delta, np.array([5.0, 7.0, 9.0]))
        assert g_theta == 0.0

    def test_theta_gradient(self) -> None:
        names = ("C1'",)
        mat = np.array([[1.0, 0.0, 0.0]])
        g_w = {"C1'": np.array([0.0, 1.0, 0.0])}
        # dR/dθ such that dR @ [1,0,0] = [0,1,0]
        dR = np.array([
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
            [0.0, 0.0, 0.0],
        ])
        _, g_theta = _rb_grad_propagate(g_w, names, mat, dR)
        # dot([0,1,0], dR @ [1,0,0]) = dot([0,1,0],[0,1,0]) = 1.0
        assert g_theta == pytest.approx(1.0)

    def test_unknown_name_skipped(self) -> None:
        names = ("C1'",)
        mat = np.array([[1.0, 0.0, 0.0]])
        g_w = {"C1'": np.array([1.0, 0.0, 0.0]),
               "FOO": np.array([5.0, 0.0, 0.0])}   # not in names
        dR = np.zeros((3, 3))
        g_delta, _ = _rb_grad_propagate(g_w, names, mat, dR)
        # FOO is still summed into delta gradient (translation applies to all)
        assert np.allclose(g_delta, np.array([6.0, 0.0, 0.0]))


# ── Bridge x0 helpers ─────────────────────────────────────────────────────────


class TestFwdBridgeX0:
    def test_endpoints_in_chord(self) -> None:
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])
        o3, p, o5 = _fwd_bridge_x0(a, b)
        # All on the chord
        for pt in (o3, p, o5):
            assert pt[1] == pytest.approx(0.0)
            assert pt[2] == pytest.approx(0.0)
            assert 0.0 < pt[0] < 1.0
        # Strictly increasing along the chord
        assert o3[0] < p[0] < o5[0]


class TestBwdBridgeX0:
    def test_endpoints_in_chord(self) -> None:
        a = np.array([0.0, 0.0, 0.0])
        b = np.array([1.0, 0.0, 0.0])
        p, o5 = _bwd_bridge_x0(a, b)
        for pt in (p, o5):
            assert pt[1] == pytest.approx(0.0)
            assert pt[2] == pytest.approx(0.0)
            assert 0.0 < pt[0] < 1.0
        assert p[0] < o5[0]


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
