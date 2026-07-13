"""Phase 1a validation of the SNUPI Langevin dynamics engine (:mod:`backend.physics.snupi_dynamics`).

The rigorous, fast gates are the analytic ones: a GJF trajectory must sample the exact Boltzmann
configuration distribution, so (a) a 1-DOF harmonic oscillator gives ⟨x²⟩ = k_BT/k, and (b) a small
coupled linear network gives the full covariance k_BT·K⁻¹. The end-to-end gate (marked slow) confirms
that on a real bundle the trajectory RMSF converges to the free-free NMA RMSF — proving the integrator
+ unit system + fluctuation–dissipation are correct before any hydrodynamics (Phase 1b) or the
nonlinear/base-stacking force (Phase 2). See memory/project_snupi_dynamics.md.
"""
from __future__ import annotations

import numpy as np
import pytest

from backend.physics import snupi_dynamics as dyn
from backend.physics import snupi_hydrodynamics as hd


# ── Unit-system / constant sanity ───────────────────────────────────────────────

def test_stokes_constants_have_expected_magnitude():
    # ζ_t = 6πησ ≈ 1.845e-11 N·s/m → 18.45 pN·ns/nm; ζ_r = 8πησ³ → 29.8 pN·nm·ns.
    assert dyn.STOKES_TRANS == pytest.approx(18.45, rel=0.02)
    assert dyn.STOKES_ROT == pytest.approx(29.8, rel=0.02)
    g = dyn.stokes_friction_diag(3)
    assert g.shape == (18,)
    assert np.allclose(g.reshape(3, 6)[:, :3], dyn.STOKES_TRANS)
    assert np.allclose(g.reshape(3, 6)[:, 3:], dyn.STOKES_ROT)


# ── Gate (a): 1-DOF equipartition of POSITION ───────────────────────────────────

def test_gjf_harmonic_oscillator_position_equipartition():
    """⟨x²⟩ = k_BT/k for a single damped oscillator — the atomic proof that the integrator +
    random-force amplitude (fluctuation–dissipation) + unit system are consistent."""
    kT = dyn.KBT_300
    k = 50.0                                   # pN/nm
    m = np.array([1.0e-3])                      # mass_u (≈ a base pair)
    g = np.array([dyn.STOKES_TRANS])
    rng = np.random.default_rng(1)
    samples, _v = dyn.gjf_integrate(
        lambda q: -k * q, np.zeros(1), m, g,
        kT=kT, dt=dyn.DT_DEFAULT, n_steps=200000, n_equil=20000, sample_every=5, rng=rng,
    )
    x2 = float((samples[:, 0] ** 2).mean())
    assert x2 == pytest.approx(kT / k, rel=0.08)


# ── Gate (b): coupled linear network covariance = k_BT·K⁻¹ ───────────────────────

def test_gjf_linear_network_covariance_matches_kT_Kinv():
    """A coupled SPD network sampled by GJF reproduces the full covariance k_BT·K⁻¹ — the
    multi-DOF Boltzmann guarantee that underlies the trajectory-RMSF == NMA-RMSF equivalence."""
    kT = dyn.KBT_300
    rng = np.random.default_rng(2)
    nd = 6
    A = rng.standard_normal((nd, nd))
    K = A @ A.T + nd * np.eye(nd)               # SPD
    m = np.full(nd, 1.0e-3)
    g = np.full(nd, dyn.STOKES_TRANS)
    samples, _v = dyn.gjf_integrate(
        lambda q: -(K @ q), np.zeros(nd), m, g,
        kT=kT, dt=dyn.DT_DEFAULT, n_steps=400000, n_equil=40000, sample_every=5, rng=rng,
    )
    cov = np.cov(samples.T)
    target = kT * np.linalg.inv(K)
    rel = np.linalg.norm(cov - target) / np.linalg.norm(target)
    assert rel < 0.2


def test_gjf_diverges_raises_not_nan():
    """A too-large step raises the typed divergence error (so the driver can retry) rather than
    silently returning NaNs."""
    k = 5.0e4                                   # very stiff → unstable at 5 ps
    m = np.array([1.0e-3])
    g = np.array([dyn.STOKES_TRANS])
    with pytest.raises(dyn._GJFDiverged), np.errstate(over="ignore", invalid="ignore"):
        dyn.gjf_integrate(lambda q: -k * q, np.zeros(1), m, g,
                          dt=dyn.DT_DEFAULT, n_steps=4000, n_equil=4000, sample_every=1,
                          rng=np.random.default_rng(0))


# ── trajectory_rmsf removes rigid-body drift ────────────────────────────────────

def test_trajectory_rmsf_removes_rigid_body_motion():
    """A rigidly translating+rotating (non-deforming) body has zero RMSF after alignment."""
    rng = np.random.default_rng(3)
    ref = rng.standard_normal((10, 3))
    frames = []
    for _ in range(20):
        theta = rng.standard_normal() * 0.3
        c, s = np.cos(theta), np.sin(theta)
        Rz = np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])
        frames.append(ref @ Rz.T + rng.standard_normal(3) * 2.0)   # rigid rot + translation
    rmsf = dyn.trajectory_rmsf(np.array(frames), ref)
    assert np.all(rmsf < 1e-6)


# ── End-to-end gate: trajectory RMSF converges to NMA RMSF on a real bundle ──────

@pytest.mark.slow
def test_trajectory_rmsf_matches_nma_on_real_bundle():
    from backend.core.models import LatticeType
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.physics.fem_solver import (
        build_fem_mesh, assemble_global_stiffness, assemble_mass_matrix, compute_rmsf_nma,
    )

    cells = [(0, 1), (1, 1)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 42, lattice=LatticeType.HONEYCOMB, name="2hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        design = design_state.get_or_404().model_copy(deep=True)

    mesh = build_fem_mesh(design)
    n = len(mesh.nodes)
    K, _ = assemble_global_stiffness(mesh, material="snupi", bp_registered_frame=True)
    M = assemble_mass_matrix(mesh, design)
    nma = compute_rmsf_nma(K.tocsr(), n, M=M)

    out = dyn.simulate_equilibrium(
        design, material="snupi", n_steps=200000, n_equil=40000, sample_every=40, seed=0,
    )
    traj = out["rmsf"]
    a, b = traj - traj.mean(), nma - nma.mean()
    pearson = float((a @ b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    mag_ratio = float(traj.mean() / (nma.mean() + 1e-12))
    # The trajectory samples k_BT·K⁻¹ (as NMA does); the residual gap is slow-mode sampling.
    assert pearson >= 0.85
    assert 0.5 <= mag_ratio <= 1.3
    assert out["dt_ns"] > 0 and np.isfinite(traj).all()


# ── Phase 1b: Rotne–Prager–Yamakawa hydrodynamic friction ───────────────────────

def test_rpy_mobility_is_spd_including_overlaps():
    """The translational RPY mobility (and the 6N friction Z) must stay symmetric positive-definite
    even with overlapping beads (r < 2σ) — required so Z⁻¹ and the noise Cholesky are well-defined.
    Adjacent bp sit 0.34 nm apart ≪ 2σ = 2.2 nm, so the overlap regularization is exercised for real."""
    rng = np.random.default_rng(0)
    pos = rng.standard_normal((8, 3)) * 1.5          # nm — many pairs inside 2σ
    Xi = hd.rpy_mobility_translational(pos)
    assert np.allclose(Xi, Xi.T)
    assert np.linalg.eigvalsh(Xi).min() > 0
    Z = hd.friction_matrix(pos)
    assert np.allclose(Z, Z.T)
    assert np.linalg.eigvalsh(Z).min() > 0


def test_rpy_self_mobility_is_stokes_and_pair_decays():
    """Isolated-bead self mobility = 1/ζ_t (Stokes); the pair coupling falls off with separation."""
    far = np.array([[0.0, 0, 0], [50.0, 0, 0]])
    Xi = hd.rpy_mobility_translational(far)
    assert Xi[0, 0] == pytest.approx(1.0 / dyn.STOKES_TRANS, rel=1e-9)
    near = np.array([[0.0, 0, 0], [5.0, 0, 0]])
    coup_far = np.abs(hd.rpy_mobility_translational(far)[:3, 3:]).max()
    coup_near = np.abs(hd.rpy_mobility_translational(near)[:3, 3:]).max()
    assert coup_near > coup_far                      # closer beads couple more strongly


def test_rpy_friction_has_real_offdiagonal_coupling():
    """Z is genuinely coupled (hydrodynamic interaction present) — NOT the diagonal Stokes drag.
    The translational off-diagonal blocks must carry non-negligible weight."""
    pos = np.array([[0.0, 0, 0], [1.0, 0, 0], [2.0, 0, 0]])   # a close chain
    Z = hd.friction_matrix(pos)
    off = np.abs(Z[0:3, 6:9]).max()                  # node0↔node1 translational coupling
    diag = np.abs(Z[0:3, 0:3]).max()
    assert off > 0.05 * diag


def test_matrix_gjf_samples_kT_Kinv_with_full_friction():
    """The matrix-friction GJF (correlated noise + eigen-transform) reproduces the covariance
    k_BT·K⁻¹ for ANY SPD coupled friction — the fluctuation–dissipation gate for hydrodynamics."""
    kT = dyn.KBT_300
    rng = np.random.default_rng(4)
    nd = 6
    A = rng.standard_normal((nd, nd)); K = A @ A.T + nd * np.eye(nd)
    B = rng.standard_normal((nd, nd)); Z = B @ B.T + nd * np.eye(nd)     # arbitrary SPD friction
    m = np.full(nd, 1.0e-3)
    samples, _v = dyn.gjf_integrate_matrix_friction(
        lambda q: -(K @ q), np.zeros(nd), m, Z,
        kT=kT, dt=dyn.DT_DEFAULT, n_steps=400000, n_equil=40000, sample_every=5, rng=rng,
    )
    cov = np.cov(samples.T)
    target = kT * np.linalg.inv(K)
    assert np.linalg.norm(cov - target) / np.linalg.norm(target) < 0.2


@pytest.mark.slow
def test_rpy_equilibrium_rmsf_matches_stokes_on_real_bundle():
    """The Phase-1b headline invariant: RPY hydrodynamics leaves the EQUILIBRIUM RMSF unchanged from
    diagonal Stokes (friction only sets the kinetics, not the Boltzmann config distribution)."""
    from backend.core.models import LatticeType
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 42, lattice=LatticeType.HONEYCOMB, name="2hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        design = design_state.get_or_404().model_copy(deep=True)

    kw = dict(material="snupi", n_steps=200000, n_equil=40000, sample_every=40, seed=0)
    stokes = dyn.simulate_equilibrium(design, hydrodynamics=False, **kw)
    rpy = dyn.simulate_equilibrium(design, hydrodynamics=True, **kw)
    assert rpy["friction"] == "rpy" and stokes["friction"] == "stokes"
    # Same equilibrium distribution → same mean RMSF (independent trajectories, so allow sampling noise).
    assert rpy["rmsf"].mean() == pytest.approx(stokes["rmsf"].mean(), rel=0.15)


# ── Phase 2: salt-driven reconfiguration (the ion switch) ────────────────────────

def test_stacking_force_all_and_bond_lengths():
    from backend.physics import snupi_stacking as stk
    q = np.zeros(18)                                 # 3 nodes × 6 DOF
    q[6:9] = [stk.R0_STACK, 0, 0]                    # node1 at r₀ from node0
    q[12:15] = [5.0, 0, 0]                           # node2 far
    f = dyn.stacking_force_all(q, [(0, 1), (0, 2)])
    assert f.shape == (18,)
    assert np.allclose(f[9:12], 0) and np.allclose(f[15:18], 0)   # rotational slots untouched
    bl = dyn.bond_lengths(q, [(0, 1), (0, 2)])
    assert bl[0] == pytest.approx(stk.R0_STACK) and bl[1] == pytest.approx(5.0)


def test_reconfiguration_switch_opens_and_recloses_with_salt():
    """The paper's close→open→close ion switch: a Morse stacking bond holds a node closed against a
    weak pivot tether; a salt-driven opening force ruptures it at low salt, and it re-stacks when salt
    is restored. Validates the driver (multi-segment schedule, config continuity) + the switch physics."""
    from backend.physics import snupi_stacking as stk

    k_anchor, k_tether, r_rest = 1000.0, 40.0, stk.R0_STACK
    pairs = [(0, 1)]

    def f_open(salt):
        return 10.0 + (90.0 - 10.0) * (0.5 - salt) / (0.5 - 0.005)   # ↑ as salt ↓ (rupture ≈ 57 pN)

    def force_fn(q, salt):
        f = np.zeros(12)
        f[0:3] += -k_anchor * q[0:3]                 # anchor node0
        d = q[6:9] - q[0:3]; r = np.linalg.norm(d); rh = d / (r + 1e-12)
        ft = -k_tether * (r - r_rest) * rh           # pivot tether (the arms' return path)
        f[6:9] += ft; f[0:3] -= ft
        f += dyn.stacking_force_all(q, pairs)
        f[6:9] += np.array([f_open(salt), 0.0, 0.0])
        return f

    q0 = np.zeros(12); q0[6] = r_rest
    m = np.full(12, 1e-3); g = dyn.stokes_friction_diag(2)
    schedule = [
        {"label": "25mM closed", "salt": 0.5, "n_steps": 60000},
        {"label": "5mM open", "salt": 0.005, "n_steps": 60000},
        {"label": "25mM reclosed", "salt": 0.5, "n_steps": 60000},
    ]
    out = dyn.simulate_reconfiguration(q0, force_fn, schedule, m, g,
                                       stacking_pairs=pairs, dt=5e-4, sample_every=50, seed=1)
    closed, opened, reclosed = [s["mean_bond_length"] for s in out["segments"]]
    assert closed < 0.8                              # stacked (closed)
    assert opened > 1.8                              # unstacked (open) at low salt
    assert reclosed < 0.8                            # re-stacked when salt restored (reversible)


# ── Visualization bridge: dynamics output speaks the predict_shape contract ──────

@pytest.mark.slow
def test_predict_shape_dynamics_matches_static_contract():
    """predict_shape(dynamics=True) must return the SAME payload shape as the static solve
    (positions/axis/rmsf keyed to the same nodes) so every SNUPI display toggle works unchanged."""
    from backend.core.models import LatticeType
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.physics.fem_solver import predict_shape

    cells = [(0, 1), (1, 1)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 42, lattice=LatticeType.HONEYCOMB, name="2hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        design = design_state.get_or_404().model_copy(deep=True)

    static = predict_shape(design, material="snupi", nonlinear=False, with_rmsf=True)
    dyn_out = predict_shape(design, material="snupi", dynamics=True, dynamics_steps=40000, with_rmsf=True)
    dyn_rpy = predict_shape(design, material="snupi", dynamics=True, hydrodynamics=True,
                            dynamics_steps=40000, with_rmsf=True)

    for out, solver in [(dyn_out, "dynamics"), (dyn_rpy, "dynamics-rpy")]:
        assert out["solver"] == solver
        assert len(out["positions"]) == len(static["positions"])
        assert len(out["axis"]) == len(static["axis"])
        assert len(out["rmsf"]) == len(static["rmsf"])
        assert set(out["rmsf"][0]) == set(static["rmsf"][0])       # same keys
        assert all(np.isfinite(r["rmsf_nm"]) for r in out["rmsf"])
        assert out["n_frame"] > 0
        # Trajectory payload for the animation toggle: framesToUpdates wire shape (keys + 6 floats/key).
        traj = out["trajectory"]
        assert traj["n_frames"] > 1
        assert len(traj["keys"]) == len(static["positions"])       # one key per drawn nucleotide
        assert len(traj["keys"][0]) == 4                           # [helix, bp, dir, copy]
        assert all(len(fr) == 6 * len(traj["keys"]) for fr in traj["frames"])
        f0 = np.array(traj["frames"][0]).reshape(-1, 6)[:, :3]
        fN = np.array(traj["frames"][-1]).reshape(-1, 6)[:, :3]
        assert np.abs(f0 - fN).max() > 1e-3                        # frames actually differ (motion)

