# S21 — Lost Apply reply recovery, October 17, 2026

Parent FH-20, supporting FH-27. Current instructions/handoff, memory and ledger
read; HEAD remains `96ab701e`, prior changes preserved. Previous goal turn made
S19/S20 progress. Target before editing: actual Apply publication followed by lost
transport reply, editing lock while outcome unknown, actual Check publication
button recovery, exact receipt/adoption/persistence/undo without duplicate Apply.
Two cases (Bend/Twist), maximum two diagnostic invocations, 60-second budgets.

Test-only changes: existing held-response helper can explicitly discard delivery
with route.abort('failed') after route.fetch completes. Tests verify successful
real server response and independently read canonical checkpoint before loss;
no manufactured successful response. The normal fixture still requires empty
console. Only these injected-failure cases may return an exact expected list,
after independently asserting console message URL equals the failed Apply request,
error text is net::ERR_FAILED and the requestfailed event agrees. Page errors,
additional/other diagnostics and ordinary-case console errors still fail.
No production retry/status semantics, gates, geometry or golden changed.

Artifact inventory before browser: launcher root R contains workspace fixture
saves/project/session/playback, tmp browser profiles/downloads, Playwright output,
Vite/UV/XDG/Playwright caches, share-control.json and .owner-start. All fixtures
use __e2e__; page/document finally and outer marked-process/root finally cover
success/failure. Fault route always releases/unroutes in finally. No captures/
video/traces retained, no user-workspace writes or browser downloads.

## Results and bounded stop

- Guarded focused Vitest: controller 73, endpoints 28, editor 10: **111 passed,
  1.81 s**. `just test-focused tests/test_part_deformation_preview_receipts.py`:
  **12 passed, 3.39 s**. No production changes; broad suites/smoke not rerun.
- `NADOC_HISTORY_E2E_GREP='lost Apply reply' just validate-safe uv run --no-sync
  python scripts/run_deformation_history_e2e.py` was invoked twice, with unchanged
  60-second cases. First invocation root `/tmp/__e2e__history-ivdjicfz` disappeared;
  final tool output was lost and its result is **unknown**, not a pass.
- Second invocation, root `/tmp/__e2e__history-l4e8fy2k`, exited 1: **2 failed**,
  Bend 9.0 s / Twist 9.3 s. Both failed at `bend_release.spec.js:428`: Status
  request count expected 1, actual 3, same preview/lease/design/revision binding.
  Prior assertions establish publication once, lost request, editing lock,
  actual Status receipt recovery and browser adoption with one Apply. No production
  cause inferred: request event attribution remains to be investigated.
- Save/undo/redo/reopen and final exact console checks occur after that assertion
  and **were not reached**. Do not claim either case accepted or absence of unexpected
  errors. Test output also contains existing Node color and FastAPI deprecation warnings.
- Stop condition reached: two browser invocations. S22 solely diagnoses this count
  and completes the existing cases; no arbitrary count relaxation or broader work.

Independent cleanup: both roots absent, no accessible processes with their owner
markers, no workspace `__e2e__history*` fixture, ports 8004/5177 accept server-style
binds. 32 process environments were protected/unreadable. Own pytest-3 tree had
0 regular files/0 bytes, no accessible cwd/file/mapping references; removed with
its pytest-current link, absence verified. Root byte counts were not measured;
no captures retained. Scratch text log/scripts are removed after recording this
summary. No unrelated pytest trees or user data removed.

**21/38 Done; 17 remaining (8 core/9 parked); delta +0/+0, U1–U54 unchanged.**
ISSUE-100/MV-48 and full FH-20/FH-27 exits remain open. S21 is stopped, not accepted;
S22 is the sole unstarted successor. No scientific change or authorization needed.

Closeout checks: memory lint 0 errors/0 warnings; both edited JavaScript files
pass node syntax checks; git diff whitespace check passes. Current plan/report/
memory file link targets resolve (anchors not exhaustively checked); one handoff
successor; ledger 38 unique rows, 21 Done including checkpoint-qualified statuses,
9 parked and 8 open. Initial exact-equality count parser missed four Done rows
with checkpoint suffixes; corrected prefix parser agrees with unchanged ledger.
