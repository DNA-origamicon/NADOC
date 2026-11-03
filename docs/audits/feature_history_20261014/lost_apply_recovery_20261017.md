# S22 — Lost Apply reply recovery, October 17, 2026

Parent FH-20, supporting FH-27. Current handoff/instructions/memory/ledger and
worktree read; HEAD remains `96ab701e`, unrelated changes preserved. S21 made
progress by exposing a bad test assertion; its capped failure is retained.

## Cause and delivered correction

`deformation_history_controller.resolvePublication` issues one Status request.
`deformation_preview_endpoints.refreshCommitted` intentionally brackets private
GET design/geometry/revision with two further exact receipt checks. Existing unit
test “refreshes published data privately between two exact session-bound status
checks” explicitly requires this. No duplicate Apply or production defect found.

The two browser cases now assert exactly:
Status(resolve), Status(pre-read guard), GET design, GET geometry, GET revision,
Status(post-read guard). All three Status bodies equal the captured preview/lease/
design/revision/feature binding; all three responses match the actual Apply receipt.
This is causal accounting, not changing an arbitrary count to make the test pass.
One Apply/revision/history increment, editing lock while unknown, private display
cleanup and canonical/browser equality remain asserted. Save/undo/redo/load/reopen
and exact failed-request console identity now execute and pass. No runtime changes,
scientific changes, broad diagnostic suppression or gate changes.

## Checks actually run

- Guarded installed Vitest command:
  `just validate-safe frontend/node_modules/.bin/vitest run --root frontend
  src/features/deformation_history_controller.test.js
  src/api/deformation_preview_endpoints.test.js
  src/app/deformation_history_editor.test.js`: **111 passed, 1.86 s**, 3 files.
- Initial shell-wrapped npx command was incorrectly forwarded by the recipe;
  it attempted package resolution and exited before tests. No packages installed.
  Corrected command uses installed binary directly; npm diagnostic log removed.
- `NADOC_HISTORY_E2E_GREP='lost Apply reply' just validate-safe uv run --no-sync
  python scripts/run_deformation_history_e2e.py`: **2 passed, 25.9 s**, one invocation,
  Bend 11.1 s/Twist 9.7 s; unchanged 60-second test budgets. Existing Node color and
  FastAPI deprecation warnings remain; strict browser console/page checks pass.
- No backend runtime change, broad suites or smoke rerun; prior results are history.
  Neither tiny fixture durations nor this recovery branch qualify full latency,
  resource, scientific or release acceptance.

## Artifact inventory and cleanup

Before launch: root owns fixture saves, project/session/playback data, browser
profiles/downloads, tmp, caches, Playwright output and ownership marker. Fixture
page/document finally plus launcher process/root finally cover success/failure.
No captures/traces/videos; installed browser reused. Additional temporary text log
was inventoried separately and removed after recording results.

`/tmp/__e2e__history-fqqya6lg` independently absent; no accessible marked processes
or workspace __e2e__history fixtures; 8004/5177 server-style binds free. 32 protected
process environments unreadable. Temporary browser/npm logs had no accessible
open-file references and were removed, 4,569 bytes; root byte count not measured.
No unrelated pytest tree or user designs touched.

21/38 Done, 17 remaining (8 core/9 parked); delta +0/+0; U1–U54 unchanged.
ISSUE-100/MV-48 and full FH-20/FH-27 exits remain open. Sole successor S23 extracts
nonpublishing native evaluation in the existing immutable geometry host. The current
mutable preview cannot admit sealed sources; existing immutable edit evaluates and
publishes in one function. Extraction is a necessary implementation step toward
preview integration, not proof of complete ownership/resource qualification.

Closeout: JavaScript syntax and git diff whitespace checks pass; memory lint
0 errors/0 warnings. Current plan/report/memory file targets resolve (anchors not
exhaustively checked); 38 unique milestones, 21 Done, one S23 successor.
