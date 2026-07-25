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



# ── Phase 3: PCA breathing-mode extraction (paper Fig 3c/d) ─────────────────────

def test_breathing_pca_recovers_injected_mode():
    """Deterministic pin: frames = a single radial 'breathing' oscillation of a ring of nodes → PCA
    must recover that mode's shape, its thermal variance ⟨ξ²⟩, and the equipartition wiring
    (k_eff·⟨ξ²⟩ = k_BT, m_eff = vᵀ·diag(m)·v). A pure dilation is orthogonal to all 6 rigid modes, so
    Kabsch alignment leaves it untouched — the recovered shape/variance are exact up to sampling."""
    N, F, A = 12, 40, 0.1
    phi = 2.0 * np.pi * np.arange(N) / N
    X0 = np.stack([np.cos(phi), np.sin(phi), np.zeros(N)], axis=1)        # unit ring in xy
    radial = np.stack([np.cos(phi), np.sin(phi), np.zeros(N)], axis=1)   # outward radial per node
    mode = (radial / np.linalg.norm(radial)).reshape(N, 3)              # unit 3N shape
    amp = A * np.cos(2.0 * np.pi * np.arange(F) / F)                     # one full period, ⟨amp²⟩ = A²/2
    frames = X0[None] + amp[:, None, None] * mode[None]                  # (F,N,3)

    node_mass = np.ones(N)
    kT = dyn.KBT_300
    out = dyn.breathing_mode_pca(frames, X0, node_mass, kT=kT, n_modes=3)
    m0 = out["modes"][0]

    overlap = abs(float(m0["shape"].reshape(-1) @ mode.reshape(-1)))     # both unit vectors
    assert overlap > 0.999                                               # recovered the injected shape
    exp_var = 0.5 * A * A * F / (F - 1)                                  # SVD variance uses /(F-1)
    assert abs(m0["variance_nm2"] - exp_var) / exp_var < 0.02
    assert abs(m0["amplitude_nm"] - np.sqrt(m0["variance_nm2"])) < 1e-12
    # equipartition + effective-mass wiring
    assert abs(m0["k_eff_pN_per_nm"] * m0["variance_nm2"] - kT) < 1e-9
    assert abs(m0["m_eff"] - 1.0) < 1e-9                                 # unit shape, unit masses
    assert abs(m0["freq_GHz"] - m0["omega_per_ns"] / (2 * np.pi)) < 1e-12
    assert m0["variance_nm2"] >= out["modes"][1]["variance_nm2"]         # variance-ranked


@pytest.mark.slow
def test_breathing_pca_mode_tracks_rmsf_on_real_bundle():
    """On a real 2HB the dominant PCA mode is the softest collective motion, so where it moves most
    (per-node |shape|) must be where the structure is floppiest (per-node RMSF). Positive, finite
    natural frequency; the leading mode carries a real share of the total fluctuation variance."""
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

    sim = dyn.simulate_equilibrium(
        design, material="snupi", n_steps=120000, n_equil=20000, sample_every=30, seed=1,
    )
    N = sim["frames"].shape[1]
    node_mass = sim["mass_diag"].reshape(N, 6)[:, 0]
    pca = dyn.breathing_mode_pca(sim["frames"], sim["positions0"], node_mass, n_modes=5)
    m0 = pca["modes"][0]

    amp_per_node = np.linalg.norm(m0["shape"], axis=1)                   # (N,)
    rmsf = np.asarray(sim["rmsf"])
    a, b = amp_per_node - amp_per_node.mean(), rmsf - rmsf.mean()
    corr = float((a @ b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    assert corr > 0.5                                                    # mode motion ↔ floppiness
    assert m0["freq_GHz"] > 0 and np.isfinite(m0["freq_GHz"])
    frac = m0["variance_nm2"] / pca["variance_all"].sum()
    assert frac > 1.0 / N                                                # leading mode is collective


# ── Phase 3: DCCM + mode-kinetics primitives (RPY-payoff analysis) ──────────────

def _ring_breathing_frames(N=12, F=40, A=0.1):
    """A ring of N nodes undergoing one full period of pure radial 'breathing' (dilation) — a mode
    orthogonal to all rigid modes, so Kabsch alignment leaves it exact. Returns (X0, mode, amp, frames)."""
    phi = 2.0 * np.pi * np.arange(N) / N
    X0 = np.stack([np.cos(phi), np.sin(phi), np.zeros(N)], axis=1)
    radial = np.stack([np.cos(phi), np.sin(phi), np.zeros(N)], axis=1)
    mode = (radial / np.linalg.norm(radial)).reshape(N, 3)
    amp = A * np.cos(2.0 * np.pi * np.arange(F) / F)
    frames = X0[None] + amp[:, None, None] * mode[None]
    return X0, mode, amp, frames


def test_dynamics_dccm_signs_match_breathing_geometry():
    """Equal-time DCCM of a radial-breathing ring: opposite nodes move in opposite directions but in
    lock-step in time → correlation −1; the diagonal is +1; a node vs its neighbour ≈ cos(2π/N) > 0."""
    N = 12
    X0, mode, amp, frames = _ring_breathing_frames(N=N)
    C = dyn.dynamics_dccm(frames, X0)
    assert C.shape == (N, N)
    assert np.allclose(np.diag(C), 1.0, atol=1e-6)
    assert C[0, N // 2] < -0.99                                   # diametrically opposite node
    assert C[0, 1] > 0.5                                          # neighbour, ê·ê = cos(2π/12) ≈ 0.87
    assert abs(C[0, 1] - np.cos(2 * np.pi / N)) < 1e-3


def test_mode_coordinate_recovers_projection():
    """Projecting the breathing frames onto their unit mode returns the injected amplitude series."""
    X0, mode, amp, frames = _ring_breathing_frames()
    xi = dyn.mode_coordinate(frames, X0, mode)
    assert np.allclose(xi, amp, atol=1e-9)


def test_autocorr_time_recovers_ar1_timescale():
    """Integrated autocorrelation time of an AR(1) series x_t = φ x_{t-1} + √(1−φ²)ε recovers the
    analytic τ_int = dt·(1+φ)/(1−φ)."""
    rng = np.random.default_rng(0)
    phi, dt, n = np.exp(-1.0), 0.01, 60000
    x = np.empty(n)
    x[0] = rng.standard_normal()
    s = np.sqrt(1.0 - phi * phi)
    for t in range(1, n):
        x[t] = phi * x[t - 1] + s * rng.standard_normal()
    tau = dyn.mode_autocorr_time_ns(x, dt)
    tau_true = dt * (1.0 + phi) / (1.0 - phi)
    assert abs(tau - tau_true) / tau_true < 0.25


@pytest.mark.slow
def test_dccm_and_mode_kinetics_primitives_on_real_bundle():
    """End-to-end integration of the RPY-payoff analysis primitives on a real 2HB: (a) a dynamics
    trajectory's equal-time DCCM (:func:`dynamics_dccm`) tracks the analytic free-free NMA DCCM — i.e.
    the engine reproduces the NMA 'shape of motion'; (b) the breathing-mode relaxation time
    (:func:`mode_autocorr_time_ns` on :func:`mode_coordinate`) is a finite, positive kinetic quantity
    for BOTH diagonal-Stokes and full-RPY friction (the quantity hydrodynamics changes). The
    quantitative RPY-vs-MD comparison itself lives in ``scripts/snupi_dccm_compare.py`` (logged
    numbers, needs a local MD DCD), not a pinned assertion — the equal-time DCCM's friction-
    independence is already proven analytically by the Phase-1b ``cov = k_BT·K⁻¹`` test."""
    from backend.core.models import LatticeType
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    from backend.physics.fem_solver import (
        build_fem_mesh, assemble_global_stiffness, assemble_mass_matrix, compute_correlation_matrix,
    )

    cells = [(0, 1), (1, 1)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 42, lattice=LatticeType.HONEYCOMB, name="2hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        design = design_state.get_or_404().model_copy(deep=True)

    kw = dict(material="snupi", n_steps=120000, n_equil=20000, sample_every=20, seed=3)
    stk = dyn.simulate_equilibrium(design, hydrodynamics=False, **kw)
    rpy = dyn.simulate_equilibrium(design, hydrodynamics=True, **kw)

    # (a) dynamics DCCM tracks the analytic NMA DCCM (same node order as the frames).
    mesh = build_fem_mesh(design)
    K, _ = assemble_global_stiffness(mesh, material="snupi", bp_registered_frame=True)
    M = assemble_mass_matrix(mesh, design)
    C_nma = compute_correlation_matrix(K, len(mesh.nodes), M=M)
    C_s = dyn.dynamics_dccm(stk["frames"], stk["positions0"])
    iu = np.triu_indices(C_s.shape[0], k=1)
    agree_s = float(np.corrcoef(C_s[iu], C_nma[iu])[0, 1])
    assert C_s.shape == C_nma.shape and np.allclose(np.diag(C_s), 1.0, atol=1e-6)
    assert agree_s > 0.4                                            # engine reproduces NMA motion topology

    # (b) breathing-mode relaxation time — finite, positive kinetic quantity for both frictions.
    N = stk["frames"].shape[1]
    nm = stk["mass_diag"].reshape(N, 6)[:, 0]
    mode = dyn.breathing_mode_pca(stk["frames"], stk["positions0"], nm, n_modes=1)["modes"][0]["shape"]
    for sim in (stk, rpy):
        xi = dyn.mode_coordinate(sim["frames"], sim["positions0"], mode)
        tau = dyn.mode_autocorr_time_ns(xi, sim["dt_ns"] * kw["sample_every"])
        assert tau > 0 and np.isfinite(tau)


# ── Phase 1b-ii: full generalized RPY (rotation–translation + rotation–rotation) ──

def _two_nodes(r):
    return np.array([[0.0, 0.0, 0.0], [r, 0.0, 0.0]])


def test_generalized_rpy_spd_for_separated_beads():
    """The full generalized mobility is symmetric + positive-definite in its valid (well-separated)
    regime — a ladder at ≥ 2a spacing. Both Ξ and its inverse Z are SPD."""
    a = dyn.HYDRO_RADIUS_NM
    xs = np.arange(5) * 2.5 * a                        # non-overlapping (r ≥ 2a)
    pos = np.array([[x, 0.0, 0.0] for x in xs] + [[x, 3.0 * a, 0.0] for x in xs])
    Xi = hd.rpy_mobility_generalized(pos, a)
    assert np.allclose(Xi, Xi.T)
    assert np.linalg.eigvalsh(Xi).min() > 0
    Z = hd.friction_matrix(pos, a, generalized=True)
    assert np.allclose(Z, Z.T)
    assert np.linalg.eigvalsh(Z).min() > 0


def test_generalized_rpy_pair_is_spd_at_all_overlaps():
    """A single pair's generalized mobility is SPD at every separation, including deep overlap
    (r/a ≈ 0.3) — so the r<2a rt/rr regularizations are individually well-formed."""
    a = dyn.HYDRO_RADIUS_NM
    for frac in (0.31, 0.5, 1.0, 2.0, 3.0):
        Xi = hd.rpy_mobility_generalized(_two_nodes(frac * a), a)
        assert np.linalg.eigvalsh(Xi).min() > 0, f"non-PD pair at r/a={frac}"


def test_generalized_rpy_pd_at_origami_overlap():
    """RETRACTION PIN (commit 289aa6d): an earlier version stored the μ^rt cross-block as the
    transpose of μ^tr, flipping a sign; reciprocity forces the two blocks EQUAL, and that sign
    error made the many-body superposition appear to lose positive-definiteness at DNA-origami
    bead density (σ=1.1 nm beads 0.34 nm apart, ~10 near-concentric neighbours). With the parity
    corrected the generalized mobility is genuinely SPD on this dense config — so friction_matrix(
    generalized=True) SUCCEEDS (no longer refuses) and returns an SPD friction, and the
    translational-only production path stays SPD on the very same configuration. This is the one
    test covering the dense-overlap many-body case (test_generalized_rpy_spd_for_separated_beads
    covers r≥2a; test_generalized_rpy_pair_is_spd_at_all_overlaps covers a single pair)."""
    a = dyn.HYDRO_RADIUS_NM
    xs = np.arange(8) * 0.34                            # a dense helix-like run at the real bp spacing
    pos = np.array([[x, 0.0, 0.0] for x in xs] + [[x, 1.0, 0.0] for x in xs])
    Xi = hd.rpy_mobility_generalized(pos, a)
    assert np.allclose(Xi, Xi.T)
    assert np.linalg.eigvalsh(Xi).min() > 0                                     # PD after parity fix
    Z = hd.friction_matrix(pos, a, generalized=True)                           # no longer raises
    assert np.allclose(Z, Z.T)
    assert np.linalg.eigvalsh(Z).min() > 0
    Zt = hd.friction_matrix(pos, a, generalized=False)                         # production path
    assert np.linalg.eigvalsh(Zt).min() > 0


def test_generalized_rpy_rr_traceless_far_and_coupling_antisymmetric():
    """Structure of the far-field (r>2a) coupling blocks: μ^rr ∝ (3r̂r̂ − I) is traceless with
    along-axis = −2× transverse; μ^rt ∝ ε·r̂ is antisymmetric and non-zero."""
    a = dyn.HYDRO_RADIUS_NM
    rvec = np.array([-3.0 * a, 0.0, 0.0])
    rr = hd._rpy_pair_rr(rvec, a)
    rt = hd._rpy_pair_rt(rvec, a)
    assert abs(np.trace(rr)) < 1e-12
    assert rr[0, 0] == pytest.approx(-2.0 * rr[1, 1], rel=1e-9)
    assert np.allclose(rt, -rt.T)
    assert np.abs(rt).max() > 0


def test_generalized_rpy_continuous_at_2a():
    """The overlap regularizations join the far-field tensors continuously at r = 2a (the property
    that keeps Ξ SPD across the transition)."""
    a = dyn.HYDRO_RADIUS_NM
    eps = 1e-6
    below = np.array([-(2 * a - eps), 0.0, 0.0])
    above = np.array([-(2 * a + eps), 0.0, 0.0])
    assert np.allclose(hd._rpy_pair_rr(below, a), hd._rpy_pair_rr(above, a), atol=1e-5)
    assert np.allclose(hd._rpy_pair_rt(below, a), hd._rpy_pair_rt(above, a), atol=1e-5)


def test_generalized_rpy_self_blocks_and_far_decay():
    """Self blocks are the Stokes translational/rotational mobilities; pair coupling → 0 at large r."""
    a = dyn.HYDRO_RADIUS_NM
    Xi = hd.rpy_mobility_generalized(_two_nodes(50.0 * a), a)
    assert Xi[0, 0] == pytest.approx(1.0 / dyn.STOKES_TRANS, rel=1e-9)   # tt self
    assert Xi[3, 3] == pytest.approx(1.0 / dyn.STOKES_ROT, rel=1e-9)     # rr self
    # tt coupling decays only as 1/r, so judge it relative to the self mobility (not an absolute floor).
    assert np.abs(Xi[0:6, 6:12]).max() < 0.05 * (1.0 / dyn.STOKES_TRANS)


def test_generalized_friction_adds_rotational_coupling():
    """The 1b-ii payoff: the generalized friction carries real rotation–rotation AND rotation–
    translation pair coupling, which the translational-only pass (diagonal rotational drag) zeros."""
    a = dyn.HYDRO_RADIUS_NM
    pos = _two_nodes(2.5 * a)
    Zg = hd.friction_matrix(pos, a, generalized=True)
    Zt = hd.friction_matrix(pos, a, generalized=False)
    assert np.abs(Zt[3:6, 9:12]).max() < 1e-9        # old pass: no rot–rot pair coupling
    assert np.abs(Zg[3:6, 9:12]).max() > 1e-6        # generalized: rot–rot coupling present
    assert np.abs(Zg[3:6, 6:9]).max() > 1e-6         # ...and rot–trans coupling


# ── Phase 2: nonlinear corotational force in the Langevin loop ───────────────────

def _routed_2hb():
    from backend.core.models import LatticeType
    from backend.api import headless_build as hb
    from backend.api import state as design_state
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle([(0, 1), (1, 1)], 42, lattice=LatticeType.HONEYCOMB, name="2hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def test_corotational_force_zero_under_rigid_body():
    """The defining corotational property: a rigid-body displacement (uniform translation) produces
    ZERO internal force — the EICR filter removes rigid motion (d_local = 0) for ANY stiffness."""
    from backend.physics.fem_solver import build_fem_mesh, build_corotational_elements
    mesh = build_fem_mesh(_routed_2hb())
    N = len(mesh.nodes)
    X0, elements = build_corotational_elements(mesh)
    q = np.zeros(6 * N)
    q.reshape(N, 6)[:, 0] = 1.7                            # uniform +x translation
    f = dyn.corotational_internal_force(q, X0, elements)
    assert np.abs(f).max() < 1e-9


def test_corotational_force_reduces_to_element_tangent_for_small_q():
    """For small q the nonlinear corotational force → the linear tangent assembled from the SAME
    corotational elements (T·K₁₂·Tᵀ, geometry frame) — proving the force assembly is consistent with
    its own stiffness (NOT the bp-registered NMA K, which differs by the anisotropic-bending frame)."""
    from backend.physics.fem_solver import build_fem_mesh, build_corotational_elements
    from backend.physics.snupi_corotational import element_force_tangent
    mesh = build_fem_mesh(_routed_2hb())
    N = len(mesh.nodes)
    X0, elements = build_corotational_elements(mesh)
    Kc = np.zeros((6 * N, 6 * N))
    for (i, j, ref, K12) in elements:
        _f, Kg = element_force_tangent(X0[i], X0[j], np.eye(3), np.eye(3), ref, K12, geometric=False)
        dofs = list(range(6 * i, 6 * i + 6)) + list(range(6 * j, 6 * j + 6))
        Kc[np.ix_(dofs, dofs)] += Kg
    rng = np.random.default_rng(1)
    q = rng.standard_normal(6 * N) * 1e-5
    fc = dyn.corotational_internal_force(q, X0, elements)
    assert np.linalg.norm(fc - Kc @ q) / np.linalg.norm(Kc @ q) < 0.02


@pytest.mark.slow
def test_simulate_equilibrium_nonlinear_force_runs_and_tracks_flexibility():
    """simulate_equilibrium(nonlinear_force=True) drives the Langevin loop with the full corotational
    F(x): it produces a finite trajectory RMSF whose per-node flexibility pattern correlates with the
    linear run (same structure; the geometry-frame linearization shifts magnitude, not the topology of
    where it's floppy)."""
    design = _routed_2hb()
    kw = dict(n_steps=20000, n_equil=4000, sample_every=20, seed=0)
    lin = dyn.simulate_equilibrium(design, **kw)
    nl = dyn.simulate_equilibrium(design, nonlinear_force=True, **kw)
    assert nl["rmsf"].shape == lin["rmsf"].shape
    assert np.isfinite(nl["rmsf"]).all() and nl["rmsf"].mean() > 0
    a, b = nl["rmsf"] - nl["rmsf"].mean(), lin["rmsf"] - lin["rmsf"].mean()
    corr = float((a @ b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    assert corr > 0.4


# ── Phase 2: modified GJF (half-time + Simpson) for the paper's 5 ps step ─────────

@pytest.mark.parametrize("m,k,g,dt", [(1.0, 1.0, 1.0, 1.0), (1.0, 1.0, 3.0, 0.5), (1.0, 1.0, 3.0, 3.0)])
def test_modified_gjf_samples_boltzmann_harmonic(m, k, g, dt):
    """The paper's harmonic validation (SI §4.4, conditions i/ii/iv): the modified GJF samples the exact
    configurational variance ⟨U²⟩ = k_BT/k — INCLUDING condition iv (dt=3, ΩΔt/2=1.5) where plain GJF is
    numerically unstable. Correct sampling relies on the fluctuation-dissipation-consistent shared-half
    random impulse (β^{Δt} contains β^{Δt/2})."""
    s, _ = dyn.gjf_modified_integrate(
        lambda q: -k * q, np.zeros(1), np.array([m]), np.array([g]),
        kT=1.0, dt=dt, n_steps=400000, n_equil=40000, sample_every=4, rng=np.random.default_rng(0),
    )
    assert float((s[:, 0] ** 2).mean()) == pytest.approx(1.0 / k, rel=0.1)


def test_modified_gjf_stable_where_plain_diverges():
    """At ΩΔt/2 = 1.5 (dt=3, k=m=1) plain GJF hits its Verlet stability wall and diverges, while the
    Simpson-midpoint modified GJF stays stable AND samples ⟨U²⟩ = k_BT/k."""
    with pytest.raises(dyn._GJFDiverged), np.errstate(over="ignore", invalid="ignore"):
        dyn.gjf_integrate(lambda q: -q, np.zeros(1), np.array([1.0]), np.array([3.0]),
                          kT=1.0, dt=3.0, n_steps=20000, n_equil=2000, sample_every=1,
                          rng=np.random.default_rng(0))
    s, _ = dyn.gjf_modified_integrate(lambda q: -q, np.zeros(1), np.array([1.0]), np.array([3.0]),
                                      kT=1.0, dt=3.0, n_steps=400000, n_equil=40000, sample_every=4,
                                      rng=np.random.default_rng(0))
    assert np.isfinite(s).all()
    assert float((s[:, 0] ** 2).mean()) == pytest.approx(1.0, rel=0.1)


@pytest.mark.slow
def test_modified_gjf_extends_stable_step_on_real_bundle():
    """Phase-2(c) payoff on a real 2HB: at 1 ps (ΩΔt/2 ≈ 2.4 for the stiffest generalized mode) plain GJF
    DIVERGES but the modified GJF stays stable AND its trajectory RMSF matches the free-free NMA RMSF — a
    ~6× larger stable step (plain caps ~0.17 ps here). Reaching the paper's flat 5 ps additionally needs
    the stiff crossover modes softened/constrained (their future 'constrained Langevin'); the integrator
    itself is validated by the harmonic conditions i–iv above. Integrators are called directly so the
    simulate_equilibrium retry-guard doesn't mask the plain divergence."""
    from backend.physics.fem_solver import (
        build_fem_mesh, assemble_global_stiffness, assemble_mass_matrix, compute_rmsf_nma,
        assemble_prestress_force,
    )
    design = _routed_2hb()
    mesh = build_fem_mesh(design)
    n = len(mesh.nodes)
    Kc = assemble_global_stiffness(mesh, material="snupi", bp_registered_frame=True)[0].tocsr()
    M = assemble_mass_matrix(mesh, design)
    nma = compute_rmsf_nma(Kc, n, M=M)
    X0 = np.array([nd.position for nd in mesh.nodes])
    f_ext = np.asarray(assemble_prestress_force(mesh, design))
    m_diag = np.asarray(M.tocsr().diagonal()) * dyn.MASS_G6_TO_DYN
    gamma = dyn.stokes_friction_diag(n)

    def force_fn(q):
        return f_ext - (Kc @ q)

    kw = dict(kT=dyn.KBT_300, dt=0.001, n_steps=120000, n_equil=20000, sample_every=20)
    with pytest.raises(dyn._GJFDiverged), np.errstate(over="ignore", invalid="ignore"):
        dyn.gjf_integrate(force_fn, np.zeros(6 * n), m_diag, gamma, rng=np.random.default_rng(0), **kw)

    s, _ = dyn.gjf_modified_integrate(force_fn, np.zeros(6 * n), m_diag, gamma,
                                      rng=np.random.default_rng(0), **kw)
    disp = s.reshape(len(s), n, 6)[:, :, :3]
    r = dyn.trajectory_rmsf(X0[None] + disp, X0)
    a, b = r - r.mean(), nma - nma.mean()
    pearson = float((a @ b) / (np.linalg.norm(a) * np.linalg.norm(b) + 1e-12))
    assert np.isfinite(r).all()
    assert pearson > 0.9
    assert 0.6 <= r.mean() / nma.mean() <= 1.2


# ── E-field body load + anchor traps (project_oxdna_efield in the Langevin loop) ─────

def test_field_body_load_core_is_two_x_and_tails_are_one_x():
    """field_body_load applies the shared oxDNA per-nucleotide force: a core bp node carries two
    backbones → 2·field_pN, a free ssDNA tail bead is one nucleotide → 1·field_pN, translational
    DOF only (a pure body force, no couple). None / zero magnitude → an exact zero vector."""
    from types import SimpleNamespace
    from backend.physics.fem_solver import build_fem_mesh
    mesh = build_fem_mesh(_routed_2hb())
    n = len(mesh.nodes)
    field = {"field_pN": 0.5, "dir": [0.0, 1.0, 0.0]}

    fr = dyn.field_body_load(mesh, None, n, field).reshape(n, 6)
    assert np.allclose(fr[:, :3], [0.0, 1.0, 0.0])       # 2·0.5 = 1.0 along +y on every core node
    assert np.allclose(fr[:, 3:], 0.0)                   # no couple on rotational DOF

    block = SimpleNamespace(n_tail=2)                    # two ssDNA tail beads appended after the core
    fr2 = dyn.field_body_load(mesh, block, n + 2, field).reshape(n + 2, 6)
    assert np.allclose(fr2[:n, :3], [0.0, 1.0, 0.0])     # core unchanged (2×)
    assert np.allclose(fr2[n:, :3], [0.0, 0.5, 0.0])     # tail beads 1× = 0.5
    assert np.allclose(fr2[n:, 3:], 0.0)

    assert not dyn.field_body_load(mesh, None, n, None).any()
    assert not dyn.field_body_load(mesh, None, n, {"field_pN": 0.0, "dir": [0, 1, 0]}).any()


def test_anchor_trap_diag_places_stiffness_on_anchor_translational_dof_only():
    """anchor_trap_diag puts the trap stiffness on the 3 translational DOF of each anchor node and
    nowhere else — rotational DOF, non-anchor nodes, and out-of-core indices all stay 0."""
    diag = dyn.anchor_trap_diag(5, 5, [1, 3], 7.0).reshape(5, 6)
    assert np.allclose(diag[1, :3], 7.0) and np.allclose(diag[1, 3:], 0.0)
    assert np.allclose(diag[3, :3], 7.0)
    for i in (0, 2, 4):
        assert np.allclose(diag[i], 0.0)
    # a tail / out-of-core node index (≥ n_core_nodes) is ignored — only core bp nodes can anchor
    assert not dyn.anchor_trap_diag(6, 5, [7], 7.0).any()
    assert not dyn.anchor_trap_diag(5, 5, [], 7.0).any()


@pytest.mark.slow
def test_field_with_anchor_deflects_free_region_along_field():
    """End-to-end: a uniform E-field + one anchored end deflects the FREE end along the field, and
    the deflection is BOUNDED (the anchor absorbs the net thrust). Without the anchor the same field
    would only drift the COM. Proves the field body load + stiff harmonic trap are wired into the
    Langevin loop and produce the static field response as the trajectory mean (project_snupi_dynamics)."""
    from backend.core.models import Direction
    from backend.physics.fem_solver import build_fem_mesh
    design = _routed_2hb()
    mesh = build_fem_mesh(design)
    bps = [n.global_bp for n in mesh.nodes]
    bp_min, bp_max = min(bps), max(bps)
    end = next(n for n in mesh.nodes if n.global_bp == bp_min)
    anchor = {"kind": "base", "helix_id": end.helix_id, "bp": end.global_bp,
              "direction": Direction.FORWARD.value}
    fdir = np.array([1.0, 0.0, 0.0])                     # transverse to the z-stacked helix axis
    out = dyn.simulate_equilibrium(
        design, material="snupi", field={"field_pN": 5.0, "dir": fdir.tolist()},
        anchors=[anchor], n_steps=24000, n_equil=6000, sample_every=20, seed=0)

    proj = (out["mean_u"].reshape(len(mesh.nodes), 6)[:, :3]) @ fdir
    assert np.isfinite(proj).all()
    anchor_idx = [i for i, n in enumerate(mesh.nodes) if n.global_bp == bp_min]
    free_idx = [i for i, n in enumerate(mesh.nodes) if n.global_bp == bp_max]
    assert abs(proj[anchor_idx].mean()) < proj[free_idx].mean()   # anchored end held, free end moves
    assert proj[free_idx].mean() > 0                              # …along +field
    assert np.abs(proj).max() < 50.0                              # bounded — no runaway COM drift
    assert out["anchor_keys"] == [[end.helix_id, end.global_bp]]
