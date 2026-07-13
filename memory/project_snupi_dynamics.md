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
  - **Scope honesty:** stacking topology (which node pairs stack) is an EXPLICIT input — auto-detecting
    coaxial/blunt-end stacks from a design is a topology step to define WITH the user (Three-Layer Law,
    "ask first"). Applying the switch to a full origami design + reaching the paper's µs/50° opening
    needs (a) that stacking-site topology, (b) the nonlinear corotational force per step, (c) the
    modified GJF (half-time+Simpson) + an `F(x)` perf rewrite for millions of steps. The MECHANISM +
    element are built and validated; the full-scale origami switch is the remaining perf/topology lift.
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
  - Remaining Phase-3 ideas (not done): PCA breathing-mode extraction + its own toggle; reconfiguration
    (switch) playback surfaced as a job type.

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
  ⚠ Full in-app click-through job SUBMISSION not driven (no design loaded in the shared server;
  loading one risks clobbering a concurrent session — same caveat the SNUPI tab shipped under).

## Decisions / open
- Frame value proposition honestly: for **static shape + equilibrium flexibility** our NMA already
  matches MD cheaply (the paper itself: NMA↔dynamics RMSF overlap 0.97). Dynamics' unique value =
  **reconfigurable/responsive designs** (switches, rotors), non-equilibrium transients, solvent-damped
  spectra, and actual trajectories/movies. Prioritize Phase 2 only if responsive-device sim is wanted.
- Perf is the elephant for Phase 2 (µs runs). Phase 1 (ns equilibrium, small designs) is fine in Python.
- Three-Layer Law: trajectories are PHYSICAL/display-only, never write topology.

## Handoff (2026-07-12)
**Plan written + Phase 1a + Phase 1b DONE + validated.** Files: `backend/physics/snupi_dynamics.py`
(GJF integrator, Stokes + matrix-friction integrators, `simulate_equilibrium`),
`backend/physics/snupi_hydrodynamics.py` (RPY mobility → Z), `tests/test_snupi_dynamics.py` (11 tests).
Backend-only; no frontend/main.js touched. Uncommitted.

**Next options (pick with the user):**
- **1b-ii (refinement):** full generalized RPY — add the rotation–translation (∝1/r²) + rotation–
  rotation (∝1/r³) mobility coupling blocks (Wajnryb 2013) for torsional hydrodynamics. Low-risk,
  additive; the module is structured for it (`friction_matrix` currently zeros those blocks).
- **Dynamic-correlation validation:** show RPY changes the cross-correlation/timescale vs Stokes and
  compare the DCCM/breathing frequency to MD (reuse `scripts/snupi_dccm_compare.py`), quantifying HD's
  actual payoff.
- **Phase 2 (the real prize):** base-stacking Morse element + salt-schedule driver → the ion switch
  (anharmonic reconfiguration NMA is blind to). Needs the modified GJF (half-time+Simpson) for 5 ps
  AND a perf rewrite of `F(x)` for µs runs (millions of steps). Confirm scope first — biggest effort.
- **Frontend (Phase 3):** surface an equilibrium-dynamics run + trajectory/RMSF in the SNUPI tab.

## References
- Integrator M V̇=F−ZV+R, GJF: Grønbech-Jensen & Farago 2013 (paper ref 22); modified w/ half-time +
  Simpson (Supp Note 4). RPY: Wajnryb et al. 2013 (ref 21). Stacking Morse: paper Methods + refs 60,61
  (ε=42.79 pN·nm, a=2.668 nm⁻¹, r₀=0.3742 nm).
- Code we build on: `fem_solver.py` (`build_fem_mesh`, `assemble_mass_matrix`, `_snupi_es_params`,
  `_snupi_electro_sparse`), `snupi_corotational.py` (`element_reference`, `_snupi_element_stiffness`
  in fem_solver, `element_force_tangent`), `snupi_material.py`.
- Related: [[snupi-mimic]], [[project_snupi_gaps]], [[project_cando_fem]], [[snupi-frontend-tab]].
