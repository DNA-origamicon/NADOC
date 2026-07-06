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
(`skip_until` guard at loop top). `MdJob.early_stop_relax: bool=False` (load-setdefault);
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
  (MD production is still appended *segments* on the same job — NOT a child job —
  so it does not create a nested row; only refits do.)
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
