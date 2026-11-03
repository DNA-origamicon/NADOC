# Objective — supporting detail

[Topic head](../../project_voltroncorearm_visualization_remediation.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
