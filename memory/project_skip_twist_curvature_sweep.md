---
name: project_skip_twist_curvature_sweep
description: "exp31 — 3x6x400 SQ skip-count sweep vs global twist + new integrated-curvature metric, across 3 placement strategies"
metadata: 
  node_type: memory
  type: project
  originSessionId: dbfe337c-0487-4baa-aff7-14ee31e09249
---

# exp31 — skip count vs twist & curvature sweep (3×6×400 SQ)

Launched 2026-06-27. Maps the total-skips → total-twist response curve around the analytical
baseline (period 48) for a fresh 3×6×400 seamless square bundle, plus a NEW curvature guard, to
understand why autorefine can't optimize past the analytical skip spacing and whether placement
strategy matters. See `experiments/exp31_skip_twist_curvature_sweep/` (hypothesis.md, run.py,
plot.py, README.md, conclusion.md-pending). Extends [[project_skip_twist_selfconsistency]] +
[[project_regional_autorefine]].

## Design
- Sweep total skips by ±18 (one deletion per helix) per step, **±4 steps** (9 points), under
  3 placement strategies; 25 sims (1 shared Δ=0 baseline + 8 points × 3). Full relax + **8M**
  production each, **no early-reject** (abort only on a falling-apart structure).
- Measures DIFFERENTIALLY (sim − analytic, keyed via `core_reference_geometry`):
  net twist (`measure_bundle_twist`) + integrated curvature (NEW).

## New code (all pure-tested, full suite green 3373p)
- `oxdna_health.measure_bundle_curvature(positions, n_slices=0)` — integrated total absolute
  curvature (deg/nm): sum |turning angle| over the slab-centroid polyline / arc length. Unlike
  `measure_bundle_bend` (endpoint deflection, ~0 for an S-bend) it catches S-bends + local kinks.
  Straight→0, uniform arc R→degrees(1/R). Pins in `test_oxdna_relaxation.py`.
- `backend/core/skip_sweep_strategies.py` — 3 strategies returning `{helix:[bp]}` for
  `build_explicit_skip_from_design`: **uniform** (restagger base_count+Δ evenly), **incremental**
  (keep baseline marks, add at largest gap / remove at smallest), **deviation** (adaptive: one
  outward round placing/removing at prior sim's per-(helix,bp) deviation hotspot). All coincide at
  Δ=0, change total by exactly Δ·n_helices. Pins in `test_skip_sweep_strategies.py` (16).
- `scripts/monitor_skip_sweep.py` — read-only watchdog (VERDICT + MONITOR_LOG; exit 0/2/3).
- `scripts/watchdog_skip_sweep.sh` — durable OS loop (mirror of watchdog_18hb.sh): polls monitor
  every 420s, relaunches a dead driver (resume-safe), exits on `results/COMPLETE` sentinel.

## Orchestration
Driver runs all 25 sims sequentially in one process (synchronous chain = "next-on-end" trigger);
deviation strategy runs each ±chain in order (round N consumes round N−1's deviation field).
Resume-safe: completed points reloaded from results.json (stores per-point `skips` +
`deviation_by_bp` so the deviation chain reconstructs). Writes `results/current.json` (active job +
expected wall-clock) for the monitor's 10%/50% checks; live PNG regenerated after each sim.

## oxDNA benchmark CUDA-proxy bug — ROOT-CAUSED + FIXED 2026-06-27
Symptom: `run_oxdna_benchmark`'s synthetic 6hb proxy CUDA trial exited code 1 → recommended CPU
(18 steps/s → ~5 days/sim, infeasible), even though real CUDA works fine
(`~/oxDNA/build_cuda/bin/oxDNA`; `test_full_scale_converges_3x6x400` ran on this 3080 Ti).
TWO root causes (both in `benchmark_runner.run_oxdna_trials`):
1. **Raw clashing proxy.** The synthetic bundle is written from RAW ideal geometry; its
   helix-junction clashes give ~1e15 starting energy. An MD trial straight onto it is unstable on
   CUDA (huge forces overflow the GPU cell list → exit 1). FIX: a short CPU MC pre-relax settles
   the proxy ONCE (oxDNA MC is CPU-only, like the real pipeline's stage 1); all trials start from
   that conf.
2. **I/O-dominated timing.** A 2k-step trial spent ~95% of wall-time writing ~100 trajectory
   frames (identical cost CPU vs CUDA) → CUDA's per-step speedup was masked → mis-picked CPU. FIX:
   new `OxdnaStageSpec.print_conf_interval_override`/`print_energy_every_override` (None→old
   behavior); the trial sets `print_conf_interval=steps+1` (no intermediate frames) so timing is
   COMPUTE. Now recommends **CUDA 409 vs CPU 28 steps/s**. Pins: `test_oxdna_relaxation.py::
   test_render_output_cadence_overrides`, `test_benchmark.py::test_run_oxdna_trials_prerelaxes_and_
   suppresses_trajectory` (+ updated sequential test for the extra pre-relax runner call).
The exp31 series was launched BEFORE this fix with `--backend CUDA --skip-benchmark --steps-per-s
2551.7` (real rate measured directly on 3×6×400, 14686 nt: 2552 steps/s → relax ~8 min, 8M
production ~52 min, **~1 h/sim, ~25 h total**). With the benchmark fixed, future runs can drop
`--skip-benchmark`. NOTE: benchmark steps/s (409, 2k-step trial, GPU shared w/ production) under-
reads the true production rate (2552) — it's only for RELATIVE backend ranking, not absolute ETA.

## Launch command (running)
```
nohup uv run python experiments/exp31_skip_twist_curvature_sweep/run.py \
   --backend CUDA --device 0 --skip-benchmark --steps-per-s 2551.7 > .../driver.log 2>&1 &
nohup bash scripts/watchdog_skip_sweep.sh --backend CUDA --device 0 \
   --skip-benchmark --steps-per-s 2551.7 > .../watchdog.log 2>&1 &
```

## Expectations under test (from prior square-lattice findings)
Square twist-zero sits near period ~24 (≈2× analytical-48), i.e. ~+8 steps beyond baseline — so
within ±4 the twist should descend monotonically toward (not necessarily cross) zero; the
analytical baseline is NOT at the twist minimum (prior live runs read +69–80° at period ~50).
Predict: curvature low + strategy-insensitive; placement shifts the twist curve (~±30° register
sensitivity per prior work) with uniform smoothest, deviation noisiest; likely no clear winner over
uniform. Disproven predictions → conclusion.md + `LESSONS.md`.

## Disk / archiving (added 2026-06-27 — ran out of disk mid-series)
Each run's job folder is ~2.5 GB (trajectory); 25 sims would blow the root disk (was 18 GB free).
FIX: the driver MOVES each finished run's job folder to the archive drive right after metrics are
saved (`run.py::_archive_run` → new sync `backend/core/job_archive.archive_job(job, ws,
"oxdna_jobs", dest_root)`; default root `/media/jojo/Archive/NADOC_archive/exp31_skip_twist_
curvature_sweep`). `archive_job` = blocking analog of `start_archive` (extracted shared
`_check_archive_preconditions`); copy-then-delete + index update, so archived runs stay
loadable/unarchivable. `--no-archive` disables. Archive drive = `/dev/sdb` (7.3T, mounted at
`/media/jojo/Archive`). Pins: `test_job_archive.py::test_archive_job_sync_*`. The 5 pre-fix runs
(baseline + uniform/incr −4,−3) were archived manually; metrics already in results.json so resume
is unaffected (it reads results.json, never job dirs). Watchdog has a disk guard (won't relaunch
if <8 GB free). NOTE: a "completed" job dir NOT in results.json = a run the driver finished but was
killed before saving (superseded duplicate) — safe to delete, the point recomputes on resume.

## KEY FINDING — twist is spatially non-uniform → local refinement warranted (2026-06-27)
The per-run twist-vs-position profiles (24-bp bins, `results/profiles/<run>.csv`; combined plot =
one overlay panel per strategy in `skip_twist_curvature.png`) revealed that the baseline
(uniform_d+0, period 48) cumulative twist is **flat over the front half and ramps in the back
half**: 0→200 bp carries ~10% (6.0°), 200→400 bp carries ~90% (51.7°) of the 57.7° total. So a
spatially-UNIFORM skip density leaves the bundle near-untwisted in front and strongly over-wound
in back — direct proof that local (non-uniform) twist correction is more appropriate for this
structure than uniform density. Logged as evidence in [[project_regional_autorefine]] (the
autorefine local-refinement doc) + experiments/exp31.../FINDINGS.md. User flagged it explicitly;
no code change made — it's a marker for future autorefine work. Profiling = `profile.py`
(`compute_twist_profile`, axis-projected NOT bp-indexed because SQ helices alternate polarity);
backfilled to archived runs via `backfill_profiles.py`.

## CROSS-ENGINE CHECK — mrdna does NOT reproduce the SQ global twist (2026-06-28)

User asked whether mrdna could drive the skip-twist loop more cheaply than oxDNA. Built
`experiments/exp31_skip_twist_curvature_sweep/mrdna_compare.py`: rebuilds the EXACT oxDNA
skip designs from `results.json` (`skips:{helix:[bp]}` → `build_explicit_skip_from_design`),
relaxes with mrdna, scores with the SAME `core_reference_geometry`/`_filter_to_reference_core`/
`measure_bundle_twist`/`compute_twist_profile` — only the engine differs.

**Result (period-48 baseline, 150 skips, 14686 nt):**
| coarse steps | mrdna twist_diff | mrdna curv | oxDNA |
|---|---|---|---|
| 2e6 | −0.12° | 1.58 | **+51.4° twist / 1.72 curv** |
| 1.2e7 | −1.19° | 1.47 | (8M prod) |

mrdna's global twist stays **≈0° even at 12M coarse steps** (mrdna default is 5e7) while oxDNA
is +51°. Twist PROFILE: oxDNA ramps to +57.7° (flat-front/back-loaded); mrdna flat at +0.19°
(`results/mrdna/twist_profile_compare.png`). CRUCIALLY mrdna **curvature is comparable** (1.47–1.58
vs 1.72) — it captures bending/global shape, the gap is **specifically the twist DOF**.

**NO-SKIP CONTROL (clinching — user-requested, /tmp/mrdna_noskip.py).** A ~0° reading on the
*skipped* design alone is AMBIGUOUS: it could mean (a) mrdna is twist-blind, or (b) mrdna captures
twist and says the analytical skips fully nullify it (disagreeing with oxDNA's +51° residual). The
discriminator is the BARE bundle (0 skips), which MUST be strongly over-wound if mrdna sees SQ twist
at all. Result: bare bundle mrdna twist = **+0.8° @12M** (−0.41 @2M) — statistically identical to the
skipped design's −1.2°, curv 1.49–1.57. Removing every skip changed mrdna's global twist by ~0°.
→ **Interpretation (a): mrdna is genuinely twist-blind here; it is NOT validating the analytical
placement.** Mechanism:
mrdna's default bead model is generated "without twist" (coarse), and even with `coarse_local_twist=
True` the soft crossover torsional stiffness (~0.05 kJ/mol/Å², see [[project_crossover_parameterization]])
lets skip strain relax locally instead of accumulating into a global supertwist — a concrete instance
of the literature's "mrdna neglects twist-stretch/twist-bend coupling" caveat.

**CONCLUSION: mrdna CANNOT stand in for oxDNA as the twist-nulling signal in the skip-twist loop**,
despite being far cheaper. It IS still viable for the curvature/shape part. oxDNA stays the twist oracle.

### mrdna-run GOTCHAS (cost real debugging — keep)
1. **`model.simulate(coarse_steps=…, fine_steps=…)` SILENTLY SWALLOWS those kwargs** — it's a
   single-stage `ArbdModel` method that runs default steps (~7s no-op → spurious ~0 twist regardless
   of step count). Use `mrdna.simulate.multiresolution_simulation(model, name, coarse_steps=,
   fine_steps=, coarse_output_period=, fine_output_period=, coarse_local_twist=)` for a real
   coarse→fine relaxation. (`scripts/benchmark_mrdna_roundtrip.py` + the round-trip tests use
   model.simulate deliberately — they only need *a* relaxation, not a specific depth.)
2. **multiresolution writes 4 stages**: `-0` coarse (5bp/bead), `-1`/`-2` fine (1 bead/bp+O bead),
   `-3` ATOMISTIC (~30× atoms, NO DCD). `_find_fine` must pick the largest stage **that has a matching
   DCD** (atomistic has none) → else psf↔dcd atom-count mismatch on read-back. Prefer the LAST fine
   stage (`-2`) on the NATOM tie.
3. Throughput on this 3080 Ti, 14686 nt: coarse ~15k steps/s, fine ~2.8k steps/s, +~73s fixed
   overhead/run (model-gen + atomistic backmap + I/O). 1.2e7 coarse ≈ 16 min/run.

## NICK-ARTIFACT TEST — REFUTED: the +51° is NOT a nick artifact (2026-06-28)

Counting audit first CONFIRMED there's no definitional mismatch: period-48 places EXACTLY the
literature density — 18 helices × 411 bp at the canonical **10.667 bp/turn** SQ pitch, **150 skips =
1 per 48 bp per helix, staggered** (offsets (i·48)//18). oxDNA genuinely converges to period ~24 = 2×.
Pitch arithmetic: period-48 corrects design 10.667→10.44 bp/turn (≈B-DNA); oxDNA's null (period 24)
→ 10.22 bp/turn — INCONSISTENT with oxDNA2's own intrinsic duplex pitch 10.55 (which alone would need
FEWER skips, null ~period 90). So the excess skip demand is NOT duplex-pitch physics.

Hypothesis tested: oxDNA2's residual +1.3°/step NICK overtwist over the design's 112 mid-helix nicks
accumulates into the spurious +51°. Test (`experiments/exp31.../ligation_test.py`): ligate all 112
co-linear nicks (152→40 strands, geometry + sequence byte-identical — only the nick backbone bonds
change), re-run same 8M-prod CUDA protocol. **RESULT: twist +51.4° → +61.9° (went UP ~20%, curv
1.72→1.28). REFUTED.** Removing nicks did not reduce the twist. Mechanism (now understood): a nick is
a single-backbone break = a point of TORSIONAL COMPLIANCE (relief valve); the nicked structure bleeds
some twist strain off by local swiveling, so ligating STIFFENS the backbone → MORE coherent global
twist, LESS bending. So oxDNA nicks net-RELIEVE global twist, not inflate it — the +1.3°/step is a
local geometric offset, dominated mechanically by the added compliance. → LESSONS-worthy: the "nick
overtwist inflates the bundle twist" intuition is backwards. Artifacts: `results/ligation/
ligation_twist_compare.png` + `ligation_summary.json`.

**CONSEQUENCE:** the +51° is robust real-structure mechanics in oxDNA, NOT a removable preprocessing
artifact. The cheap "ligate-before-measure" fix is OFF the table. Remaining possibilities: (a) real SQ
twist the 48-bp convention underestimates (oxDNA right, convention coarse — publishable), or (b) the
baked-in force-field pitch (10.55) / weave-supertwist artifact (not removable by preprocessing). BOTH
point to the ALL-ATOM MD tiebreaker (exp33 `md_twist_validation`) on the period-48 structure as the
decisive next step — NOT an engine rewrite. If atomistic also shows large residual → oxDNA right; if
~0 → force-field calibration (not "our own oxDNA").

## exp31 STATUS: paused at 17/25 (2026-06-28)
Driver exited cleanly after deviation Δ=-2 (00:46); no watchdog running, GPU freed for the mrdna
comparison. Remaining points (deviation Δ=-3,-4; uniform/incremental Δ=+2 etc.) NOT run. results.json
has the 17 done. To resume: relaunch run.py (resume-safe, reloads from results.json).

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
