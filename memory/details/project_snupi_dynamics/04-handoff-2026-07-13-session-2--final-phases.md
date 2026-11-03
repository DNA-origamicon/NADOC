# Handoff (2026-07-13, session 2 — "final phases") — supporting detail

[Topic head](../../project_snupi_dynamics.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
