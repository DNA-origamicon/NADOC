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
from typing import Callable, Optional

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
        if step % 500 == 0 and not np.isfinite(q).all():
            raise _GJFDiverged(f"GJF diverged at step {step} (dt={dt} too large for the stiffest mode)")
    return np.array(samples), v


class _GJFDiverged(RuntimeError):
    """Raised when the explicit GJF step exceeds the stiff-mode stability limit."""


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


# ── High-level: equilibrium dynamics of a design (linear force, Phase 1a) ────────

def simulate_equilibrium(
    design,
    *,
    material: str = "snupi",
    with_electrostatics: bool = False,
    hydrodynamics: bool = False,
    mgcl2_M: Optional[float] = None,
    temperature_K: float = 300.0,
    dt: Optional[float] = None,
    n_steps: int = 20000,
    n_equil: int = 4000,
    sample_every: int = 20,
    seed: int = 0,
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

    ``hydrodynamics`` (Phase 1b) swaps the diagonal Stokes drag for the full Rotne–Prager–Yamakawa
    friction matrix Z (:func:`snupi_hydrodynamics.friction_matrix`) + correlated noise, integrated by
    :func:`gjf_integrate_matrix_friction`. The EQUILIBRIUM RMSF is unchanged (friction-independent);
    RPY only alters the kinetics + dynamic cross-correlations. Costs an O((6N)³) eigendecomposition
    once, so it's practical for small/medium designs (Phase-2 perf work for large bundles).

    Returns ``{positions0, frames, rmsf, helix_ids, bp_indices, n_frame, dt_ns, friction, stiffness, mass_diag}``
    (positions in nm; frames are absolute node positions, rigid-body drift retained —
    :func:`trajectory_rmsf` removes it).
    """
    from backend.physics.fem_solver import (
        build_fem_mesh,
        assemble_global_stiffness,
        assemble_mass_matrix,
        assemble_prestress_force,
        SNUPI_DEFAULT_MGCL2_M,
    )

    mesh = build_fem_mesh(design)
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

    if dt is None:
        # Plain GJF inherits Verlet's step limit dt < 2/ω_max; ω_max is the largest GENERALIZED
        # frequency √λ of (K, M). 0.8/ω_max ≈ 0.4·(2/ω_max) leaves a stability margin.
        from scipy.sparse import diags
        from scipy.sparse.linalg import eigsh
        Md = diags(m_diag).tocsr()
        lam_g = float(eigsh(Kcsr, k=1, M=Md, which="LM", return_eigenvectors=False)[0])
        omega_max = math.sqrt(max(lam_g, 1e-30))
        dt = min(DT_DEFAULT, 0.8 / omega_max)

    def force_fn(q):
        return f_ext - (Kcsr @ q)

    Z = None
    if hydrodynamics:
        from backend.physics.snupi_hydrodynamics import friction_matrix
        Z = friction_matrix(X0)

    # Run with a divergence-guarded retry: if the auto/explicit dt still overshoots the stiffest
    # mode, halve and retry (up to 4×) so the run always completes at a stable step.
    samples = None
    for _attempt in range(4):
        rng = np.random.default_rng(seed)
        try:
            if hydrodynamics:
                samples, _v = gjf_integrate_matrix_friction(
                    force_fn, np.zeros(6 * n), m_diag, Z,
                    kT=kT, dt=dt, n_steps=n_steps, n_equil=n_equil,
                    sample_every=sample_every, rng=rng,
                )
            else:
                samples, _v = gjf_integrate(
                    force_fn, np.zeros(6 * n), m_diag, gamma,
                    kT=kT, dt=dt, n_steps=n_steps, n_equil=n_equil,
                    sample_every=sample_every, rng=rng,
                )
            break
        except _GJFDiverged:
            dt *= 0.5
    if samples is None:
        raise _GJFDiverged("GJF failed to stabilise after halving dt 4×")

    disp = samples.reshape(len(samples), n, 6)[:, :, :3]     # translational displacement per frame
    frames = X0[None, :, :] + disp
    rmsf = trajectory_rmsf(frames, X0)
    mean_u = np.zeros(6 * n, dtype=float)
    mean_u.reshape(n, 6)[:, :3] = disp.mean(axis=0)          # mean translational displacement per node
    return {
        "positions0": X0,
        "frames": frames,
        "mean_u": mean_u,
        "rmsf": rmsf,
        "helix_ids": [node.helix_id for node in mesh.nodes],
        "bp_indices": [node.global_bp for node in mesh.nodes],
        "n_frame": int(len(samples)),
        "dt_ns": float(dt),
        "friction": "rpy" if hydrodynamics else "stokes",
        "stiffness": Kcsr,
        "mass_diag": m_diag,
    }
