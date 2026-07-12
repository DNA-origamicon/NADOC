---
name: md-job-system
description: Milestone 1 MD integration — new backend modules for managed NAMD jobs
metadata: 
  node_type: memory
  type: project
  originSessionId: baf07637-75d1-45c3-9ad6-60ff363faf17
---

Implemented Milestone 1 of the MD integration plan (memory/md_integration_plan.md).

**Why:** Replace ad hoc experiment scripts with server-managed NAMD jobs that
persist through browser refreshes, run health gates automatically, and expose a
REST API.

**New modules:**

- `backend/core/md_job.py` — `MdJob` dataclass with status enum, health samples,
  segment list; persists to `workspace/md_jobs/{job_id}/job.json`.
- `backend/core/namd_metrics.py` — NAMD log parser using ETITLE/ENERGY columns;
  extracts TEMP, TEMPAVG, PRESSURE, GPRESSURE, VOLUME, TOTAL; ns/day from
  "Benchmark time: … days/ns" line.
- `backend/core/md_health.py` — C1'/WC health analysis as library functions
  (ported from exp25 scripts); `build_c1_pairs`, `build_wc_pairs`,
  `run_health_check`, `append_health_jsonl`.
- `backend/core/md_protocols.py` — `mgh_slow_release` preset: segment sequence
  (50K/100K/200K/300K NVT → 310K NPT k=5→0.05), config generation,
  `write_restraints_pdb`, `parse_box_from_namd_conf`, `prepare_mgh_slow_release`
  (calls `build_namd_solvated_package` + extracts ZIP + writes all conf files).
- `backend/core/namd_runner.py` — async segmented runner; uses
  `asyncio.create_subprocess_exec`; global `_RUNNING` dict; health gate after
  every segment; appends to `output/health.jsonl` and `output/metrics.jsonl`;
  stop via task cancellation + SIGTERM to process group.
- `backend/api/routes_md.py` — REST endpoints under `/api/md/`:
  - `POST /md/jobs` — prepare + optionally autostart (GROMACS solvation in threadpool)
  - `GET /md/jobs`, `GET /md/jobs/{job_id}` — list/status
  - `POST /md/jobs/{job_id}/start` / `/stop`
  - `GET /md/jobs/{job_id}/health` / `/metrics`
  - `GET /md/namd-available`

**How to apply:** When resuming MD job work or adding new protocol presets,
read this file and md_integration_plan.md for Milestones 2-5.

**Next milestone (2):** MD Job UI panel — Run MD button, preset selector,
job timeline, live metric cards, health gate display, WS streaming.

**Clean-stop UI fix (2026-07-04):** Stopping a running local job left the sidebar
showing a **spinning stage** + **"Unknown error"** (seen on the two stopped
`6hb_2xT` jobs `78a15b57195a`/`d097bad60cf2`). Two independent causes:
- Backend flipped `status→stopped` but never cleared `error` and left the in-flight
  segment marked `"running"` on disk. New shared helper `namd_runner.apply_user_stop(job)`
  sets stopped + `user_stopped=True`, clears `error=None`, and rewinds any `running`
  segment → `pending` (it re-runs from its checkpoint on resume). Called from ALL stop
  transitions: `_thread_main` finally (cancel), `stop_job` orphan path, and the three
  `routes_md.stop_md_job` sites (remote-disconnected, remote-scancel, local-not-in-registry).
- Frontend `md_jobs_panel.js`: a `stopped` job unconditionally showed the error box
  (`job.error ?? 'Unknown error'`), and the timeline spun on ANY `running` segment
  regardless of job liveness. Now pure `mdDetailErrorText(job)` returns null for a
  clean stop (box only when a message exists — failed submit / raced failure / legacy);
  `_renderTimeline` gates the spinner + `_segSymbol` on `mdJobIsActive(job)`, so a
  terminal job's leftover `running` segment renders as interrupted `·`, never spinning.
  This also heals already-saved bad job.json (no backend re-save needed).
  Tests: `TestOrphanStop::{test_stop_clears_error_and_reverts_running_segment,
  test_apply_user_stop_only_reverts_running_segments}`; vitest `mdDetailErrorText` block.

**Start/Stop buttons are spam-guarded (2026-07-05):** The Start + Stop buttons on
BOTH the MD and oxDNA job panels had no in-flight guard — a Stop request takes a beat
to register on the backend, so an impatient user could fire it several times. New shared
`frontend/src/ui/primitives/button_busy.js` (`runExclusive(btn, action, {label})`): a
module-level WeakSet keyed on the button element ignores re-entrant presses while one is
in flight, and it immediately disables + spins the button (`.nadoc-spinner` + `.is-busy`
CSS added to `components.css` for the inline-styled job buttons that don't carry `.btn`),
restoring the original label/disabled state in a `finally`. The 4 handlers
(`{md,oxdna}_jobs_panel.js` start/stop) now wrap their body in `runExclusive` with labels
"Starting…"/"Stopping…". Run/Prod/Seed/Archive already had their own `_launching`/`_seeding`/
disabled guards — left as-is. Pin: `button_busy.test.js` (7). MV-BTNBUSY logs the live
mash-the-button gesture (needs a running GPU job). No `main.js` change (panels are their own
factory modules).

**Resume doesn't update the detail/spinners (2026-07-04):** After clicking Start to
resume a stopped/failed LOCAL job, NAMD runs but the detail panel (stage timeline,
spinners) + live status froze — only the list rows updated. Cause: the Start handler
(and the Fix-modal "retry") did `await _fetchJobs(); _selectJob(_selectedId)`, but
`_selectJob` **early-returns when the id is unchanged**, so `_openDetailForJob` (which
opens the status WebSocket for a now-live job) never ran → no WS → no live updates.
This is the SAME failure the old "Monitoring model" note below describes, but the
`_ensureSelectedSubscription()` heal it credits **no longer exists** in
`md_jobs_panel.js` (refactored away) — so nothing re-subscribed. Fix: new
`_reselectJob(jobId)` = `_openDetailForJob(jobId)` when `id===_selectedId` (force
re-subscribe) else `_selectJob(jobId)`; Start handler + retry flow now call it. Backend
`/md/jobs/{id}/start` already sets `status=running` synchronously before returning, so
the WS opens against a live job. NOTE: still no periodic list/detail poll and no
`_ensureSelectedSubscription`, so a BACKEND auto-resume (supervisor relaunch) of a
selected terminal job won't live-update until the next `_fetchJobs` — button resume is
covered; passive auto-resume heal is a remaining gap.

**Crash/interruption resilience (added 2026-06-10):** NAMD jobs survive a
server/runner death. Three layers in `namd_runner.py`:

- **Mid-segment resume.** If NAMD is killed partway through a segment,
  `_write_resume_conf` rewrites the segment conf to read its own
  `.restart.{coor,vel,xsc}` (copied to a `<seg>.resumeN.*` input set),
  `firsttimestep` + `run upto N` runs only the remaining steps, and trajectory
  continues in a fresh `<seg>.contN.dcd` (partial `<seg>.dcd` preserved —
  display picks the newest). `_resume_step` reads the checkpoint step from
  `.restart.xsc`; returns None (fresh run) if final `.coor` exists or no restart.
- **Auto-resume on "periodic cell too small" (2026-07-06).** A full-solvation NPT
  segment (`useFlexibleCell no` + langevinPiston) shrinks the box ~3% linear as it
  relaxes to equilibrium density; NAMD fixes the patch grid at startup with only a
  tiny auto margin (~0.4 Å), so the shrink crosses the grid floor and NAMD exits
  `FATAL: Periodic cell has become too small for original patch grid!`. This is NOT
  a blow-up (T/P/energy stay healthy) and is self-healing: restarting from the
  checkpoint rebuilds the grid at the smaller box. New failure kind
  `FAILURE_CELL_SHRINK` (`md_vram.classify_failure_log`, pattern "Periodic cell has
  become too small") — kept distinct from `instability` ("Margin is too small" =
  RATTLE blow-up, which would just re-crash). In `run_job`'s `rc!=0` handler, when
  the kind is `cell_shrink` AND a usable checkpoint exists AND
  `seg.auto_resumes < MAX_CELL_SHRINK_RESUMES` (4), the job is left `running`
  (segment→running, `failure_kind=None`, `auto_resumes++`) so the supervisor
  auto-resumes it instead of dead-ending; past the cap it fails normally. Tests:
  `test_md_runner_proceeds::test_cell_shrink_*`, `test_md_vram` classifier row.
  **DO NOT "fix" this with a `margin` keyword** — a large margin crashes NAMD's GPU
  tile-list kernel on a carved box; pinned by `test_md_water_shell::test_no_explicit_margin_in_configs`
  (see [[water-shell-carve]]).
- **Orphan adoption.** A NAMD that outlived its orchestrator (dev-server reload —
  it runs with `start_new_session=True`) is detected via `/proc`
  (`_segment_process_running`) and *waited on* rather than duplicated.
  **STOP-KILL BUG (fixed 2026-07-03):** an adopted orphan's PID is never recorded in
  `_ACTIVE_PIDS` (the new worker only `_wait_for_segment_process`es it), so the old
  `stop_job` path-A killed `_ACTIVE_PIDS.get(job_id)` == `None` → it cancelled the
  wait, flipped the job to `stopped` on disk, and returned True while NAMD kept
  running on the GPU (orphaned to `systemd --user`). Symptom: Stop "does nothing",
  job shows stopped but a `namd3 …<seg>.conf` process is still live + `namd_pid` never
  cleared. Fix: `stop_job` now resolves the kill PID from `_ACTIVE_PIDS` → `_external_pid`
  (self-verifying /proc scan by conf name — catches the adopted orphan) → persisted
  `namd_pid`, and **always** kills the found process AND cancels the runner task,
  regardless of on-disk status (so a retry after a half-stop still kills). Cancel is
  issued *before* the kill so `CancelledError` beats the wait-loop's "ended without
  completing" FAILED check. Regression test: `TestOrphanStop::test_stop_adopted_orphan_kills_via_proc_scan`.
- **Auto-resume supervisor.** `resume_interrupted_jobs(workspace)` relaunches any
  job persisted as `running` with no live process and `user_stopped=False`.
  Called on startup AND every 30 s by `_md_supervisor_loop` in `main.py` lifespan.
  `reconcile_job_status` now keeps resumable jobs `running` (was `stopped`) so the
  supervisor picks them up; only `completed`/`failed`/user-`stopped` are terminal.
  New `MdJob.user_stopped` flag (set by /stop + on task-cancel, cleared by
  /start + production-append) prevents auto-resurrecting a deliberately paused job.

Recurring symptom this fixed: a long relaxation that "didn't complete" was usually
a clean inter-segment stall — NAMD finished the segment but the dev server had
reloaded, so nothing launched the next segment; it sat at `stopped` awaiting a
manual click. Investigated via `workspace/md_jobs/01968f730c8e` (18hb_42bp).

**Monitoring model + stale-state fix (added 2026-06-10):** Symptom — sidebar showed
"stopped — resume to continue from p100" while NAMD was actively running p100.
Root cause was NOT contention (backend has one writer: the runner thread, with
reconcile/supervisor guarded by `is_running` + `_external_process_running`; verified
exactly one NAMD process). It was frontend staleness:
- `md_jobs_panel.js` only opens the status WebSocket for *live* statuses; it treated
  `stopped` as terminal, and the resume action handlers called `_selectJob(sameId)`
  which early-returns — so after Resume, the panel never re-subscribed and the detail
  (incl. its old error banner) froze. Fix: `_resumeJob`/start handlers now call
  `_openDetailForJob` to force re-subscribe; new exported `isLiveStatus()` drives the
  WS decision; `_ensureSelectedSubscription()` on the 30 s prewarm timer heals any
  missed transition (dropped WS / server restart / backend auto-resume).
- Backend: `run_job` now clears `job.error` when (re)entering the running state and at
  each segment start, so a live job never carries a stale "interrupted/resuming" message.
- Validation: `tests/test_md_runner_proceeds.py` drives the full `run_job` state machine
  with a stubbed NAMD (`_run_namd_async`) + health check — asserts fresh→completed,
  mid-segment resume uses a resume conf, error clears, and re-run is idempotent. Frontend
  `isLiveStatus`/`resumeKindForJob` unit-tested; e2e `md_live_no_stale.spec.js` asserts a
  running job shows live status, no stale banner, and an open WS.

**Health scoring excludes deliberately-ssDNA residues (2026-07-04):** `md_health`
`build_c1_pairs`/`build_wc_pairs` take `exclude_residues` — the same (chain,resid)
keys `md_protocols.identify_unpaired_residues` produces (chain = segid[-1]), which
the declash ENM already excludes. `run_health_check` fills it via
`_unpaired_exclusion_set(psf,pdb)`: computes the ss set ONLY when the declash marker
`{stem}_build.pdb` exists (extra-base/declash designs), else empty → fully-duplex
designs unchanged. So crossover extra bases + other designed ssDNA can't form a
spurious geometric pair (e.g. inserted T landing near a real A across the gap) that
then "fails" and depresses the fraction. Pin: `tests/test_md_health_ss_exclusion.py`
(can-go-red: shows the spurious ss pair forms without exclusion, is dropped with it,
and the real duplex pair is restored). **CAVEAT — small effect on 6hb_2xT:** measured
on the live job `78a15b57195a` k=0.1 frame, exclusion moved WC 47.9%→48.6% (1 pair)
and C1' 77.3%→78.1% (4 pairs). The low WC is NOT the extra bases being counted — it's
that 6hb_2xT is largely UNSEQUENCED (453/656 bases default to THY), so only ~73 of 251
duplex C1' pairs are WC-complementary/scorable, and that sparse biased subset is
genuinely losing ref-relative H-bond contacts at low restraint. To trust WC as a health
signal on this design, assign the scaffold sequence first (see [[feedback-wc-calibration]]).

**Declash protocol for clashed single-stranded inserted bases (added 2026-06-11):**
Designs with extra unpaired bases at crossovers (e.g. "6hb_2xT" — 2 ss thymines
per junction via `crossover.extra_bases="TT"`) are BUILT in hard steric clash:
the geometric layer threads the inserted-T backbone through the cramped
inter-helix gap, overlapping neighbour-helix backbones (667 sub-2 Å overlaps,
P–P to 0.19 Å; 7× the passing baseline). Pinning them with the base-ring ENM
stores that strain and breaks marginal duplex pairs once dynamics starts →
health gate fails (6hb_2xT: C1' 85.2%<90, WC 77.2%<80 at first k=0.5 stage,
vs baseline 100%/95%).

Two complementary fixes, both shipped:
1. **Build geometry (`atomistic.py` `_build_extra_base_atoms`)** — extra-base
   sugar origins were `_lerp`'d along the STRAIGHT chord C3'(src)→C5'(dst)
   (through the gap); only the base *orientation* was bowed. Changed to place
   origins along the rendered bezier arc (`_arc_ctrl_pt`/`_bezier_pt`/
   `_bezier_tan`, BOW_FRAC_3D=0.3) so the loop bulges into solvent. Reduces true
   clashes 893→738 (−17%) but the RESIDUAL is the backbone minimizer
   (`_minimize_N_extra_base`) placing strained phosphate linkers (635/738 clashes
   involve a backbone atom; repel_pos only knows the same-junction opposite
   strand, not neighbour helices). Full build fix needs minimizer rework — deferred.
2. **MD declash protocol (`md_protocols.py` + `namd_runner.py`)** — the working
   route. `prepare_*(declash=True)`: detect ss bases (`identify_unpaired_residues`:
   C1' with no cross-seg partner <10.8 Å), minimise against an ss-EXCLUDED ENM
   (`{stem}_declash_k0.5.enm.extra`) so the ss bases relax out of clash (667→0).
   Runner hook after min → `rebuild_declashed_references`: overwrite `{stem}.pdb`
   from the declashed `.coor` (backup → `{stem}_build.pdb`), rebuild ss-excluded
   ENM ladder + restraints + health reference from declashed coords. Ladder runs
   the SOFT integrator (`SegmentSpec.soft` → rigidBonds none + 1 fs) because ~18
   residual ss-T↔scaffold contacts (<2.4 Å) crash rigid-bond RATTLE otherwise.
   VALIDATED on 6hb_2xT: first k=0.5 stage C1' 94.0% / WC 91.5% (both pass), vs
   85.2%/77.2% un-declashed. AUTO-ENABLED by `design_has_extra_bases(design)`
   (any crossover/forced-ligation `extra_bases`) inside `prepare_*`; the
   `CreateJobRequest.declash` flag only force-enables otherwise. Tests:
   `tests/test_md_declash.py` (pure config/IO). Soft integrator is needed
   THROUGHOUT (tight contacts persist), so the durable fix remains the build-side
   minimizer rework.

**Health gate REMOVED — now advisory only (2026-06-25):** The C1'/WC health check
no longer stops an MD run. Trigger: 2hb_noT died at a k=0.01 checkpoint on a C1'
breach despite being fine. `namd_runner.py` (both the main run loop AND the
resume/reconcile path) used to set `job.status = failed` + "Health gate failed…"
on a blocking (C1') breach. Both gates deleted — a not-passed `run_health_check`
now only logs a WARN and the ladder marches to `completed`. Health samples
(`passed`/`blocking`/`reason`) are still recorded per checkpoint; `blocking` is now
display-severity metadata, not control flow. Frontend `md_jobs_panel.js`:
`_isAdvisoryWarning` returns true for ANY `passed===false` (was non-blocking only),
so below-threshold done segments show a ⚠ dot; stage-summary row also shows ⚠ when
any of its segments warned. Test `test_c1_breach_warns_and_continues` (was
`…_still_fails_the_run`) now asserts completed + samples recorded. oxDNA runner
gate (`oxdna_runner.py:948`) left untouched — separate engine, not in scope.

**Relaxation early-stop accelerator — opt-in, default OFF (2026-07-04):** New
`backend/core/md_cutoff.py` = pure multi-criteria plateau decision
(`should_early_stop_stage(frames, wc_per_frame)` → skip only when POTENTIAL(+VOLUME)
AND WC base-pairing are BOTH flat over the trailing window; energy-alone is unsafe at
low restraint on fragile designs — 2hb_noT k=0.01). Consumes
`namd_metrics.parse_namd_log_frames` (new: returns ALL ENERGY frames, resume-seam
deduped, vs `parse_namd_log`'s last-frame-only). `namd_runner.run_job`: after a chunk's
(advisory) health check, if `job.early_stop_relax` and it's a relaxation stage's
non-final chunk (`_stage_base`/`_stage_last_chunk_idx`, `_is_production_segment` excludes
production/qualification), evaluate the plateau on that chunk's log; on a hit, mark the
stage's remaining p50/p100 chunks `done` + jump `current_segment_idx` past them
(`skip_until` guard at loop top). **Skipped-chunk glyph (2026-07-06):** a skipped chunk
also gets `MdSegmentStatus.skipped=True` (status stays `done` so all rollups/counts are
unchanged); the stage timeline renders it as a green **right-arrow `→`** instead of the
solid green circle, with a tooltip explaining the accelerator skipped it because the stage
already satisfied its plateau requirements. Decision is a pure exported helper
`mdSegGlyphKind(status,{skipped,advisory,jobLive})` (unit-tested), consumed by `_segSymbol`.
`MdJob.early_stop_relax: bool=False` (load-setdefault);
`CreateJobRequest.early_stop_relax` field → set on the job in create route. **Default OFF
= zero behavior change to existing runs** (the whole hook is under `if job.early_stop_relax`).
UI (2026-07-04): `#md-jobs-early-stop` checkbox in the MD launch Advanced card (index.html,
under "Fast relaxation"), read into the create payload as `early_stop_relax` in
`md_jobs_panel.js` (mirrors the `fast`/`autostart` toggles); unchecked by default.
Mid-run toggle (2026-07-05): `POST /md/jobs/{id}/early-stop {enabled}` →
`namd_runner.set_early_stop`. A RUNNING job can't have job.json rewritten by the route
(runner is sole writer), so it stashes `_EARLY_STOP_OVERRIDE[job_id]` which `run_job`
consumes+persists at its next chunk boundary; an idle job is written directly. UI: a
"Early-stop settled stages (live)" checkbox in the job detail (`#md-jobs-early-stop-live`,
shown only for a running local job), client `setMdEarlyStop`. **Pending-state fix
(2026-07-05):** a running chunk can be hours long, so `early_stop_relax` on disk lags
the user's intent that whole time; the old UI re-synced the checkbox to that stale flag
on every 3 s WS push → it "toggled back off". Fix: backend surfaces the queued override
as `early_stop_pending` (via `namd_runner.pending_early_stop`) in the WS payload +
`GET /md/jobs[/{id}]`; frontend `mdEarlyStopToggleState(job, busy)` (pure, unit-tested)
derives `{checked, pending}` — while the override differs from persisted (or a POST is
in flight) the toggle is shown in the REQUESTED position, `disabled` (no spam-toggle),
with a `⧗ pending` span (`#md-jobs-early-stop-live-pending`). Clears when the runner
consumes the override at the next boundary. Tests: `test_{set_early_stop_persists_when_idle,
set_early_stop_override_when_running,pending_early_stop_reports_queued_override,
runner_consumes_midrun_override}`; frontend `mdEarlyStopToggleState` (4 cases).
**Threshold recalibration (2026-07-04, from a live fast run) — LOAD-BEARING:** the first
live run (2hb_noT, `early_stop_relax` on, FAST=HMR+4fs) NEVER skipped: the old single
threshold (`eps_pot`=0.1%, `eps_vol`=0.2% for BOTH drift and scatter) sat *below* fast-run
instantaneous thermal noise (measured POT fluct ~0.13%, VOL ~0.24% even when the mean had
settled to ~0.02% drift). Fix in `md_cutoff.CutoffParams`: **separate DRIFT (mean settled —
tight: `eps_pot_drift`=0.05%, `eps_vol_drift`=0.30%) from FLUCT (thermal-noise guard —
loose: `eps_pot_fluct`=0.35%, `eps_vol_fluct`=0.50%; WC drift 0.02 / fluct 0.05)** and raise
`min_frames` 12→20 so a ~13-frame fast `p10` chunk can't trigger on too little data (skips
are judged on the fuller p50 chunk). Validated per-chunk on BOTH the live run (k0.5 p50→skip
settled, k0.1 p50→hold still-relaxing) AND the exp36 bank (18hb: all 8 non-final chunks skip;
2hb: skips settled restrained stages but HOLDS the true-zero k=0/MGHH melt stage — the
safety-critical property). Regression tests `test_{noisy_but_settled_energy_plateaus,
drifting_mean_not_plateaued_even_if_quiet}`. **A running job imports `md_cutoff` at server
start — a recalibration only affects a NEW job after a server restart.**
Motivated + validated offline by `experiments/exp36_relax_cutoff_bank/` (parser + replay on
real reference runs: 2hb 2.45× / 3x6x200 4.9× / 18hb 11.4× / 3x4SQ 29× multi-criteria
speedup; the gate self-holds fragile low-k stages, cuts hard on over-provisioned ladders).
Tests: `tests/test_md_cutoff.py` (10 — pure decision, frame parser, flag round-trip, and a
stubbed-NAMD `run_job` proving skip + flag-off-runs-all). **NOT yet exercised on a live GPU
relax run** — needs one real run with the flag on to confirm the skipped structure matches a
full run's endpoint (owes an MV row). [[md-prep-relaxation-exp29]], [[oxdna-relaxation]].

**Fast production runs — HMR + GPUresident + 4 fs (2026-07-02):** production was
pinned at ~1.3 ns/day because `_conservative_production_conf`/`_seed_production_conf`
in `routes_md.py` never got the fast-relaxation treatment — they ran `rigidBonds
none` + `timestep 1.0` + no GPUresident (CPU-integrated 1 fs). Applied the shipped
fast-relaxation win (`md_protocols.write_hmr_psf` + GPUresident + 4 fs) to the
production path:
- `_production_fast_plan(job, body)` decides eligibility from the manifest: fast is
  the DEFAULT; a **declash / soft-integrator** relaxation (manifest `declash` or any
  segment `soft:true`) falls back to conservative 1 fs (HMR + rigid bonds crash
  those flexible-bond structures). Also `from_seed` → conservative.
- `_production_steps_and_ns(body, timestep_fs)` now takes the timestep so a
  requested `length_ns` maps to 1/4 the steps at 4 fs (same simulated ns, ~4× fewer
  steps). Callers pass the plan's timestep.
- `_append_production_segments(job, plan, …)` (signature changed from `total_steps`
  int → `plan` dict): if fast, reuse `{stem}_hmr.psf` from a fast relaxation ladder
  or build it once via `write_hmr_psf`; write fast confs (HMR PSF + `rigidBonds all`
  + `timestep 4` + `GPUresident on` + `fullElectFrequency 2`). **Electrostatics
  (PME grid 1.0, cutoff 12, barostat coupling) are LEFT IDENTICAL to the
  conservative run** — same production ensemble, only integrator/throughput knobs
  move. Manifest `production_extension` gains `fast_production{…}` + `settings:
  "fast_hmr_gpuresident_4fs"`.
- Runner needs NO change: health check keys off the original `{stem}.psf`/pdb (HMR
  only rewrites masses, not topology/coords/order); resume (`_write_resume_conf`)
  preserves the structure line + GPUresident (neither in `_RESUME_DROP`).
- Compounding win: 4 fs (4×) × GPUresident (~3×) × MTS ≈ ~10× → 1.3 → >16 ns/day.
- Tests: `test_md_milestone1.py` — `test_appended_production_uses_fast_hmr_settings_by_default`,
  `test_declash_job_falls_back_to_conservative_production`, updated steps/ns test.
  Full suite green (3523 passed). NOT yet benchmarked on a real GPU production run —
  the ns/day claim is projected from the fast-relaxation validation, not measured
  on this production path.

**Disk-space guard + forecast (2026-07-02):** new `backend/core/disk_guard.py`
owns the whole "will this run out of disk" policy for BOTH engines:
- Thresholds: `WARN_MIN_FREE_BYTES=10 GiB` (pre-run popup), `ABORT_MIN_FREE_BYTES=5
  GiB` (in-run kill), `GUARD_POLL_S=15`, sentinel `DISK_ABORT_RC=-99`.
- `free_bytes(path)` (walks to nearest existing ancestor; returns 1<<62 on OSError
  so a stat hiccup never aborts a run). `namd_run_output_bytes(segments, n_atoms)`
  (DCD ≈12·n_atoms+80 B/frame + 48·n_atoms restart/seg, ×1.15 safety);
  `oxdna_run_output_bytes(stages, n_nt)` (~130 B/nt/frame; oxDNA prints ~100
  configs/stage so it's bounded/small — the warn rarely fires for CG, but the
  abort guard still protects a near-full disk). `forecast(dir, predicted)` →
  {free_bytes, predicted_bytes, free_after_bytes, warn, …}.
- `wait_proc_with_disk_guard(proc, dir, kill=…)` wraps `proc.wait()`
  (`asyncio.wait_for` polled): on free<floor it kills the process group and
  returns `DISK_ABORT_RC`. Called from BOTH `_run_namd_async` and
  `_run_oxdna_async` (replacing the bare `await proc.wait()`).
- Runners also do a **pre-launch floor check** before minimization + each
  segment/stage (`namd_runner._disk_floor_ok`; inline in oxdna_runner) and map
  `DISK_ABORT_RC` → `status=failed`, NAMD `failure_kind="disk_full"`, with a
  "free up space then resume" error. In oxDNA the sentinel is handled BEFORE the
  crash-retry block so it doesn't trigger dt-halve / relax-escalation.
- Forecast endpoints: `POST /md/jobs/estimate-disk` (relax; active design +
  `mgh_slow_release_segments` + `estimate_profile_from_design`),
  `POST /md/jobs/{id}/estimate-production-disk` (exact PSF `!NATOM` count),
  `POST /oxdna/jobs/estimate-disk`, `POST /oxdna/jobs/{id}/estimate-run-disk`.
  All best-effort → `skipped:true` / warn=false on any error (never block a launch).
- Frontend: `job_activity.js` gains pure `diskWarningMessage(forecast)` +
  `confirmDiskSpaceOk(forecast)` (reuses `showConfirm`), mirroring
  `confirmNoConcurrentJob`. Wired into 4 launch handlers (MD relax/production,
  oxDNA relax/production) right by the existing concurrent/GPU confirms. Client
  fns: `estimateMdDisk`, `estimateMdProductionDisk`, `estimateOxdnaDisk`,
  `estimateOxdnaRunDisk`. Tests: `tests/test_disk_guard.py` (9),
  `job_activity.test.js` diskWarningMessage block. VERIFIED via curl on a real
  job: 100 ns production → predicted 24.7 GB vs 20.6 GB free → warn:true; 1 ns →
  warn:false. In-browser popup click NOT hand-exercised.

**MD↔oxDNA panel unification + viz radios (2026-07-02):** made the MD job list
mirror the oxDNA panel's indented parent→child hierarchy, and both panels' display
toggles mutually-exclusive radios in a "Visualizations & processing" card.
- `MdJob.parent_job_id` (new field; `new_job(parent_job_id=…)`, load-setdefault).
  `routes_md._spawn_prep_job(parent_job_id=…)`; the **refit** endpoint passes
  `parent_job_id=<old job id>` so a refit/retry-derived job nests under its origin.
  (SUPERSEDED 2026-07-07 — production now ALSO spawns a nested child job, not
  same-job segments; see "Production = child job" below.)
- Frontend: `flattenJobTree`/`descendantIds` moved out of `oxdna_jobs_panel.js` into
  shared `ui/job_tree.js` (re-exported from the oxDNA panel for existing importers;
  `job_tree.test.js`). MD `_renderList` rewritten to flatten + indent by depth via a
  new `_jobRow` (mirrors oxDNA), children labelled `Refit N` (`mdChildRowLabel`,
  global run number). Removed the old flat `slice(0,8)`.
- Radios: `index.html` viz toggles for BOTH panels are `type=radio` sharing a group
  name (`md-viz` / `oxdna-viz`) inside an `.ox-card` titled "Visualizations &
  processing", plus an explicit **Off** radio (`*-viz-off`, checked by default).
  oxDNA views = display/flex/deviation/traj; MD views = display/flex/traj. oxDNA
  "Align to design pose" stays a checkbox (a display modifier, not a view). The
  existing per-view "on" handlers already tore the others down; added an Off-radio
  handler (`_allDisplaysOff` on oxDNA; the three teardowns on MD) and a
  `_syncVizOffRadio()` called from every `_setXOff`/guard-return so the group always
  shows a selection after a programmatic turn-off. Element IDs unchanged, so all the
  intricate display/prewarm `.checked` reads keep working.
- LAYOUT (unified 2026-07-02 follow-up): the viz card is now a **collapsible
  `ox-card` positioned directly below the Jobs list** in BOTH panels (MD: after Jobs,
  before Advanced; oxDNA: between Jobs and Health — pulled OUT of `#oxdna-jobs-detail`
  so it's always visible). Collapse wiring added to each panel's Jobs/Health toggle
  loop (`{md,oxdna}-jobs-viz-toggle`/`-body`/`-arrow`, start open, non-persistent).
  GATING: with no job selected only "Off" is selectable — MD `_updateVizToggles(job=
  _selectedJob())` disables display when `!job` and flex/traj when no trajectory
  (called from `_applyJobState`, `_clearSelectedJob`, and once at init); oxDNA
  `_updateButtons` already gated flex/traj/deviation on `samplingState`/`hasTrajectory`
  (null-job → disabled), and the display radio now also gates on `!!job` (was liveOn
  only, fine when the card was hidden in the detail). `_syncVizOffRadio()` keeps Off
  checked whenever nothing is selectable.
- Verified: `test_md_milestone1.py::TestMdJob` (8, incl. parent_job_id roundtrip),
  full frontend vitest 1853 green, `just smoke` 22/22 (console-error gate), and a
  throwaway Playwright spec against the live app confirming both cards render, the
  radios are grouped/mutually-exclusive, Off is default-checked, and select→Off
  round-trips (spec deleted after).

**Early-stop restart-chain fix (2026-07-05):** The relaxation early-stop
accelerator (`early_stop_relax`; `md_cutoff.should_early_stop_stage`) marks a
plateaued stage's trailing p50/p100 chunks `done` WITHOUT running NAMD, then jumps
to the next stage. But each stage's first chunk conf was packaged to restart from
the *previous stage's LAST chunk* (e.g. `02_p10` reads `01_..p100.{coor,vel,xsc}`).
Skipping that last chunk meant its restart files never existed → NAMD `FATAL ERROR:
Unable to open extended system file` (job `3f4d932cd76c`). Fix:
`namd_runner._alias_skipped_stage_outputs()` copies the last *completed* chunk's
final coords onto every skipped chunk's expected output names (plain + `.restart.`)
so the chain stays intact; called from the skip block in `run_job`. Pinned by
`test_early_stop_skips_remaining_chunks` (asserts the bridge files exist).

**Host-OOM bounded auto-resume (2026-07-07):** A host pinned-memory OOM (`FAILURE_HOST_OOM`,
`cudaHostAlloc` in bonded-CUDA staging — [[water-shell-carve]]) is usually a TRANSIENT host
starvation (the identical alloc succeeded on the previous segment; the supervisor's ~30 s relaunch
cadence lets pressure clear). `run_job`'s `rc!=0` handler now mirrors the cell-shrink block for
`host_oom`: leave the job RUNNING (segment→running, `failure_kind=None`, `auto_resumes++`), bounded by
`MAX_HOST_OOM_RESUMES=3`, past which it fails normally with the host-OOM Fix popup. UNLIKE cell-shrink
it does NOT require a mid-segment checkpoint — a step-0 death (no restart files) re-runs the segment
fresh from the previous segment's coords. Also `_free_host_ram_for_namd` releases NADOC's atomistic
cache before each spawn when RAM is low (see [[md-live-model-cache]]). Tests:
`test_host_oom_auto_resumes_without_a_checkpoint`, `test_host_oom_gives_up_after_resume_cap`.
Diagnosis of the original failure: WSL2 24 GB box, 404k ENM springs; real error was host pinned RAM,
NOT the "3.0 GB / 8.0 GB card" the old classifier misreported.

**Production = child job (mirrors oxDNA `/oxdna/jobs/{id}/run`) — 2026-07-07:** MD
production used to APPEND p10/p50/p100 segments onto the SAME relaxation `MdJob`, so
the relaxation stopped being a distinct entry and you couldn't fan out several
productions. Now the Production button spawns a **child `MdJob`** seeded from the
parent's equilibrated checkpoint, exactly like oxDNA's child runs — the relaxation
stays a selectable root row and each production nests under it.
- **Endpoint** `POST /md/jobs/{parent_id}/production-run` (`routes_md.spawn_md_production`,
  body `ProductionRunRequest{steps,length_ns,autostart}`). Resolves the seed coords via
  `_production_seed_checkpoint(parent)` — a relaxation parent → `_production_ready_checkpoint`;
  a completed production child → `_completed_production_checkpoint` (so selecting a finished
  production and clicking Production **chains** a fresh run off its end state). Reuses
  `md_ensemble.build_replica_package` VERBATIM (single seed) to build the production-only
  child package (reseed conf in the `minimization` slot → one production segment). Child gets
  `parent_job_id=parent`, `run_kind="production"`, a distinct velocity `ensemble_seed`
  (`54321+N` where N = existing production siblings → independent trajectories), takes its
  run target from the request; local + autostart → `start_job` immediately. Parent job is
  NEVER mutated (its segments/manifest untouched) — verified live on `c0e02dadf996` (2hb_noT).
- **Alpine target (fix 2026-07-07):** the Production button must honor the panel's
  Local/Alpine radio (`_currentRunTarget()`), NOT the parent's target — a locally-relaxed
  structure is commonly produced on Alpine. `ProductionRunRequest` gained
  `execution_target`/`cluster_name`; `spawn_md_production` sets `child.execution_target =
  body.execution_target or parent's or "local"` and **only autostarts when target=="local"**
  — an `alpine` child is left `queued` (no `start_job`) for the submit-review card. Frontend
  prodBtn: reads the radio, skips the local disk/concurrent guards for Alpine, passes
  `execution_target`+`autostart:isLocalRun`, and on an Alpine spawn opens
  `_submitReview.open(childId)` (same card the relax/ensemble Alpine paths use → resource
  sizing + SLURM submit; Duo needed). Bug it fixed: the first cut inherited the parent's
  `execution_target`, so selecting Alpine still launched a LOCAL production. Test
  `test_production_alpine_target_queues_without_local_start` (queued alpine child, `start_job`
  never called); verified live (child `queued`, exec=alpine, namd_pid None).

**Ensemble/remote readout UX (2026-07-07, frontend-only):** the detail panel was built for
a single LOCAL job; selecting an ensemble parent or a remote replica mis-behaved. Fixes in
`md_jobs_panel.js`:
- **No local WS for cluster jobs.** `_openDetailForJob` opened `ws://…/ws/md-jobs/{id}` for
  any non-terminal job, but a job handed to SLURM (`slurm_job_id` set) pushes nothing locally.
  Now gated on `!job.slurm_job_id` — a remote job's detail is refreshed by the SLURM poll
  (`_maybePollRemote → _applyJobState`), not a dead WS. (A LOCAL prep of an Alpine relaxation,
  no slurm id yet, still gets its WS for the solvation bar.)
- **Remote in-flight jobs show a note, not a perpetual spinner.** A running Alpine replica has
  0 local health_samples (metrics live on cluster scratch until results fetch), so `mdJobIsActive`
  true + no metrics → the old code span "Waiting for first metrics…" forever. New pure
  `mdHasLocalReadouts(job)` (local always; remote only once `health_samples` present) +
  `mdRemoteReadoutNote(job)`; `_renderMetrics` short-circuits to the note ("Running on Alpine
  (SLURM …) — live metrics aren't streamed for cluster runs…") + `_setHealthSpinner(false)`.
- **Ensemble roll-up in the detail.** New `#md-jobs-ensemble-rollup` + `_renderEnsembleRollup(job)`:
  when a parent OR one of its replicas is selected, lists every replica (`mdReplicaRowLabel` /
  `mdProductionRowLabel`) with its SLURM state (`mdReplicaStateText`), clickable to jump. Header
  reuses `ensembleChildSummary`. Pure `ensembleReplicas(job, jobs)` (sorted by ensemble_index).
  So selecting the "N replicas" parent reads as the ensemble, not just the underlying relaxation.
- Pins: `md_jobs_panel.test.js` (+4 blocks: mdHasLocalReadouts / mdRemoteReadoutNote /
  mdReplicaStateText / ensembleReplicas). VERIFIED LIVE against the 4-replica 6hbx100_1xT
  ensemble (parent roll-up lists 4 RUNNING replicas w/ SLURM ids; replica shows the Alpine note;
  no local WS opened for a cluster job). **Watch:** when a replica finishes, local health/metrics
  populate only if the backend fetches results on SLURM completion — confirm that path once a
  replica completes so the grid fills in (else it stays on the note).
- **New `MdJob.run_kind: Optional[str]=None`** (load-setdefault; `new_job(run_kind=)`).
  `"production"` marks a production child; None = relaxation / refit / Alpine ensemble replica.
- **Old `append_md_production` (`/md/jobs/{id}/production`) endpoint kept** (still client-exported
  + doc-header-tested) but the app no longer calls it.
- **Frontend:** `client.spawnMdProduction`; the prodBtn handler calls it then selects the NEW
  child. `_renderProductionControls` gates on `production_ready || production_continue_available`
  (chain mode) — the old `continue_from_production` checkbox (`#md-jobs-prod-continue`) is GONE,
  replaced by a static hint. New pure helpers `mdIsProductionChild(job)` (run_kind check) +
  `mdProductionRowLabel` ("Production N · seed S"); `_jobRow` branches label/title on it.
  `mdIsEnsembleReplica` still matches production children (ensemble_seed set) so they indent +
  collapse under the parent via `flattenJobTree` — but auto-collapse is now scoped to
  Alpine ensembles ONLY (a production fan-out keeps the just-started child visible).
  `ensembleChildSummary` says "N production runs" vs "N replicas" by child kind.
- **Tests:** `test_md_milestone1.py::TestProductionAppend` (+4: child-created-parent-intact,
  distinct-seeds, autostart-launches-local, refused-while-running); vitest
  `md_jobs_panel.test.js` production-child block (+4). Full backend `just test` green apart
  from 2 pre-existing xdist cross-file ordering flakes in `test_md_executor.py`
  (`test_remote_recommendation_unknown_{profile,partition}` — pass in isolation, unrelated
  cluster-recommendation code). NOT hand-clicked in the browser, but the full backend path +
  rendered data shape were exercised live via curl against a real completed relaxation.
  [[alpine-cluster-submission]] (ensemble replica machinery this reuses).

**Legacy-job migration — revert appended production (2026-07-07):** Jobs created before
the child-model have production p10/p50/p100 segments APPENDED onto the relaxation, so
they show as ONE combined entry. `md_job.revert_appended_production(job, ws)` peels them
back to a clean completed relaxation: drops the production segments from `job.segments` +
`manifest["segments"]`, removes `production_extension`, restores `status=completed` /
`current_segment_idx=len(relax)` / `user_stopped=False` / `error=None`. **Non-destructive**
— the production confs/logs/output are MOVED (`Path.replace`) to
`{job_dir}/_superseded_production/` (preserving the package-relative tree), NOT deleted, so
a stopped-mid-run partial trajectory is recoverable. Dot-prefixed output globs
(`output/{name}.`) so a `_p10` segment never sweeps `_p100` files. Idempotent; refuses a
production child (`run_kind=="production"`) or any derived job (`parent_job_id`) so it can't
nuke a legit run. Helper `segment_is_production(job)` / `_is_production_segment_name`.
Endpoint `POST /md/jobs/{id}/revert-production` (`routes_md.revert_md_production`, 400 if
running / nothing to revert). Frontend: pure `mdHasAppendedProduction(job)` (root relaxation
carrying a production segment) gates a `#md-jobs-revert-prod-btn` "⧉ Separate production into
its own run" button in the production box (`_renderProductionControls`), `client.revertMdProduction`,
`window.confirm` + toast, reselects the now-clean relaxation. Tests: `test_md_milestone1.py`
(+2: restores-clean-relaxation incl. p10/p100 glob + backup-not-deleted + relax-checkpoint-intact;
idempotent-and-guards-children); vitest `mdHasAppendedProduction` (+4). VERIFIED LIVE on
`a0e54cdbf20f` (6hbx100_1xT): 15→12 segs, 80 MB partial production moved to backup, then a
fresh production child spawned off the cleaned relaxation.

## ⚡ Implicit-solvent (GBIS) protocol — no-water relaxation for small GPUs (2026-07-11)
Third protocol `implicit_gbis_namd` (`IMPLICIT_GBIS_PROTOCOL`, in `md_protocols.SUPPORTED_PROTOCOLS`).
**Why:** a large single-layer origami (e.g. GT_corner_v2, ~287k DNA atoms) in explicit water balloons to
~1.9M atoms and NAMD dies at `buildTileLists` on an 8 GB GPU (VRAM). GBIS (Generalised Born) drops the
system to DNA-only, so it fits. Trade-off (stated in UI/manifest): **no explicit Mg²⁺** → relaxation/
minimise engine, not a Mg-stability model.
- **Builder:** `backend/core/namd_gbis.py` (NEW module — kept out of the md_protocols god-file).
  `build_namd_gbis_package` reuses `build_charmm_psfgen_topology` (the SAME H-complete dry PSF/PDB the
  explicit strict path builds *before* solvation) → copies forcefield → ENM (`write_aksimentiev_enm_files`)
  → **NVT-only** ladder (`mgh_slow_release_segments(nvt_only=True)`, no barostat in implicit) → GBIS confs.
  `prepare_implicit_gbis_namd` is the protocol entry (accepts+ignores the explicit-solvent kwargs so
  routes_md passes one uniform kwarg set). Salt: `ion_conc_mM`→GBIS Debye `ionConcentration` (M), else 0.15.
- **Conf change:** `md_protocols._common_header(gbis=…)` swaps the periodic-box+PME block for the GBIS block
  (`gbis on / alphaCutoff 14 / ionConcentration / solventDielectric 78.5`, cutoff 16/switch 14/pairlist 18,
  NO cellBasisVector, NO PME, NO wrapWater). Threaded through `_min_conf`/`_segment_conf`; NPT + fast/HMR
  (GPUresident) forced OFF under GBIS.
- **Prep phases:** `build_prep_phases(implicit=True)` drops `solvate`+`assemble` (→ topology·enm·finalize,
  n_phases=3). routes_md also **skips the `auto_water_shell` VRAM preflight** for GBIS (no water box; that
  preflight is SLOW on large designs — builds the full atom model to count).
- **Dispatch:** routes_md `_prepare_job_bg` maps protocol→prepare fn (gbis branch lazy-imports namd_gbis).
- **⚠️ Runs on the CPU NAMD build, NOT CUDA.** GBIS is unsupported on the NAMD 3 CUDA nonbonded kernel
  ("Warning: Always using force tables … unsupported config parameters" → `buildTileLists` illegal-memory
  crash on the FIRST step) EVEN at 445k atoms (so it was never a VRAM problem — atom count is irrelevant
  to that crash). `namd_runner.find_namd(prefer_cpu=True)` returns the first non-CUDA (`…-multicore`) build
  and `run_job` passes `run_devices=""` (no `+devices`) for `implicit_gbis_namd`; raises a clear error if
  only a CUDA build is installed. VERIFIED: same GT_corner_v2 GBIS package → CUDA build crashes at
  buildTileLists; `…Linux-x86_64-multicore` build minimizes fine (clash count falls, GBIS energy finite).
  **Caveat:** CPU GBIS is slow — minimize (4800 steps) is minutes, but the full 12-segment ×2.4M-step
  ladder is impractical on CPU; use it to minimize/declash a seed + short relax (early-stop), not full
  production. See [[LESSONS]] K4.
- **Frontend:** third `<option value="implicit_gbis_namd">` in the Protocol `<select>` (`#md-jobs-preset`,
  index.html) — flows straight into the payload `protocol` + restores via `_maybePrefillDraft`. Pure
  `isImplicitSolventProtocol()` grays the explicit-only knobs (salt/mg/nacl/padding/watershell/fast) via
  `_syncSolventFields()` on preset change.
- **Tests:** `tests/test_md_gbis.py` (7: registered, phases drop solvation, dry PSF has no water/Mg, every
  conf is GBIS-not-PME, NVT-only ladder, ENM present+referenced, salt maps mM→M); vitest
  `isImplicitSolventProtocol` (+1). Backend prep VERIFIED headless (no GROMACS) + live via the API on
  GT_corner_v2 (n_phases=3 confirmed). **App click-through of the dropdown NOT yet exercised live** (option
  is served + payload wiring is unit-tested).
- **Known cosmetic:** GBIS segments inherit the explicit ladder's names (`…_300K_NPT_ENM_…`, `…MGHH_only`)
  from the shared `mgh_slow_release_segments`; the confs are correctly NVT/GBIS but the stage LABELS still
  say NPT/MGHH. Left as-is to avoid touching the shared segment naming (resume/manifest key on it).

## ⚡ Compute: GPU/CPU selector (any protocol can run on the CPU build) — 2026-07-11
Generalised the GBIS CPU routing into a first-class **Compute** choice, because the CUDA `buildTileLists`
crash is NOT memory (K2). PROVEN: the SAME 1.72M-atom explicit shell-solvated GT_corner_v2 that crashes on
the CUDA build **minimizes fine on the `-multicore` build** (real water + Mg²⁺ intact, energy dropping).
So CPU is a valid escape hatch for ANY protocol on a system the GPU can't take.
⚠️ The old "large lateral footprint / too many patches" explanation is **superseded** — see the GPU
pre-flight probe section below and K2. The crash is not a function of the patch grid at all.
- **Encoding:** the job's `devices` string carries the choice — `"cpu"`/`"none"` → CPU build; GPU ids
  (`"0"`, `"0,1"`, empty=auto) → CUDA build. `namd_runner.job_wants_cpu(protocol, devices)` (GBIS always
  True) + `resolve_namd_launch(protocol, devices) → (namd_bin, run_devices)` pick the binary robustly across
  ALL install combos: both builds present (honour choice); CPU-only machine (GPU request degrades to
  multicore, no `+devices`); CUDA-only machine (explicit CPU request best-efforts to GPU; GBIS raises).
  `run_job` calls the resolver.
- **auto_water_shell is now CPU-aware** (`md_vram.py`): `devices="cpu"` → skip VRAM, size the carve to
  **host RAM** (`max_atoms_for_host_ram`) — the carve still helps (fewer atoms = faster CPU). routes_md's
  preflight runs for CPU too (only GBIS skips it entirely — no water box).
- **Frontend:** `#md-jobs-compute` `<select>` (GPU (CUDA) / CPU (multicore)) in the Advanced drawer. Pure
  `deviceStringForCompute(compute, cudaDevices, protocol)` builds the payload `devices`; `computeFromDeviceString`
  restores it for drafts. GBIS forces Compute=CPU + **disables the GPU option** (auto-reverts a prior GPU
  pick) and grays the CUDA-device field, via `_syncSolventFields()` (bound to preset+compute change). The
  GPU-busy confirm is skipped for CPU runs.
- **Tests:** `test_namd_discovery.py` (job_wants_cpu param table + resolve_namd_launch across every build
  combo, incl. degrade/raise); `test_md_vram.py` (CPU sizes to host RAM not VRAM; no-host → full box);
  vitest `deviceStringForCompute`/`computeFromDeviceString`. **Managed CPU explicit run VERIFIED live** end
  to end (job 598… → prep w/ CPU host-RAM shell → `Linux-x86_64-multicore` binary → minimizing, 0 FATAL).
  Compute dropdown served in-app; **the GBIS→force-CPU dropdown INTERACTION not click-verified live** (pure
  logic is unit-tested + served).
- **Benchmarks (RTX 2080 SUPER 8 GB / 8-thread CPU, NAMD 3.0.2):**
  - Small explicit 4hb, **103,745 atoms**, 1200-step min: **GPU 12.0 s vs CPU 115.8 s → GPU ~9.7× faster**.
    → Use GPU whenever the system fits; CPU is the fallback, not the default.
  - GT_corner_v2 explicit shell, **1,716,606 atoms**: GPU **crashes** (footprint); CPU **1.43 s/step**
    (2400-step min ≈ 57 min). GBIS variant (445k atoms) is ~4× lighter on CPU.
  - Takeaway: on this 8 GB card GT_corner is CPU-only either way (explicit=tile-list crash, GBIS=CUDA-
    unsupported). Explicit-CPU gives Mg but is ~4× heavier than GBIS-CPU; the full MD ladder is impractical
    at 1.7M atoms on CPU — use CPU for minimize/declash + short relax. See [[LESSONS]] K2, K4.

## 🧠 GPU-resident needs PINNED host RAM — probe it, and downgrade 4 fs → 2 fs (2026-07-12)
The fast segments (HMR + `rigidBonds all` + 4 fs + **`GPUresident on`**) pin a large host buffer.
**A host's pinned pool is NOT its free RAM**: this WSL box pins only **1.0 GB** with 15 GB free
(`ulimit -l` is 64 MB yet CUDA pins 1 GB → RLIMIT_MEMLOCK is not the constraint; it's the WSL2
driver's pool, unraisable). Above ~800k atoms NAMD dies at segment **start**:
`FATAL ERROR: CUDA error cudaMallocHost(...) in CudaUtils.C, allocate_host_T, line 88`.
Measured ceiling: 380k/541k/756k RUN · **971k FAILS**; GT_corner_v2's 1.44M-atom relax package fails.

- **INVARIANT — `GPUresident off` alone is NOT a valid fallback.** The 4 fs timestep survives only
  under GPU-resident's GPU constraint solver; the CPU RATTLE path dies instantly with
  "Constraint failure in RATTLE algorithm for atom N". Verified from a real checkpoint: 4 fs fails,
  **2 fs runs**. (`strip_gpu_resident`'s docstring used to claim otherwise — it was wrong.)
- **What ships:** `namd_runner.gpu_resident_probe()` (one cycle of the first fast conf, ~60 s, cached
  as `.gpu_resident_probe.json`) → on failure `downgrade_gpu_resident_confs()` rewrites every fast conf
  via `md_protocols.downgrade_gpu_resident()`: drop GPUresident, **4→2 fs, and ×2 on `run` +
  `dcdFreq`/`restartfreq`/`xstFreq`/`outputEnergies`** so the segment covers the SAME simulated time and
  writes the SAME frame count. HMR/rigidBonds/PSF/PME/barostat untouched → physics unchanged. Originals
  kept as `<name>.conf.gpuresident`.
- **Probe, don't threshold:** the ceiling is a property of the HOST, so an atom-count cutoff fitted here
  would be wrong on the 3080 Ti box. Tests: `tests/test_md_gpu_resident.py`. See [[LESSONS]] K6.

## 🔬 GPU pre-flight probe — the Compute decision is now PRINCIPLED, not manual (2026-07-11)
Root-caused the CUDA `buildTileLists` crash with `compute-sanitizer` and replaced the blunt manual toggle
with an empirical pre-flight. **Read this before touching GPU/CPU routing.**

**The crash.** NAMD counts tile lists on the CPU (to size the kernel's loop) but fills them on the GPU.
When the CPU count is larger, the tail of `tileLists[]` is never written; the kernel reads those **zeroed**
entries and dereferences them into `boundingBoxes` far out of bounds (measured: index 184,320 into a
13,166-entry array) → `cudaErrorIllegalAddress` on the first step. `boundingBoxes` is unguarded in that kernel.

**INVARIANT — do not re-derive this.** The crash is **NOT a function of the patch grid**, so any
`patch_grid_is_gpu_safe(Px,Py,Pz)` API is unsound. Decisive test: box held byte-identical (grid 26×3×34,
P=2652), only the water shell varied → 0.5 nm/380k atoms **CRASH**, 1.0 nm/611k **RUN**, 1.5 nm/782k **RUN**.
Same geometry, opposite verdicts; *adding* atoms can fix it. The real variable is the tile-list count
≈ `14·P·⌈atoms/(32·P)⌉`, and it fails in **BANDS** (safe <~183k · CRASH ~186k–250k · safe ~251k–333k ·
CRASH ~360k+), not above a threshold. That estimate separates 34/35 measured configs but mispredicts
carved-shell systems (uneven per-patch density) — it can **flag risk but never certify safety**, which is
exactly why routing on a formula was rejected. NAMD 3.1 does **not** fix the bug upstream.

**What ships.** `namd_runner.gpu_tilelist_probe(package_dir, min_name, namd_bin, devices, threads)` runs ONE
minimization cycle on the GPU (NAMD rejects step counts that aren't a multiple of `stepspercycle`, hence one
cycle) with `outputName` diverted to a scratch stem so the real `output/` is never touched. ~5–15 s; verdict
cached in the package as `.gpu_tilelist_probe.json` so a resume never re-pays. `run_job` calls it via
`asyncio.to_thread` (it's a blocking subprocess — calling it directly would stall the API event loop) and,
when unsafe, re-resolves to `find_namd(prefer_cpu=True)` with no `+devices`. Verified 4/4 exact against real
crashing/running packages. **Fails open** (probe error → assume safe; a broken probe must never block a job)
and is skipped entirely for Compute=CPU / GBIS jobs. Diagnostic `_gpu_probe.log` is left in the package.

**Tests:** `tests/test_namd_gpu_probe.py` (conf rewrite, verdict, caching, cleanup, fail-open, devices
wiring); `test_md_runner_proceeds.py::test_gpu_unsafe_geometry_reroutes_to_cpu_build` / `..._safe_geometry_
stays_on_cuda_build` / `..._cpu_job_never_pays_for_the_probe`. See [[LESSONS]] K2.

## ✅ SOLVED — the crash is a ONE-LINE NAMD BUG; patched build now ships (2026-07-12)
Got the real 3.0.2 source. NAMD counts tile-lists twice: host `(n-1)/32+1` vs device `(n+31)/32`. They
differ **only for an EMPTY patch** (host 1, GPU 0), so every compute with an empty i-patch leaves an
uninitialised tile-list entry → the kernel reads it → wild `boundingBoxes[]` index → illegal address.
Empty patches = **vacuum at the box corners** of a solvent-carved origami, which is why this hits us.

- **Fix:** `tools/namd_tilelist_fix/` (1-line patch + `build_patched_namd.sh`) →
  `~/Applications/NAMD_3.0.2p1_Linux-x86_64-multicore-CUDA/`. `find_namd()` prefers it **automatically**
  (reverse-sorts `~/Applications/NAMD_*`; `3.0.2p1` > `3.0.2_`) — **no NADOC code change**.
- **Proof it's causal:** an UNPATCHED rebuild from the same tree + same CUDA 12.6 toolchain still crashes
  13/13; the patched one runs 13/13. Patched GPU matches the CPU build to ~0.02% total energy.
- **⚠️ The other computer still runs stock NAMD** until `build_patched_namd.sh` is run there (needs
  `sudo apt install cuda-toolkit-12-6` and the source tarball; use `sm_86` for the 3080 Ti). Until then its
  GPU jobs are covered by the pre-flight probe above — that's why the probe stays.
- Corrects two earlier claims in this file's history: the crash is **not** a "large lateral footprint"
  (that was correlation), and NAMD 3.1 **does** fix it upstream (dev routes the host count through
  `computeNumTiles()`).
