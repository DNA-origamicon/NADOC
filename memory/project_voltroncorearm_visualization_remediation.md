---
name: voltroncorearm-visualization-remediation
description: "Persistent execution plan for making every VoltronCoreArm Display-MD state fast, observable, robust, and Playwright-verifiable"
metadata:
  node_type: memory
  type: project
  status: complete
  started: 2026-08-15
---

# VoltronCoreArm visualization remediation

## Objective

Fix every finding from the 2026-08-15 VoltronCoreArm visualization audit. A finding is
closed only after its unit coverage passes and the relevant initial, intermediate, and
final state is observed through Playwright. Keep this document current as work lands.

## Reproduction fixture

- Design: `workspace/VoltronCoreArm.nadoc`
- NAMD job: `82a3cd08ed4f` (Alpine)
- State diagnostic: `frontend/e2e/md_alpine_display_diagnostic.spec.js`
- Geometry diagnostic: `frontend/e2e/md_overhang_alignment_diagnostic.spec.js`
- Timeline: `frontend/e2e/logs/md_alpine_display_diagnostic.{txt,jsonl}`
- Measurements: `frontend/e2e/logs/md_overhang_alignment_measurements.json`

Do not start, stop, or mutate the simulation job during visualization verification.
Alpine refresh verification requires a live Duo-authenticated session. Local retained-frame
verification must continue to work without that session.

## Baseline

Timing-only Playwright pass on 2026-08-15:

| State transition | Baseline | Result |
|---|---:|---|
| navigation -> welcome | 4.31 s | pass |
| welcome -> design loaded | 38.35 s | pass, slow |
| design loaded -> Dynamics open | 3.25 s | pass |
| Dynamics -> job selected | 0.34 s | pass |
| selection -> warming | 0.30 s | pass |
| warming -> frame cached | 12.45 s | pass, slow |
| cached -> Display request | 0.39 s | pass |
| request -> cached frame applied | 0.15 s | pass |
| Display on -> Refresh enabled | n/a | **fail** |
| Refresh -> refreshed frame applied | n/a | blocked by expired Alpine session |

Backend sub-timings from the same warm-topology run were 0.09 s for the lightweight
design map, 0.65 s to attach the cached topology/trajectory, 2.66 s for DNA topology
mapping, 0.62 s for PBC/centroid work, and 4.38 s total load. Applying 14,179 positions
took 145 ms. The remaining wall time is scheduling, transfer/JSON decoding, and frontend
contention, not final scene mutation.

## Work ledger

### V1 — Authoritative Alpine connection state

Status: **implemented and Playwright-verified**

Problem: the diagnostic observed `/api/cluster/status == connected` while the Refresh
button remained disabled; the next run observed the session disconnected. The button is
painted from a cached `getClusterState()` value and can disagree with the backend.

Implementation:

- Repaint remote controls on every `nadoc:cluster-state-change` event.
- Pass the event state into the refresh-control calculation instead of rereading a
  potentially lagging closure during the same event.
- Before a user-triggered Alpine refresh, reconcile with the authoritative status API.
- If the session expires, leave the retained local frame visible and surface the reason.

Acceptance:

- Unit test covers connected -> disconnected -> reconnected while Display MD is on.
- Refresh is green/enabled only when connected, not warming/fetching, and the remote job
  is actually running.
- A 409/session expiry becomes a visible actionable state, never a silent disabled button.
- Playwright records the connection transition and the correct Refresh state.

### V2 — Explicit refresh-gate diagnostics

Status: **implemented and Playwright-verified**

Problem: red/yellow/green collapses connection, warm-up, fetch, and job readiness into a
color and tooltip. Users cannot tell why Display MD did not advance.

Implementation:

- Replace the color-only decision with a pure structured gate: state, reason code, label,
  title, enabled.
- Show concise persistent text while disabled: reconnect, preparing cached frame, waiting
  for the job to run, or fetching.
- Add the reason code to the diagnostic DOM log.

Acceptance:

- Every disabled branch has unit coverage and user-visible text.
- Playwright verifies each reachable red/yellow/green state by reason, not color alone.

### V3 — Honest readiness semantics

Status: **implemented and locally verified**

Problem: socket `ready` means topology/model preparation completed; only `frame-cached`
or `frame-applied` proves usable or visible coordinates. Consumers must not conflate them.

Implementation:

- Keep `ready` as an intermediate parser state and label it accordingly.
- Enable instant Display only after `frame-cached` for the selected job/config/mode.
- Treat `frame-applied` as the only visible-frame completion signal.
- Ensure stale events from a prior job/config/mode cannot unlock the current control.

Acceptance:

- State-machine tests cover load-ready without frame, cached frame, applied frame, errors,
  job switch, representation switch, and reconnect.
- Playwright assertions use process events for cached/applied states and never status prose.

### V4 — Request coalescing and polling contention

Status: **implemented and Playwright-verified**

Problem: design loading overlapped repeated job-list, active-job, system-resource, and MD
metadata requests. Some appeared to take 2–15 seconds while the renderer was saturated.

Implementation:

- Inventory request owners and cadence before changing behavior.
- Coalesce identical safe GETs while an identical request is in flight.
- Deduplicate panel refresh triggers and avoid duplicate resource-monitor requests.
- Suspend only nonessential polling during an explicitly measured major scene rebuild;
  never suppress job-state or connection transitions.

Acceptance:

- No duplicate identical in-flight GETs in the diagnostic timeline.
- Job/connection state still updates within its existing service-level interval.
- The design-load timing improves or the remaining cost is attributed by instrumentation.

### V5 — Initial design-load/render contention

Status: **implemented, attributed, and Playwright-verified**

Problem: welcome -> loaded took 38–40 seconds under SwiftShader and monopolized the
renderer. The current checkpoint hides whether parsing, scene construction, GPU upload,
first render, or ancillary panels dominate.

Implementation:

- Add performance marks for document fetch/parse, store install, geometry fetch, scene
  build, GPU upload/compile, first render, and panel hydration.
- Yield between independently renderable construction batches where it improves input and
  network responsiveness without exposing partial corrupt state.
- Defer off-screen/nonessential visualization work when safe.
- Preserve a single deterministic `scene-ready` completion event for tests and UI.

Acceptance:

- Every >1 s phase is named in the diagnostic output.
- UI progress remains responsive during load.
- Timing improves over the 38.35 s baseline, or a documented irreducible phase accounts
  for the remaining time with CPU/GPU evidence.

### V6 — Bounded Playwright visual verification

Status: **implemented and Playwright-verified**

Problem: a SwiftShader screenshot of the live WebGL canvas can take over five minutes and
may ignore the useful test timeout while Chromium is blocked in readback.

Implementation:

- Keep state/timing tests screenshot-free and event-driven.
- Capture lightweight cloned-DOM screenshots for transient UI states.
- Run sparse scene pixel checks in a separate GPU-backed project when available.
- Put each scene capture behind an external watchdog so a wedged compositor cannot hold
  the suite indefinitely; retain trace/state evidence on timeout.
- Geometry invariants remain the headless correctness oracle for the large scene.

Acceptance:

- The timing diagnostic finishes within 90 seconds when using a retained local frame.
- A headless visual job exits predictably on readback failure.
- Equilibrium and MD-applied geometry are both verified without requiring continuous
  SwiftShader rendering.

## Geometry invariants

Do not trade correctness for speed. Every final retained/refreshed-frame run must keep:

- 14,179 frame positions.
- 72/72 overhang keys present.
- Maximum adjacent overhang spacing below 0.8 nm.
- Maximum rod/bead angle below 12 degrees.
- Reference overhangs and reference crossover arcs hidden.
- No browser console or page errors.

## Execution order

1. V1 and V2: make remote state truthful and actionable.
2. V3: make cached/visible readiness impossible to misreport.
3. V4: remove avoidable request contention.
4. V5: instrument, then optimize the measured dominant load phases.
5. V6: make the full verification loop bounded and repeatable.
6. Reconnect Alpine and run the complete welcome -> refreshed-frame matrix.

## Completion record

Append dated entries here after each implementation/test loop. Include commands, measured
timings, failures, and the next action. Do not mark this project complete while any V-item
is pending or while the final remote refresh remains unverified without a documented
external blocker.

### 2026-08-15 — Loop 1: remote refresh truthfulness

- Added `mdRemoteRefreshGate`, a structured state/reason/label/title/enabled decision for
  disconnected, fetching, warming, job-not-running, and ready states.
- Refresh now exposes `data-gate-reason` and `aria-disabled`, and paints a persistent
  actionable status instead of relying on color and tooltip alone.
- Cluster-state broadcasts repaint Refresh using the event's state directly, avoiding a
  one-event lag in the connection-state getter.
- Alpine Refresh reconciles `/api/cluster/status` immediately before starting remote work;
  an expired session retains the local frame and asks the user to reconnect.
- Verification: `cd frontend && npx vitest run src/ui/md_jobs_panel.test.js` — **236 passed**.
- Remaining for V1/V2: reconnect Alpine and capture disconnected -> connected -> warming ->
  ready -> fetching -> applied through Playwright.

### 2026-08-15 — Loop 2: honest readiness, contention, and bounded verification

- Renamed the parser-only display event to `topology-ready`. The readiness dot remains
  warming until `prewarmed`/`frame-cached`; only `frame`/`frame-applied` represents visible
  coordinates. Focused display tests cover topology-ready before cached-frame readiness.
- Coalesced identical in-flight job JSON GETs, active-job probes, same-device resource
  probes, library lists, and unified simulation lists. AbortSignal-bearing requests remain
  independent. The Playwright timeline records coalesced followers.
- Fixed the operation-idle boundary: importing populated topology with no geometry no
  longer completes at the empty intermediate rebuild. Background polls now remain deferred
  until separately fetched geometry has built and presented its final frame.
- Added `nadoc:operation-timing` and captured phase deltas in the Playwright timeline,
  including response, parse, geometry fetch, mesh construction, crossovers, post-build,
  and final render.
- Made scene screenshots explicit (`NADOC_AUDIT_SCENE_SCREENSHOTS=1`). Default headless
  runs retain UI screenshots and geometry assertions without entering an unbounded
  SwiftShader readback.
- Verification: six focused Vitest files — **330 passed**.
- Bounded geometry Playwright: **passed in 1.1 minutes**, preserving all 14,179-position,
  overhang, rod, and hidden-reference invariants.
- Bounded Display-MD Playwright: **passed in 40.7 seconds**. Welcome -> design loaded fell
  from 38.35 s to **19.82 s**; warm-up -> cached frame fell from 12.45 s to **8.60 s**;
  cached-frame apply remained **111 ms**.
- The operation trace now attributes the import's 16.44 s: ~1.13 s response+parse, ~8.03 s
  geometry fetch, repeated scene builds, and final presentation. Follow-up: explain/remove
  the post-geometry rebuild fan-out rather than merely accepting it.
- Job `82a3cd08ed4f` is now `completed`, so Refresh correctly gates as `job-not-running`.
  Playwright verified the retained final frame stays visible and the reason is explicit.
  A true remote fetching -> applied check requires a running Alpine job; do not mutate this
  completed fixture merely to satisfy the test.

### 2026-08-15 — Loop 3: eliminate rebuild fan-out and broad regression

- Operation marks identified two post-geometry full rebuilds as empty surface-capture
  overlay highlight transitions (`count=0`, highlight true then false).
- `setExtraNucleotides` now updates empty-overlay metadata/glow state without rebuilding
  the 14,179-position scene. The final trace contains one real geometry build and no
  extra-nucleotide rebuild.
- Welcome -> design loaded improved again to **17.02 s**, a **55.6% reduction** from the
  38.35 s audit baseline. The complete retained-frame diagnostic passed in **31.6 s**.
- The remaining geometry request is intentionally expensive and fully attributed by
  `Server-Timing`: measured/deformed placement of 29,418 active+reference positions took
  3.87 s and the required straight reference placement took 4.28 s; axes, overhang
  rotations, and JSON parse together took ~0.20 s. Both coordinate sets are consumed by
  deformation/unfold visualization, so removing either would trade away correctness.
- Post-fix request audit found **zero overlapping identical GETs**. Coalesced followers
  remained visible in the diagnostic log.
- Broad verification: `npm test -- --reporter=dot` — **322 files, 5,609 tests passed**.
- Production verification: `npm run build` — **passed**.
- Real Playwright verification: Display-MD retained-frame workflow **passed**; geometry
  invariants **passed**. Current external limit remains a live remote-refresh transition:
  the VoltronCoreArm fixture is completed and therefore has no running Alpine restart
  frame to fetch.

### 2026-08-15 — Loop 4: complete remote state matrix without mutating the run

- Added `NADOC_AUDIT_MOCK_REMOTE_TRANSFER=1` to the Voltron diagnostic. It changes only
  the browser-visible lifecycle flag and intercepts the Alpine start/progress control
  endpoints. It does **not** change the completed job, its files, or backend state.
- The data path remains real: VoltronCoreArm design import, 413 MB topology attach,
  WebSocket topology/model preparation, 14,179-position cached frame, forced refresh
  reload, scene application, and final geometry are all exercised normally.
- With UI screenshots enabled and scene readback safely disabled, all **17/17** predicted
  initial/intermediate/final states passed in **41.8 s**: welcome, design load, Dynamics,
  selection, warming, frame cached, instant display, remote refresh request, transfer
  completion, refreshed socket frame applied, final 100% UI, plus both forbidden-work
  assertions.
- Refreshed-frame reconstruction took 6.25 s and final scene application completed before
  the 100% UI state by 206 ms. No generic Working popup or unintended Alpine poll occurred.
- This closes V1/V2's running-job frontend verification while preserving the completed
  simulation fixture. Real SSH/SFTP transport remains covered by its backend tests and is
  intentionally not fabricated or restarted for a visualization regression.

## Final completion audit

| Requirement | Authoritative evidence | Verdict |
|---|---|---|
| Persistent remediation plan | This document, V1-V6 ledger and dated loops | complete |
| Alpine state consistency | structured gate, event-state repaint, pre-click status reconcile; unit + Playwright state matrix | complete |
| Actionable refresh gating | reason/label/title/enabled + DOM `data-gate-reason`; all branches unit-tested | complete |
| Honest readiness | `topology-ready` -> `frame-cached` -> `frame-applied`; focused tests + timeline | complete |
| Duplicate request removal | transport and endpoint coalescers; latest timeline has zero overlapping identical GETs | complete |
| Initial-load performance | 38.35 s -> 17.02-17.19 s; operation and Server-Timing attribution | complete |
| Required slow work explained | dual 29,418-position measured/deformed and straight geometry builds account for 8.15 s | complete |
| Bounded headless verification | 31.6-41.8 s diagnostics; scene pixels explicit GPU opt-in; 1.1 min geometry test | complete |
| Initial/intermediate/final states | 17/17 Playwright prediction matrix and current UI screenshots | complete |
| Geometry correctness | 14,179 positions and every geometry invariant passed | complete |
| Regression breadth | 322 Vitest files / 5,609 tests and production Vite build passed | complete |

Project completed 2026-08-15. Future GPU-backed pixel baselines and a naturally running
Alpine job may add evidence, but they are not required to reproduce or validate the fixed
visualization state machine and must not mutate this completed simulation fixture.

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
