---
name: project_job_activity_spinner
description: Welcome-screen running-job spinner + concurrent-job guard; /api/jobs/active cross-engine endpoint
metadata: 
  node_type: memory
  type: project
  originSessionId: 89b346a9-503f-40f0-986c-cbd77693b63c
---

Welcome screen shows a spinning indicator on any design that has a running/preparing MD or oxDNA job, with an ETA tooltip on hover; launching a new job while one is busy pops a Continue/Cancel warning.

**Entry points**
- Backend: `backend/api/routes_jobs.py` → `GET /api/jobs/active` returns `{jobs, count, any_running}`. One cheap cross-engine scan (reconciles each job's status, reads ≤1 log per *running* job for ETA). Registered in `main.py` as `jobs_router`.
- Frontend shared module: `frontend/src/ui/job_activity.js` — pure helpers (`activeJobForPath`, `jobActivityTooltip`, `pickBlockingJob`, `formatEta`, `normPath`) + `fetchActiveJobs()` (via `client.listActiveJobs`) + `confirmNoConcurrentJob({excludeJobId})`. Tested in `job_activity.test.js`.
- Welcome spinner: `library_panel.js` polls every 4 s (skips while `mount.offsetParent === null`), decorates each file row's `.lib-row-status` span in place (reuses global `.nadoc-spinner` CSS) so the animation never restarts.
- Guard wired into all 7 launch handlers: MD relax/start/production (`md_jobs_panel.js`), oxDNA relax/start/production/seed (`oxdna_jobs_panel.js`). `excludeJobId=_selectedId` on resume so a job never warns about itself.

**Design decisions**
- "Busy" = `running` or `preparing` only; `queued` does NOT count (waiting its turn, not consuming the machine).
- Guard is global (any busy *local* job blocks any new local launch), not per-engine — both engines contend for the one GPU.
- **Remote (Alpine) jobs are NOT local contention (2026-07-06).** `/api/jobs/active` now tags every entry with `execution_target` (MD from the job; oxDNA always `"local"` — it has no remote backend). `pickBlockingJob` only counts LOCAL jobs (`isLocalJob` = target `"local"` or missing/legacy), so a job running on the Alpine cluster never blocks a local launch, and the welcome-row spinner still shows it (the design *is* simulating, just remotely). Vice versa: the MD panel's Relax handler reads `_currentRunTarget()` FIRST and skips all three local-resource guards (`confirmNoConcurrentJob`, `confirmGpuNotBusy`, `confirmDiskSpaceOk`) when the target is Alpine — a remote submit isn't gated by a local run, a local GPU hog, or local disk (its trajectory writes to cluster scratch). Alpine submit-via-review-card was already unguarded. Pins: `job_activity.test.js` (alpine-ignored / still-blocks-local / legacy-missing-target / `isLocalJob`), `tests/test_jobs_active_execution_target.py`. Verified live: an actual running Alpine job (`6hbx100_noT`) is tagged `execution_target:"alpine"` by the endpoint.
- ETA: oxDNA reuses `oxdna_runner.job_progress().eta_seconds`; MD is best-effort from the current segment's ns/day × conf fs/step over remaining steps, `null` when any ingredient missing (e.g. log hasn't printed yet).

**Test gotcha**: the guard adds an async hop before a launch proceeds; panel tests that pump a fixed number of microtasks needed a `flush()` loop (see the seed tests in `oxdna_jobs_panel.test.js`). Verified in-app via Playwright route-stubbing of `/api/jobs/active` (temp spec, removed). Related: [[project_md_job_system]], [[project_job_disk_usage]].
