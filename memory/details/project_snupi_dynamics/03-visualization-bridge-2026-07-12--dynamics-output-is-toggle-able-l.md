# Visualization bridge (2026-07-12) — dynamics output is toggle-able like every structure prediction — supporting detail

[Topic head](../../project_snupi_dynamics.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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

## E-field in the Langevin loop (2026-07-25) — DONE
The static solver's E-field body load is now wired into `simulate_equilibrium`, so the dynamics
engine gives the field response with **correct overdamped damping** (no oxDNA thermostat ringing) —
the point of the exercise (see `project_oxdna_efield`; oxDNA's per-nucleotide field force + Bussi
thermostat leave a whole-arm mode under-damped → artefactual oscillation about the field vector).
- **Wiring:** `predict_shape(dynamics=True, field=, anchors=)` → `_predict_shape_dynamics` →
  `simulate_equilibrium(field=, anchors=)`. Two pure helpers in `snupi_dynamics.py`:
  `field_body_load(mesh, block, n_tot, field)` (core bp node = **2·field_pN**, free ssDNA tail bead =
  **1·field_pN** — the user chose core+tails; reuses `fem_solver.assemble_field_force` for the core)
  and `anchor_trap_diag(n_tot, n_core, fixed_nodes, k)`.
- **Anchors = stiff harmonic trap** (user decision, mirrors oxDNA's `trap`, not the static solver's
  hard Dirichlet clamp): `k_anchor = ANCHOR_TRAP_FACTOR(=2)·max|diag(K)|` on anchor translational DOF,
  added as `−k_anchor_diag·q` INSIDE `force_fn` (kept out of K/core_int, so the validated no-anchor
  equilibrium path is byte-for-byte unchanged — gated on `has_anchor`) and folded into the plain-GJF
  `dt` eigensolve so the stiff spring doesn't just surface as a divergence retry. **A field needs ≥1
  anchor** — uniform force with no clamp = pure COM drift, zero internal deflection.
- **Why it's correct:** the field is a constant dead load, so the overdamped mean satisfies
  `K_eff·mean_u = f_ext` = the SAME static field response; the trajectory adds the correctly-damped
  thermal motion about it. `mean_u` = the deflection; `out["anchor_keys"]` reported.
- **Verified (direct exercise, `_routed_2hb`, field ⟂ axis, one anchored end):** free-end deflection
  **+0.62 nm along +field** > anchored-end, bounded ~1.2 nm (trap holds — no runaway); field-off = pure
  thermal noise, no systematic deflection. Tests: 2 fast pure pins (`field_body_load`, `anchor_trap_diag`)
  + 1 slow integration pin (`test_field_with_anchor_deflects_free_region_along_field`) in
  `test_snupi_dynamics.py`. `just test-smart` FAST 5496 passed. Backend-only, `main.js` LOC Δ = 0.
- **End-to-end via the API already:** the create request (`routes_cando` CandoJobRequest), `SnupiJob`,
  and `snupi_runner` already carry+forward `field`/`anchors` to `predict_shape`; the ONLY thing my change
  fixed was `predict_shape(dynamics=True)` → `_predict_shape_dynamics` dropping them. So a POST predict job
  with `dynamics=true` + `field` + `anchors` now runs the field response with correct damping, no further
  plumbing. **Frontend (2026-07-25):** the SNUPI panel's E-field + Anchors cards ALREADY existed
  (byte-for-byte clones of the oxDNA markup, reusing the shared `forces_card`/`oxdna_anchors_setup`
  factories; `_launch()` already sends `field`/`anchors`). The one behavioral parity gap — repopulating
  the cards on job-select (oxDNA does this via `_applyRunControls`→`applyConfig`) — is now closed: pure
  `snupiRunConfig(job)` + `_applyRunConfig` in `snupi_jobs_panel.js` call `_efieldCard.applyConfig` /
  `_anchorsCard.applyConfig` on `_selectJob` (explicit-select only, never on poll → no mid-edit clobber).
  `main.js` LOC Δ = 0; `just test-frontend` 3167 pass; `just smoke` 23 pass. **NOT hand-verified in app:**
  clicking a completed SNUPI field job to watch the cards repopulate (needs a live completed field job;
  can't POST to the shared server) — logged as manual-validation debt.
  **Open:** trap stiffness at 2× the stiffest CanDo crossover rigid-link shrinks `dt` (~1/√2); origami-scale
  field runs will want the Phase-2 modified-GJF/constrained-Langevin step widening.
