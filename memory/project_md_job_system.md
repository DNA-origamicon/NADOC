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
