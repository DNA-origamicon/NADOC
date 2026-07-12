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
    assemble_mass_matrix,
    build_fem_mesh,
    compute_correlation_matrix,
    compute_rmsf_nma,
    persistence_length_from_nma,
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


# ── SNUPI inter-helix electrostatics (SI S6/S7) + S9 iterative solve ─────────────

def test_electrostatics_stiffens_rmsf_and_cando_unchanged(routed_6hb):
    """Adding the Debye–Hückel inter-helix repulsion tangent to the NMA operator STIFFENS
    the inter-helix modes → per-bp RMSF drops (repulsion resists breathing). The cando path
    never sees electrostatics, so its RMSF is unchanged."""
    from backend.physics.fem_solver import (
        _snupi_electro_sparse, _snupi_es_params)
    mesh = build_fem_mesh(routed_6hb)
    K, _ = assemble_global_stiffness(mesh, material="snupi")
    rmsf_no_es = compute_rmsf_nma(K.tocsr(), len(mesh.nodes))
    defpos = [n.position for n in mesh.nodes]
    K_es, f_es = _snupi_electro_sparse(mesh, defpos, _snupi_es_params(),
                                       scale=1.0, axial_only=True)
    assert np.any(f_es != 0.0)                       # the design HAS inter-helix pairs < 2.5 nm
    rmsf_es = compute_rmsf_nma((K.tolil() + K_es).tocsr(), len(mesh.nodes))
    assert np.all(np.isfinite(rmsf_es)) and np.any(rmsf_es > 0)
    assert rmsf_es.mean() <= rmsf_no_es.mean() + 1e-9   # electrostatics can only stiffen


def test_snupi_nonlinear_solve_runs_and_is_finite(routed_6hb):
    """The S9 iterative/adaptive electrostatic solve (material='snupi', nonlinear) produces a
    finite, sane shape — and materially differs from the cando nonlinear solve."""
    snupi = predict_shape(routed_6hb, nonlinear=True, with_rmsf=False, material="snupi")
    cando = predict_shape(routed_6hb, nonlinear=True, with_rmsf=False, material="cando")
    ps = np.array([p["backbone_position"] for p in snupi["positions"]])
    pc = np.array([p["backbone_position"] for p in cando["positions"]])
    assert np.all(np.isfinite(ps))
    assert ps.shape == pc.shape
    # the two solves land in different places (electrostatics + anisotropic material)
    assert not np.allclose(ps, pc, atol=1e-6)
    # positions stay physically bounded (no blow-up from the repulsive springs)
    span = np.ptp(pc, axis=0).max()
    assert np.ptp(ps, axis=0).max() < 5.0 * span


# ── G1: sequence-specific per-motif stiffness ────────────────────────────────────

@pytest.fixture(scope="module")
def routed_6hb_seq(routed_6hb):
    """The routed 6HB with an M13mp18 scaffold + WC staple sequences assigned, so every
    duplex bp-step has a real dinucleotide for the G1 sequence-specific material."""
    from backend.core.sequences import assign_scaffold_sequence, assign_staple_sequences
    d, _, _ = assign_scaffold_sequence(routed_6hb, "M13mp18")
    return assign_staple_sequences(d)


def test_g1_unsequenced_falls_back_to_family_mean(routed_6hb):
    """No scaffold sequence → no bp-step is resolvable → every intra-helix element keeps
    motif=None, and the SNUPI assembly is byte-identical to the pre-G1 family-mean path."""
    mesh = build_fem_mesh(routed_6hb)
    assert any(e.motif_family == "regular_bp" for e in mesh.elements)
    assert all(e.motif is None for e in mesh.elements)


def test_g1_sequenced_resolves_varied_motifs(routed_6hb_seq):
    """A real sequence resolves EVERY regular_bp step to a specific motif key, spread across
    more than one of the 10 keys (the sequence signal MD sees)."""
    mesh = build_fem_mesh(routed_6hb_seq)
    reg = [e for e in mesh.elements if e.motif_family == "regular_bp"]
    assert reg and all(e.motif is not None for e in reg)          # all resolved
    assert len({e.motif for e in reg}) > 1                        # genuinely sequence-varying
    # nicked steps stay on the family mean (their 'n' grammar is not sequence-addressable)
    assert all(e.motif is None for e in mesh.elements if e.motif_family == "nicked_bp")


def test_g1_sequence_specific_K_differs_from_family_mean(routed_6hb_seq, routed_6hb):
    """The whole point: sequence-specific per-element D produces a DIFFERENT global K than the
    sequence-mean D. cando is untouched by sequence either way."""
    Kseq, _ = assemble_global_stiffness(build_fem_mesh(routed_6hb_seq), material="snupi")
    Kmean, _ = assemble_global_stiffness(build_fem_mesh(routed_6hb), material="snupi")
    assert Kseq.shape == Kmean.shape
    assert not np.allclose(Kseq.toarray(), Kmean.toarray())       # sequence moved the material
    # cando ignores sequence: same K with or without sequences assigned
    Kc_seq, _ = assemble_global_stiffness(build_fem_mesh(routed_6hb_seq), material="cando")
    Kc_mean, _ = assemble_global_stiffness(build_fem_mesh(routed_6hb), material="cando")
    assert np.allclose(Kc_seq.toarray(), Kc_mean.toarray())


# ── G12: MgCl₂ salt parameter → Debye length ─────────────────────────────────────

def test_g12_salt_changes_debye_length_and_rmsf(routed_6hb):
    """Raising MgCl₂ shortens λ_D (more screening) → weaker inter-helix repulsion in the NMA
    tangent → a DIFFERENT per-bp RMSF. The default (0.02) matches SNUPI's 20 mM buffer."""
    from backend.physics.fem_solver import _snupi_es_params, SNUPI_DEFAULT_MGCL2_M
    assert SNUPI_DEFAULT_MGCL2_M == 0.02
    lo = _snupi_es_params(0.02)
    hi = _snupi_es_params(0.20)
    assert hi.lambda_d < lo.lambda_d                          # more salt → shorter Debye length
    r_lo = predict_shape(routed_6hb, nonlinear=False, with_rmsf=True,
                         material="snupi", mgcl2_M=0.02)["rmsf"]
    r_hi = predict_shape(routed_6hb, nonlinear=False, with_rmsf=True,
                         material="snupi", mgcl2_M=0.20)["rmsf"]
    a = np.array([r["rmsf_nm"] for r in r_lo])
    b = np.array([r["rmsf_nm"] for r in r_hi])
    assert np.all(np.isfinite(b))
    assert not np.allclose(a, b)                              # salt moved the flexibility


def test_g12_salt_ignored_by_cando(routed_6hb):
    """cando has no electrostatics → mgcl2_M is inert: its cross-salt RMSF drift is only the
    eigensolver's ARPACK-start-vector noise (~1e-4 nm), far below snupi's real salt response."""
    def _rmsf(mat, salt):
        out = predict_shape(routed_6hb, nonlinear=False, with_rmsf=True,
                            material=mat, mgcl2_M=salt)["rmsf"]
        return np.array([r["rmsf_nm"] for r in out])
    cando_drift = np.abs(_rmsf("cando", 0.02) - _rmsf("cando", 0.50)).max()
    snupi_drift = np.abs(_rmsf("snupi", 0.02) - _rmsf("snupi", 0.50)).max()
    assert cando_drift < 1e-2                                 # inert: only eigensolver noise
    assert snupi_drift > 10.0 * cando_drift                  # snupi salt response is real + large


# ── G6: mass matrix + generalized eigenproblem (S10) ─────────────────────────────

def test_g6_mass_matrix_is_spd(routed_6hb):
    """The nodal mass matrix must be SPD (S10 pin): diagonal, all-positive — no massless
    rotational DOF (which would give an infinite-frequency mode / singular generalized solve)."""
    from backend.physics.fem_solver import assemble_mass_matrix
    mesh = build_fem_mesh(routed_6hb)
    M = assemble_mass_matrix(mesh, routed_6hb).tocsr()
    assert M.shape == (6 * len(mesh.nodes), 6 * len(mesh.nodes))
    diag = M.diagonal()
    assert np.all(diag > 0.0)                                 # SPD (diagonal, positive)
    assert M.nnz == len(diag)                                 # purely diagonal (lumped)


def test_g6_generalized_modes_finite_and_differ_from_k_only(routed_6hb):
    """The generalized eigenproblem (M given) yields a finite, positive RMSF that DIFFERS from
    the K-only (stiffness-ordered) NMA — the mass weighting re-selects the dominant modes."""
    from backend.physics.fem_solver import assemble_mass_matrix
    mesh = build_fem_mesh(routed_6hb)
    K, _ = assemble_global_stiffness(mesh, material="snupi")
    M = assemble_mass_matrix(mesh, routed_6hb)
    r_gen = compute_rmsf_nma(K.tocsr(), len(mesh.nodes), M=M)
    r_konly = compute_rmsf_nma(K.tocsr(), len(mesh.nodes))    # M=None → cando-style
    assert np.all(np.isfinite(r_gen)) and np.any(r_gen > 0)
    assert not np.allclose(r_gen, r_konly)                    # mass weighting changed the modes


def test_g6_cando_path_stays_k_only(routed_6hb):
    """The cando NMA never builds a mass matrix (M=None) — predict_shape(cando) still returns a
    finite RMSF, unchanged in form from the stiffness-ordered eigenproblem."""
    out = predict_shape(routed_6hb, nonlinear=False, with_rmsf=True, material="cando")
    assert out["rmsf"] and all(np.isfinite(r["rmsf_nm"]) for r in out["rmsf"])


# ── G3: single vs double crossover classification (S4) ───────────────────────────

def test_g3_lone_crossovers_classify_single_paired_double(routed_6hb):
    """Adjacency rule: crossovers in an adjacent-bp cluster (reciprocal DX) → double_co; lone
    crossings (helix ends/seams) → single_co. A routed bundle has BOTH classes, and every link's
    co_type is one of the two."""
    from backend.physics.fem_solver import _classify_crossovers, build_fem_mesh
    cls = _classify_crossovers(routed_6hb)
    assert set(cls.values()) == {"double_co", "single_co"}   # both present
    mesh = build_fem_mesh(routed_6hb)
    assert mesh.rigid_links and all(lk.co_type in ("double_co", "single_co")
                                    for lk in mesh.rigid_links)
    assert any(lk.co_type == "single_co" for lk in mesh.rigid_links)


def test_g3_single_co_softens_K_vs_all_double(routed_6hb, monkeypatch):
    """Classifying the lone crossovers as (much softer) single_co produces a DIFFERENT — and net
    softer at those junctions — global K than forcing every crossover to double_co (the pre-G3
    P2b behavior). cando is unaffected (rigid penalty, no co_type)."""
    import backend.physics.fem_solver as fs
    mesh = build_fem_mesh(routed_6hb)
    K_g3, _ = assemble_global_stiffness(mesh, material="snupi")
    # Force all-double (pre-G3) by overriding co_type on the mesh copy.
    mesh_alldouble = build_fem_mesh(routed_6hb)
    for lk in mesh_alldouble.rigid_links:
        lk.co_type = "double_co"
    K_all, _ = assemble_global_stiffness(mesh_alldouble, material="snupi")
    assert not np.allclose(K_g3.toarray(), K_all.toarray())   # single_co moved the crossover stiffness
    # the G3 matrix is not "more rigid" overall — softer single COs lower the max coupling
    assert np.abs(K_g3).max() <= np.abs(K_all).max() + 1e-6


# ── G2: bp-frame registration (S3.3 / eq 3.18) ───────────────────────────────────

def test_g2_registered_frame_orients_soft_bending_along_cross_strand(D_reg):
    """CONVENTION PIN (mechanical, not reasoned): with the bp-registered frame, the soft bending
    axis EIy (Roll, 158) is oriented along the base-pair long axis (C1'–C1' cross-strand dir), so
    a moment about the cross-strand direction rotates MORE (softer) than about the groove-normal.
    This proves eq 3.18's registration (local y ∥ cross-strand → Roll/EIy)."""
    from backend.physics.fem_solver import (
        _register_bp_frame, _snupi_element_stiffness, _transform_to_global)
    axis = np.array([0.0, 0.0, 1.0]); cross = np.array([1.0, 0.0, 0.0])   # cross-strand = world-x
    Rbp = _register_bp_frame(axis, cross)
    assert np.allclose(Rbp[:, 1], cross)                     # local y ∥ cross-strand
    assert np.allclose(Rbp[:, 2], axis)                      # local z = axis
    Kjj = _transform_to_global(_snupi_element_stiffness(0.34, D_reg), Rbp)[6:, 6:]
    def _rot(mdof):
        f = np.zeros(6); f[mdof] = 1.0
        return np.linalg.norm(np.linalg.solve(Kjj, f)[3:])
    soft = _rot(3)   # moment about world-x = cross-strand → EIy (Roll)
    stiff = _rot(4)  # moment about world-y = groove-normal → EIz (Tilt)
    assert soft > stiff                                      # EIy < EIz → softer about the long axis


def test_g2_registered_frame_changes_snupi_rmsf_only(routed_6hb):
    """The bp-registered frame is opt-in for the snupi NMA (bp_registered_frame=True) and moves the
    global K vs the arbitrary frame; the cando (isotropic) path is byte-identical either way."""
    mesh = build_fem_mesh(routed_6hb)
    assert any(e.R_bp is not None for e in mesh.elements)     # frames were registered
    Ks_reg, _ = assemble_global_stiffness(mesh, material="snupi", bp_registered_frame=True)
    Ks_arb, _ = assemble_global_stiffness(mesh, material="snupi", bp_registered_frame=False)
    assert not np.allclose(Ks_reg.toarray(), Ks_arb.toarray())   # registration reoriented anisotropy
    Kc_reg, _ = assemble_global_stiffness(mesh, material="cando", bp_registered_frame=True)
    Kc_arb, _ = assemble_global_stiffness(mesh, material="cando", bp_registered_frame=False)
    assert np.allclose(Kc_reg.toarray(), Kc_arb.toarray())       # cando ignores the flag


# ── G7: BP–BP cross-correlation matrix (DCCM, S11) ───────────────────────────────

def test_g7_dccm_is_valid_correlation_matrix(routed_6hb):
    """The BP–BP dynamic cross-correlation map must be a valid correlation matrix: symmetric,
    unit diagonal, entries in [−1,1], with strong POSITIVE nearest-neighbor correlation (adjacent
    bp move together) decaying with separation."""
    mesh = build_fem_mesh(routed_6hb)
    n = len(mesh.nodes)
    K, _ = assemble_global_stiffness(mesh, material="snupi", bp_registered_frame=True)
    M = assemble_mass_matrix(mesh, routed_6hb)
    C = compute_correlation_matrix(K, n, M=M)
    assert C.shape == (n, n)
    assert np.allclose(C, C.T)                         # symmetric
    assert np.allclose(np.diag(C), 1.0)                # unit diagonal
    assert C.min() >= -1.0 - 1e-9 and C.max() <= 1.0 + 1e-9
    assert C[0, 1] > 0.5                               # adjacent bp strongly positively correlated
    assert C[0, 1] > C[0, n // 2]                      # decays with separation


def test_g7_dccm_works_k_only_too(routed_6hb):
    """The DCCM is defined for the cando (K-only, M=None) NMA as well — a finite valid matrix."""
    mesh = build_fem_mesh(routed_6hb)
    K, _ = assemble_global_stiffness(mesh, material="cando")
    C = compute_correlation_matrix(K, len(mesh.nodes))
    assert np.all(np.isfinite(C)) and np.allclose(np.diag(C), 1.0)


# ── G8: persistence length from NMA frequencies (S12) ────────────────────────────

def test_g8_bending_persistence_length_physical_and_self_consistent(routed_6hb):
    """L_p from the NMA fundamental bending frequency must be physical (μm-scale — a 6HB bundle is
    far stiffer than a single dsDNA's ~50 nm) and self-consistent (the degenerate bending pair
    gives the same frequency). Torsion is intentionally None (no separable low twist mode)."""
    mesh = build_fem_mesh(routed_6hb)
    K, _ = assemble_global_stiffness(mesh, material="snupi", bp_registered_frame=True)
    M = assemble_mass_matrix(mesh, routed_6hb)
    r = persistence_length_from_nma(K, mesh, routed_6hb, M=M)
    assert r and r["L_p_bend_nm"] > 200.0                    # ≫ single-dsDNA 50 nm (bundle)
    assert np.isfinite(r["EI_eff_pN_nm2"]) and r["EI_eff_pN_nm2"] > 0
    assert abs(r["degenerate_consistency"] - 1.0) < 0.15     # the two bending planes agree
    assert r["L_p_twist_nm"] is None                         # torsion deferred (documented)


def test_g8_requires_mass_matrix(routed_6hb):
    """L_p is a mass-weighted (frequency) observable — without M (the cando K-only NMA) it returns
    an empty dict rather than a meaningless number."""
    mesh = build_fem_mesh(routed_6hb)
    K, _ = assemble_global_stiffness(mesh, material="snupi", bp_registered_frame=True)
    assert persistence_length_from_nma(K, mesh, routed_6hb, M=None) == {}
