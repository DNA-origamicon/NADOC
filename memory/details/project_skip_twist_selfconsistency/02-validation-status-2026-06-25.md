# Validation status (2026-06-25) — supporting detail

[Topic head](../../project_skip_twist_selfconsistency.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Validation status (2026-06-25)

- Phases 0–3 fast pins green: `tests/test_oxdna_relaxation.py` (geometry_rmsd / bundle_twist
  / geometry_match / steering / differential), `tests/test_skip_twist_tuning.py` (builder /
  reference key-alignment / secant). `sq_lattice_periodic_skips` refactor preserves period-48
  (test_loop_skip green).
- Phase 4 real-CUDA proxy run (`2x3x40`): iter 0 (period 48) completed full relax+production,
  loop adjusted period and re-relaxed → mechanics confirmed on real hardware.
- Slow oracle: `tests/test_skip_twist_tuning_production.py` (`NADOC_RUN_OXDNA_SLOW=1`,
  needs CUDA) — proxy mechanics + `3x6x400` convergence/non-vacuity.

## Frontend: "Autorefine skips/loops" button (2026-06-25)

oxDNA sidebar button below Relax/Live/Full-Sim (`oxdna-jobs-autorefine-btn` in index.html;
handler/gating/poll/before-after render in `frontend/src/ui/oxdna_jobs_panel.js`; gated by
`getDesignLattice` dep passed from main.js → SQUARE only). Backend: `routes_autorefine.py`
(`POST /design/oxdna/autorefine/start` + `GET .../{id}`) runs `autorefine_sq_design` in a
daemon thread with an in-memory registry + on-disk result. `autorefine_sq_design`
(skip_twist_tuning.py) measures BEFORE (design as-loaded) vs AFTER (refined) and picks
`primary_metric`: `global_twist_deg` for plain SQ (no deformations), else `deviation_nm`.
`build_sq_skip_from_design` = the loaded-design build_fn; `iterate_to_constraint` gained an
`on_iteration` progress hook. Verified in-app via `frontend/e2e/autorefine_button.spec.js`
(enables on teeth.nadoc SQUARE, disables on 26hb HONEYCOMB).

## Autorefine UI — status / re-run guard / deviation map (2026-06-25)

- **Live status**: braille spinner (120 ms timer) + `Autorefine · iteration N · {substage}…` where
  substage (relaxing/equilibrating/producing) comes from polling the in-flight job
  (`current_job_id` in the autorefine status → `getOxdnaJob`), iteration N = distinct jobs seen.
  Completion glyphs ✓ / ■ / ✕. Iteration log in the result panel (period → twist°, accepted/rejected/
  early-rejected badge).
- **Re-run guard**: `_autorefineCleanForDesign` set on completion, cleared on `nadoc:design-changed`;
  a re-run with the flag set prompts "nothing has changed… run anyway?" (vs the normal long-run confirm).
- **Deviation map toggle** (`oxdna-jobs-deviation-toggle`, in the AUTOREFINE section — NOT the job-detail
  display section, which is hidden without a selected job): enabled once a run completes, gated by
  `_autorefineCompleteId` (cleared on design edit). Renders the converged design's mean structure
  recoloured green→red by per-base deviation. Backend `GET /design/oxdna/autorefine/{id}/deviation` →
  `geometry_deviation_map` (oxdna_health: per-nucleotide Kabsch deviation, shared `_kabsch_superpose`).
  `_FINAL[id]={design,job_id}` cached on completion (build_sq_skip_from_design(base, converged_period)).
  Frontend: `oxdnaDisplay.displayDeviation(resp)` (CG beads only, v1) + `deviationColorMap`/`deviationHex`
  (green→amber→red, mirrors rmsfColorMap/viridisHex). Mutually exclusive with relaxed/flex/trajectory/live.
  Pins: vitest deviationColorMap/Hex, pytest geometry_deviation_map, e2e autorefine_button.spec.js
  (status+completion+deviation+re-run guard, mocked backend).

## First-iteration seed = literature standard (2026-06-25)

`autorefine_sq_design`/route `initial_period` defaults to None → `seed_skip_period(base_design)`:
the literature-standard **48 bp** "add loops/skips" pattern when the design has no marks (so
iteration 0 starts at the standard correction, not a bare bundle), else the **existing skip
density** (total core length / marks-per-helix) so it refines in place. Verified recovery on
3x6x400: bare→48, period-48→50, period-24→25. Pin:
`test_seed_skip_period_standard_when_no_skips_else_from_density`. An explicit `initial_period`
still overrides. (`iterate_sq_skips` build-from-cells path keeps its own 48 default — no loaded
design to seed from.)

## Autorefine applies skips to the design + per-job deviation map (2026-06-25)

- **Skips land on the model (seekable/revertable/deletable).** On completion the panel calls
  `POST /design/oxdna/autorefine/{id}/apply` → `mutate_with_feature_log(op_kind='autorefine-skips',
  fn=apply_loop_skips(clear_all_loop_skips(d), sq_lattice_periodic_skips(d, converged_period)))`.
  Registered `'autorefine-skips'` in `SnapshotOpKind` (models.py) — the ONLY change needed: seek
  (`_seek_snapshot_base`), revert, delete, and the frontend feature-log panel are all op_kind-agnostic
  (snapshot-based, label-driven). Frontend `api.syncDesignResponse(applied)` refreshes editor + Feature
  Log (fires `design-changed`); set `_autorefineCleanForDesign/_autorefineCompleteId/_autorefineFinalJobId`
  AFTER the sync so the apply's own design-changed doesn't clobber them. Pin:
  `test_autorefine_apply_adds_skips_and_feature_log_entry` (asserts marks + op_kind + feature_type=snapshot).
- **Autorefine jobs in the list.** `design_source_path` now threaded route → `autorefine_sq_design`
  (`**relax_params`) → `run_relaxation` → `create_job`, so the run's jobs filter with the current design.
  On completion the panel `_fetchJobs()` + auto-selects the final job (`current_job_id`) if present.
- **Deviation map = generic PER-JOB display** (2026-06-25 redesign): `GET /oxdna/jobs/{id}/deviation`
  (routes_oxdna.py, mirrors the RMSF route — loads the job's persisted `design.json`, production_rmsf
  mean, `geometry_deviation_map` vs `core_reference_geometry`). Toggle sits below the flex toggle and is
  gated EXACTLY like flex in `_updateButtons` (any selected job with sampling, `samplingState`), fetches
  `getOxdnaDeviation(_selectedId)`. Dropped the autorefine-run-scoped `_FINAL` dict + `/autorefine/{id}/
  deviation` route + final-job gating — "view deviation after ANY job". `getAutorefineDeviation`→`getOxdnaDeviation`.

- **Live per-iteration design updates** (2026-06-25): the apply route takes an optional `?period=` and runs
  even mid-loop. `autorefine_sq_design` emits a `seed` progress event; the route's on_progress persists
  `current_period`. Frontend `_maybeApplyPeriod(runId, period)` (deduped via `_autorefineLastAppliedPeriod`)
  applies each new period live — the seed at start, then each iteration's pattern — so the user watches the
  skips move and can Stop early. Each apply is its own `autorefine-skips` feature-log entry (chain shows the
  progression; revert/seek/delete each). Pin: `test_autorefine_apply_with_explicit_period_during_run`.

## Full-scale run (3x6x400, launched 2026-06-25)

Running on real CUDA, high-confidence sampling (10M-step production/round, min_confidence
400). Build needed a longer scaffold: M13 (7249) overflows the ~7423-nt seamless path, so
`build_sq_skip_design`/`_select_scaffold` auto-pick the shortest covering library scaffold
(p7560 here). Result lands in /tmp/skip_twist_fullscale_result.json (workspace
/tmp/skip_twist_fullscale_ws). Slow oracle test: `test_full_scale_converges_3x6x400`.

## Stop / cancellation (2026-06-25)

Autorefine is cancellable: `POST /design/oxdna/autorefine/{id}/stop` sets a per-run
`threading.Event` AND calls `oxdna_runner.stop_job(current_job_id)` to kill the in-flight
relaxation/production so the stop is prompt (not deferred to the next iteration). `iterate_to_constraint`
+ `_pool_until_conclusive` gained `should_stop` (checked at iteration/pooling boundaries) and
`on_job` (reports the active job so the route can kill it); a stopped run returns
`status="stopped"` and the panel shows the best-so-far before/after. Frontend "■ Stop" button
sits next to "✦ Autorefine", revealed while running. Pins: `test_autorefine_stop_route_*` +
e2e start→stop flow in `autorefine_button.spec.js` (mocked backend, no GPU).

## Independent skip placement — already supported (for Phase 5)

The knob is only periodic by CHOICE (a single secant-tunable scalar), not by limitation. Per-position
placement is native: `Helix.loop_skips` is a list of `LoopSkip(bp_index, delta)`; place arbitrary
marks via `apply_loop_skips(design, {helix_id: [LoopSkip(...)]})`, the headless `loop_skip(helix_id,
bp_index, delta)` wrapper, or the build_spec `loop_skip` op. `sq_lattice_periodic_skips` is just one
generator of that mod dict. The Phase-5 per-region optimizer needs only the SEARCH logic (turn the
per-nucleotide deviation field into discrete add/remove-skip-here moves); the placement substrate is ready.

## "Structure blowing up" — production-stage explosion, NOT a skip bug (2026-06-26)

Symptom: running autorefine on `3x6x400_test.nadoc` (14,386 nt) showed the structure blowing up.
Diagnosis (NOT autorefine- or skip-specific):
- Span progression of a "completed" job: mc/md_relax/equil all compact [15,7,165] units; **production
  exploded to [430,354,261]** (coords ±200, past the 189 box). The structure relaxes fine then blows up
  in the unbiased production MD at dt=0.005.
- The job still read `completed` because the expansion never hit oxDNA's hard `_max_n_per_cell` abort, so
  the crash-based dt-halving (`_log_indicates_explosion`) never fired → the autorefine measured a
  blown-apart structure. The production health check passed (bp can stay paired while the bundle swells).
- **Skips do NOT cause it**: direct GPU A/B (same design, skips vs none) — both relaxed AND produced
  intact (no-skip prod span [70,22,156], period-48 [66,28,152]). It's a STOCHASTIC late-nucleating melt
  (the metastable-large-floppy-design failure mode already noted in [[project_oxdna_extra_bases]]). The
  scary 4.2 nm cross-helix bonds are a `backbone_bond_pairs` PHANTOM at compact-skip crossovers (the real
  config relaxes to a compact 15-unit structure — a real 4.2 nm FENE bond would explode at step 0).
- **Real gap (not autorefine-specific)**: skips→oxDNA *production* was never tested. The only skip test
  (`test_large_structure_skip_compaction_no_fene_violation`) is geometry-only, on a CROSSOVER-FREE bundle,
  intra-helix bonds only; the slow real-engine production test covers EXTRA BASES (loops), not skips.

FIX (oxdna_runner.py): non-aborting blow-up gate. After a `_DT_HALVE_KINDS` stage completes + passes
health, `_structure_blew_up(stage_dir, conf)` compares the final structure's max extent to the relaxed
seed's; if > `_EXPLOSION_EXTENT_FACTOR` (2.0×) → treat exactly like a crash blow-up (`_halve_dt_and_restart`
+ retry; clear failure once the budget is out). `_conf_max_extent` also catches NaN coords. Pins:
`test_structure_blew_up_detects_nonaborting_explosion` (unit) + `test_skipped_square_design_relaxes_and_
produces_intact` (slow real-engine skip+crossover production, asserts intact). Gentler default production
dt would further cut the stochastic hit rate but the detect+retry handles it without slowing every run.
