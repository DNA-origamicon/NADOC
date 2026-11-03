# exp32 RESULT — profile-guided MIMO secant DIVERGED (2026-06-28) — supporting detail

[Topic head](../../project_skip_twist_curvature_sweep.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## exp32 RESULT — profile-guided MIMO secant DIVERGED (2026-06-28)
exp32 (`experiments/exp32_profile_guided_refine/`, COMPLETE, see its `conclusion.md`) ran the
per-segment signed-twist secant to flatten the profile. It DIVERGED: total skips oscillated
90↔1367, bins demanded 67–96 deletions/helix, final flatness (52°) WORSE than the period-48 seed.
Two faults: (1) divide-by-noise — the secant estimates each bin's gain from a single one-deletion
response (~1–3°) measured against ≥±35° per-run scatter → step explodes; (2) 6 uncoupled SISO loops
on a globally-coupled (cumulative-integral) plant, made worse by gain 1.3 overshoot. Same regime
[[project_regional_autorefine]] §5.4 already ruled non-viable. → LESSONS **A7**. Retire wholesale /
per-segment profile control.

## DECISIVE re-read of exp31 data — PLACEMENT is the whole lever (2026-06-28)
At a MATCHED 222 skips (incremental delta +4 over period-48 baseline): **incremental-gap = net
twist −3.2°, max|profile| 5.2°** (flat AND net-null, one shot) vs uniform-restagger 46°/52° vs
deviation 59°/68°. So the recommended autorefine is just the existing scalar net-twist COUNT secant
+ **incremental-gap placement** (swap production placement off `sq_lattice_periodic_skips`'s uniform
restagger) — no MIMO controller, likely no fine-tuner. CAVEAT: 5.2° is ONE sim; its reality depends
on the per-run noise floor, which NEITHER exp31 nor exp32 ever measured.

## exp34 RESULT — the noise was an EQUILIBRATION artifact; net-zero is d+4=222 skips (2026-06-29)
exp34 (`experiments/exp34_finetune_validation/conclusion.md`) ran Gate 0/1/2 (8M) + an 80M long
run + exp34c warm-started burn-in sweep. KEY FINDINGS:
- The 3×6×400 square bundle's global twist has a **~5M-step EQUILIBRATION transient** (relaxes from
  the +90° built/over-wound seed), after which it decorrelates FAST (τ≈3 frames, SEM ±0.4–0.6°).
  The standard **8M autorefine production NEVER equilibrates the twist** → every prior twist number
  (exp31 "flat at +4", exp34 Gate 0/1) was a biased mid-transient read (±9° scatter).
- ROOT CAUSE: relax `equil_steps` default = **100,000** (`STANDARD_RELAX_PARAMS`), ~50× too short.
- **EQUILIBRATED twist-vs-count: net-zero at d+4 = 222 skips (−0.6 ± 0.6°)**, not d+5. The
  analytical-ish incremental+4 count was right; the "needs ~2× / d+5" claims were equilibration
  artifacts. d+3(204)=+35.7°, d+4(222)=−0.6°, d+5(240)=−19.8°.
- NEW TOOLING (pinned, suite green 3397): `oxdna_health.{twist_series_stats, production_twist_
  series, detect_equilibration}` (per-frame twist + τ/N_eff + Chodera burn-in) + headless
  `read_twist_series`. Warm-start pattern = `append_production` to an unarchived job (continues its
  trajectory — see `run_burnin.py`). FIX: equilibrate ~10M before measuring (in `autorefine_sq_
  design`); validated by exp35.
- A8 LESSON corrected (was "slow mode / need seeds" → now "equilibration transient / burn-in").

## exp35 RESULT — the 10M-equil fix is necessary but NOT sufficient; d+4 does NOT equilibrate to 0 on a cold build (2026-06-30)
exp35 (`experiments/exp35_autorefine_equilibration_test/conclusion.md`) validated the shipped 10M-equil
`autorefine_sq_design` on real CUDA. Modes: proxy wiring smoke (autorefine completes + every iteration's
production measurable via `read_twist_series`, `per_iter_measurable=True`); the crux **residual-transient
test** (fresh d+4=222 skips, mc+md_relax(1M)+**equil(10M)**+production(16M)); e2e NOT run (premise below).
- **The equil fix WORKS at its stated job:** fresh d+4 production is post-ramp — burn-in `t0=0`, trace FLAT
  from frame 0 (no +90°→equilibrium ramp), τ=2.9, N_eff 272/800, SEM ±0.68°, whole-production mean ==
  `detect_equilibration`-trimmed mean EXACTLY (0.0° gap). PROMPT criteria 1&2 PASS.
- **BUT equilibrated d+4 twist = +18.2 ± 0.7°, NOT ~0°.** CONTRADICTS exp34c's warm-started −0.6°, REPRODUCES
  the OLD "8M under-equilibrated → +17° → needs d+5" number. exp34c's "count was always right, d+4=net-zero"
  is UNCONFIRMED / likely premature.
- **THIRD case the PROMPT's binary missed; the prescribed FAIL remedy (burn-in DISCARD) is a NO-OP** (no
  in-window transient to trim, `t0=0`). The miss is the SLOW twist glide: +18° sits between exp34c's d+3=+36°
  and d+4=−0.6°, i.e. the cold build relaxed LESS than the longer-history warm-start. A glide slower than the
  16M window reads "flat" and `detect_equilibration` can't see a transient longer than the trajectory → `t0=0`
  is a FALSE "equilibrated" (same low-τ trap one level up). See LESSONS A8 CRITICAL CORRECTION.
- **Implication for e2e:** a cold autorefine would measure +18° at d+4 and steer toward MORE skips (~d+5=240),
  not converge at 222 — the fix did NOT change the count outcome the way the PROMPT expected.
- **Fix needed:** a twist-CONVERGENCE gate (equilibrate until block-averaged twist slope ≈0), not a fixed 10M
  equil. Decisive open experiment: continue the archived exp35 d+4 job (`.../76deb290aba8`) ~64M more steps
  (warm-restore + `append_production`, exp34c pattern) → does +18° glide to 0 (exp34c right) or stay (metastable
  basin, hysteretic count)?
- No backend change (harness only); equilibration pin green. Tooling: `run.py` (dry/proxy/residual/e2e),
  `export_png.py` + `trigger_export.sh` (end-of-job PNG trigger).

## (historical) exp34 — set up, NOT yet launched (2026-06-28)
`experiments/exp34_finetune_validation/` (hypothesis.md + run.py, dry-run-validated). Kill-gated,
reuses exp31 `run.measure` + `skip_sweep_strategies` + `profile_guided_refine` (bin_layout/
local_twist only — NOT the divergent secant). **Gate 0 (keystone, the thing exp32 skipped):** re-sim
the IDENTICAL incremental+4 design K=4× → σ(max|profile|), δ_min=2σ; KILL if σ≥15° (then no
fine-tuner can ever be validated). **Gate 1:** incremental delta +3/+4/+5 — does the net-twist-null
delta coincide with the flat-profile minimum within δ_min? **Gate 2 (conditional):** signed-twist
≤5 single-skip greedy fine-tune, accept iff Δmax|profile| > δ_min & |twist|≤tol. **Gate 3 (doc'd,
not in run.py yet):** is the back-loading route-anchored (relocate seamless nick) → artifact vs real.
Launch mirrors exp31/32 (`--backend CUDA --device 0 --skip-benchmark --steps-per-s 2551.7`), ~10 h,
ASK user before launching. FOLLOW-UP TECH DEBT: shipped `greedy_finetune_skips`/`identify_finetune_
edits` still rank+accept on unsigned `dev_max` (violates LESSONS A6) — needs the signed-twist variant.
