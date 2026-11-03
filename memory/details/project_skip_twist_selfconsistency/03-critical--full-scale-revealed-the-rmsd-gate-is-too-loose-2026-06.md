# CRITICAL — full-scale revealed the RMSD gate is too loose (2026-06-25) — supporting detail

[Topic head](../../project_skip_twist_selfconsistency.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
