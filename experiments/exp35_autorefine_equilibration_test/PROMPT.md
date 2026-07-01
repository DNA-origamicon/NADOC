# exp35 — validate the equilibration-fixed autorefine with post-transient analysis

## Context (what changed and why)
exp34 (`experiments/exp34_finetune_validation/conclusion.md`, LESSONS A8) found the 3×6×400
square bundle's global twist has a **~5M-step equilibration transient** (the built/over-wound seed
unwinding). The stock relax `equil_steps` is **100k** — ~50× too short — so the MEASURED production
started badly unequilibrated and read a biased, drifting twist (the ±9° "noise" that derailed
exp31/exp32 was this transient, not sampling). The equilibrated twist-vs-count curve (exp34c,
warm-started + `detect_equilibration`) showed **net-twist zero at d+4 = 222 skips (−0.6 ± 0.6°)**,
not d+5: the analytical-ish count was right; only the equilibration was broken.

**The fix (already landed):** `autorefine_sq_design` now defaults `equilibration_steps = 10_000_000`
(injected as `equil_steps` into relax_params, threaded to the baseline + every iteration + fine-tune;
overridable). Pin: `tests/test_skip_twist_tuning.py::test_autorefine_defaults_long_equilibration_and_override`.

**Tooling to reuse (do NOT rebuild):**
- `backend.core.oxdna_health.production_twist_series(design, traj_paths, ref_conf, analytic_ref)` →
  per-frame twist + `twist_series_stats` + `equilibrated` (`detect_equilibration`: Chodera N_eff-max
  burn-in cutoff `t0`).
- `backend.api.headless_oxdna_build.read_twist_series(job_id, ws, design, core_reference_geometry(design))`.
- `experiments/exp31_skip_twist_curvature_sweep/run.py::measure` (relax+production+profile+health+archive),
  `build_sq_skip_design` / `build_explicit_skip_from_design` / `place_incremental` / `baseline_skips`.
- `experiments/exp34_finetune_validation/plot34.py` (annotated PNGs incl. burn-in-marked twist-series).

## Question
Does the long-equilibration fix make the autorefine measure the TRUE (equilibrated) twist — i.e. is
the pooled-production twist now post-transient — and does the loop converge to the right count
(~222 skips, twist ≈ 0)? Or does a RESIDUAL transient survive at the equil→production handoff
(equil runs dt=0.003 with a backbone-force cap; production dt=0.005 bare FENE), so that a burn-in
DISCARD in the measurement is still required?

## Method (cheap → expensive, real CUDA: `~/oxDNA/build_cuda/bin/oxDNA`)
1. **Proxy smoke (2×3×40, ~10 min):** run `autorefine_sq_design` with the new default. Confirm it
   completes, converges, and the per-iteration production is measurable. Wire `read_twist_series`
   into the iteration so each measured production yields a per-frame twist series + `detect_equilibration`.

2. **Residual-transient test (the crux), 3×6×400, real CUDA:** build the d+4 design
   (`place_incremental(bare, baseline_skips(bare), 4)` = 222 skips). Run a SINGLE relax with the NEW
   `equil_steps=10M`, then a measured production (e.g. 8×2M like exp34c for ~20k-step frame spacing).
   Compute `production_twist_series` + `detect_equilibration` on that production.
   - **PASS (fix works):** the burn-in cutoff `t0` is now small (≲ ~1M steps), the per-frame trace is
     flat from the start (no +90°→equilibrium ramp), and the WHOLE-production-mean twist (what the
     secant actually steers on) agrees with the equilibrated mean within ~2°. Equilibrated twist of
     d+4 should reproduce exp34c: **≈ 0 ± ~2°**.
   - **FAIL (residual transient):** `t0` still ≫ 1M and the whole-mean is biased vs equilibrated by
     ≫ 2°. Then the equil-lengthening alone is insufficient (dt handoff re-transients) → implement
     burn-in discard IN the measurement (steer the secant on `detect_equilibration`-trimmed twist,
     not the whole-production mean) and re-test. This is the real follow-up fix if it triggers.

3. **End-to-end convergence, 3×6×400:** run the full fixed `autorefine_sq_design` from the analytical
   seed. PASS = converges to ~222 skips (d+4) with steering twist within tol of 0, and the per-iteration
   post-transient analysis shows each measured production is equilibrated. Compare the converged count
   + twist to the OLD (100k-equil) behavior to demonstrate the fix changed the outcome (old: biased
   +17° at d+4 → "needs d+5"; new: ≈0° at d+4, converges there).

## Deliverables
- Per-iteration annotated PNGs (twist profile + curvature + burn-in-marked per-frame twist) via plot34.
- A `t0` (residual-transient) summary across iterations: is the measured production post-transient?
- `conclusion.md`: PASS/FAIL on the residual-transient test; whether equil-lengthening suffices or
  burn-in discard is needed; the converged count + equilibrated twist vs exp34c (222 skips, ≈0°).
- Update LESSONS A8 / `project_skip_twist_selfconsistency.md` with the verified autorefine behavior;
  if a fine-tune pass is now worthwhile (twist measurable to ±0.5°), note it for a follow-up.

## Guardrails
- Three-Layer Law: tune only skip TOPOLOGY; relaxed coords are read to score, never written back.
- Cost: equil 10M ≈ doubles per-iteration wall (~adds ~25 min/iter at ~7k steps/s). If that's too
  slow for the loop, the burn-in-discard route (short equil + trim the production mean) is the cheaper
  alternative — decide from the step-2 residual-transient result.
- Archive each run's job folder off-workspace (disk; `R._archive_run`). Warm-start (append_production
  to an unarchived job) is available to save time — see `run_burnin.py`.
- Run `just test` for any backend change; the equilibration pin must stay green.
</content>
