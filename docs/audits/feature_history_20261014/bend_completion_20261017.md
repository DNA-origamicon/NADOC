# Bend completion series — October 17, 2026

The user requested finishing the Bend series, superseding the prior one-task and
five-task stop limits. Preserve FH-20/FH-27 exits, all scientific authorization,
production gates and unrelated dirty work at HEAD 96ab701e. No commit/push.

Finite acceptance package recorded before implementation:

1. S15: real publication/Cancel race for shared Bend/Twist ownership; at most two
   diagnostic invocations, unchanged 60-second case budget and strict console.
2. Bend controls/creation: ordinary popup angle/radius/direction/planes and toolbar
   creation on explicit native selections, scope/Cancel/Apply/persistence; inspect
   end-menu and polymer prerequisites and exercise available native cases.
3. Native feature-chain acceptance: historical Bend edit with a later native
   feature, independent replay and persistence. No recovery geometry as authority.
4. Resource/release assessment: bounded measurements of this actual path with
   larger synthetic native parts, existing capture/retention limits, request/render
   and light-read evidence. Do not infer interactive qualification from test duration.

A demonstrated production defect gets a focused repair and validation within the
user's requested series; molecular uncertainty still requires concrete review and
authorization. A failed fixed limit blocks rollout, never justifies raising it.
Complete the feasible package and record exact remaining blockers, without calling
partial acceptance a completed milestone or producing an unlimited task chain.

Artifact contract: all fixture/project/log/cache/browser/report output beneath the
launcher's fresh machine-local root; __e2e__ fixture names, no retained screenshots,
video or traces. Held real responses release and routes are removed in finally;
fixture/page cleanup and outer process/root cleanup run after failure. Independently
verify root absence, owned process markers, ports and workspace fixtures after runs.
Any visual-review capture is temporary, reviewed then removed with the root.

## Reconciliation and delivered checks

HEAD remains 96ab701e. The user's request supersedes the S15-only stop in the
previous handoff. S10–S14 source and prior worktree changes were present; none
were reset. Shared test helpers were extracted without removing their assertions.
No production source, gate, molecular parameter, golden or threshold changed.

S15 passes for both Bend and Twist: hold the real Apply reply *after* the backend
checkpoint proves publication; Cancel returns `applied`; releasing the original
reply adopts the committed geometry once. Exactly one revision/history increment
and Apply request, unchanged backend checkpoint after Cancel, zero private roots,
and strict empty browser console are asserted. Initial S15 run: 4 passed in
1.6 minutes (new cases 9.8/8.3 s, retained cases 37.2/36.2 s).

Toolbar Bend creation passes with actual selection-controller input: empty
selection refusal, Change/Clear selection, Cancel preserves canonical state,
Apply appends one row/operation, explicit strand target ranges survive save,
undo/redo/load and history reopen. This is toolbar/strand coverage, not end-menu
picking or all target kinds.

A four-helix native bundle → Bend → Twist chain passes earlier-Bend editing,
unchanged later Twist inputs and feature identities, native independent proof,
save/undo/redo/load and proof after reload. This does not cover later routing,
Sweep, missing-reference repair or named/domain organization.

Expanded fixture tests: `just test-focused tests/test_deformation_history_app.py`
— 7 passed, one existing FastAPI ORJSON deprecation warning, 2.92 s. Includes
native proof for 1/4/16/17 helices, restricted proof/resource endpoints, unchanged
checkpoint and production route/lifespan/gate restoration. An initial attempt
hung because the new proof endpoint reacquired the non-reentrant state lock;
that owned pytest process was interrupted/killed and the test-only endpoint was
corrected to copy the session design while already holding the lock. That
interrupted run is not a pass. No production lock implementation changed.

## Remaining release boundary

The actual private mutable path fixes MAX_HELICES=16 and MAX_SLOTS=1024; capture
remains 25 ms, two live sessions, sixteen tombstones, cooperative preview/apply
budgets unchanged. The immutable host's capabilities do not automatically wire
this path or remove its limits. A normal larger part therefore cannot be claimed
qualified simply because tiny-fixture interaction passes. Full latency, lock
hold/read tails, frame responsiveness and retained-resource qualification need
measured complete paths, not browser-test duration or three RSS samples.

Native unrouted fixtures correctly disable polymer-circle controls. Eligibility
requires genuine polymerization connector strands plus periodic seam ligations;
adding synthetic notes/ligations would not constitute replay-qualified routing.
End-menu picking, eligible polymer controls, all target kinds, later routing/Sweep,
failed/lost publication and expiry/disconnect still lack complete browser evidence.
Existing unit coverage is retained and does not substitute for those workflows.
FH-20 additionally requires paired route/editor rollout and obsolete mutating
preview retirement; both must wait for qualification. FH-27 broad debt remains.

Diagnostics are retained here rather than hidden: the six-case run had 5 passes
and one controls failure, from selecting an earlier in-flight plane response.
The nine-case expansion had 6 passes and 3 failures: comparison to intermediate
rather than finally displayed rounded angle, global session count including the
other document's applied receipt, and expecting 422 instead of the implemented
413 size-refusal contract. Fixes correlate the intended plane response, assert
exact persisted curvature from the final visible angle/24 (no tolerance), report
both document and global retention, and assert 413 plus `preview_limit`. No
production behavior, precision, limit or assertion deadline was changed.

Reviewed scope limits: all four end-menu dispatches have unit tests but no new
canvas-click browser acceptance here. Polymer popup unit tests exercise circle
counts and seam-span math; eligible native-routing browser proof remains open.
These are explicit remainders, not qualified controls or completed milestones.

## Fixed-limit measurements

The final boundary cases pass: 16 helices × 32 bp × 2 sites = 1,024 sites;
three Open/edit/Cancel cycles preserve the entire canonical checkpoint and leave
zero document sessions/private display roots. Global retained sessions are 1,1,0
(the other document's scalar applied receipt expires); tombstones 9,10,12 stay
within 16. A subsequent Apply publishes once and independently proves verified.
The 17-helix fixture returns HTTP 413 / `preview_limit`, retains no document
session and leaves the checkpoint unchanged. This is a demonstrated larger-part
admission blocker for general rollout, not a reason to raise the fixed allowance.

| Cycle | Open wall ms | Edit wall ms | Concurrent revision GET ms | Cancel/check wall ms | Server RSS bytes |
|---|---:|---:|---:|---:|---:|
| 0 | 3525 | 1673 | 6 | 1651 | 240324608 |
| 1 | 3494 | 1776 | 7 | 1639 | 240181248 |
| 2 | 3463 | 1774 | 8 | 1479 | 242331648 |

These wall intervals include Playwright actions, polling and assertions; they
are not isolated backend durations, frame latency, capture-lock hold times or
interactive percentiles. Cancel/check includes resource/checkpoint requests.
RSS samples are process-wide and no forced GC was used. Three observations do
not prove leak freedom. No deadline, cap or retained-history allowance changed.

## Final validation and cleanup

- Browser command (four serialized invocations):
  `just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py`.
  Results in order: 4 passed (S15), 5 passed/1 failed, 6 passed/3 failed, **9 passed
  in 3.0 minutes**. Final case times: publication/Cancel Bend 8.5 s, Twist 7.0 s;
  Bend controls 9.9 s; toolbar creation 12.2 s; four-helix chain 13.5 s;
  fixed-limit cycles/Apply 37.3 s; above-limit refusal 8.1 s; retained accumulated
  Bend 34.4 s and Twist 40.9 s. All remain below the unchanged 60-second case cap.
- Final `just test-focused tests/test_deformation_history_app.py`: **7 passed**,
  one existing ORJSON deprecation warning, **3.13 s**.
- `just validate-safe npm --prefix frontend run test -- src/features/deformation_history_controller.test.js src/app/deformation_history_editor.test.js src/app/deformation_creation_editor.test.js src/ui/bend_twist_popup.test.js src/ui/blunt_end_menus.test.js src/ui/deformation_tool_launcher.test.js src/api/deformation_preview_endpoints.test.js src/test-helpers/deformation_history_launch.test.js src/scene/deformation_history_adapter.test.js`:
  **190 passed across 9 files, 4.94 s**.
- Node syntax checks pass for both browser specs and shared helper. Memory lint:
  **0 errors/0 warnings**. `git diff --check` and scoped untracked whitespace
  pass; 13 handoff/evidence local links resolve; ledger has 38 unique milestone
  rows and 21 statuses beginning with Done (four have qualifiers).

Owned roots `/tmp/__e2e__history-m2xwr7fw`,
`/tmp/__e2e__history-joov8cc4`, `/tmp/__e2e__history-eklytnbv`,
`/tmp/__e2e__history-rovxh5zv` are absent. Launcher finally and independent check
both verify cleanup. No accessible environment-marked owned process, no listeners
on 8004/5177, both ports reusable, no workspace `__e2e__history-*` fixtures.
31 protected process environments could not be read; they were not signaled.
No screenshots, videos, traces or fixture files are retained. Temporary helper
scripts are removed at closeout. Scientific validation, visual molecular review,
full regression and general rollout were not performed. Earlier broad failures
remain open; these focused passes do not clear them.

**21/38 complete, 17 remaining (8 core, 9 parked); delta +0/+0; U1–U54 unchanged.**
Completed this package: S15, ordinary Bend controls, toolbar creation, native
Bend→Twist chain and bounded capacity/refusal/resource observations. Full Bend
release is incomplete for the explicit gaps above. Exactly one successor:
**S16 — Bend creation through both real domain-end menus**, fully specified in
[the handoff](session_handoff.md), unstarted. No commit/push or gate enablement.
