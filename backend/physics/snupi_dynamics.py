"""SNUPI structural DYNAMICS — Langevin time-integration (Lee, Koh & Kim, *Nat Commun* 14:7079, 2023).

This is the dynamics engine bolted on top of the static SNUPI mimic (:mod:`snupi_material`,
:mod:`snupi_corotational`, :mod:`snupi_electrostatics`, :func:`fem_solver.assemble_global_stiffness`).
The static mimic gives one mean structure + a free-free NMA flexibility; this integrates the Langevin
equation of motion so you get an actual thermal TRAJECTORY:

    M V̇ = F − Z V + R ,   U̇ = V

with M the nodal mass matrix (:func:`fem_solver.assemble_mass_matrix`, G6), F the internal force
(elastic + electrostatic), Z the hydrodynamic friction matrix, and R a random force satisfying
fluctuation–dissipation ``⟨R(t)R(t')⟩ = 2 k_BT Z δ(t−t')``. Integrated with the Grønbech-Jensen–Farago
(GJF-2013) scheme — robust in the heavily overdamped regime DNA nodes live in (inertial relaxation
m/ζ ≈ 0.06 ps ≪ Δt = 5 ps) and provably samples the correct Boltzmann configuration distribution.

**Phase 1a scope (this module, first pass):** the GJF integrator + DIAGONAL Stokes friction +
UNCORRELATED noise, driven by the LINEAR assembled stiffness force ``F = −K·q``. The equilibrium
configuration distribution is friction-independent (Boltzmann ∝ exp(−U/k_BT) regardless of Z), so a
diagonal friction already gives the correct static covariance — which means the trajectory RMSF MUST
equal our free-free NMA RMSF (both sample k_BT·K⁻¹). That is the cheap, decisive validation gate
proving the integrator + unit system + fluctuation–dissipation are correct, before any hydrodynamics
(Phase 1b: full Rotne–Prager–Yamakawa Z + correlated noise) or the nonlinear corotational force /
base-stacking (Phase 2, needed only for large-amplitude reconfiguration). See
``memory/project_snupi_dynamics.md``.

**Unit system (nm · pN · ns).** We integrate in a consistent mixed system so the assembled stiffness
K and displacement q keep their NATURAL units (no per-block SI conversion of K):
  - length = nm, force = pN, energy = pN·nm, angle = rad, time = ns
  - k_BT = 4.142 pN·nm at 300 K (NB :data:`fem_solver.KBT` = 4.11 is the 298 K NMA value — distinct)
  - derived mass unit = pN·ns²/nm = 1e-21 kg (a bp ≈ 654 g/mol ≈ 1.086e-3 of these). So the G6 mass
    matrix (SI kg / kg·nm²) is scaled by :data:`MASS_G6_TO_DYN` = 1e21 to reach (mass_u / mass_u·nm²).
  - Stokes drag on a σ = 1.1 nm bead in water (η = 8.9e-4 Pa·s): translational ζ_t = 6πησ, rotational
    ζ_r = 8πησ³, converted N·s/m → pN·ns/nm (×1e12) and N·m·s → pN·nm·ns (×1e30).

Three-Layer Law: trajectories are PHYSICAL/display state only — never written back to topology/geometry.
"""
from __future__ import annotations

import math
from typing import Callable, List, Optional

import numpy as np

# ── Unit system / physical constants (nm · pN · ns) ─────────────────────────────
KBT_300 = 4.142          # pN·nm — thermal energy at 300 K (the paper's simulation temperature)
DT_DEFAULT = 0.005       # ns = 5 ps (the paper's time step)
ETA_WATER = 8.9e-4       # Pa·s — dynamic viscosity of water near 300 K (paper: 890 µN·s/m²)
HYDRO_RADIUS_NM = 1.1    # nm — per-node hydrodynamic radius σ (paper)
MASS_G6_TO_DYN = 1e21    # scales assemble_mass_matrix (kg / kg·nm²) → (mass_u / mass_u·nm²)

# Stokes drag constants in the nm·pN·ns system (traceable to η, σ; used for the diagonal friction).
_sigma_m = HYDRO_RADIUS_NM * 1e-9
STOKES_TRANS = 6.0 * math.pi * ETA_WATER * _sigma_m * 1e12          # pN·ns/nm  (N·s/m ×1e12)
STOKES_ROT = 8.0 * math.pi * ETA_WATER * _sigma_m**3 * 1e30         # pN·nm·ns  (N·m·s ×1e30)


def stokes_friction_diag(n_node: int) -> np.ndarray:
    """Per-DOF diagonal Stokes friction γ (6N,) — translational ζ_t on the 3 linear DOF, rotational
    ζ_r on the 3 angular DOF of every node. The isotropic single-bead approximation to the full RPY
    friction matrix (Phase 1b replaces this with the coupled ``Z``; the EQUILIBRIUM RMSF is identical
    for either, since the static covariance is friction-independent — only the kinetics change)."""
    g = np.empty(6 * n_node, dtype=float)
    g.reshape(n_node, 6)[:, :3] = STOKES_TRANS
    g.reshape(n_node, 6)[:, 3:] = STOKES_ROT
    return g


# ── GJF-2013 Langevin integrator (diagonal m, γ; generic force) ─────────────────

def gjf_integrate(
    force_fn: Callable[[np.ndarray], np.ndarray],
    q0: np.ndarray,
    m: np.ndarray,
    gamma: np.ndarray,
    *,
    kT: float = KBT_300,
    dt: float = DT_DEFAULT,
    n_steps: int = 20000,
    n_equil: int = 4000,
    sample_every: int = 20,
    rng: Optional[np.random.Generator] = None,
    v0: Optional[np.ndarray] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
):
    """Grønbech-Jensen–Farago (2013) Langevin integrator over FLAT generalized coordinates.

    Solves ``m q̈ = f(q) − γ q̇ + β`` per DOF (diagonal ``m``, ``gamma`` arrays of length ndof),
    with the random impulse ``β`` ~ N(0, 2 γ k_BT Δt) — the discrete fluctuation–dissipation relation.
    GJF is the position–velocity form (Mol. Phys. 111:983, 2013): it reproduces the exact Boltzmann
    configuration distribution for ANY Δt in the diffusive regime, which is why the paper can use a
    5 ps step for DNA nodes whose inertial time is ~0.06 ps.

    ``force_fn(q) → f`` (same shape as ``q``). Returns ``(samples, v_final)`` where ``samples`` is
    ``(n_sample, ndof)`` — ``q`` snapshotted every ``sample_every`` steps after ``n_equil`` equilibration.
    """
    rng = np.random.default_rng() if rng is None else rng
    q = np.array(q0, dtype=float)
    v = np.zeros_like(q) if v0 is None else np.array(v0, dtype=float)
    m = np.asarray(m, dtype=float)
    gamma = np.asarray(gamma, dtype=float)

    half = gamma * dt / (2.0 * m)
    b = 1.0 / (1.0 + half)
    a = (1.0 - half) * b
    sig = np.sqrt(2.0 * gamma * kT * dt)      # std of the integrated random impulse per step

    f = force_fn(q)
    samples = []
    for step in range(n_steps):
        beta = rng.standard_normal(q.shape) * sig
        dq = b * dt * v + b * dt * dt / (2.0 * m) * f + b * dt / (2.0 * m) * beta
        q = q + dq
        f_new = force_fn(q)
        v = a * v + dt / (2.0 * m) * (a * f + f_new) + b / m * beta
        f = f_new
        if step >= n_equil and (step - n_equil) % sample_every == 0:
            samples.append(q.copy())
        if step % 500 == 0:
            if not np.isfinite(q).all():
                raise _GJFDiverged(
                    f"GJF diverged at step {step} (dt={dt} too large for the stiffest mode)")
            _report_progress(progress_cb, step, n_steps)
    return np.array(samples), v


def gjf_modified_integrate(
    force_fn: Callable[[np.ndarray], np.ndarray],
    q0: np.ndarray,
    m: np.ndarray,
    gamma: np.ndarray,
    *,
    kT: float = KBT_300,
    dt: float = DT_DEFAULT,
    n_steps: int = 20000,
    n_equil: int = 4000,
    sample_every: int = 20,
    rng: Optional[np.random.Generator] = None,
    v0: Optional[np.ndarray] = None,
):
    """The paper's MODIFIED GJF integrator (Lee/Koh/Kim 2023, Supplementary Note 4) — half-time
    stepping + Simpson's rule on the internal force, which WIDENS the stable step region (empirically
    ~6× here: plain :func:`gjf_integrate` caps ~0.17 ps on a stiff 2HB, this reaches ~1 ps at correct
    sampling). Reproduces the paper's harmonic validation (SI §4.4 conditions i–iv, ΩΔt/2 ≤ 1.5) exactly.
    Reaching the paper's flat **5 ps** on an arbitrary design additionally requires the stiffest
    generalized modes to be soft enough (γ/2Ω large, ΩΔt/2 < ~2 — the overdamped DNA regime the paper
    targets); designs with ultra-stiff CanDo crossover rigid-links need those constrained/softened first
    (the paper's future 'constrained Langevin'). Diagonal (Stokes) friction: ``m``, ``gamma``(=ζ) per-DOF.

    Per step (SI §4.3), carrying the internal force ``f^t = F(U^t)/m`` from the previous step:
      1. half-time coordinate  U^{t+½} = U^t + Δt·j·(½V + ⅛f^t + ¼θ^{½})          (4.31)
      2. evaluate f^{t+½} = F(U^{t+½})/m                                          (the Simpson midpoint)
      3. full-step coordinate  U^{t+1} = U^t + Δt·b·(V + ½f^{t+½} + ½θ^{1})        (4.32)
      4. evaluate f^{t+1} = F(U^{t+1})/m
      5. velocity  V^{t+1} = a·V + (Δt/6)(f^{t+1} + 2(a+b)f^{t+½} + f^t) + b·θ^{1}  (4.34)
    with ``j=(I+Δtγ̄/4)⁻¹``, ``b=(I+Δtγ̄/2)⁻¹``, ``a=2b−1`` (γ̄=γ/m), and independent random impulses
    ``θ^{½}=β^{½}/m`` (var ⟨ββ⟩=2kTζ·Δt/2) and ``θ^{1}=β^{1}/m`` (var 2kTζ·Δt). The full-step force uses
    the Simpson quadrature ``∫_t^{t+Δt}F ≈ Δt·F^{t+½}`` (4.28) — the midpoint evaluation is what buys
    the stability. Costs 2 force evals/step vs 1 for plain GJF, but the ~10× larger dt is a net win.

    Reduces to the original GJF (samples the exact Boltzmann distribution) — the paper proves the
    flat-potential and harmonic cases (SI §4.4). Returns ``(samples, v_final)`` like :func:`gjf_integrate`.
    """
    rng = np.random.default_rng() if rng is None else rng
    q = np.array(q0, dtype=float)
    v = np.zeros_like(q) if v0 is None else np.array(v0, dtype=float)
    m = np.asarray(m, dtype=float)
    gamma = np.asarray(gamma, dtype=float)

    gbar = gamma / m                                   # mass-normalized friction γ̄
    j = 1.0 / (1.0 + gbar * dt / 4.0)
    b = 1.0 / (1.0 + gbar * dt / 2.0)
    a = 2.0 * b - 1.0
    # Each HALF-step random impulse has variance ⟨ββ⟩ = k_BT·ζ·Δt (SI eq 4.7); the full-step impulse is
    # the SUM of the two half impulses (β^{Δt} = β^{[t,t+Δt/2]} + β^{[t+Δt/2,t+Δt]}, eq 4.5) → they SHARE
    # the first half (fluctuation–dissipation consistency), NOT independent draws.
    s_half = np.sqrt(gamma * kT * dt)                  # std of one half-step impulse β

    acc = force_fn(q) / m                              # a^t = M⁻¹F^t (accel); carried across steps
    samples = []
    for step in range(n_steps):
        b1 = s_half * rng.standard_normal(q.shape)     # first half impulse  β^{[t, t+Δt/2]}
        b2 = s_half * rng.standard_normal(q.shape)     # second half impulse β^{[t+Δt/2, t+Δt]}
        th_half = b1 / m                               # θ^{½} = M⁻¹β^{Δt/2}
        th_full = (b1 + b2) / m                        # θ^{1} = M⁻¹β^{Δt} = M⁻¹(β^{Δt/2}+·)
        # coordinate: the force enters via ∫F dt ≈ (Δt/2)F^t (4.27) → (Δt/8)·acc; θ is a velocity impulse
        q_half = q + dt * j * (0.5 * v + (dt / 8.0) * acc + 0.25 * th_half)
        acc_half = force_fn(q_half) / m                # the Simpson MIDPOINT accel — buys the stability
        # full-step force via Simpson ∫F dt ≈ Δt·F^{t+½} (4.28) → (Δt/2)·acc_half
        q_new = q + dt * b * (v + (dt / 2.0) * acc_half + 0.5 * th_full)
        acc_new = force_fn(q_new) / m
        v = a * v + (dt / 6.0) * (acc_new + 2.0 * (a + b) * acc_half + acc) + b * th_full
        q = q_new
        acc = acc_new
        if step >= n_equil and (step - n_equil) % sample_every == 0:
            samples.append(q.copy())
        if step % 500 == 0 and not np.isfinite(q).all():
            raise _GJFDiverged(f"modified GJF diverged at step {step} (dt={dt})")
    return np.array(samples), v


class _GJFDiverged(RuntimeError):
    """Raised when the explicit GJF step exceeds the stiff-mode stability limit."""


# Share of the progress bar given to the friction/setup phase before the trajectory starts stepping.
# The dt auto-sizing eigsh + the friction build are genuinely slow at scale, so the bar must not sit
# at 0% through them; but the trajectory dominates, so keep the slice small.
_SETUP_FRACTION = 0.10


def _report_progress(cb: Optional[Callable[[float, int], None]], step: int, n_steps: int) -> None:
    """Report the trajectory fraction + step index to an optional callback. REAL progress, not a
    wall-clock guess: the dynamics run is a fixed number of GJF steps, so ``step/n_steps`` is exactly
    how far along we are. The runner turns this into the panel's percentage and a ``worker.log``
    heartbeat (see ``snupi_runner.solve_and_cache``).

    Never let a reporting failure kill a multi-minute solve — the callback writes a file."""
    if cb is None:
        return
    try:
        cb(min(1.0, step / max(1, n_steps)), step)
    except Exception:                                  # pragma: no cover — progress is best-effort
        pass


# ── Operator (structured) friction — no dense 6N×6N anywhere ────────────────────

def gjf_integrate_operator_friction(
    force_fn: Callable[[np.ndarray], np.ndarray],
    q0: np.ndarray,
    m_diag: np.ndarray,
    fric,
    *,
    kT: float = KBT_300,
    dt: float = DT_DEFAULT,
    n_steps: int = 20000,
    n_equil: int = 4000,
    sample_every: int = 20,
    rng: Optional[np.random.Generator] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
):
    """GJF Langevin with a friction supplied as an OPERATOR rather than a dense matrix — the route that
    makes origami-scale hydrodynamics fit in RAM.

    ``fric`` is a :class:`backend.physics.snupi_hydro_coarse.CoarseFriction` (or anything exposing
    ``apply_Ztilde(x)``, ``apply_b_inv(x, dt)`` and ``sample_beta(kT, dt, rng)``). Nothing 6N×6N is ever
    formed — cf. :func:`gjf_integrate_matrix_friction`, which needs the full eigendecomposition of Z̃.

    We integrate in MASS-WEIGHTED coordinates ``q̃ = M^{1/2} q``, where the equation becomes unit-mass
    with symmetric friction ``Z̃ = M^{-1/2} Z M^{-1/2}``. The GJF update is then the direct matrix
    analogue of the scalar one, with every operator symmetric (so the orderings that bite in the
    unsymmetric ``γ = M⁻¹Z`` form cannot):

        b = (I + Δt·Z̃/2)⁻¹                a = (I − Δt·Z̃/2)·b
        Δq̃ = b·[Δt·ṽ + (Δt²/2)·f̃ + (Δt/2)·β̃]
        ṽ  = a·ṽ + (Δt/2)·(a·f̃ + f̃_new) + b·β̃ ,     ⟨β̃β̃ᵀ⟩ = 2 k_BT Δt Z̃

    Setting Z̃ = diag(γ) and M = I reduces this LINE FOR LINE to the validated :func:`gjf_integrate`
    (m = 1), which is how its correctness is inherited. Returns ``(samples_q, v_final)`` in PHYSICAL
    coordinates."""
    rng = np.random.default_rng() if rng is None else rng
    m_diag = np.asarray(m_diag, dtype=float)
    m_half, minv_half = np.sqrt(m_diag), 1.0 / np.sqrt(m_diag)

    fric.prepare_gjf(dt)

    def force_tilde(qt):
        return minv_half * force_fn(minv_half * qt)

    qt = m_half * np.asarray(q0, dtype=float)
    vt = np.zeros_like(qt)
    ft = force_tilde(qt)

    def apply_a(x):
        bx = fric.apply_b_inv(x, dt)
        return bx - 0.5 * dt * fric.apply_Ztilde(bx)

    samples = []
    for step in range(n_steps):
        beta = fric.sample_beta(kT, dt, rng)
        qt = qt + fric.apply_b_inv(dt * vt + (0.5 * dt * dt) * ft + (0.5 * dt) * beta, dt)
        ft_new = force_tilde(qt)
        vt = apply_a(vt) + 0.5 * dt * (apply_a(ft) + ft_new) + fric.apply_b_inv(beta, dt)
        ft = ft_new
        if step >= n_equil and (step - n_equil) % sample_every == 0:
            samples.append(minv_half * qt)
        if step % 500 == 0:
            if not np.isfinite(qt).all():
                raise _GJFDiverged(
                    f"GJF diverged at step {step} (dt={dt} too large for the stiffest mode)")
            _report_progress(progress_cb, step, n_steps)
    return np.array(samples), minv_half * vt


# ── Matrix (hydrodynamic) friction via a mass-weighted eigen-transform ──────────

def gjf_integrate_matrix_friction(
    force_fn: Callable[[np.ndarray], np.ndarray],
    q0: np.ndarray,
    m_diag: np.ndarray,
    Z: np.ndarray,
    *,
    kT: float = KBT_300,
    dt: float = DT_DEFAULT,
    n_steps: int = 20000,
    n_equil: int = 4000,
    sample_every: int = 20,
    rng: Optional[np.random.Generator] = None,
    progress_cb: Optional[Callable[[float], None]] = None,
):
    """GJF Langevin with a FULL (coupled) friction matrix ``Z`` — the hydrodynamic case (Phase 1b).

    The matrix Langevin ``M q̈ = f − Z q̇ + β`` (⟨ββᵀ⟩ = 2 k_BT Z Δt) diagonalises exactly in the
    mass-weighted, friction-eigen basis: with ``q̃ = M^{1/2} q`` and ``Z̃ = M^{-1/2} Z M^{-1/2} = U Λ Uᵀ``,
    the coordinate ``p = Uᵀ q̃`` obeys a set of INDEPENDENT unit-mass scalar Langevin equations with
    per-mode friction ``Λ_i``. So the full-matrix GJF reduces to the validated diagonal
    :func:`gjf_integrate` (m = 1, γ = Λ) applied in this basis — the correlated noise is produced
    automatically (diagonal in ``p``, hence colored by ``Z`` in physical coordinates), and correctness
    is inherited from the diagonal integrator. ``Z``/``M`` are configuration-independent, so ``U, Λ``
    are precomputed once. Returns ``(samples_q, v_final)`` with ``samples_q`` in PHYSICAL coordinates.
    """
    m_diag = np.asarray(m_diag, dtype=float)
    minv_half = 1.0 / np.sqrt(m_diag)
    Ztil = (minv_half[:, None] * Z) * minv_half[None, :]
    Ztil = 0.5 * (Ztil + Ztil.T)
    lam, U = np.linalg.eigh(Ztil)
    lam = np.clip(lam, 1e-12 * float(lam.max()), None)     # SPD → all > 0; guard round-off

    def force_p(p):
        q = minv_half * (U @ p)
        return U.T @ (minv_half * force_fn(q))

    p0 = U.T @ (np.asarray(q0, float) / minv_half)         # p = Uᵀ M^{1/2} q
    samples_p, v = gjf_integrate(
        force_p, p0, np.ones_like(m_diag), lam,
        kT=kT, dt=dt, n_steps=n_steps, n_equil=n_equil, sample_every=sample_every, rng=rng,
        progress_cb=progress_cb,
    )
    samples_q = (samples_p @ U.T) * minv_half[None, :]     # p → q = M^{-1/2} U p, per row
    return samples_q, v


# ── Rigid-body removal + trajectory RMSF ────────────────────────────────────────

def _kabsch(P: np.ndarray, Q: np.ndarray) -> np.ndarray:
    """Rotation R (3×3) best-aligning centered P onto centered Q (min ‖R·P − Q‖). Both (N,3)."""
    H = P.T @ Q
    U, _s, Vt = np.linalg.svd(H)
    d = np.sign(np.linalg.det(Vt.T @ U.T))
    Dm = np.diag([1.0, 1.0, d])
    return Vt.T @ Dm @ U.T


def trajectory_rmsf(frames: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Per-node RMSF (nm) from a stack of absolute-position frames ``(n_frame, N, 3)``, after
    removing rigid-body translation+rotation of each frame (Kabsch-aligned to ``ref``) — the same
    treatment the MD RMSF pipeline uses, and the correct comparison to free-free NMA (which projects
    out the 6 rigid modes). ``ref`` (N,3) is the reference config (typically the mean or X0)."""
    ref_c = ref - ref.mean(axis=0)
    aligned = np.empty_like(frames)
    for k, fr in enumerate(frames):
        fc = fr - fr.mean(axis=0)
        aligned[k] = fc @ _kabsch(fc, ref_c).T
    mean = aligned.mean(axis=0)
    var = ((aligned - mean) ** 2).sum(axis=2).mean(axis=0)   # <|Δr_i|²> per node
    return np.sqrt(var)


def corotational_internal_force(q: np.ndarray, X0: np.ndarray, elements) -> np.ndarray:
    """Nonlinear corotational INTERNAL elastic force ``f_int(q)`` (6N) — the Phase-2 drop-in for the
    linear ``K·q`` in the Langevin loop (exact under LARGE rotations, the point of a reconfiguration
    switch).

    ``q`` = 6N generalized displacement ``[Δu; θ]`` per node from the rest config ``X0`` (N,3): node
    positions ``X = X0 + Δu`` and orientations ``R = exp(θ)``. ``elements`` = the corotational beam list
    ``[(i, j, ref, K12), ...]`` from :func:`fem_solver.build_corotational_elements`. The consistent
    internal force is assembled per element by :func:`snupi_corotational._internal_force`, whose EICR
    corotational filter removes rigid-body motion (rigid ``q`` ⇒ ``d_local = 0`` ⇒ zero force for ANY
    stiffness). For small ``q`` it reduces to the linear tangent ``K·q``. The driver's total force is
    ``f_ext − corotational_internal_force(q, X0, elements)`` — matching the linear ``f_ext − K·q``.
    """
    from backend.physics.snupi_corotational import _internal_force, exp_so3
    X0 = np.asarray(X0, dtype=float)
    N = len(X0)
    qn = np.asarray(q, dtype=float).reshape(N, 6)
    X = X0 + qn[:, :3]
    R = [exp_so3(qn[n, 3:6]) for n in range(N)]
    f_int = np.zeros(6 * N)
    for (i, j, ref, K12) in elements:
        fg = _internal_force(X[i], X[j], R[i], R[j], ref, K12)
        f_int[6 * i:6 * i + 6] += fg[:6]
        f_int[6 * j:6 * j + 6] += fg[6:]
    return f_int


def _align_to_ref(frames: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Kabsch-align each frame (N,3) onto ``ref`` (N,3), removing rigid-body translation+rotation.
    Returns the centred, rotation-aligned frame stack (F,N,3) — the internal-deformation part."""
    ref_c = ref - ref.mean(axis=0)
    aligned = np.empty_like(frames)
    for k, fr in enumerate(frames):
        fc = fr - fr.mean(axis=0)
        aligned[k] = fc @ _kabsch(fc, ref_c).T
    return aligned


def breathing_mode_pca(
    frames: np.ndarray,
    ref: np.ndarray,
    node_mass_trans: np.ndarray,
    *,
    kT: float = KBT_300,
    n_modes: int = 3,
) -> dict:
    """Principal-component (quasi-harmonic) analysis of an equilibrium trajectory → the dominant
    collective **breathing / bending modes**: shape, thermal amplitude, and natural frequency
    (the paper's Fig 3c/d low-frequency mode).

    PCA of equilibrium thermal fluctuations recovers the softest normal modes: the highest-variance
    fluctuation direction is the lowest-stiffness (lowest-frequency) collective motion — the breathing
    mode. Rigid-body translation+rotation are removed per frame (Kabsch to ``ref``) so only internal
    deformation is analysed.

    Args:
        frames: ``(F,N,3)`` absolute node positions from :func:`simulate_equilibrium`.
        ref: ``(N,3)`` reference config (``positions0`` / X0, or the mean shape).
        node_mass_trans: ``(N,)`` per-node translational mass in the module's dyn units
            (``pN·ns²/nm``) — e.g. ``mass_diag.reshape(N,6)[:,0]`` from the sim output.
        kT: thermal energy in pN·nm (default 300 K).
        n_modes: how many leading modes to return.

    For each mode i (variance-ranked): unit shape ``vᵢ`` (N,3), thermal variance ``σᵢ² = ⟨ξᵢ²⟩`` (nm²),
    equipartition effective stiffness ``kᵢ = k_BT/σᵢ²`` (pN/nm, from ``½kᵢ⟨ξᵢ²⟩ = ½k_BT``), mode
    effective mass ``mᵢ = vᵢᵀ diag(m_trans) vᵢ``, angular frequency ``ωᵢ = √(kᵢ/mᵢ)`` (1/ns) and
    natural frequency ``fᵢ = ωᵢ/2π`` (GHz).
    """
    frames = np.asarray(frames, dtype=float)
    ref = np.asarray(ref, dtype=float)
    F, N, _ = frames.shape
    aligned = _align_to_ref(frames, ref)
    disp = (aligned - aligned.mean(axis=0)).reshape(F, 3 * N)   # mean-centred fluctuations (F,3N)
    # Thin SVD of the F×3N fluctuation matrix — at most F−1 nonzero modes; avoids the 3N×3N covariance.
    _U, S, Vt = np.linalg.svd(disp, full_matrices=False)
    var_all = (S ** 2) / max(F - 1, 1)                          # per-mode fluctuation variance (nm²)
    m3 = np.repeat(np.asarray(node_mass_trans, dtype=float), 3)  # per-DOF translational mass (3N,)
    modes = []
    for i in range(min(n_modes, len(S))):
        sig2 = float(var_all[i])
        if sig2 <= 0.0:
            break
        v = Vt[i]                                               # unit 3N shape
        k_eff = kT / sig2                                       # pN/nm
        m_eff = float(v @ (m3 * v))                             # pN·ns²/nm
        omega = math.sqrt(max(k_eff / m_eff, 0.0))             # 1/ns
        modes.append({
            "shape": v.reshape(N, 3),                          # unit per-node displacement direction
            "variance_nm2": sig2,
            "amplitude_nm": math.sqrt(sig2),                   # RMS thermal amplitude of the mode
            "k_eff_pN_per_nm": float(k_eff),
            "m_eff": m_eff,
            "omega_per_ns": float(omega),
            "freq_GHz": float(omega / (2.0 * math.pi)),
        })
    return {"modes": modes, "variance_all": var_all}


def dynamics_dccm(frames: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Equal-time bp–bp displacement cross-correlation matrix (DCCM, N×N) from a trajectory frame
    stack ``(F,N,3)`` Kabsch-aligned to ``ref`` (rigid body removed). Entry (i,j) is the Pearson of
    the per-node displacement dot-products ``⟨Δrᵢ·Δrⱼ⟩/(σᵢσⱼ)`` — the same 'shape of motion' observable
    as the MD and free-free NMA DCCM (:func:`fem_solver.compute_correlation_matrix`), so the three are
    directly comparable on matched (helix, bp) keys.

    NOTE: this equal-time correlation is the normalized ``k_BT·K⁻¹`` covariance and is therefore
    **friction-independent** — Stokes and RPY give the same DCCM. It validates that the dynamics engine
    reproduces the NMA/MD motion topology, but the quantity hydrodynamics actually changes is kinetic:
    use :func:`mode_autocorr_time_ns` for the mode relaxation time.
    """
    frames = np.asarray(frames, dtype=float)
    aligned = _align_to_ref(frames, np.asarray(ref, dtype=float))
    disp = aligned - aligned.mean(axis=0)                    # (F,N,3) mean-centred fluctuations
    F = disp.shape[0]
    cov = np.einsum("fik,fjk->ij", disp, disp) / F           # ⟨Δrᵢ·Δrⱼ⟩ (dot over xyz)
    d = np.sqrt(np.clip(np.diag(cov), 1e-30, None))
    return np.clip(cov / np.outer(d, d), -1.0, 1.0)


def mode_coordinate(frames: np.ndarray, ref: np.ndarray, mode_shape: np.ndarray) -> np.ndarray:
    """Scalar mode coordinate ``ξ(t) = Σᵢ shapeᵢ · Δrᵢ(t)`` per frame — the projection of the
    rigid-body-aligned displacement onto a unit mode shape ``(N,3)`` (e.g. a PCA breathing mode).
    Returns a ``(F,)`` time series (nm)."""
    aligned = _align_to_ref(np.asarray(frames, dtype=float), np.asarray(ref, dtype=float))
    disp = aligned - np.asarray(ref, dtype=float)
    return np.einsum("fik,ik->f", disp, np.asarray(mode_shape, dtype=float))


def mode_autocorr_time_ns(coord: np.ndarray, dt_ns: float) -> float:
    """Integrated autocorrelation time (ns) of a scalar mode-coordinate time series ``coord`` sampled
    at spacing ``dt_ns``. ``τ = dt·(1 + 2·Σ_{k≥1} ρ_k)`` truncated at the first non-positive ρ_k (the
    standard initial-positive-sequence estimator). This is the mode's relaxation time — the KINETIC
    quantity that hydrodynamic coupling (RPY vs diagonal Stokes) changes, unlike the equal-time
    variance which is friction-independent."""
    x = np.asarray(coord, dtype=float)
    x = x - x.mean()
    n = len(x)
    var = float(x @ x / n)
    if var <= 0.0 or n < 4:
        return 0.0
    tau = 1.0
    for k in range(1, n):
        rho = float((x[: n - k] @ x[k:]) / (n - k)) / var
        if rho <= 0.0:
            break
        tau += 2.0 * rho
    return float(dt_ns * tau)


# ── Phase 2: base-stacking force composer + salt-driven reconfiguration driver ──

def stacking_force_all(positions_flat: np.ndarray, pairs, prm=None) -> np.ndarray:
    """Assemble the total Morse base-stacking force into a flat 6N vector (translational DOF).

    ``positions_flat`` is the flat generalized-coordinate vector whose ``[6i:6i+3]`` slots are node
    i's ABSOLUTE position (nm); ``pairs`` = list of ``(i, j)`` stacking bonds. Returns the applied
    stacking force (pN) on every DOF (rotational slots stay 0). See :mod:`snupi_stacking`."""
    from backend.physics import snupi_stacking as stk
    prm = stk.MorseParams() if prm is None else prm
    q = np.asarray(positions_flat, float)
    f = np.zeros_like(q)
    for (i, j) in pairs:
        xi = q[6 * i:6 * i + 3]
        xj = q[6 * j:6 * j + 3]
        fi, fj = stk.stacking_force(xi, xj, prm)
        f[6 * i:6 * i + 3] += fi
        f[6 * j:6 * j + 3] += fj
    return f


def bond_lengths(positions_flat: np.ndarray, pairs) -> np.ndarray:
    """Current length (nm) of each stacking bond in ``pairs`` — the switch state diagnostic
    (near r₀ ⇒ stacked/closed; large ⇒ unstacked/open)."""
    q = np.asarray(positions_flat, float)
    return np.array([float(np.linalg.norm(q[6 * j:6 * j + 3] - q[6 * i:6 * i + 3]))
                     for (i, j) in pairs])


def simulate_reconfiguration(
    q0: np.ndarray,
    force_fn,
    schedule,
    m_diag: np.ndarray,
    gamma_diag: np.ndarray,
    *,
    stacking_pairs=None,
    kT: float = KBT_300,
    dt: float = DT_DEFAULT,
    sample_every: int = 20,
    seed: int = 0,
):
    """Drive an ion-responsive reconfiguration by running Langevin dynamics through a SALT SCHEDULE.

    The switch (paper Fig 6) closes/opens as the Mg²⁺ concentration changes: the base-stacking Morse
    bonds hold it closed, and the salt-dependent inter-helix electrostatic repulsion (which grows as
    salt drops → longer Debye length) competes to pop the stacks and open it. This driver integrates
    the SAME structure across a sequence of salt segments, carrying position + velocity between them.

    ``force_fn(q, salt) → f`` is the composed force at a given Mg²⁺ molarity (elastic + Morse stacking
    :func:`stacking_force_all` + Debye–Hückel electrostatics at ``salt``). ``schedule`` is a list of
    ``{"label", "salt", "n_steps"}`` segments. ``q0`` is the initial (closed) generalized-coordinate
    vector (absolute node positions in the translational slots). Returns per-segment frames + the
    mean stacking-bond length (the open/closed state) so the transition can be visualized/quantified.
    """
    q = np.array(q0, dtype=float)
    v = np.zeros_like(q)
    m_diag = np.asarray(m_diag, float)
    gamma_diag = np.asarray(gamma_diag, float)
    rng = np.random.default_rng(seed)
    segments = []
    for seg in schedule:
        salt = float(seg["salt"])
        n_steps = int(seg["n_steps"])

        def seg_force(qq, _salt=salt):
            return force_fn(qq, _salt)

        samples, v = gjf_integrate(
            seg_force, q, m_diag, gamma_diag,
            kT=kT, dt=dt, n_steps=n_steps, n_equil=max(0, n_steps // 5),
            sample_every=sample_every, rng=rng, v0=v,
        )
        if len(samples):
            q = samples[-1].copy()          # continue from the last sampled config
        bl = None
        if stacking_pairs is not None and len(samples):
            bl = np.array([bond_lengths(fr, stacking_pairs) for fr in samples])
        segments.append({
            "label": seg.get("label", ""),
            "salt": salt,
            "frames": samples,
            "bond_lengths": bl,
            "mean_bond_length": float(bl.mean()) if bl is not None and bl.size else None,
        })
    return {"segments": segments, "q_final": q}


# ── E-field body load + anchor traps (project_oxdna_efield, project_snupi_dynamics) ──

#: Anchor-trap stiffness is set to this multiple of the largest diagonal stiffness in K, so the
#: restraint is reliably rigid relative to the SOFT arm-deflection mode (orders of magnitude below
#: the stiffest local mode) while barely moving the step-size ceiling (dt ~ 1/√k of the stiffest
#: mode, which the trap only matches to within √FACTOR). A stiff harmonic trap mirrors oxDNA's
#: `trap` anchor (stiff=1000), so the two engines are driven by comparable anchoring.
ANCHOR_TRAP_FACTOR = 2.0


def field_body_load(mesh, block, n_tot: int, field: Optional[dict]) -> np.ndarray:
    """Per-DOF uniform-E-field body load (pN, global) over the FULL core+tail DOF vector.

    The same per-nucleotide force oxDNA applies (``project_oxdna_efield``): a core duplex bp node
    carries two backbones → ``2·field_pN·dir_hat`` (via :func:`fem_solver.assemble_field_force`,
    ``FEM_FIELD_CHARGES_PER_NODE=2``); each FREE ssDNA tail bead is ONE nucleotide → ``1·field_pN``.
    Translational DOF only (a pure body force, no couple). ``None`` / zero magnitude → a zero vector.

    Returns a length-``6*n_tot`` vector; the caller adds it to ``f_ext``. Pure (no integration).
    """
    from backend.physics.fem_solver import assemble_field_force
    f = np.zeros(6 * n_tot, dtype=float)
    core = assemble_field_force(mesh, field)            # 6*n_core, already 2·field_pN·dir_hat
    f[: core.shape[0]] = core
    if block is not None and field:
        mag = float(field.get("field_pN", 0.0) or 0.0)
        direction = np.asarray(field.get("dir") or (0.0, 0.0, 0.0), dtype=float)
        dnorm = float(np.linalg.norm(direction))
        if mag != 0.0 and dnorm > 1e-12:
            tvec = mag * (direction / dnorm)           # one nucleotide → 1× per tail bead
            n = len(mesh.nodes)
            for j in range(block.n_tail):
                f[6 * (n + j): 6 * (n + j) + 3] += tvec
    return f


def anchor_trap_diag(n_tot: int, n_core_nodes: int, fixed_nodes, k_anchor: float) -> np.ndarray:
    """Diagonal harmonic-trap stiffness (pN/nm) on the translational DOF of each anchor node.

    A stiff restraint that holds the anchor nodes near rest (∼ oxDNA ``trap``): without it a uniform
    field applies the SAME force to every node → pure rigid COM drift and ZERO internal deflection.
    The trap lets the free region deflect while the anchor absorbs the net thrust. Rotational DOF and
    every non-anchor DOF get 0 (a single anchor node still leaves the arm free to pivot about it —
    the joint). Only core nodes can be anchored (tails have no anchor scope). Pure (no integration).
    """
    diag = np.zeros(6 * n_tot, dtype=float)
    for node in (fixed_nodes or ()):
        if 0 <= node < n_core_nodes:
            diag[6 * node: 6 * node + 3] = k_anchor
    return diag


# ── High-level: equilibrium dynamics of a design (linear force, Phase 1a) ────────

def simulate_equilibrium(
    design,
    *,
    material: str = "snupi",
    with_electrostatics: bool = False,
    hydrodynamics: bool = False,
    field: Optional[dict] = None,
    anchors: Optional[List[dict]] = None,
    mgcl2_M: Optional[float] = None,
    temperature_K: float = 300.0,
    dt: Optional[float] = None,
    n_steps: int = 20000,
    n_equil: int = 4000,
    sample_every: int = 20,
    seed: int = 0,
    nonlinear_force: bool = False,
    modified_gjf: bool = False,
    hydro_coarse_bp: Optional[int] = None,
    hydro_generalized: bool = False,
    tails: bool = False,
    tail_max_nt: Optional[int] = None,
    progress_cb: Optional[Callable[[float, str], None]] = None,
) -> dict:
    """Run an equilibrium Langevin trajectory of ``design`` and return frames + trajectory RMSF.

    ``dt`` (ns) defaults to ``None`` → auto-sized to 40% of the plain-GJF overdamped stability limit
    ``2 γ_min / λ_max(K)`` (capped at :data:`DT_DEFAULT` = 5 ps for soft designs). The stiffest local
    modes (12EI/L³ at the 0.34 nm bp spacing) cap plain-GJF at ~1–2 ps here; the paper's flat 5 ps
    needs their MODIFIED GJF (half-time stepping + Simpson's rule, Supp Note 4) — a Phase-2 follow-up.
    The validation gate (trajectory RMSF == NMA RMSF) is dt-independent for any stable step, since GJF
    samples the exact Boltzmann configuration distribution regardless of Δt.

    Phase 1a: the internal force is the LINEAR assembled stiffness, ``F = −K·q`` (K from
    :func:`fem_solver.assemble_global_stiffness` for the chosen ``material``, optionally + the
    inter-helix Debye–Hückel PD tangent when ``with_electrostatics``). This is the correct force
    model for the small-amplitude EQUILIBRIUM regime of a well-formed bundle (thermal fluctuations
    keep it linear); the nonlinear corotational force + base stacking (Phase 2) are only needed for
    large-amplitude reconfiguration. Because the equilibrium covariance is k_BT·K⁻¹, the returned
    ``rmsf`` must agree with :func:`fem_solver.compute_rmsf_nma` on the same K — the validation gate.

    ``hydrodynamics`` (Phase 1b) swaps the diagonal Stokes drag for the Rotne–Prager–Yamakawa friction
    matrix Z (:func:`snupi_hydrodynamics.friction_matrix`) + correlated noise, integrated by
    :func:`gjf_integrate_matrix_friction`. The EQUILIBRIUM RMSF is unchanged (friction-independent);
    RPY only alters the kinetics + dynamic cross-correlations.

    **Hydrodynamics is memory-bound — pick a mode.** Z is dense and O(N²): measured peak ≈ 1.5e-6·N² GB,
    so a full M13 origami (N ≈ 7240) wants ≈ 79 GB. :func:`snupi_hydrodynamics.check_friction_memory`
    preflights this and REFUSES rather than let the OOM killer take the machine.

    * ``hydro_coarse_bp=k`` — the coarse blob model (:mod:`snupi_hydro_coarse`): one hydrodynamic bead
      per ``k`` bp, structured (diagonal-minus-low-rank) friction, integrated by
      :func:`gjf_integrate_operator_friction`. Nothing 6N×6N is ever formed, so origami scale fits
      (≈0.4 GB at k=8). This is the ONLY mode that runs a full-size design. ``k=1`` = the exact model.
    * ``hydro_generalized`` — use the FULL generalized RPY (rotation–translation + rotation–rotation
      coupling, SI Note 3.2) instead of translational-only. Paper-faithful; costs the 4× memory of a
      dense 6N×6N Z in the exact path (free in the coarse path, where the dense object is 6B×6B).

    ``field`` (the shared ``{"field_pN", "dir"}`` E-field descriptor, ``project_oxdna_efield``) adds
    the same uniform per-nucleotide force oxDNA applies as a constant dead body load — core bp nodes
    2×, free tail beads 1× (:func:`field_body_load`). The overdamped mean then satisfies
    ``K_eff·mean_u = f_ext``, i.e. the SAME static field response, so ``mean_u`` is the field deflection
    and the trajectory adds its (now correctly damped) thermal motion about it. ``anchors`` (the shared
    oxDNA anchor scopes, resolved by :func:`fem_solver.resolve_anchor_nodes`) hold the anchored nodes
    with a stiff harmonic trap (∼ oxDNA ``trap``). **A field needs ≥1 anchor** — without one the uniform
    force only drifts the COM and produces zero internal deflection (:func:`anchor_trap_diag`).

    ``tails`` (SS-2, ``material="snupi"`` only) adds the FREE ssDNA tails — overhangs, toeholds,
    dangling scaffold ends — as explicit one-bead-per-nucleotide Langevin chains hanging off their
    anchor base pairs (:mod:`snupi_tails`). **A documented NADOC extension: published SNUPI cannot
    represent a free tail at all**, having no distal base-pair node to connect to. The tails enter
    the force, mass and drag of THIS integrator only; they are absent from ``K``, from the static
    solve, and from the NMA, by decision (a floppy tail's near-zero eigenvalues would flood the
    200-mode RMSF basis). With ``hydrodynamics`` they also join the coarse blob set (SS-3), at their
    own smaller bead radius — which requires ``hydro_coarse_bp`` (the exact per-bp friction is
    single-radius). Consequently every core observable below is unchanged, and the tails are
    reported alongside rather than mixed in: ``frames``/``rmsf``/``positions0``/``helix_ids``/
    ``bp_indices``/``mean_u`` stay strictly duplex-core, and the tail beads arrive as
    ``tail_frames``/``tail_positions0``/``tail_nodes``. Downstream Kabsch fits therefore keep
    fitting on the core, which is what they must do. ``tail_max_nt`` optionally truncates each tail.

    Returns ``{positions0, frames, rmsf, helix_ids, bp_indices, n_frame, dt_ns, anchor_keys, friction, stiffness, mass_diag}``
    (positions in nm; frames are absolute node positions, rigid-body drift retained —
    :func:`trajectory_rmsf` removes it), plus the ``tail_*`` keys above when ``tails=True``.
    """
    from backend.physics.fem_solver import (
        build_fem_mesh,
        assemble_global_stiffness,
        assemble_mass_matrix,
        assemble_prestress_force,
        resolve_anchor_nodes,
        SNUPI_DEFAULT_MGCL2_M,
    )

    mesh = build_fem_mesh(design, material=material)
    n = len(mesh.nodes)
    X0 = np.array([node.position for node in mesh.nodes], dtype=float)

    K, _ = assemble_global_stiffness(
        mesh, material=material, bp_registered_frame=(material == "snupi")
    )
    K = K.tolil()
    # Loop/skip eigenstrain prestress — a self-equilibrated internal load, so it sets the MEAN
    # (equilibrium) shape without breaking the free-free fluctuation covariance (still k_BT·K⁻¹).
    f_ext = np.asarray(assemble_prestress_force(mesh, design), dtype=float)
    if with_electrostatics and material == "snupi":
        from backend.physics.fem_solver import _snupi_es_params, _snupi_electro_sparse
        prm = _snupi_es_params(SNUPI_DEFAULT_MGCL2_M if mgcl2_M is None else mgcl2_M)
        K_es, _f = _snupi_electro_sparse(mesh, X0, prm, axial_only=True)  # PD tangent (matches NMA)
        K = K + K_es.tolil()
    Kcsr = K.tocsr()

    M = assemble_mass_matrix(mesh, design)
    m_diag = np.asarray(M.tocsr().diagonal(), dtype=float) * MASS_G6_TO_DYN
    gamma = stokes_friction_diag(n)
    kT = KBT_300 * (temperature_K / 300.0)

    # ── Free ssDNA tails (SS-2) — dynamics-only, appended AFTER the core's DOF ────────
    block = None
    if tails:
        from backend.physics import snupi_tails as st
        if material != "snupi":
            raise ValueError(
                "free ssDNA tails are a snupi-only extension (material='snupi'); "
                f"got material={material!r}")
        if hydrodynamics and not hydro_coarse_bp:
            # The tails' drag lives in the COARSE blob model (SS-3, snupi_hydro_coarse): its blob set
            # takes both species, giving each its own bead radius (σ_ss = 0.5 nm vs σ = 1.1 nm for a
            # bp). The exact path would instead need an unequal-radius RPY tensor (Zuk 2014) — a
            # different tensor, with its own overlap regularizations — and it cannot run origami scale
            # anyway. Refuse rather than silently drop the tails' drag.
            raise ValueError(
                "hydrodynamics + free ssDNA tails needs the coarse blob model: pass "
                "hydro_coarse_bp=k (8 is the calibrated default). The exact per-bp friction does not "
                "support the tails' smaller hydrodynamic radius.")
        block = st.build_tail_block(design, mesh, max_nt=tail_max_nt)
        if block.n_tail == 0:
            block = None                       # no tails in this design — take the plain path

    n_tot = n if block is None else block.n_total
    q_start = np.zeros(6 * n_tot)
    if block is not None:
        X0 = np.vstack([X0, block.positions])
        m_diag = np.concatenate([m_diag, block.mass_diag()])
        gamma = np.concatenate([gamma, block.stokes_diag()])
        f_ext = np.concatenate([f_ext, np.zeros(6 * block.n_tail)])
        _touched = block.touched_nodes()
        # The tails start as thermal COILS, not rods (snupi_tails._coil_run): X0 already holds the
        # coiled positions, and q_start carries the bead triads that go with them. Starting straight
        # would strand every tail in a fully extended state that no affordable trajectory can relax
        # — collapsing a rod into a coil is precisely the slow long-wavelength mode.
        q_start[6 * n:] = block.q0

    # ── E-field body load + anchor traps (project_oxdna_efield) ────────────────────────
    # The field is a constant DEAD load added to f_ext (like the prestress): the overdamped mean
    # then satisfies K_eff·mean_u = f_ext, i.e. the SAME static field response, but with a stiff
    # harmonic trap standing in for the static solver's hard Dirichlet clamp. A field WITHOUT an
    # anchor only drifts the COM (uniform force ⇒ no internal strain); resolve anchors so the free
    # region actually deflects. Only core bp nodes can be anchored (tails have no anchor scope).
    f_ext = f_ext + field_body_load(mesh, block, n_tot, field)
    fixed_nodes, anchor_keys = (
        resolve_anchor_nodes(design, mesh, anchors) if anchors else ([], []))
    k_anchor = ANCHOR_TRAP_FACTOR * (float(np.max(np.abs(Kcsr.diagonal()))) or 1.0)
    k_anchor_diag = anchor_trap_diag(n_tot, n, fixed_nodes, k_anchor)
    has_anchor = bool(np.any(k_anchor_diag))

    if dt is None:
        if modified_gjf:
            # The modified GJF (Simpson midpoint force) has a much wider stable region than plain GJF,
            # so start from the paper's flat 5 ps; the divergence-guarded retry below halves it only if
            # the design's stiffest generalized mode still overshoots even the widened region.
            dt = DT_DEFAULT
        else:
            # Plain GJF inherits Verlet's step limit dt < 2/ω_max; ω_max is the largest GENERALIZED
            # frequency √λ of (K, M). 0.8/ω_max ≈ 0.4·(2/ω_max) leaves a stability margin.
            from scipy.sparse import diags
            from scipy.sparse.linalg import eigsh
            Md = diags(m_diag[:6 * n]).tocsr()          # K is core-only; so is its mass metric
            # Include the anchor trap: it is a stiff diagonal spring, so it can be the stiffest core
            # mode and must enter ω_max or the step overshoots it (surfacing only as a divergence retry).
            K_dt = (Kcsr + diags(k_anchor_diag[:6 * n])).tocsr() if has_anchor else Kcsr
            lam_g = float(eigsh(K_dt, k=1, M=Md, which="LM", return_eigenvectors=False)[0])
            omega_max = math.sqrt(max(lam_g, 1e-30))
            if block is not None:
                # The tails are not in K, so their stiffest mode is invisible to that eigensolve. A
                # stiff ssDNA link (EA = 710 pN on a 0.68 nm bond) on a light nucleotide bead is
                # comparable to the duplex core's stiffest mode, so it must enter the step sizing —
                # otherwise a tail-driven instability only ever surfaces as a divergence retry.
                omega_max = max(omega_max, st.tail_omega_max(block))
            dt = min(DT_DEFAULT, 0.8 / omega_max)

    if nonlinear_force:
        # Phase 2: the FULL nonlinear corotational internal force per step (exact under large rotations),
        # in place of the linear F=−K·q. Needed for large-amplitude reconfiguration/switching; for
        # small thermal fluctuations it reduces to the linear force (so the equilibrium RMSF is
        # unchanged). SLOW at origami scale — the per-step Python element loop is the target of the
        # Phase-2(d) F(x) perf rewrite. dt auto-sizing still uses the linear K tangent (same stiff modes).
        from backend.physics.fem_solver import build_corotational_elements
        _X0cr, _cr_elements = build_corotational_elements(mesh, X0[:n])

        def core_int(q):
            return corotational_internal_force(q[:6 * n], X0[:n], _cr_elements)
    else:
        def core_int(q):
            return Kcsr @ q[:6 * n]

    # The anchor trap is an extra diagonal spring −k_anchor_diag·q (a stiff harmonic restraint toward
    # rest). It is kept OUT of core_int / K so the elastic model is untouched, and out of the force_fn
    # entirely when no anchors are set — so the validated equilibrium path stays byte-for-byte as before.
    if block is None:
        if has_anchor:
            def force_fn(q):
                return f_ext - core_int(q) - k_anchor_diag * q
        else:
            def force_fn(q):
                return f_ext - core_int(q)
    else:
        # Hybrid force: the duplex core keeps its validated model (the linear K, or the
        # corotational element set), and the tails add their COROTATIONAL chain force on top. The
        # two overlap only at the anchor nodes, where the forces simply add — which is exactly how
        # the core comes to feel each tail's mass and drag.
        if has_anchor:
            def force_fn(q):
                f = f_ext - st.tail_internal_force(q, X0, block, _touched)
                f[:6 * n] -= core_int(q)
                f -= k_anchor_diag * q
                return f
        else:
            def force_fn(q):
                f = f_ext - st.tail_internal_force(q, X0, block, _touched)
                f[:6 * n] -= core_int(q)
                return f

    # Progress: the friction build is a real, non-trivial phase (a dense O((6N)³) factorisation, or
    # ~11 s even coarse at M13 scale), so give it its own slice of the bar rather than letting the
    # panel sit at 0% through it. The trajectory then fills the rest.
    def _phase(frac: float, label: str, info: Optional[dict] = None) -> None:
        if progress_cb is not None:
            try:
                progress_cb(frac, label, info or {})
            except Exception:                          # pragma: no cover — progress is best-effort
                pass

    Z = None
    coarse_fric = None
    if hydrodynamics:
        from backend.physics.snupi_hydrodynamics import check_friction_memory, friction_matrix
        # Preflight the O(N²) friction BEFORE allocating: a dense 6N×6N Z on a full-size origami wants
        # tens of GB and the OOM killer takes the user's editor, not just this job. The blob count is
        # the real B (helix fragmentation + tail chains push it above ⌈N/k⌉), so count it — it is O(N).
        nb = None
        if hydro_coarse_bp:
            from backend.physics.snupi_hydro_coarse import blob_count, build_coarse_friction
            nb = blob_count(mesh, hydro_coarse_bp, block)
        check_friction_memory(n_tot, hydro_coarse_bp, nb)
        _phase(0.0, "building hydrodynamic friction",
               {"n_nodes": n_tot, "coarse_bp": hydro_coarse_bp, "n_blobs": nb or n_tot})
        if hydro_coarse_bp:
            coarse_fric = build_coarse_friction(mesh, X0, m_diag, hydro_coarse_bp,
                                                generalized=hydro_generalized, block=block)
        else:
            Z = friction_matrix(X0, generalized=hydro_generalized)

    _phase(_SETUP_FRACTION, "trajectory", {"n_nodes": n, "n_steps": n_steps, "dt_ns": dt})

    # The trajectory occupies the remaining [_SETUP_FRACTION, 1] of the bar. `_attempt_box` carries
    # the divergence-retry index so the reported detail says WHY the step counter just reset to 0 —
    # a dt halving restarts the whole trajectory, which otherwise looks like the bar going backwards
    # (or, on the old time-based bar, like a run silently taking 2×/4× as long for no visible reason).
    _attempt_box = [0]

    traj_cb = None
    if progress_cb is not None:
        def traj_cb(f: float, step: int) -> None:                       # noqa: F811
            _phase(_SETUP_FRACTION + (1.0 - _SETUP_FRACTION) * f, "trajectory",
                   {"step": step, "n_steps": n_steps, "dt_ns": dt,
                    "n_nodes": n, "attempt": _attempt_box[0]})

    # Run with a divergence-guarded retry: if the auto/explicit dt still overshoots the stiffest
    # mode, halve and retry (up to 4×) so the run always completes at a stable step.
    samples = None
    for _attempt in range(4):
        _attempt_box[0] = _attempt
        if _attempt:
            # A retry throws away the whole trajectory and starts over at half the step — that is a
            # 2×/4× wall-clock hit, so SAY so rather than let the run just appear to take forever.
            _phase(_SETUP_FRACTION, "trajectory (restarted: dt halved after divergence)",
                   {"attempt": _attempt, "dt_ns": dt, "n_steps": n_steps, "n_nodes": n})
        rng = np.random.default_rng(seed)
        try:
            if coarse_fric is not None:
                samples, _v = gjf_integrate_operator_friction(
                    force_fn, q_start, m_diag, coarse_fric,
                    kT=kT, dt=dt, n_steps=n_steps, n_equil=n_equil,
                    sample_every=sample_every, rng=rng, progress_cb=traj_cb,
                )
            elif hydrodynamics:
                samples, _v = gjf_integrate_matrix_friction(
                    force_fn, q_start, m_diag, Z,
                    kT=kT, dt=dt, n_steps=n_steps, n_equil=n_equil,
                    sample_every=sample_every, rng=rng, progress_cb=traj_cb,
                )
            elif modified_gjf:
                samples, _v = gjf_modified_integrate(
                    force_fn, q_start, m_diag, gamma,
                    kT=kT, dt=dt, n_steps=n_steps, n_equil=n_equil,
                    sample_every=sample_every, rng=rng,
                )
            else:
                samples, _v = gjf_integrate(
                    force_fn, q_start, m_diag, gamma,
                    kT=kT, dt=dt, n_steps=n_steps, n_equil=n_equil,
                    sample_every=sample_every, rng=rng, progress_cb=traj_cb,
                )
            break
        except _GJFDiverged:
            dt *= 0.5
    if samples is None:
        raise _GJFDiverged("GJF failed to stabilise after halving dt 4×")

    disp_all = samples.reshape(len(samples), n_tot, 6)[:, :, :3]   # translational disp per frame
    frames_all = X0[None, :, :] + disp_all
    # Everything below the tail block is reported on the DUPLEX CORE ONLY, byte-for-byte as before:
    # `frames`, `rmsf`, `mean_u`, `positions0` are (…, n, …). Mixing tail beads into them would put
    # floppy, badly-placed points into every downstream Kabsch fit and RMSF comparison — the exact
    # bug the VoltronCore DISPLAY fix had to undo. The tails are reported separately.
    disp = disp_all[:, :n, :]
    frames = frames_all[:, :n, :]
    rmsf = trajectory_rmsf(frames, X0[:n])
    mean_u = np.zeros(6 * n, dtype=float)
    mean_u.reshape(n, 6)[:, :3] = disp.mean(axis=0)          # mean translational displacement per node
    out = {
        "positions0": X0[:n],
        "frames": frames,
        "mean_u": mean_u,
        "rmsf": rmsf,
        "helix_ids": [node.helix_id for node in mesh.nodes],
        "bp_indices": [node.global_bp for node in mesh.nodes],
        "n_frame": int(len(samples)),
        "dt_ns": float(dt),
        "anchor_keys": [[hid, bp] for (hid, bp) in anchor_keys],
        "friction": (
            f"rpy-coarse{hydro_coarse_bp}" if coarse_fric is not None
            else "rpy" if hydrodynamics else "stokes"
        ),
        "stiffness": Kcsr,
        "mass_diag": m_diag[:6 * n],
    }
    if block is not None:
        out.update({
            "tail_block": block,
            "tail_nodes": [
                {"helix_id": nd.helix_id, "bp_index": nd.bp, "direction": nd.direction,
                 "run": nd.run, "index_in_run": nd.index_in_run,
                 "overhang_ids": list(nd.overhang_ids)}
                for nd in block.nodes
            ],
            "tail_positions0": X0[n:],
            "tail_frames": frames_all[:, n:, :],
            # The FULL stack (core + tails) in one array — what snupi_tails.tail_end_to_end and the
            # SS-4 display path index into, since a tail's end-to-end vector starts at a CORE node.
            "frames_all": frames_all,
            "n_tail_nodes": int(block.n_tail),
        })
    return out
