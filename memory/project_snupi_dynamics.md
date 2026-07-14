---
name: project_snupi_dynamics
description: "Plan + build log — add Langevin structural DYNAMICS (Lee/Koh/Kim, Nat Commun 2023) on top of our static SNUPI mimic. Friction (RPY) + random force + GJF integrator + base-stacking Morse + trajectory analysis. Phase 1 = equilibrium-dynamics validator vs our own NMA."
metadata:
  node_type: memory
  type: project
---

# SNUPI dynamics — Langevin time-integration on top of the static mimic

Source paper: **Lee, Koh & Kim, *Nat Commun* 14:7079 (2023)** — `Literature/SNUPI_dynamics.pdf`
(read in full 2026-07-12). This is the *dynamics engine* bolted onto the SNUPI **ACS Nano 2021**
structural model we already mimic ([[snupi-mimic]], [[project_snupi_gaps]]). It keeps SNUPI's FE
internal-force + mass description verbatim and adds **Langevin time-integration** → trajectories
instead of a single mean structure.

Governing equation (everything scopes off this):

    M V̇ = F − Z V + R ,   U̇ = V

## What we already have (≈60% of the machine)
| Term | Paper | Ours | Status |
|---|---|---|---|
| **M** mass matrix | seq-dependent nodal masses, 6 DOF/node | `assemble_mass_matrix` (G6, SPD, kg) | ✅ |
| **F** elastic internal force | corotational consistent internal-force vector | `snupi_corotational.element_force_tangent` → `f_g=T·K₁₂·d_local`; global assembly in `solve_corotational` | ✅ |
| **F** electrostatic | Debye–Hückel inter-helix, salt-dependent | `snupi_electrostatics` / `_snupi_electro_sparse` | ✅ |
| element D (74 motif 6×6) | anisotropic + coupled | `snupi_material`, exact | ✅ |

## What's missing (the dynamics contribution)
1. **Friction matrix `Z`** — generalized Rotne–Prager–Yamakawa (RPY) mobility `Ξ` (6 DOF/node,
   Wajnryb 2013), `Z = Ξ⁻¹`. σ=1.1 nm hydrodynamic radius, η=890 µN·s/m² @ 300 K. Dense; updated
   every 1000–10000 steps.
2. **Random force `R`** — `⟨R⟩=0`, `⟨R(t)R(t′)⟩=2k_BT·Z·δ(t−t′)`; colored by a Cholesky factor of
   `Z` (full matrix ⇒ correlated noise), refactored at the same slow cadence.
3. **Modified Grønbech-Jensen–Farago integrator** — half-time stepping + Simpson's rule on the
   internal force (Supp Note 4), real-time Δt=5 ps. Inner loop reuses our global `F(x)`.
4. **Base-stacking Morse element** — `Π_sk(r)=ε[(1−e^{−a(r−r₀)})²−1]`, ε=42.79 pN·nm, a=2.668 nm⁻¹,
   r₀=0.3742 nm; salt-dependent ε. 2-node FE (easy); the work is identifying stacking-site topology.
   **Only needed for reconfigurable designs** (switch/rotor). Not needed for equilibrium dynamics.
5. **Trajectory analysis** — RMSD(t), RMSF-from-frames, PCA (→ breathing freq + mode shapes),
   correlation maps, 3DNA bp-step distributions. Reuses existing compare/DCCM code on a frame stack.
6. **Salt-schedule reconfiguration driver** — orchestration (mgcl2_M schedule → ES + stacking react).

## The load-bearing insight (why phase it this way)
The **equilibrium config distribution is friction-independent** — GJF samples the correct Boltzmann
distribution `∝exp(−U/k_BT)` regardless of `Z` (friction only sets the *timescale* and dynamic
cross-correlations, not the static variance). So:
- **trajectory RMSF must equal our NMA RMSF** (both sample `k_BT·K⁻¹`) — a clean, cheap validation
  gate that needs NO hydrodynamics, only the integrator + units + fluctuation-dissipation.
- Node inertial relaxation `m/ζ ≈ 0.06 ps ≪ Δt=5 ps` → heavily overdamped; GJF is built for exactly
  this (correct Boltzmann sampling at large Δt). Confirms the paper's Δt.

Consequence: hydrodynamics (RPY) buys **kinetics + motion cross-correlations + damped real
frequencies**, NOT the static flexibility we already match. Build the integrator first with cheap
diagonal (Stokes) friction, validate against NMA, *then* add RPY.

## Units (locked — get this wrong and it silently corrupts)
Integrate in a consistent **nm · pN · ns** system so the assembled K and displacement q keep their
NATURAL units (no per-block SI conversion of K). Derived mass unit = pN·ns²/nm = 1e-21 kg (a bp ≈
1.086e-3 of these) → the G6 mass matrix (SI kg / kg·nm²) is scaled by `MASS_G6_TO_DYN=1e21`. k_BT =
4.142 pN·nm @300 K. Stokes drag on σ=1.1 nm in water η=8.9e-4 Pa·s: `STOKES_TRANS=6πησ` → 18.45
pN·ns/nm (N·s/m ×1e12); `STOKES_ROT=8πησ³` → 29.8 pN·nm·ns (N·m·s ×1e30). Δt in ns (5 ps = 0.005).
(NB `fem_solver.KBT=4.11 pN·nm` is the 298 K NMA value; dynamics uses 300 K 4.142 — keep distinct.)
Implemented exactly this way in `snupi_dynamics.py`; validated by the 1-DOF `⟨x²⟩=k_BT/k` test.

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

## Visualization bridge (2026-07-12) — dynamics output is toggle-able like every structure prediction
The dynamics engine now feeds the SAME display contract as the static solve, so ALL existing SNUPI
toggles (deform / flex-RMSF / deviation / cylinders) visualize it with **zero new display code**:
- `predict_shape(design, material="snupi", dynamics=True, hydrodynamics=?)` →
  `fem_solver._predict_shape_dynamics` runs `simulate_equilibrium` and packages the time-MEAN shape as
  `positions`/`axis` and the TRAJECTORY RMSF as `rmsf` — identical keys/format to the static payload
  (verified by `test_predict_shape_dynamics_matches_static_contract`). `simulate_equilibrium` now adds
  the loop/skip prestress to its force so the mean shape = the static equilibrium (fluctuation
  covariance unchanged → RMSF gate still holds) and exposes `mean_u`.
- **Job plumbing:** `SnupiJob.dynamics`/`.hydrodynamics` → `new_snupi_job` → `snupi_runner` →
  `predict_shape` → cached `display.json`/`rmsf.json` (the runner is unchanged — it just passes the
  flags; the display processors are material/method-agnostic). `CreateSnupiJobRequest.dynamics/
  hydrodynamics`. Frontend: two checkboxes in the SNUPI Advanced card (`snupi-jobs-dynamics`,
  `snupi-jobs-hydrodynamics`) → the create body; `solverLabel` names "Dynamics (Langevin/RPY)".
  `just test-frontend` 2696 pass (+solverLabel case). Toggles served by the live vite server.
  ✅ **VERIFIED IN APP 2026-07-13.** User loaded `workspace/snupi_dyn_demo.nadoc` (the 6HB/147 bp/882-node
  beam built for this) and ran a **dynamics + RPY** job through the SNUPI Advanced panel; the
  **Trajectory (animate dynamics)** radio lit up and the player animates the thermal motion (user: "works…
  looks pretty good"). Job took ~11 min (658 s) — RPY dense linalg at 882 nodes pins CPU ~100% (expected).
  - **Progress-bar fix (2026-07-13):** the `_estimate_seconds` model (snupi_runner) only knew the static
    solve (~47 s), so a 658 s dynamics-RPY run pinned the bar at its 0.97 cap in ~45 s. Made it dynamics-
    aware (fixed 60k-step trajectory) and RPY-aware (dense friction ∝ nodes², calibrated to the 882-node
    /658 s run) → the bar now climbs from 0 with a real ETA. Dynamics jobs also get an honest stage label
    (`dynamics` / `dynamics-rpy`, not `nonlinear`). Tests in `test_snupi_job.py` (stage-name + estimate).

## Hydrodynamics is MEMORY-BOUND — the O(N²) wall + the coarse blob model (2026-07-13)
**Symptom:** running full-hydrodynamics SNUPI on a full-size origami crashes VS Code. **Cause:** a
genuine OOM, and it is *inherent to the method*, not our code. `Z = Ξ⁻¹` is dense in the 6N DOF (N = one
FE node per bp) and the paper's own algorithm (SI Note 4.3) holds several dense 6N×6N matrices at once
(Z, Cholesky S, auxiliaries j and b). Measured peak RSS of our exact path ≈ **1.5e-6 · N² GB**
(N=798→1.01 GB, 1200→2.20, 1596→3.85 — the model reproduces these to a few %).

| design | nodes | exact peak |
|---|---|---|
| **SNUPI's OWN `Ex4_Triangle_dynamic`** (the only dynamics example it ships) | 339 | 0.2 GB |
| `snupi_dyn_demo` (ran fine, 11 min) | 882 | 1.2 GB |
| `26hb_platform_v3` | 5200 | 41 GB |
| `2x20sq_m13` (full M13) | 7240 | **79–83 GB** |

**We were 21× outside the regime SNUPI demonstrates.** On a 30 GB box the machine swaps and the OOM
killer takes the biggest process — the user's editor. Two responses, both shipped:

1. **Preflight guard** (`snupi_hydrodynamics.check_friction_memory` / `estimate_friction_memory_gb` /
   `hydro_memory_budget_gb`, budget = ½ physical RAM, override `NADOC_HYDRO_MEM_GB`). Called from
   `simulate_equilibrium` AND from `POST /snupi/jobs` (→ **413** before the detached worker spawns).
   User's call: **refuse with a clear error**, never silently downgrade to Stokes.
2. **Coarse blob hydrodynamics** — `backend/physics/snupi_hydro_coarse.py`. One hydrodynamic bead per
   `k` bp (default **k=8**). Physically overdue anyway: σ=1.1 nm beads 0.34 nm apart are ~90%
   overlapping, i.e. resolving the flow far below any scale it varies on.
   - **Model** `Ξ = D + AᵀCA`: `C` = generalized RPY between the B blob centres at blob radius
     σ_b = hypot((k−1)·rise/2, σ); `A` = node→blob map (sum forces / broadcast velocity — the rigid-blob
     picture); `D` = diag(μ_self(σ) − μ_self(σ_b)) > 0, so each node's self-drag stays EXACT and Ξ SPD.
   - **Woodbury ⇒ `Z = D⁻¹ − Yᵀ G⁻¹ Y` — diagonal minus rank-6B.** Nothing 6N×6N is ever formed; the
     only dense object is 6B×6B. Noise is drawn from the MOBILITY side
     (`y = M^½D^½g₁ + M^½AᵀL_C g₂`, then `β̃ = √(2kTΔt)·Z̃y`) so we never Cholesky a 6N×6N Z — the
     paper's dense bottleneck. New `snupi_dynamics.gjf_integrate_operator_friction` (mass-weighted, so
     it reduces LINE-FOR-LINE to the validated diagonal `gjf_integrate` — verified bit-identical).
   - **Result: full M13 (7240 nodes) runs in 1.74 GB / 11 s setup**, vs 83 GB refused. B=920 blobs.
   - **⚠️ Valid range k ≥ 4, default 8 — it does NOT converge to exact as k→1, it DEGENERATES.** At k=2,
     σ_b=1.113 nm vs σ=1.1 → `D` is only **1.1%** of the node self-mobility, so the blob supplies ~99% of
     the drag while containing 2 nodes: they get slaved together and the hydrodynamic enhancement is
     LOST. Measured on 6hbx100_noT (630 nodes, breathing-mode τ vs exact generalized RPY):
     **τ/τ_exact = 0.52 (k=2), 0.86 (k=4), 0.97 (k=8), 1.10 (k=16); no-HI Stokes = 0.58.** k=2 lands on
     the Stokes value — the tell. `build_coarse_friction` refuses k<4 (k=1 → use the exact path).
     Caveat: the τ estimator is only ~±20% at these trajectory lengths (≈5τ of data), so read k≥8 as
     "recovers the hydrodynamic speedup that Stokes lacks", not as a 3%-accurate claim.

## Decisions / open
- Frame value proposition honestly: for **static shape + equilibrium flexibility** our NMA already
  matches MD cheaply (the paper itself: NMA↔dynamics RMSF overlap 0.97). Dynamics' unique value =
  **reconfigurable/responsive designs** (switches, rotors), non-equilibrium transients, solvent-damped
  spectra, and actual trajectories/movies. Prioritize Phase 2 only if responsive-device sim is wanted.
- Perf is the elephant for Phase 2 (µs runs). Phase 1 (ns equilibrium, small designs) is fine in Python.
- Three-Layer Law: trajectories are PHYSICAL/display-only, never write topology.

## Handoff (2026-07-13, session 2 — "final phases")
**Phases 1a/1b/2/3 + viz bridge + trajectory toggle previously committed (8b5661a).** This session
completed the plan's "final phases" (full-suite `just test` 4896 passed). All backend; `main.js` LOC Δ = 0;
Three-Layer Law + `_PHASE_*` untouched. Shipped (details in the Phase sub-sections above):
- **Live-UI ✅ VERIFIED IN APP** — user ran a Langevin+RPY job on `workspace/snupi_dyn_demo.nadoc`
  (gitignored 6HB/147 bp/882-node beam built this session); Trajectory toggle animates ("looks pretty good").
- **Progress-bar fix** (dynamics/RPY-aware ETA + stage labels; `snupi_runner`/`snupi_job`).
- **Phase-3 PCA breathing mode** + kinetics primitives (`breathing_mode_pca`, `dynamics_dccm`,
  `mode_coordinate`, `mode_autocorr_time_ns`).
- **Validation depth** — `--dynamics` channel in `scripts/snupi_dccm_compare.py`; on 6hbx100_noT:
  snupi-NMA→MD 0.491 > cando 0.454; **×2.6 RPY breathing-relaxation speedup**.
- **1b-ii generalized RPY** — full rt+rr coupling; opt-in + PD guard (NOT production; see sub-section).
- **Phase-2 (a) blunt-end stacking detection · (b) nonlinear corotational F(x) · (c) modified GJF**
  (half-time+Simpson, ~6× stable-step; from `Literature/SnupidyanamicsSI.pdf` Supp Note 4).

**Remaining Phase-2 lift (each session-sized — pick with user):**
- **(d) `F(x)` perf rewrite** — the per-step corotational force loop (`corotational_internal_force`) is
  pure-Python; µs / origami-scale switching needs vectorization / Numba / C. Biggest lever.
- **(e) closed-stack demo design** — every example is a bundle or open hinge, so `detect_blunt_end_stacks`
  correctly finds nothing to switch; need a reconfigurable device with two facing blunt ends <0.85 nm
  apart to exercise `simulate_reconfiguration` end-to-end.
- **Modified GJF → 5 ps** — soften/constrain the ultra-stiff CanDo crossover rigid-links (ΩΔt/2≈12) so
  the widened stable region reaches the paper's flat 5 ps (paper's future "constrained Langevin").
- **PCA breathing-mode / reconfiguration FRONTEND toggles** — surface `breathing_mode_pca` as its own
  animation, and reconfiguration playback as a job type (both need the live-app exercise).

## Kickoff prompt for a fresh session (continue + drive the live UI)

> **Continue the SNUPI structural-dynamics plan.** Read `memory/project_snupi_dynamics.md` (this file
> — the plan + what's built) and skim `memory/project_snupi_mimic.md` / `memory/project_snupi_gaps.md`
> for the static-mimic context. Phases 1a/1b/2/3 + the visualization bridge + the trajectory-animation
> toggle are DONE and committed (`8b5661a`): GJF Langevin integrator, RPY hydrodynamic friction, the
> base-stacking Morse element + reversible ion-switch driver, `predict_shape(material="snupi",
> dynamics=, hydrodynamics=)` returning the standard display contract, and a "Trajectory (animate
> dynamics)" toggle with a play/scrubber player. Backend `just test-smart` FULL green (bar the
> pre-existing `test_g12_salt_ignored_by_cando` ARPACK flake — verify it passes in isolation, ignore);
> frontend `just test-frontend` green.
>
> **FIRST — the one thing that's NOT verified: drive the live UI.** You ARE authorized to submit SNUPI
> jobs and flip display toggles in the running app to verify the dynamics + trajectory animation
> actually render. But FIRST read `memory/feedback_no_live_server_mutation_for_verify.md` and follow it:
> the dev server holds ONE shared active design + jobs across the user and concurrent sessions. So (1)
> ASK the user which design is loaded / safe to run a job against (or to load `Examples/26hb_platform_v3.nadoc`
> or `workspace/6hbx100_noT.nadoc`); (2) NEVER `POST /design` (resets the active design) or delete jobs
> you didn't create; (3) read-only GETs are always fine. With `just dev` + `just frontend` running and a
> user-approved design: open Simulate ▸ SNUPI ▸ Advanced, tick **Langevin dynamics** (and optionally
> **Hydrodynamics (RPY)**), run a job, then in Visualizations flip **Predicted shape**, **Flexibility
> map**, and **Trajectory (animate dynamics)** — confirm the player plays/scrubs and there are 0 console
> errors. This is the sanctioned live-UI exercise; report what you saw.
>
> **THEN pick up the remaining work (in the plan):**
> - **Phase-3 extras:** PCA on the trajectory → the low-frequency breathing mode + its natural frequency
>   (paper Fig 3c/d), surfaced as its own toggle/animation; and the salt-schedule RECONFIGURATION (the
>   ion switch) surfaced as a job type with trajectory playback (the driver `simulate_reconfiguration`
>   exists; it needs a design→stacking-site mapping — ASK the user how coaxial/blunt-end stacks are
>   defined for their designs, per the DNA-topology "ask first" rule).
> - **1b-ii:** full generalized RPY — add the rotation–translation (∝1/r²) + rotation–rotation (∝1/r³)
>   mobility coupling blocks (Wajnryb 2013); `snupi_hydrodynamics.friction_matrix` currently zeros them.
> - **Phase-2 full origami switch:** apply stacking + the NONLINEAR corotational force per step at origami
>   scale — needs the modified GJF (half-time + Simpson, Supp Note 4) for the paper's 5 ps step AND an
>   `F(x)` perf rewrite for µs runs (millions of steps; current Python force eval is the bottleneck).
> - **Validation depth:** compare the dynamics DCCM / breathing frequency to MD (reuse
>   `scripts/snupi_dccm_compare.py`) to quantify what RPY hydrodynamics buys over the static NMA.
>
> Guardrails: module-first (no `main.js` growth — cite its LOC Δ), Three-Layer Law (dynamics output is
> Physical/display-only, never writes topology), `_PHASE_*` locked, a mechanical/unit test per new piece,
> and `just test-smart` + `just test-frontend` before claiming done. Commit only when asked.

## References
- Integrator M V̇=F−ZV+R, GJF: Grønbech-Jensen & Farago 2013 (paper ref 22); modified w/ half-time +
  Simpson (Supp Note 4). RPY: Wajnryb et al. 2013 (ref 21). Stacking Morse: paper Methods + refs 60,61
  (ε=42.79 pN·nm, a=2.668 nm⁻¹, r₀=0.3742 nm).
- Code we build on: `fem_solver.py` (`build_fem_mesh`, `assemble_mass_matrix`, `_snupi_es_params`,
  `_snupi_electro_sparse`), `snupi_corotational.py` (`element_reference`, `_snupi_element_stiffness`
  in fem_solver, `element_force_tangent`), `snupi_material.py`.
- Related: [[snupi-mimic]], [[project_snupi_gaps]], [[project_cando_fem]], [[snupi-frontend-tab]].
