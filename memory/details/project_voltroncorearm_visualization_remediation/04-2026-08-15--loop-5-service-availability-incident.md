# 2026-08-15 — Loop 5: service-availability incident — supporting detail

[Topic head](../../project_voltroncorearm_visualization_remediation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

### 2026-08-15 — Loop 5: service-availability incident

- User report: the frontend shell remained available, but files would not load.
- Reproduction: Vite answered on `127.0.0.1:5173`; nothing listened on backend port
  `127.0.0.1:8000`. This was an unavailable process, not a visualization or file-parser
  failure. No evidence identified the event that stopped the earlier backend process.
- Recovery: started FastAPI independently without disturbing the existing Vite process.
- Browser-facing verification through Vite's `/api` proxy: `/library/files` returned 269
  entries; `/library/content?path=VoltronCoreArm.nadoc` returned 10,509,420 characters;
  `/design/import` returned HTTP 200 with the named VoltronCoreArm design, 71 helices,
  436 strands, and zero validation errors.
- Current state: backend and frontend are both listening, and the exact frontend file-open
  data path is operational. Use `./start.sh` for future launches so both processes share
  one supervised lifetime.

### 2026-08-15 — Loop 6: cached completed frame must not look failed

- User report: selecting the completed Alpine job and enabling Display MD briefly painted
  the red “Reconnect to Alpine to refresh the frame” warning even though its retained
  frame was current and subsequently displayed correctly.
- Root cause: passive Refresh-control repaints wrote every disabled gate reason into the
  shared display-status line. Connection/refresh policy therefore overwrote legitimate
  cached-frame preparation and application progress.
- Fix: passive repaints keep `disconnected` and `job-not-running` information on the
  Refresh control (`data-gate-reason`, disabled state, dot, and tooltip) without announcing
  it as a display failure. Only cached-frame warming may passively occupy the status line;
  the explicit refresh path retains its reconnect warning.
- Verification: `md_jobs_panel.test.js` — **237 passed**. Real Playwright completed-job
  path loaded VoltronCoreArm, cached its frame, applied it in 106 ms, made no Alpine poll,
  and asserted that neither reconnect nor job-running refresh policy appeared in the
  shared display status.

### 2026-08-15 — Loop 7: selected-job ownership of the Alpine submit control

- Required invariant: a prepared (`queued`, not yet handed to SLURM) Alpine job may label
  the primary control “Submit to Alpine” only while that exact job is selected.
- Added `mdRunControlForSelection`, an explicit pure selection boundary. The primary
  control now resolves the selected id against the current job cache and never falls back
  to another queued job. A completed selection, no selection, or a missing/stale selected
  id produces the appropriate disabled control even when an awaiting-submit Alpine job
  exists elsewhere in the list.
- Hardened the Job Wizard creation callback: if the new job has not reached the panel's
  cache yet, it refetches first and then selects/reselects that new id. Existing relaxation
  and production creation paths also refetch and select their returned job ids.
- Verification: `md_jobs_panel.test.js` — **238 passed**, including queued-selected,
  queued-unselected/completed-selected, empty-selection, and stale-id cases;
  `md_job_wizard_readonly.test.js` — **28 passed**, including the new-job callback after
  successful creation. The live job inventory was inspected read-only; no running or
  queued simulation was changed.

### 2026-08-15 — Loop 8: selected job synchronizes the Clusters card

- Selecting an NAMD job now makes its persisted execution target authoritative for the
  Clusters card: legacy/explicit local selects Local, Alpine selects Alpine, and RunPod
  selects RunPod.
- The corresponding radio and detail pane switch together. Selecting RunPod also refreshes
  its pre-flight once (without the former duplicate probe); leaving RunPod clears its
  transient picker state through the existing pane-transition path.
- Verification: `md_jobs_panel.test.js` — **241 passed**, including a real panel DOM test
  that selects local, Alpine, and RunPod records in sequence and checks both the radio and
  mutually-exclusive visible pane for every transition.

### 2026-09-16/17 — Loop 9: event-loop threading (Codex) + client-side connection-pool contention

- A separate agent (Codex) diagnosed a fresh incident: VoltronCoreArm/V2 (~80 MB, mostly
  loadout snapshots + feature-log history) took up to 184 s to open. Root cause: several
  job-list routes (`blade`/`cando`/`lammps`/`mrdna`/`oxdna`/`snupi`/`md`/`md/queue`/
  `simulate/jobs`) did synchronous disk scans inside `async def` handlers, blocking the
  FastAPI event loop for every concurrent request including the design/geometry fetch.
  Codex wrapped all of them in `run_in_threadpool`, added `backend/core/collaboration_status.py`
  (single-flight + 10 s TTL peer-reachability cache shared across tabs), skipped mrDNA's
  per-process cwd resolution unless the cmdline mentions `arbd`, and set `suppressBusy` on
  peer-status polling so an unreachable peer can't paint the blocking modal. That work ran
  out of usage credits mid-verification; resumed and verified here (96 focused tests, full
  frontend suite, `just test-smart` baseline unchanged from before the fix).
- Follow-up (this loop): the threading fix alone left the **client-side** bottleneck
  unaddressed. Vite's dev server is plain HTTP/1.1, capping Chromium at 6 concurrent
  connections per origin; ~20 GETs (job lists, `jobs/active`, `md/queue`, peer status,
  health, engines/status, primitives, library/files) fire within the first 3 s of boot,
  unconditionally and on a 4-5 s repeat cadence, competing with `/design` +
  `/design/geometry` for that budget. In Codex's own post-fix reproduction
  (`/tmp/nadoc-blocking-fix/browser-final.log`), `/design/geometry` alone spanned
  8.4 s→41.7 s (33.3 s) despite the same computation profiling at ~5 s in isolation — pure
  queueing. The codebase already had a polling-deferral mechanism
  (`frontend/src/perf/operation_timing.js`'s `whenOperationIdle()`, consumed by
  `listActiveJobs`/`listSimJobs`/every `_backgroundJobList`-wrapped engine job list) but it
  never engaged during initial load because `GET /design` and `GET /design/geometry` were
  excluded from `client.js`'s `isTimedOperation` allowlist (GET requests were categorically
  excluded). Fix: added those two GET paths to the allowlist (a metadata-only `getDesign()`
  call is explicitly excluded — it never triggers `design_renderer`'s
  `finishOperationAfterRender()`, so tracing it would leave the trace dangling); added the
  two remaining pollers that bypassed `whenOperationIdle()` entirely
  (`getCollaborationPeerStatuses`, `getMdQueue`). No new mechanism — this only closes the gap
  in the existing one, so `jobs/active` and all six engine job lists now correctly defer
  during a load for free.
- Parity fix: `list_md_jobs` already used the non-blocking `dir_size_bytes_cached_only` +
  background `warm_dir_sizes` pattern (the exact pattern the 18hb-archive incident this
  module documents was built to prevent) but the other five engines still called the
  blocking `dir_size_bytes_cached`. Extended the pattern to `mrdna`/`cando`/`oxdna`/`snupi`/
  `blade` via a new shared `schedule_dir_size_warm()` in `design_disk_usage.py` (also used to
  de-duplicate `routes_md.py`'s own inline task-ref bookkeeping).
- Verification: 198 focused backend tests (all six engines + collaboration/status/queue
  suites) pass; full frontend suite — **446 files / 6506 tests** pass; `just test-smart` —
  **8632 passed, 30 failed→29 failed after fixing a test that assumed the old blocking
  disk-size read (`test_job_archive.py::test_oxdna_archive_unarchive_via_api`, now polls like
  its `md` sibling)**; failure set otherwise byte-identical to the pre-change baseline (all
  pre-existing local-environment gaps: stale oxDNA build, missing `tclsh` — unrelated).
  Not independently re-verified end-to-end in a live browser: doing so would require driving
  the shared dev server's `POST /design/import` (or a fresh tab against the same live `doc`),
  which risks clobbering a concurrent session's in-flight work; ask before retrying that.
