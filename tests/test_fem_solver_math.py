"""
Pure-math unit tests for backend.physics.fem_solver helpers.

Targets the deterministic numpy-in / numpy-out helpers:
  - _beam_stiffness_local(L)  → 12×12 Euler-Bernoulli element matrix
  - _transform_to_global(K_local, R) → R^T K R rotation to global frame
  - normalize_rmsf(rmsf, mesh) → per-key normalised dict (small + pure)

Skipped (integration paths covered elsewhere): build_fem_mesh,
assemble_global_stiffness, apply_boundary_conditions, solve_equilibrium,
compute_rmsf, deformed_positions.

DOF ordering convention from fem_solver: at each node
  [u_x, u_y, u_z, θ_x, θ_y, θ_z]
12-DOF element vector is [node_i_dofs (6), node_j_dofs (6)].
Beam axis = local z, so axial DOFs are 2 and 8 (NOT 0/6).
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.physics.fem_solver import (
    EA_DS,
    EI_DS,
    GJ_DS,
    FEMNode,
    FEMMesh,
    _beam_stiffness_local,
    _transform_to_global,
    normalize_rmsf,
)


# ─────────────────────────────────────────────────────────────────────────────
# _beam_stiffness_local
# ─────────────────────────────────────────────────────────────────────────────


class TestBeamStiffnessLocal:
    """Tests for the 12×12 local-frame Euler-Bernoulli beam stiffness matrix."""

    def test_shape_is_12x12(self) -> None:
        K = _beam_stiffness_local(0.34)
        assert K.shape == (12, 12)
        assert K.dtype == np.float64

    def test_symmetric(self) -> None:
        """Stiffness matrices must be symmetric (K_ij = K_ji)."""
        K = _beam_stiffness_local(0.34)
        # Use exact equality — entries are written symmetrically by hand.
        assert np.allclose(K, K.T, atol=1e-15)

    def test_axial_block_uses_local_z(self) -> None:
        """
        Axial DOFs are at local-z (indices 2 and 8).  For length L:
            K[2,2] = K[8,8] = EA/L,  K[2,8] = K[8,2] = -EA/L.
        """
        L = 0.5
        K = _beam_stiffness_local(L)
        ea_over_L = EA_DS / L
        assert K[2, 2] == pytest.approx(ea_over_L)
        assert K[8, 8] == pytest.approx(ea_over_L)
        assert K[2, 8] == pytest.approx(-ea_over_L)
        assert K[8, 2] == pytest.approx(-ea_over_L)

    def test_torsion_block_at_theta_z(self) -> None:
        """
        Torsion DOFs are θ_z at each node (indices 5 and 11).
            K[5,5] = K[11,11] = GJ/L,  K[5,11] = -GJ/L.
        """
        L = 0.5
        K = _beam_stiffness_local(L)
        gj_over_L = GJ_DS / L
        assert K[5, 5] == pytest.approx(gj_over_L)
        assert K[11, 11] == pytest.approx(gj_over_L)
        assert K[5, 11] == pytest.approx(-gj_over_L)
        assert K[11, 5] == pytest.approx(-gj_over_L)

    def test_bending_xz_plane_diagonal_constants(self) -> None:
        """
        Bending in x-z plane couples u (idx 0) and θ_y (idx 4) at each node.
        Standard Bernoulli element:
            K[u,u]   =  12 EI / L^3   (= c1)
            K[θy,θy] =   4 EI / L     (= c3)
        """
        L = 0.34
        K = _beam_stiffness_local(L)
        c1 = 12.0 * EI_DS / L**3
        c3 = 4.0 * EI_DS / L
        # u1, u2 diagonals
        assert K[0, 0] == pytest.approx(c1)
        assert K[6, 6] == pytest.approx(c1)
        # θy1, θy2 diagonals
        assert K[4, 4] == pytest.approx(c3)
        assert K[10, 10] == pytest.approx(c3)
        # u1-u2 off-diagonal
        assert K[0, 6] == pytest.approx(-c1)
        # u1-θy1 off-diagonal (c2)
        c2 = 6.0 * EI_DS / L**2
        assert K[0, 4] == pytest.approx(c2)

    def test_bending_yz_plane_diagonal_constants(self) -> None:
        """
        Bending in y-z plane couples v (idx 1) and θ_x (idx 3).  Same magnitudes
        as x-z plane but with sign convention "positive v couples with negative
        θ_x at near end" (per fem_solver docstring).
        """
        L = 0.34
        K = _beam_stiffness_local(L)
        c1 = 12.0 * EI_DS / L**3
        c2 = 6.0 * EI_DS / L**2
        c3 = 4.0 * EI_DS / L
        assert K[1, 1] == pytest.approx(c1)
        assert K[7, 7] == pytest.approx(c1)
        assert K[3, 3] == pytest.approx(c3)
        assert K[9, 9] == pytest.approx(c3)
        # The codified sign convention: K[1,3] = -c2 (not +c2)
        assert K[1, 3] == pytest.approx(-c2)
        # And K[1,7] = -c1 (off-diagonal between two transverse DOFs)
        assert K[1, 7] == pytest.approx(-c1)

    def test_six_zero_eigenvalues_rigid_body_modes(self) -> None:
        """
        Free-free Euler-Bernoulli element has 6 rigid-body modes (3 trans,
        3 rot) → 6 zero eigenvalues, leaving rank 6.
        """
        K = _beam_stiffness_local(0.34)
        eigvals = np.linalg.eigvalsh(K)  # symmetric → real eigenvalues
        # Sort ascending; lowest 6 should be ≈ 0.
        eigvals_sorted = np.sort(eigvals)
        # Tolerance: K entries scale ~ EI/L^3 ≈ 5800; use a safe relative tol.
        scale = max(abs(eigvals_sorted).max(), 1.0)
        zero_threshold = 1e-9 * scale
        n_zero = int(np.sum(np.abs(eigvals_sorted) < zero_threshold))
        assert n_zero == 6, f"expected 6 rigid-body modes, got {n_zero}"

    def test_length_scaling_axial(self) -> None:
        """
        Axial stiffness scales as 1/L: K_axial(L1) / K_axial(L2) = L2 / L1.
        """
        K1 = _beam_stiffness_local(1.0)
        K2 = _beam_stiffness_local(2.0)
        assert K1[2, 2] / K2[2, 2] == pytest.approx(2.0)

    def test_length_scaling_bending(self) -> None:
        """
        Bending diagonal (12 EI / L^3) scales as 1/L^3.
        Halving L → 8× stiffness.
        """
        K1 = _beam_stiffness_local(1.0)
        K_half = _beam_stiffness_local(0.5)
        assert K_half[0, 0] / K1[0, 0] == pytest.approx(8.0)

    def test_unrelated_blocks_are_zero(self) -> None:
        """
        Entries that don't belong to any of the 4 coupled groups should be zero.
        e.g. axial DOF (index 2) does not couple with bending u (index 0).
        """
        K = _beam_stiffness_local(0.34)
        # Axial (z) ↔ bending (u, v, θx, θy) decoupling
        assert K[2, 0] == 0.0
        assert K[2, 1] == 0.0
        assert K[2, 3] == 0.0
        assert K[2, 4] == 0.0
        # Torsion (θz) ↔ bending decoupling
        assert K[5, 0] == 0.0
        assert K[5, 1] == 0.0
        # x-z bending (u, θy) ↔ y-z bending (v, θx) decoupling
        assert K[0, 1] == 0.0
        assert K[0, 3] == 0.0
        assert K[4, 1] == 0.0
        assert K[4, 3] == 0.0


# ─────────────────────────────────────────────────────────────────────────────
# _transform_to_global
# ─────────────────────────────────────────────────────────────────────────────


class TestTransformToGlobal:
    """Tests for the local→global element-matrix rotation."""

    def test_identity_rotation_returns_input(self) -> None:
        """R = I  →  K_global = K_local exactly."""
        K_local = _beam_stiffness_local(0.34)
        R = np.eye(3)
        K_global = _transform_to_global(K_local, R)
        assert np.allclose(K_global, K_local, atol=1e-15)

    def test_shape_preservation(self) -> None:
        K_local = _beam_stiffness_local(0.34)
        R = np.eye(3)
        K_global = _transform_to_global(K_local, R)
        assert K_global.shape == (12, 12)

    def test_orthogonal_R_preserves_symmetry(self) -> None:
        """If R is orthogonal and K_local is symmetric → K_global symmetric."""
        K_local = _beam_stiffness_local(0.34)
        # Random rotation: 90° around y-axis composed with 30° around x-axis.
        ca, sa = np.cos(np.deg2rad(30.0)), np.sin(np.deg2rad(30.0))
        Rx = np.array([[1, 0, 0], [0, ca, -sa], [0, sa, ca]])
        Ry = np.array([[0, 0, 1], [0, 1, 0], [-1, 0, 0]])  # 90° around y
        R = Rx @ Ry
        # Sanity: R is orthogonal.
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-12)
        K_global = _transform_to_global(K_local, R)
        assert np.allclose(K_global, K_global.T, atol=1e-9)

    def test_orthogonal_R_preserves_eigenvalues(self) -> None:
        """
        Similarity transform by an orthogonal matrix preserves eigenvalues.
        (T12 is block-diag of R.T which is orthogonal → so is T12.)
        """
        K_local = _beam_stiffness_local(0.34)
        # 45° around z-axis.
        c, s = np.cos(np.deg2rad(45.0)), np.sin(np.deg2rad(45.0))
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        K_global = _transform_to_global(K_local, R)
        eig_local = np.sort(np.linalg.eigvalsh(K_local))
        eig_global = np.sort(np.linalg.eigvalsh(K_global))
        assert np.allclose(eig_local, eig_global, atol=1e-6)

    def test_z_axis_rotation_swaps_u_and_v_blocks(self) -> None:
        """
        90° rotation about local z (the beam axis) swaps the in-plane
        directions: a +x global vector becomes +y in local.  In particular,
        bending stiffness in the global x direction at node i should equal
        the local-frame bending stiffness — independent of the in-plane axis
        chosen, by isotropy of EI in this Bernoulli element.
        """
        K_local = _beam_stiffness_local(0.34)
        c, s = np.cos(np.deg2rad(90.0)), np.sin(np.deg2rad(90.0))
        R = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        K_global = _transform_to_global(K_local, R)
        # Diagonal bending entries for global u_x (idx 0) and u_y (idx 1) at
        # node i should both equal the isotropic 12 EI / L^3 value.
        c1 = 12.0 * EI_DS / 0.34**3
        assert K_global[0, 0] == pytest.approx(c1, rel=1e-9)
        assert K_global[1, 1] == pytest.approx(c1, rel=1e-9)
        # Axial (now along global z still, since rotation was about z) unchanged.
        ea_over_L = EA_DS / 0.34
        assert K_global[2, 2] == pytest.approx(ea_over_L, rel=1e-9)

    def test_x_axis_rotation_swaps_axial_and_transverse(self) -> None:
        """
        90° rotation about global x-axis maps local z → global y (or -y).
        The axial-stiffness diagonal (originally at index 2 = local z) should
        appear at index 1 (global y) of the rotated matrix at node i.

        R columns express local axes in global frame.  If we want local z to
        point along global +y, then the third column of R is [0,1,0]:
            R = [[1,0,0],[0,0,?],[0,?,0]] with orthogonality
        Use R = [[1,0,0],[0,0,-1],[0,1,0]] (90° rotation of frame about x).
        """
        L = 0.34
        K_local = _beam_stiffness_local(L)
        R = np.array([[1.0, 0.0, 0.0], [0.0, 0.0, -1.0], [0.0, 1.0, 0.0]])
        # Verify R is orthogonal det=+1.
        assert np.allclose(R @ R.T, np.eye(3), atol=1e-12)
        assert np.linalg.det(R) == pytest.approx(1.0, abs=1e-12)
        K_global = _transform_to_global(K_local, R)
        ea_over_L = EA_DS / L
        # Axial stiffness now along global y (index 1) at node i.
        assert K_global[1, 1] == pytest.approx(ea_over_L, rel=1e-9)
        # And along global y at node j (index 7).
        assert K_global[7, 7] == pytest.approx(ea_over_L, rel=1e-9)
        # Anti-coupling: K_global[1, 7] = -EA/L.
        assert K_global[1, 7] == pytest.approx(-ea_over_L, rel=1e-9)

    def test_eigenvalues_remain_six_zero(self) -> None:
        """Six rigid-body zero-eigenvalues survive the rotation."""
        K_local = _beam_stiffness_local(0.34)
        c, s = np.cos(np.deg2rad(37.5)), np.sin(np.deg2rad(37.5))
        R = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])  # rotation about y
        K_global = _transform_to_global(K_local, R)
        eigvals = np.sort(np.linalg.eigvalsh(K_global))
        scale = max(abs(eigvals).max(), 1.0)
        n_zero = int(np.sum(np.abs(eigvals) < 1e-9 * scale))
        assert n_zero == 6


# ─────────────────────────────────────────────────────────────────────────────
# normalize_rmsf  (small pure helper — included for additional coverage)
# ─────────────────────────────────────────────────────────────────────────────


class TestNormalizeRmsf:
    """normalize_rmsf maps per-node RMSF values to a {key: value} dict in [0,1]."""

    def _make_mesh(self, n: int) -> FEMMesh:
        mesh = FEMMesh()
        for i in range(n):
            mesh.nodes.append(
                FEMNode(helix_id="h0", global_bp=i, position=np.zeros(3))
            )
        return mesh

    def test_max_value_normalised_to_one(self) -> None:
        mesh = self._make_mesh(3)
        rmsf = np.array([1.0, 2.0, 4.0])
        result = normalize_rmsf(rmsf, mesh)
        # 4.0 / 4.0 = 1.0  (Direction.value is upper-case in models.Direction)
        assert result["h0:2:FORWARD"] == pytest.approx(1.0)
        assert result["h0:2:REVERSE"] == pytest.approx(1.0)
        # 1.0 / 4.0 = 0.25
        assert result["h0:0:FORWARD"] == pytest.approx(0.25)

    def test_emits_both_directions_per_node(self) -> None:
        mesh = self._make_mesh(2)
        rmsf = np.array([1.0, 1.0])
        result = normalize_rmsf(rmsf, mesh)
        # Each node yields exactly two keys (FORWARD + REVERSE).
        assert len(result) == 4
        for bp in (0, 1):
            assert f"h0:{bp}:FORWARD" in result
            assert f"h0:{bp}:REVERSE" in result

    def test_zero_input_does_not_divide_by_zero(self) -> None:
        """All-zero RMSF: helper falls back to denominator 1.0 to avoid /0."""
        mesh = self._make_mesh(2)
        rmsf = np.zeros(2)
        result = normalize_rmsf(rmsf, mesh)
        # All values 0 / 1 = 0.0 — finite, no NaN.
        for v in result.values():
            assert v == 0.0
            assert np.isfinite(v)
