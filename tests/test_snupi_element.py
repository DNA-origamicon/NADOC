"""Phase-2 step-3 pin: the anisotropic Timoshenko SNUPI beam element.

Proves the element CONVENTION mechanically (not by reasoning): diagonal rigidity
recovery, the twist-stretch coupling wiring, symmetry/PSD, and that a real bundle
solves with material="snupi" while the cando baseline is untouched. See
memory/project_snupi_mimic.md (Phase 2).
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.core.models import LatticeType
from backend.physics import snupi_material as sm
from backend.physics.fem_solver import (
    _snupi_element_stiffness,
    _beam_stiffness_local,
    assemble_global_stiffness,
    build_fem_mesh,
    compute_rmsf_nma,
    predict_shape,
)

L = 0.34  # nm, one bp rise


@pytest.fixture(scope="module")
def D_reg():
    return sm.family_mean_D("regular_bp")


def test_element_symmetric_and_size(D_reg):
    K = _snupi_element_stiffness(L, D_reg)
    assert K.shape == (12, 12)
    assert np.allclose(K, K.T)


def test_diagonal_rigidity_recovery(D_reg):
    """Axial pull only stretches (EA/L); pure torsion only twists (GJ/L). DOF order
    [u,v,w,θx,θy,θz] per node, local z = axial → w=index2/8, θz=index5/11."""
    K = _snupi_element_stiffness(L, D_reg)
    EA = D_reg[0, 0]
    GJ = D_reg[3, 3]
    assert K[8, 8] == pytest.approx(EA / L, rel=1e-9)     # axial (w_j)
    assert K[2, 2] == pytest.approx(EA / L, rel=1e-9)     # axial (w_i)
    assert K[2, 8] == pytest.approx(-EA / L, rel=1e-9)    # axial i-j coupling
    assert K[11, 11] == pytest.approx(GJ / L, rel=1e-9)   # torsion (θz_j)


def test_twist_stretch_coupling_wired(D_reg):
    """The signature SNUPI delta: axial stretch couples to axial twist. g(dx,θx)=D[0,3]
    lands on the (w, θz) block as D[0,3]/L — frame-independent (both are helix-axis DOFs)."""
    K = _snupi_element_stiffness(L, D_reg)
    g = D_reg[0, 3]                          # ~ -277.4 pN*nm for regular_bp mean
    assert g < 0                             # DNA overwinds under tension (negative coupling)
    assert K[8, 11] == pytest.approx(g / L, rel=1e-9)   # w_j ↔ θz_j
    assert K[2, 5] == pytest.approx(g / L, rel=1e-9)     # w_i ↔ θz_i


def test_twist_stretch_physical_response(D_reg):
    """Fix node i, pull node j axially → a NON-zero induced twist (θz_j). Confirms the
    coupling produces the physical response, with the sign set by g<0."""
    K = _snupi_element_stiffness(L, D_reg)
    Kjj = K[6:, 6:]                          # node-j block with node-i clamped
    f = np.zeros(6); f[2] = 1.0              # unit axial force on w_j
    u = np.linalg.solve(Kjj, f)
    assert abs(u[5]) > 1e-6                  # induced twist θz_j is non-zero
    # cando element under the same load induces ZERO twist (no coupling) — contrast
    Kc = _beam_stiffness_local(L)[6:, 6:]
    uc = np.linalg.solve(Kc, f)
    assert abs(uc[5]) < 1e-12


def test_element_psd_up_to_rigid_modes(D_reg):
    # a free 2-node beam element has 6 rigid-body zero modes; the rest must be > 0.
    w = np.linalg.eigvalsh(_snupi_element_stiffness(L, D_reg))
    assert np.sum(w < 1e-6) <= 6
    assert np.all(w > -1e-6)                 # no negative eigenvalues (element is PSD)


@pytest.fixture(scope="module")
def routed_6hb():
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def test_snupi_material_assembles_and_solves(routed_6hb):
    mesh = build_fem_mesh(routed_6hb)
    Ks, _ = assemble_global_stiffness(mesh, material="snupi")
    Kc, _ = assemble_global_stiffness(mesh, material="cando")
    assert Ks.shape == Kc.shape
    # the two materials must actually differ (SNUPI != isotropic cando)
    assert not np.allclose(Ks.toarray(), Kc.toarray())
    # snupi RMSF solves and is finite + positive
    rmsf = compute_rmsf_nma(Ks.tocsr(), len(mesh.nodes))
    assert np.all(np.isfinite(rmsf))
    assert np.any(rmsf > 0)


def test_p2b_crossovers_are_compliant_not_rigid(routed_6hb):
    """P2b: under material='snupi' the DX crossovers are finite-stiffness CO-step beams,
    NOT rigid penalty links. So the snupi K must carry NO 1e6-scale (K_PENALTY) entries,
    while the cando K does. Also the bundle must stay connected (only 6 rigid modes)."""
    from backend.physics.fem_solver import K_PENALTY
    mesh = build_fem_mesh(routed_6hb)
    assert len(mesh.rigid_links) > 0
    Ks, _ = assemble_global_stiffness(mesh, material="snupi")
    Kc, _ = assemble_global_stiffness(mesh, material="cando")
    assert np.abs(Ks).max() < 0.1 * K_PENALTY       # compliant: no penalty-scale coupling
    assert np.abs(Kc).max() >= K_PENALTY            # cando: rigid penalty present
    # connectivity preserved: exactly 6 near-zero (rigid-body) eigenvalues
    from scipy.sparse.linalg import eigsh
    w = eigsh(Ks.tocsr(), k=8, sigma=1e-8, which="LM", return_eigenvectors=False)
    assert np.sum(np.sort(w) < 1e-4) <= 6


def test_unknown_material_rejected(routed_6hb):
    mesh = build_fem_mesh(routed_6hb)
    with pytest.raises(ValueError, match="unknown FEM material"):
        assemble_global_stiffness(mesh, material="bogus")


def test_predict_shape_snupi_runs(routed_6hb):
    out = predict_shape(routed_6hb, nonlinear=False, with_rmsf=True, material="snupi")
    assert out["positions"]
    assert out["rmsf"]
    assert all(np.isfinite(r["rmsf_nm"]) for r in out["rmsf"])
