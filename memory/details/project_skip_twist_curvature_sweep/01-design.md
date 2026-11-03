# Design — supporting detail

[Topic head](../../project_skip_twist_curvature_sweep.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
