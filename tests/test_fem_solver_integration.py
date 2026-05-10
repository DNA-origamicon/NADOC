"""
Integration tests for backend.physics.fem_solver orchestrators.

Companion to ``tests/test_fem_solver_math.py`` (Pass 9-C, pure-math helpers).
These tests drive the full FEM pipeline end-to-end on a minimal Design fixture
and exercise the orchestrators that were Skip-listed in 9-C:

  - build_fem_mesh
  - assemble_global_stiffness
  - apply_boundary_conditions
  - solve_equilibrium
  - compute_rmsf
  - deformed_positions

DOF ordering (from fem_solver): per node [u_x, u_y, u_z, θ_x, θ_y, θ_z].
12-DOF element vector is [node_i_dofs (6), node_j_dofs (6)].
Beam axis = local z (axial DOFs at indices 2 and 8).

Apparent-bug flags (do not modify production code; flagged for a future pass):
  1. ``build_fem_mesh`` accesses ``design.crossover_bases`` (line 153) but
     the ``Design`` model has no such attribute (it was removed in commit
     a6df304, the cadnano overhaul). Every test below patches the missing
     attribute via ``_patch_crossover_bases`` so the mesh builder can run.
     Without the patch, every call AttributeError-s on any Design.
  2. The crossover-spring loop (lines 159–195) reads ``xo.strand_a_id``,
     ``xo.strand_b_id``, ``xo.domain_a_index``, ``xo.domain_b_index`` — none
     of which exist on the current ``Crossover`` model (which exposes
     ``half_a`` / ``half_b`` instead). Any Design with crossovers therefore
     AttributeError-s. These tests use crossover-free designs and rely on the
     "singular stiffness matrix" guard for the disconnected-helix case.

Both bugs are LATENT — they only surface when ``build_fem_mesh`` is invoked
against a real Design. Production callers under coverage today appear to
load JSON via ``Design.model_validate`` which (without ``extra="allow"``)
strips the missing fields, so the failure is silent / unreached. The
orchestrators have been at 22%-37% test coverage since merge.
"""

from __future__ import annotations

import numpy as np
import pytest

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import Design, Helix, LatticeType, Vec3
from backend.physics.fem_solver import (
    KBT,
    K_PENALTY,
    apply_boundary_conditions,
    assemble_global_stiffness,
    build_fem_mesh,
    compute_rmsf,
    deformed_positions,
    solve_equilibrium,
)
from tests.conftest import make_minimal_design


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────


def _patch_crossover_bases(design: Design) -> Design:
    """Add the missing ``crossover_bases`` attribute that ``build_fem_mesh``
    expects (see Apparent-bug #1 in module docstring).  Pydantic v2 stores
    instance values in ``__dict__``; assigning there makes attribute access
    succeed without modifying the schema.
    """
    design.__dict__.setdefault("crossover_bases", [])
    return design


def _build_full_pipeline(design: Design):
    """Run mesh → assemble → BC → solve.  Returns the intermediate artifacts."""
    mesh = build_fem_mesh(_patch_crossover_bases(design))
    K, f = assemble_global_stiffness(mesh)
    K_free, f_free, free_dofs = apply_boundary_conditions(K, f, mesh)
    u = solve_equilibrium(K_free, f_free, K.shape[0], free_dofs)
    return mesh, K, f, K_free, f_free, free_dofs, u


# ─────────────────────────────────────────────────────────────────────────────
# build_fem_mesh
# ─────────────────────────────────────────────────────────────────────────────


class TestBuildFemMesh:
    """Mesh construction from a Design (no crossover springs in scope)."""

    def test_single_helix_node_and_element_counts(self) -> None:
        """One axis node per active bp; one beam element per consecutive pair."""
        d = make_minimal_design(n_helices=1, helix_length_bp=42)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        assert len(mesh.nodes) == 42
        assert len(mesh.elements) == 41           # n_bp − 1 elements per helix
        assert len(mesh.springs) == 0             # no crossovers in fixture

    def test_two_helix_independent_chains(self) -> None:
        """Two disjoint helices → 2 × (nodes, elements − 1)."""
        d = make_minimal_design(n_helices=2, helix_length_bp=20)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        assert len(mesh.nodes) == 40              # 2 × 20
        assert len(mesh.elements) == 38           # 2 × (20 − 1)
        # All elements share the same R because both helices run along +z.
        assert all(np.allclose(el.R, mesh.elements[0].R) for el in mesh.elements)

    def test_node_positions_match_axis_geometry(self) -> None:
        """Node positions are start + i × BDNA_RISE_PER_BP × axis_hat."""
        d = make_minimal_design(n_helices=1, helix_length_bp=10)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        for i, node in enumerate(mesh.nodes):
            expected_z = i * BDNA_RISE_PER_BP
            assert node.position[2] == pytest.approx(expected_z, abs=1e-9)
            # Helix axis at (0,0,*) → x and y components zero.
            assert node.position[0] == pytest.approx(0.0, abs=1e-9)
            assert node.position[1] == pytest.approx(0.0, abs=1e-9)

    def test_element_length_is_bdna_rise(self) -> None:
        """All beam elements have length == BDNA_RISE_PER_BP."""
        d = make_minimal_design(n_helices=1, helix_length_bp=15)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        for el in mesh.elements:
            assert el.length == pytest.approx(BDNA_RISE_PER_BP, abs=1e-12)

    def test_element_node_indices_consecutive(self) -> None:
        """Element i connects nodes (i, i+1) for a single contiguous helix."""
        d = make_minimal_design(n_helices=1, helix_length_bp=8)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        for i, el in enumerate(mesh.elements):
            assert el.node_i == i
            assert el.node_j == i + 1

    def test_zero_length_helix_skipped(self) -> None:
        """A degenerate (axis_start == axis_end) helix contributes 0 nodes."""
        h = Helix(
            id="degenerate",
            axis_start=Vec3(x=0.0, y=0.0, z=0.0),
            axis_end=Vec3(x=0.0, y=0.0, z=0.0),
            length_bp=0,
            bp_start=0,
        )
        d = Design(helices=[h], strands=[], lattice_type=LatticeType.HONEYCOMB)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        assert len(mesh.nodes) == 0
        assert len(mesh.elements) == 0

    def test_empty_design(self) -> None:
        """No helices → empty mesh."""
        d = Design(helices=[], strands=[], lattice_type=LatticeType.HONEYCOMB)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        assert len(mesh.nodes) == 0
        assert len(mesh.elements) == 0
        assert len(mesh.springs) == 0

    def test_global_bp_offset_respects_bp_start(self) -> None:
        """global_bp = local_i + helix.bp_start."""
        helix_len = 7
        h = Helix(
            id="h0",
            axis_start=Vec3(x=0.0, y=0.0, z=0.0),
            axis_end=Vec3(x=0.0, y=0.0, z=helix_len * BDNA_RISE_PER_BP),
            length_bp=helix_len,
            bp_start=100,                          # nonzero offset
        )
        d = Design(helices=[h], strands=[], lattice_type=LatticeType.HONEYCOMB)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        for i, node in enumerate(mesh.nodes):
            assert node.global_bp == 100 + i


# ─────────────────────────────────────────────────────────────────────────────
# assemble_global_stiffness
# ─────────────────────────────────────────────────────────────────────────────


class TestAssembleGlobalStiffness:
    """Global K assembly from FEMMesh."""

    def test_shape_and_zero_force(self) -> None:
        """K is (6n × 6n) and f is the all-zero (6n,) vector."""
        d = make_minimal_design(n_helices=1, helix_length_bp=10)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        K, f = assemble_global_stiffness(mesh)
        n = len(mesh.nodes)
        assert K.shape == (6 * n, 6 * n)
        assert f.shape == (6 * n,)
        assert np.max(np.abs(f)) == 0.0

    def test_K_is_symmetric(self) -> None:
        """Stiffness matrix is symmetric (sparse → dense compare on small mesh)."""
        d = make_minimal_design(n_helices=1, helix_length_bp=8)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        K, _ = assemble_global_stiffness(mesh)
        K_dense = K.toarray()
        assert np.allclose(K_dense, K_dense.T, atol=1e-9)

    def test_K_is_psd_with_six_zero_eigenvalues(self) -> None:
        """
        Connected single-helix system has exactly 6 rigid-body zero modes
        (3 trans + 3 rot) and is otherwise positive-semi-definite.
        """
        d = make_minimal_design(n_helices=1, helix_length_bp=8)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        K, _ = assemble_global_stiffness(mesh)
        eigs = np.sort(np.linalg.eigvalsh(K.toarray()))
        scale = max(abs(eigs).max(), 1.0)
        n_zero = int(np.sum(np.abs(eigs) < 1e-7 * scale))
        assert n_zero == 6
        # All non-rigid eigenvalues strictly positive.
        assert (eigs[6:] > 0.0).all()

    def test_two_disconnected_helices_have_twelve_zero_modes(self) -> None:
        """
        Two disconnected components → 12 rigid-body zero modes (6 per component).
        """
        d = make_minimal_design(n_helices=2, helix_length_bp=6)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        K, _ = assemble_global_stiffness(mesh)
        eigs = np.sort(np.linalg.eigvalsh(K.toarray()))
        scale = max(abs(eigs).max(), 1.0)
        n_zero = int(np.sum(np.abs(eigs) < 1e-7 * scale))
        assert n_zero == 12

    def test_translational_spring_contribution(self) -> None:
        """
        Manually inject one FEMSpring (translational only) and verify diagonals
        increment by k_trans on both nodes' first 3 DOFs and the corresponding
        off-diagonal blocks decrement.
        """
        from backend.physics.fem_solver import FEMSpring
        d = make_minimal_design(n_helices=2, helix_length_bp=6)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        # Without a spring, nodes 0 and len(h0_nodes) belong to disjoint helices.
        ni = 0
        nj = len(mesh.nodes) - 1
        kt = K_PENALTY
        K_no_spring, _ = assemble_global_stiffness(mesh)
        mesh.springs.append(FEMSpring(node_i=ni, node_j=nj, k_trans=kt, k_rot=0.0))
        K_with_spring, _ = assemble_global_stiffness(mesh)
        # Diagonal increments at node ni's translational DOFs (dim 0..2).
        for dim in range(3):
            di = 6 * ni + dim
            dj = 6 * nj + dim
            assert K_with_spring[di, di] - K_no_spring[di, di] == pytest.approx(kt)
            assert K_with_spring[dj, dj] - K_no_spring[dj, dj] == pytest.approx(kt)
            assert K_with_spring[di, dj] - K_no_spring[di, dj] == pytest.approx(-kt)
            assert K_with_spring[dj, di] - K_no_spring[dj, di] == pytest.approx(-kt)
        # No rotational change (k_rot=0).
        for dim in range(3):
            di = 6 * ni + 3 + dim
            assert K_with_spring[di, di] == pytest.approx(K_no_spring[di, di])

    def test_rotational_spring_contribution(self) -> None:
        """k_rot != 0 also adds to rotational DOF blocks (lines 308-313)."""
        from backend.physics.fem_solver import FEMSpring
        d = make_minimal_design(n_helices=2, helix_length_bp=4)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        ni, nj = 0, len(mesh.nodes) - 1
        kr = 5.0
        K_no_spring, _ = assemble_global_stiffness(mesh)
        mesh.springs.append(FEMSpring(node_i=ni, node_j=nj, k_trans=0.0, k_rot=kr))
        K_with_spring, _ = assemble_global_stiffness(mesh)
        # Rotational DOFs are 3,4,5.
        for dim in range(3):
            di = 6 * ni + 3 + dim
            dj = 6 * nj + 3 + dim
            assert K_with_spring[di, di] - K_no_spring[di, di] == pytest.approx(kr)
            assert K_with_spring[di, dj] - K_no_spring[di, dj] == pytest.approx(-kr)


# ─────────────────────────────────────────────────────────────────────────────
# apply_boundary_conditions
# ─────────────────────────────────────────────────────────────────────────────


class TestApplyBoundaryConditions:
    """Centroid-pin BC: removes 6 DOF, returns sliced K_free / f_free / free_dofs."""

    def test_six_dofs_removed(self) -> None:
        """K shrinks from (6n,6n) to (6n-6, 6n-6); free_dofs has length 6n-6."""
        d = make_minimal_design(n_helices=1, helix_length_bp=10)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        K, f = assemble_global_stiffness(mesh)
        K_free, f_free, free_dofs = apply_boundary_conditions(K, f, mesh)
        n_dof = K.shape[0]
        assert K_free.shape == (n_dof - 6, n_dof - 6)
        assert f_free.shape == (n_dof - 6,)
        assert len(free_dofs) == n_dof - 6

    def test_pinned_node_is_centroid(self) -> None:
        """
        The pinned 6 DOFs span exactly one node, and that node sits closest
        to the geometric centroid of the mesh.
        """
        d = make_minimal_design(n_helices=1, helix_length_bp=11)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        K, f = assemble_global_stiffness(mesh)
        _, _, free_dofs = apply_boundary_conditions(K, f, mesh)
        all_dofs = set(range(K.shape[0]))
        pinned = sorted(all_dofs - set(free_dofs.tolist()))
        assert len(pinned) == 6
        # All 6 pinned DOFs belong to the same node.
        pinned_nodes = {d_ // 6 for d_ in pinned}
        assert len(pinned_nodes) == 1
        pinned_node_idx = pinned_nodes.pop()
        # That node is the one closest to the centroid.
        positions = np.array([n.position for n in mesh.nodes])
        centroid = positions.mean(axis=0)
        dists = np.linalg.norm(positions - centroid, axis=1)
        assert pinned_node_idx == int(np.argmin(dists))

    def test_free_dofs_are_sorted_and_unique(self) -> None:
        """free_dofs must be sorted (apply_boundary_conditions builds via list comp)."""
        d = make_minimal_design(n_helices=1, helix_length_bp=8)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        K, f = assemble_global_stiffness(mesh)
        _, _, free_dofs = apply_boundary_conditions(K, f, mesh)
        assert (np.diff(free_dofs) > 0).all()      # strictly increasing
        assert len(set(free_dofs.tolist())) == len(free_dofs)


# ─────────────────────────────────────────────────────────────────────────────
# solve_equilibrium
# ─────────────────────────────────────────────────────────────────────────────


class TestSolveEquilibrium:
    """Equilibrium solve: K_free · u_free = f_free."""

    def test_zero_force_yields_zero_displacement(self) -> None:
        """No external load → u ≈ 0 (pre-stress is by design zero)."""
        d = make_minimal_design(n_helices=1, helix_length_bp=12)
        mesh, K, f, K_free, f_free, free_dofs, u = _build_full_pipeline(d)
        assert u.shape == (K.shape[0],)
        assert np.max(np.abs(u)) < 1e-6

    def test_pinned_dofs_are_exactly_zero(self) -> None:
        """The pinned 6 DOFs in u remain 0 (filled at the end by free_dofs index)."""
        d = make_minimal_design(n_helices=1, helix_length_bp=10)
        _, K, _, K_free, f_free, free_dofs, u = _build_full_pipeline(d)
        all_dofs = set(range(K.shape[0]))
        pinned = sorted(all_dofs - set(free_dofs.tolist()))
        for dof in pinned:
            assert u[dof] == 0.0

    def test_disconnected_helices_raise_singular_value_error(self) -> None:
        """
        Two helices with no crossover spring → K is singular → solve_equilibrium
        raises ValueError mentioning disconnected helices.
        """
        d = make_minimal_design(n_helices=2, helix_length_bp=5)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        K, f = assemble_global_stiffness(mesh)
        K_free, f_free, free_dofs = apply_boundary_conditions(K, f, mesh)
        with pytest.raises(ValueError, match=r"singular|disconnected"):
            solve_equilibrium(K_free, f_free, K.shape[0], free_dofs)


# ─────────────────────────────────────────────────────────────────────────────
# compute_rmsf
# ─────────────────────────────────────────────────────────────────────────────


class TestComputeRmsf:
    """RMSF estimation from the n_modes lowest eigenpairs."""

    def test_shape_and_finite_nonneg(self) -> None:
        """Returns (n_nodes,), all entries finite and ≥ 0."""
        d = make_minimal_design(n_helices=1, helix_length_bp=12)
        mesh, K, _, K_free, _, free_dofs, _ = _build_full_pipeline(d)
        rmsf = compute_rmsf(K_free, free_dofs, len(mesh.nodes))
        assert rmsf.shape == (len(mesh.nodes),)
        assert np.all(np.isfinite(rmsf))
        assert (rmsf >= 0.0).all()

    def test_n_modes_clamped_below_matrix_rank(self) -> None:
        """
        Requesting more modes than (n_free − 2) should clamp internally and
        still return a finite result of correct shape (no IndexError).
        """
        d = make_minimal_design(n_helices=1, helix_length_bp=4)
        mesh, K, _, K_free, _, free_dofs, _ = _build_full_pipeline(d)
        rmsf = compute_rmsf(K_free, free_dofs, len(mesh.nodes), n_modes=10_000)
        assert rmsf.shape == (len(mesh.nodes),)
        assert np.all(np.isfinite(rmsf))

    def test_returns_zeros_when_n_free_too_small(self) -> None:
        """
        If the free-DOF count is too small for any mode (k = min(n_modes, n_free-2) < 1),
        the helper returns a zero array of length n_nodes (early-out path).
        """
        # n_free = 1 → k = min(n_modes, -1) = -1, hits early return.
        K_free = np.array([[1.0]])
        from scipy.sparse import csr_matrix
        K_free_sp = csr_matrix(K_free)
        free_dofs = np.array([0], dtype=int)
        rmsf = compute_rmsf(K_free_sp, free_dofs, n_nodes=1)
        assert rmsf.shape == (1,)
        assert (rmsf == 0.0).all()

    def test_rmsf_uses_translational_dofs_only(self) -> None:
        """
        compute_rmsf sums φ²/λ over translational DOFs (dim 0..2) only.
        A solely rotational excitation would not contribute — but verifying
        this directly requires synthesising eigenvectors. Instead, sanity-check
        that RMSF magnitudes are physically plausible: sqrt(KBT/k_min) ≤ a few nm.
        """
        d = make_minimal_design(n_helices=1, helix_length_bp=10)
        mesh, _, _, K_free, _, free_dofs, _ = _build_full_pipeline(d)
        rmsf = compute_rmsf(K_free, free_dofs, len(mesh.nodes))
        # 30 nm cap is a generous upper bound for a 10-bp / 3.4 nm beam at 310 K.
        # RMSF ~ sqrt(k_BT/k_bend) and k_bend ~ EI/L^3.
        assert rmsf.max() < 30.0
        assert KBT > 0.0                            # sanity check: imported constant


# ─────────────────────────────────────────────────────────────────────────────
# deformed_positions
# ─────────────────────────────────────────────────────────────────────────────


class TestDeformedPositions:
    """Apply axis displacements to backbone bead positions."""

    def test_one_entry_per_node_per_direction(self) -> None:
        """Each FEM node yields 2 entries (FORWARD + REVERSE)."""
        d = make_minimal_design(n_helices=1, helix_length_bp=10)
        mesh, _, _, _, _, _, u = _build_full_pipeline(d)
        results = deformed_positions(d, mesh, u)
        assert len(results) == 2 * len(mesh.nodes)
        # Both directions present per (helix, bp).
        keys = {(r["helix_id"], r["bp_index"], r["direction"]) for r in results}
        for node in mesh.nodes:
            assert (node.helix_id, node.global_bp, "FORWARD") in keys
            assert (node.helix_id, node.global_bp, "REVERSE") in keys

    def test_zero_displacement_recovers_undeformed_backbone(self) -> None:
        """
        u = 0 → deformed_positions returns the original backbone bead positions
        (which are the geometry layer's nucleotide_positions).
        """
        from backend.core.geometry import nucleotide_positions

        d = make_minimal_design(n_helices=1, helix_length_bp=8)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        K, _ = assemble_global_stiffness(mesh)
        u_zero = np.zeros(K.shape[0])

        # Build geometry-layer expected positions.
        expected: dict = {}
        for helix in d.helices:
            for nuc in nucleotide_positions(helix):
                expected[(nuc.helix_id, nuc.bp_index, nuc.direction.value)] = nuc.position

        results = deformed_positions(d, mesh, u_zero)
        for r in results:
            key = (r["helix_id"], r["bp_index"], r["direction"])
            base = expected[key]
            got = np.array(r["backbone_position"])
            assert np.allclose(got, base, atol=1e-9)

    def test_uniform_translation_propagates_to_backbone(self) -> None:
        """
        Inject a uniform u_x = +1 nm at every node's translational DOFs.
        Every backbone bead shifts by +1 nm in x, leaving y and z untouched.
        """
        from backend.core.geometry import nucleotide_positions

        d = make_minimal_design(n_helices=1, helix_length_bp=6)
        mesh = build_fem_mesh(_patch_crossover_bases(d))
        n_dof = 6 * len(mesh.nodes)
        u = np.zeros(n_dof)
        for i in range(len(mesh.nodes)):
            u[6 * i + 0] = 1.0                      # uniform +x displacement

        # Cache original geometry-layer backbone positions.
        orig: dict = {}
        for helix in d.helices:
            for nuc in nucleotide_positions(helix):
                orig[(nuc.helix_id, nuc.bp_index, nuc.direction.value)] = nuc.position

        results = deformed_positions(d, mesh, u)
        for r in results:
            key = (r["helix_id"], r["bp_index"], r["direction"])
            base = orig[key]
            got = np.array(r["backbone_position"])
            assert got[0] == pytest.approx(base[0] + 1.0, abs=1e-9)
            assert got[1] == pytest.approx(base[1], abs=1e-9)
            assert got[2] == pytest.approx(base[2], abs=1e-9)

    def test_returns_dict_with_expected_keys(self) -> None:
        """Each result entry has the documented dict shape."""
        d = make_minimal_design(n_helices=1, helix_length_bp=4)
        mesh, _, _, _, _, _, u = _build_full_pipeline(d)
        results = deformed_positions(d, mesh, u)
        assert results, "expected non-empty result for non-empty mesh"
        sample = results[0]
        for k in ("helix_id", "bp_index", "direction", "backbone_position"):
            assert k in sample
        # backbone_position is a list (per the .tolist() call in the helper).
        assert isinstance(sample["backbone_position"], list)
        assert len(sample["backbone_position"]) == 3


# ─────────────────────────────────────────────────────────────────────────────
# End-to-end smoke test
# ─────────────────────────────────────────────────────────────────────────────


class TestEndToEndPipeline:
    """Single test exercising every orchestrator in one call sequence."""

    def test_full_pipeline_single_helix(self) -> None:
        d = make_minimal_design(n_helices=1, helix_length_bp=20)
        mesh, K, f, K_free, f_free, free_dofs, u = _build_full_pipeline(d)
        # Mesh
        assert len(mesh.nodes) == 20
        # K assembled, no force.
        assert K.shape == (120, 120)
        assert np.max(np.abs(f)) == 0.0
        # BC removed exactly 6 DOF.
        assert K_free.shape == (114, 114)
        # Solve produced 0-displacement vector matching K shape.
        assert u.shape == (120,)
        assert np.max(np.abs(u)) < 1e-6
        # RMSF produced.
        rmsf = compute_rmsf(K_free, free_dofs, len(mesh.nodes))
        assert rmsf.shape == (20,)
        # Deformed positions populated for both strands at each bp.
        results = deformed_positions(d, mesh, u)
        assert len(results) == 40
