# Phases — supporting detail

[Topic head](../../project_snupi_dynamics.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Phases
- **Phase 1a — GJF integrator + diagonal Stokes friction + uncorrelated noise. ✅ DONE 2026-07-12.**
  `backend/physics/snupi_dynamics.py` + `tests/test_snupi_dynamics.py` (6 tests, 1 slow). Reuses the
  assembled snupi K (linear force `F=−K·q`) + G6 mass matrix + optional ES PD tangent. **Validation
  gate MET on all three tiers:** (a) 1-DOF oscillator `⟨x²⟩=k_BT/k` (ratio 0.989); (b) coupled linear
  network covariance = `k_BT·K⁻¹` (Frobenius rel err 0.088); (c) real 2HB bundle — trajectory RMSF
  converges to the free-free NMA RMSF (pearson 0.75→**0.91**, mag ratio 0.58→**0.75**, as steps
  80k→200k; the residual gap is slow-mode sampling, not bias). Proves the integrator + nm·pN·ns unit
  system + fluctuation–dissipation are correct. No dense matrix yet.
  - **Key finding — plain GJF inherits Verlet's `dt<2/ω_max` step cap.** The stiffest LOCAL modes
    (12EI/L³ at the 0.34 nm bp spacing) give ω_max≈4800/ns on a small bundle → stable dt≈0.5 ps, NOT
    the paper's 5 ps. `simulate_equilibrium(dt=None)` auto-sizes dt=0.8/ω_max (generalized `eigsh(K,M)`)
    + a `_GJFDiverged` guard that halves dt and retries. **Reaching the flat 5 ps needs the paper's
    MODIFIED GJF (half-time stepping + Simpson's rule on F, Supp Note 4) — deferred to Phase 2** (it's
    a perf/stability upgrade, NOT a correctness issue: config sampling is exact at any stable dt).
  - **On-site GJF velocity ≠ thermodynamic velocity in this deeply-overdamped regime** (γΔt/2m≈46) —
    `½m⟨v²⟩` reads low (ratio ~0.68). Expected GJF property, NOT a bug; we report configurational
    quantities (RMSF), which are exact. So NO velocity-equipartition assertion in the gate.
- **Phase 1b — RPY mobility → full friction `Z` + correlated noise. ✅ DONE 2026-07-12.**
  `backend/physics/snupi_hydrodynamics.py` (`rpy_mobility_translational`, `friction_matrix`) +
  `gjf_integrate_matrix_friction` in `snupi_dynamics.py` + `simulate_equilibrium(hydrodynamics=True)`.
  Phase-1b tests in `tests/test_snupi_dynamics.py` (5 new; 11 total green).
  - **Translational RPY tensor** Ξ_tt (self Stokes + pair, with the r<2σ OVERLAP regularization —
    essential: adjacent bp are 0.34 nm ≪ 2σ=2.2 nm) → `Z_tt = inv(Ξ_tt)`; rotational DOF keep the
    diagonal self rotational Stokes drag (rot–rot/rot–trans coupling = the **1b-ii** refinement,
    Wajnryb 2013). Ξ, Z verified SPD incl. overlaps.
  - **Matrix-GJF via a mass-weighted eigen-transform (the clean trick):** `q̃=M^{1/2}q`,
    `Z̃=M^{-1/2}ZM^{-1/2}=UΛUᵀ`; in the `p=Uᵀq̃` basis each mode is an INDEPENDENT unit-mass scalar
    Langevin with friction Λ_i → the full-matrix GJF **reduces to the validated diagonal
    `gjf_integrate`** (m=1, γ=Λ), correlated noise produced automatically. Correctness inherited; the
    covariance test (cov = k_BT·K⁻¹, rel err 0.067 with an arbitrary SPD Z) gates the transform.
  - **Headline invariant MET:** RPY vs Stokes give the SAME equilibrium RMSF on the real 2HB
    (mag ratio **0.998**, means 0.354/0.354) — friction-independence confirmed. RPY's value is the
    kinetics/cross-correlations, not the static variance. Z carries real off-diagonal (hydrodynamic)
    coupling, distinguishing it from diagonal Stokes.
  - **Cost:** one O((6N)³) inverse + eigendecomposition (RPY run ~3× the Stokes run on 2HB: 11.5 vs
    3.6 s). Practical for small/medium designs; large bundles need the block-structure / iterative
    route (Phase-2 perf). dt auto-sizing unchanged (friction-independent ω_max).
  - **⚠️ RETRACTED 2026-07-13 — "generalized RPY loses PD at origami bead density" was OUR BUG.** The
    1b-ii sub-section below (and `snupi_hydrodynamics`'s docstring) used to claim the many-body
    superposition of the generalized RPY goes indefinite at σ=1.1 nm beads 0.34 nm apart, so
    `friction_matrix(generalized=True)` raised and translational-only became "the production model".
    **False.** The SNUPI dynamics SI (Note 3.2 + 4.2) builds the FULL 6N×6N generalized RPY on exactly
    this bead set and Cholesky-factors Z, asserting PD (proved, refs 7/15). Our bug: `ε·r` is
    ANTISYMMETRIC and ODD in r, so reciprocity forces `μ^tr_ij = +μ^rt_ij` — **the two cross-blocks of
    a pair are EQUAL, not transposes**. We stored `tr` / `trᵀ` (the SI's literal `μ^rt = [μ^tr]ᵀ`),
    flipping one sign; the error COMPOUNDS through the superposition (min eig −2.6e-2 → −1.8e-1 as
    N 40 → 480). With the parity right, Ξ is PD with a min eigenvalue *stable* in N (+1.58e-3). Fixed
    + pinned in `tests/test_snupi_hydro_coarse.py`. Related latent bug also fixed: `_rpy_pair_rr` /
    `_rpy_pair_rt` / the self blocks took a radius `a` but hardcoded the σ=1.1 nm drag — harmless while
    every caller used the default, silently wrong for any other radius (which the blob model needs).
- **Phase 2 — base-stacking Morse + salt-schedule driver → the switch. ✅ DONE 2026-07-12 (mechanism).**
  `backend/physics/snupi_stacking.py` (Morse element) + `simulate_reconfiguration` / `stacking_force_all`
  / `bond_lengths` in `snupi_dynamics.py`. Tests: `tests/test_snupi_stacking.py` (6) + reconfiguration
  test in `test_snupi_dynamics.py`.
  - **Morse stacking element** `Π_sk(r)=ε[(1−e^{−a(r−r₀)})²−1]`, ε=42.79 pN·nm, a=2.668 nm⁻¹, r₀=0.3742 nm
    (paper Methods). Bistable: well −ε at r₀, →0 unstacked; **rupture force ≈57 pN** = max(dΠ/dr) — the
    latch. Force = −dΠ/dr and the 6×6 tangent both finite-diff-verified.
  - **Salt-driven reconfiguration driver** runs Langevin through a Mg²⁺ SCHEDULE (segments, carrying
    q+v between them), force = elastic + Morse stacking + salt-dependent opening. **Demonstrated the
    reversible close→open→close switch** on a minimal bistable model: bond 0.46 nm (stacked/closed) →
    2.5 nm (unstacked/open at low salt) → 0.46 nm (re-stacked when salt restored). Matches the paper's
    ion-responsive switch mechanism (Fig 6).
  - **Phase-2 step (a) — blunt-end stacking-site AUTO-DETECTION. ✅ DONE 2026-07-13.** User chose
    "auto-detect blunt-end abutments" (the DNA-topology ask-first). `snupi_stacking.detect_blunt_end_stacks
    (design|mesh) → [(node_i,node_j),...]` (the format `simulate_reconfiguration`/`stacking_force_all`
    consume). A **blunt end** = a FREE duplex terminus: a helix-end node with NO inter-helix element/
    spring/rigid-link (crossover/continuation/linker all wire there) and no `ForcedLigation` (covalent
    joins excluded — a switch stacks reversibly). Two blunt ends **stack** when they abut coaxially:
    gap ≤ 0.85 nm, outward terminal-segment tangents antiparallel (facing, `t·t≤−0.7`), gap collinear
    with them (`|d̂·t|≥0.7`). Read-only (Layer-2 geom from Layer-1 topo, no writes). 5 tests
    (`test_snupi_stacking.py`: coaxial hit, side-by-side reject, gap reject, joined reject, ligation
    reject). **Real-design verified:** bundles → 0 (parallel faces); hingeV4 free ends parallel
    (`t·t=+1`); y4HB has facing collinear ends but 13.9 nm apart (arms OPEN) → 0. Correctly fires only
    on CLOSED facing ends <0.85 nm.
  - **Phase-2 step (b) — NONLINEAR corotational force in the Langevin loop. ✅ DONE 2026-07-13.**
    `fem_solver.build_corotational_elements(mesh, X0)` (extracted from `_solve_snupi_corotational`, which
    now reuses it — 22 corotational/shape tests still green) returns the shared `[(i,j,ref,K12)]` beam
    list. `snupi_dynamics.corotational_internal_force(q, X0, elements)` assembles the consistent internal
    force (via `snupi_corotational._internal_force`) at `X=X0+Δu, R=exp(θ)`. `simulate_equilibrium(...,
    nonlinear_force=True)` (opt-in; default False keeps the validated linear path) swaps `F=−Kq` for
    `f_ext − corotational_internal_force`. **Verified:** rigid-body q → exactly 0 force (EICR filter);
    small q → the corotational element tangent `T·K₁₂·Tᵀ` (1.6% @ 1e-4). **NB the corot tangent differs
    ~45% from the bp-registered NMA `K`** (geometry frame vs bp-registered anisotropic-bending frame) —
    so `nonlinear_force=True` uses the SHAPE-solver linearization, NOT the RMSF/NMA one; its equilibrium
    RMSF pattern still correlates with the linear run (>0.4) but the magnitude shifts. dt auto-sizing
    still uses the linear K. SLOW at scale (per-step Python element loop = the step-(d) perf target).
    3 tests (`test_snupi_dynamics.py`: rigid-zero, small-q tangent, slow nonlinear-vs-linear correlation).
  - **Phase-2 step (c) — MODIFIED GJF (half-time + Simpson). ✅ DONE 2026-07-13.** From the dynamics SI
    (`Literature/SnupidyanamicsSI.pdf`, Supp Note 4 — user supplied it). `snupi_dynamics.gjf_modified_integrate`
    (diagonal/Stokes) + `simulate_equilibrium(..., modified_gjf=True)`. Per step: half-time coordinate
    `U^{t+½}=U^t+Δt·j(½V+⅛·acc+¼θ^{½})`, evaluate the SIMPSON MIDPOINT force `acc^{t+½}`, full step
    `U^{t+1}=U^t+Δt·b(V+½·acc^{t+½}+½θ^{1})`, velocity `V^{t+1}=a·V+(Δt/6)(acc^{t+1}+2(a+b)acc^{t+½}+acc^t)+b·θ^{1}`;
    `j=(I+Δtγ̄/4)⁻¹, b=(I+Δtγ̄/2)⁻¹, a=2b−1`. **Two subtle bugs found+fixed:** (1) the coordinate-update
    force terms carry an extra Δt (from `∫F dt≈(Δt/2)F^t` / `≈Δt·F^{t+½}`, eqs 4.27/4.28), the velocity
    uses bare accel; (2) the noise must be fluctuation-dissipation-consistent — `β^{Δt}` CONTAINS
    `β^{Δt/2}` (share the first half-impulse), not independent draws (else it over-heats, ⟨U²⟩ up to 2×).
    **Validated:** reproduces the paper's harmonic conditions i–iv (⟨U²⟩=k_BT/k, 0.95–1.0) INCLUDING (iv)
    where plain GJF diverges; on a real 2HB it's stable + matches NMA at **1 ps where plain DIVERGES**
    (~6× step gain, pearson 0.97). **Honest scope:** does NOT auto-reach 5 ps on this 2HB — its stiffest
    generalized mode (ΩΔt/2≈12, the ultra-stiff CanDo crossover rigid-links) is beyond even the widened
    region (both diverge ≥2 ps). The paper's flat 5 ps assumes the overdamped DNA regime (γ/2Ω>30,
    ΩΔt/2<0.8); ultra-stiff crossover modes need constraining first (paper's future constrained-Langevin).
    5 tests (`test_snupi_dynamics.py`: 3 harmonic conditions, stable-where-plain-diverges, slow real-2HB).
  - **Scope honesty — remaining Phase-2 lift.** Still needed for the full µs origami switch: (d) an `F(x)`
    perf rewrite (the per-step corot loop is pure-Python — µs runs need vectorization/Numba/C), (e) a
    CLOSED-stack demo design (examples are bundles/open hinges → detector correctly finds no closed stacks
    to switch), and optionally softening the crossover rigid-links so the modified GJF reaches 5 ps.
    Stacking detection (a) + nonlinear force (b) + modified GJF (c) + Morse element + mechanism are built/tested.
- **Phase 3 — trajectory surfacing (animation toggle). ✅ DONE 2026-07-12 (trajectory animation).**
  A NEW visualizable feature (the actual motion, not just the mean shape) with its OWN frontend toggle:
  - **Backend:** `_predict_shape_dynamics` also emits a downsampled `trajectory` = `{keys, frames, n_frames}`
    (40 frames, 6 floats/key: backbone + normal — the SAME wire shape as oxDNA's `/trajectory`, via
    `deformed_positions_with_axis` per frame). Runner caches `trajectory.json`; route
    `GET /snupi/jobs/{id}/trajectory`; `load_trajectory`. Pinned in `test_predict_shape_dynamics_matches_static_contract`.
  - **Frontend:** new "Trajectory (animate dynamics)" radio in the SNUPI Visualizations card + a player
    (play/pause + scrubber + frame label, `#snupi-traj-*`). `snupi_display.showTrajectory/stopTrajectory`
    reuse oxDNA's `framesToUpdates` + `designRenderer.applyFemPositions` (rAF loop at 12 fps). Radio
    gated to dynamics jobs (`job.dynamics`); `client.getSnupiTrajectory`; `_MODE_FNS.trajectory`.
    `just test-frontend` 2696 pass. `main.js` LOC Δ = 0.
  - **Phase-3 extra — PCA breathing-mode + kinetics primitives. ✅ DONE 2026-07-13 (backend + tests).**
    `snupi_dynamics.breathing_mode_pca(frames, ref, node_mass_trans, kT, n_modes)` — thin-SVD PCA of the
    Kabsch-aligned equilibrium trajectory → the dominant collective **breathing/bending modes** (paper
    Fig 3c/d): per mode a unit shape `(N,3)`, thermal variance σ²=⟨ξ²⟩, equipartition `k_eff=k_BT/σ²`,
    effective mass `m_eff=vᵀ diag(m_trans) v`, ω=√(k_eff/m_eff), natural freq `f=ω/2π` (GHz). On the
    demo design (`workspace/snupi_dyn_demo.nadoc`) mode 0 = 3.6 nm RMS, 32% of variance, ~2.75 GHz.
    Plus the RPY-payoff primitives: `dynamics_dccm(frames, ref)` (equal-time N×N bp–bp DCCM, same
    observable as `fem_solver.compute_correlation_matrix` / MD — but **friction-independent**, so it
    validates the engine's motion topology, NOT what RPY buys); `mode_coordinate` (project traj onto a
    mode) + `mode_autocorr_time_ns` (integrated autocorr time = the mode RELAXATION TIME, the KINETIC
    quantity RPY actually changes and static NMA lacks entirely). Tests: 6 new in
    `test_snupi_dynamics.py` (2 PCA + 3 fast primitive pins + 1 slow real-2HB integration) — synthetic
    ring-breathing pins recover injected shape/variance/DCCM signs exactly; AR(1) pins the τ estimator.
    `backend just test-smart` FULL: 4869 passed (1 unrelated `test_real_arbd_field` ARBD-hardware flake).
    `main.js` untouched (backend-only). **Frontend toggle for the breathing mode still TODO** (needs the
    live-app exercise — deferred with the reconfiguration playback below).
  - **Validation depth — dynamics channel in `scripts/snupi_dccm_compare.py`. ✅ DONE 2026-07-13.**
    New `--dynamics` flag adds, per design with a local MD DCD (6hbx100_noT, 3x4SQ): the dynamics-
    trajectory DCCM→MD agreement (≈ the snupi-NMA→MD number, confirming friction-independence on the
    real design), the breathing mode + freq, and **τ_stokes vs τ_rpy** (breathing-mode relaxation time,
    the hydrodynamics speedup ratio). Writes `experiments/exp42_snupi_cross_compare/dccm.json`. Analysis
    script (logged numbers), not a CI pin — DCDs are gitignored/local-only.
    - **Results on 6hbx100_noT (2026-07-13, `--dyn-steps 80000`):** snupi-NMA DCCM→MD **0.491** > cando→MD
      **0.454** (SNUPI captures the motion topology better on the real design). dyn-trajectory DCCM→MD
      **0.235** — LOWER because a finite (~10 ns) trajectory is a noisier estimator of the same `k_BT·K⁻¹`
      NMA computes exactly ⇒ *for equilibrium statics NMA is cheaper AND more accurate than a trajectory*.
      Breathing mode ~2.85 GHz; **τ_stokes 4.40 ns → τ_rpy 1.71 ns = ×2.6 hydrodynamic speedup** — the
      concrete kinetic thing RPY buys that static NMA lacks entirely. Caveat: absolute τ is rough
      (trajectory only ~2× τ), the ratio more robust (bias ~cancels). A fully-converged τ needs a smaller
      design or the Phase-2 RPY perf rewrite: a 240k-step full-RPY run at 630 nodes exceeds ~10 min
      (dense O((6N)²) basis transform per step = the documented RPY perf wall).
  - Remaining Phase-3 ideas (not done): PCA breathing-mode **frontend toggle/animation**; reconfiguration
    (switch) playback surfaced as a job type (needs the design→stacking-site mapping — DNA-topology
    "ask first").
