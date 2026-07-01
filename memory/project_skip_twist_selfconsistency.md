---
name: project_skip_twist_selfconsistency
description: Self-consistency loop that tunes square-lattice skips until the simulated mean matches the straight analytic geometry (option a)
metadata:
  type: project
---

# Skip/loop self-consistency validation loop (option a)

Goal (user, 2026-06-25): validate that the geometry a square-lattice design *depicts*
is what the sequence design *actually produces* — and iterate skip placement until the
oxDNA time-averaged structure matches the straight analytic geometry within a tolerance.
First target: square-lattice bundles that need skips to cancel global twist. Proxy for
loop mechanics = `2x3x40` seamless; full-scale validation = `3x6x400` seamless.

**Option (a)** = the target IS the design's own analytic (B-DNA) geometry; the loop
checks the relaxed mean against it (not against an external CAD shape).

## Architecture (build → relax → produce → measure → adjust → repeat)

- **Measures** (pure, in `backend/core/oxdna_health.py`):
  - `measure_geometry_rmsd(positions, reference)` — Kabsch-superpose the mean structure
    onto the analytic reference over shared keys → RMSD (nm). The STOP gate (target 0).
  - `measure_bundle_twist(positions)` — SIGNED global twist (deg, right-handed) the
    skips control. The STEER signal.
- **Constraint layer** (same file): `geometry_match` + `bundle_twist` registered in
  `_CONSTRAINT_MEASURES` (0 landmarks, in `_REFERENCE_MEASURES`). `check_relaxed_constraint`
  gained `reference_positions=`; `_dispatch_measure` filters the mean to the reference
  core (`_filter_to_reference_core`). For `geometry_match` the verdict also carries
  `steering={bundle_twist_residual_deg}` (RMSD is unsigned → can't pick direction).
- **Loop**: `iterate_to_constraint(..., reference_fn=)` recomputes the analytic reference
  per build (skips change the nucleotide set each iteration) and threads it to the verdict.
- **Skip tuning module** `backend/api/skip_twist_tuning.py`:
  `build_sq_skip_design(cells, length, skip_period)` (seamless route + full_autostaple +
  periodic skips + full_sequence), `core_reference_geometry(design)`, `PeriodAdjuster`
  (secant on signed twist residual), `iterate_sq_skips(...)` convenience wrapper.
- **Knob** = square-lattice skip PERIOD. `sq_lattice_periodic_skips(design, skip_period=48)`
  (loop_skip_calculator.py) is now parameterized; canonical default 48 unchanged. Smaller
  period = more deletions = more de-twist. Seed 48 (`SQ_SKIP_PERIOD_DEFAULT`).

## CRITICAL gotchas (cost real debugging — keep)

1. **Reference must be keyed like the SIMULATION, not the display.** The mean structure
   (`production_rmsf`/`read_configuration_full`) is keyed by the strand walk
   `_strand_nucleotide_order` + `resolved_nuc_map`. The render-feed `_geometry_for_design`
   disagrees on ~13% of keys (display-only phantom strands + a different `is_unpaired`
   convention). Building the reference from the display feed gave only 480/552 key overlap
   AND a false **−9° analytic twist**; building it via `resolved_nuc_map(design,
   _geometry_for_design(design, compact_skips=True))` over the strand-walk order gives
   100% overlap and **~0° analytic twist** (the straight depiction reads straight).
   `core_reference_geometry` does exactly this.
2. **`measure_bundle_twist` artifacts.** Per-helix backbone spiral (~34°/bp) + the lattice's
   per-helix phase offsets masquerade as a coherent cross-section rotation. Killed by
   collapsing each `(helix,bp)` to its **base-pair midpoint** (both strands → on-axis) +
   ~1-turn (3.5 nm) slabs. Slab-centre→slab-centre spans only `(1−1/n)` of the bundle →
   rescale to full axial span (else magnitude under-reads). Designed to be used
   DIFFERENTIALLY (`twist(sim) − twist(analytic)`) so any residual offset cancels.
3. **dsDNA core = both-strands-present, defined topologically.** A `(helix,bp)` column is
   core iff the strand walk emits BOTH directions there. Drops the floppy single-stranded
   ends a SEAMLESS route leaves (ill-defined time-average; not what skips control) without
   depending on display flags. Seamless `2x3x40` → ragged helices 43–62 bp, 72 ss display
   nucleotides; the topological core is clean.
4. **Build order**: bundle → `auto_scaffold(seamless)` → `full_autostaple` → apply periodic
   skips (needs crossovers + routed dsDNA intervals) → `full_sequence` (so the sequence
   matches the post-skip nucleotide count). Skips live as `helix.loop_skips` marks; geometry
   + oxDNA read them downstream — no separate strand-graph bake needed.

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

## CRITICAL — full-scale revealed the RMSD gate is too loose (2026-06-25)

The 3x6x400 full-scale run "converged" VACUOUSLY: it returned `status=met` at the SEED period 48
(never tuned) because geometry_match RMSD = 2.35 nm < `tol_nm=3.0` — **yet the twist residual was
42.4°** (the bundle is still badly twisted; period 48 under-corrects a large bundle, exactly like the
proxy where 48 → +37° needed period 24). Root cause: RMSD-to-analytic conflates the distributed
global twist with the CG-vs-B-DNA floor and is too INSENSITIVE to global twist on a long bundle, so a
loose tol certifies a twisted structure as "matched". One iteration, ~1.5 h, result in
/tmp/skip_twist_fullscale_result.json.

FIX (DONE 2026-06-25): the loop now gates on **bundle_twist** (target 0°, `tol_twist_deg=5°`) for
plain-SQ-no-deformation designs (geometry_match RMSD kept for curved/twisted, where deviation-from-
design is the target). `check_relaxed_constraint` now computes BOTH metrics into `steering`
(`geometry_rmsd_nm` + `bundle_twist_residual_deg`) whichever gates, so PeriodAdjuster + the before/after
panel always see both. `autorefine_sq_design` + `iterate_sq_skips` pick the gate by
`design.deformations`. Re-run VALIDATED (2026-06-25, /tmp/skip_twist_fullscale_result2.json): **48 → 24, status met**.
iter0 period 48 = +49.4° twist (rmsd 3.00 nm — sat exactly on v1's old tol_nm=3.0, the smoking gun the
RMSD gate would have falsely accepted again), `early_reject=true` after 1 round (not 4). iter1 period 24
= −5.0° twist (within 5° tol), pooled 4 rounds to 400-frame confidence to accept. ~2 iterations, ~1.5 h
(early-reject ~halved it vs pooling every round). Matches the proxy (48→24). True zero ~26-28 (24 slightly
over-corrects to −5°, inside tol).

EFFICIENCY (DONE — "don't waste compute on clearly over/under-twisted runs"): two levers in
`_pool_until_conclusive` (threaded through `iterate_to_constraint`):
- **early-reject** (`early_reject_factor=3.0`): once ≥`early_reject_min_frames` are pooled and
  |measured−target| > 3×tol, short-circuit to `unmet` without pooling to `min_confidence` — high
  confidence is needed only to ACCEPT, not REJECT. A 42°-off period rejects after 1 round, not 4.
- **screen round** (`screen_steps`): the FIRST round is short+cheap. Every production stage emits
  ~100 frames REGARDLESS of step count (`print_conf_interval = steps//100`, oxdna_protocol.py:247), so a
  short round gives enough (correlated) sampling to reject a grossly-off knob fast; longer
  `production_steps` rounds add the decorrelated frames a confident ACCEPT needs. Baseline (before)
  uses a cheap `baseline_min_confidence=100`. Net: clearly-off iterations cost ~1 short round (~4 min),
  near-tolerance ones pool to high confidence. Pins: `test_pool_until_conclusive_early_rejects_grossly_off`,
  `test_check_constraint_reports_both_metrics_in_steering`.

## Autorefine testing finished — apply-route DEADLOCK fixed + full-scale re-validated (2026-06-26)

After the oxDNA skip-production blow-up gate landed, finishing the autorefine validation surfaced
TWO things:

1. **Apply-route self-deadlock (real production bug, now fixed).** `test_autorefine_apply_adds_
   skips_and_feature_log_entry` (and the other apply pins) HUNG forever — never actually green
   despite the earlier note. Cause: `apply_autorefine_skips` (routes_autorefine.py) ran the rebuild
   INSIDE `mutate_with_feature_log`'s `fn` callback, but `mutate_with_feature_log` holds the global
   `state._lock` (a plain non-reentrant `threading.Lock`) while calling `fn`, and the rebuild
   (`build_sq_skip_from_design` → `hb.scratch_session` → `set_design`/`get_or_404`) re-acquires that
   same lock → self-deadlock. In the real app, clicking "apply skips" after an autorefine run would
   wedge the backend, not just the test. FIX: build the refined design BEFORE entering
   `mutate_with_feature_log`, hand it in as a pure replacement (`fn=lambda _d: refined`). The 19
   skip-twist fast pins now pass in 0.7 s. (General hazard: any `mutate_with_feature_log` `fn` that
   re-enters `state` via scratch_session/headless build will deadlock — build outside, replace inside.)
2. **Full-scale 3x6x400 re-validated on real CUDA with the blow-up gate active.**
   `test_full_scale_converges_3x6x400` PASSED in 2:24:52 (RTX 3080 Ti). The non-aborting explosion
   detect+retry didn't break convergence. The from-cells loop (`iterate_sq_skips`) never hits the
   apply route, which is why it passed while the apply pins were deadlocked.

Full backend suite green afterward: 3219 passed / 71 skipped (slow oxDNA oracles opt-in).

## Autorefine production 400 — ROOT CAUSE was under-relaxation, not a race (2026-06-26)

User hit `✕ Autorefine error: 400: Production requires a completed relaxation job` after the
relax "finished", intermittently (~40%). Chased a red herring first (a real-but-not-occurring
`is_running` teardown race in `append_production`); the decisive diagnostic (logging ONLY the
route's 400 branch, so it doesn't perturb the passing path) showed `is_running=False`,
**`status=failed`, `stages=[…, ('4_production','failed')]`**. So the 400 is a SYMPTOM: the
iteration's production **blew up**, the dt-halving gate exhausted its retries → stage `failed` →
the loop's NEXT `_pool_until_conclusive` round appended onto a non-completed job → 400.

ROOT CAUSE: the autorefine ROUTE passes NO relax-step params, so `create_job` used its
mock-oriented defaults (**mc=100 / md_relax=100 / equil=100, min_bp_retained=0.0**) for a REAL
CUDA run. A 100-step "relaxation" leaves a skipped square bundle badly under-relaxed → its
unbiased production immediately goes unstable. The passing slow tests never hit this because they
call `iterate_sq_skips` directly with `**STANDARD_RELAX_PARAMS` AND skip the route's BEFORE-baseline
(`measure_design_self_consistency`) path. Intermittent because the blow-up is stochastic.

FIX (two parts, both in this commit):
- **(A) primary** — `autorefine_sq_design` now defaults its relax params to `STANDARD_RELAX_PARAMS`
  (`relax_params = {**STANDARD_RELAX_PARAMS, **relax_params}`; explicit caller params still win).
  Autorefine is always a real-engine run, so it must relax properly (md_relax 1e6, min_bp 0.5).
  Validated: 10/10 clean route-path runs on 2x3x40 CUDA (was ~40% failing).
- **(B) defensive** — `_pool_until_conclusive` checks the settled job after each production round
  (`if settled is not None and settled.status is not completed: return verdict, r-1`) so a
  still-failing production can't 400 the whole run; it ends as inconclusive/exhausted instead.
  (None-guard preserves the existing tests that mock `wait_for_terminal`→None.)
Pins: `test_pool_until_conclusive_stops_on_failed_production` (headless build).

## Autorefine job UX — [AR] tag + auto-select + stale-⚠ suppression (2026-06-26)

Frontend (`oxdna_jobs_panel.js`), all verified via `autorefine_button.spec.js` (mocked backend):
- **Auto-select the in-flight job** the moment it appears, and follow each new iteration's job
  (`_arSelectedJobId` guard in `_pollAutorefine`'s running branch → `_fetchJobs()` + `_selectJob`).
- **[AR] designation** in the job list for jobs created by autorefine (persistent `_arJobIds` set;
  rendered as an amber `[AR]` chip in `_jobRow`).
- **Suppress the design-changed ⚠** while a run is active (`jobOutOfDate(job) && !_autorefineRunning`):
  the loop deliberately edits the design each iteration (lands the skip pattern live), which would
  otherwise flag every job stale mid-run. Resumes normally on completion.

## Open / next

- Calibrate the geometry_match tolerance vs the oxDNA-CG-vs-B-DNA RMSD floor on a converged
  straight structure (the "degree of variability").
- Generalize beyond uniform periodic skips (per-region placement from spatial error — substrate ready,
  see above) and to bend as well as twist — deferred (Phase 5). See [[project_oxdna_extra_bases]],
  [[project_oxdna_benchmarks]].
