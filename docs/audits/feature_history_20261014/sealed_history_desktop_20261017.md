# S29 partial — sealed desktop harness and readiness blocker

Parent FH-20, supporting FH-27/FH-28. Previous iteration was progress: S28 delivered
native sealed refresh reads. Current handoff/startup instructions, project memory,
ledger, module-first/API-state rules, artifact policy and scoped harness/consumer
contracts read. HEAD remains `96ab701e`; prior and unrelated changes preserved.
No production implementation, gate, scientific constant or golden changed here.

## Delivered harness, incomplete desktop acceptance

`NADOC_HISTORY_E2E_SEALED=1` explicitly selects two sealed browser cases in the
existing isolated configuration. The ordinary mutable harness selection remains.
`tests/sealed_history_fixture.py` owns the test-only sealed seed/checkpoint helpers,
strict policy for the two `__e2e__history-*` documents and immutable gate lifetime.
Only `/api/__e2e__/history/` controls bypass strict dispatch; all design operations
use the real production dispatcher/handlers. Unknown test controls still have no
handler; ordinary documents cannot use them. No fixture route is added to main.app.
Seeding is explicit test setup, never an implicit runtime conversion. Checkpoint
and proof materialization occur only in these small fixture controls.

Test teardown closes sealed sessions before restoring the prior policy and restores
the immutable gate even on errors. An initial failure-path unit test caught the
reverse order: restoring compatibility while sealed sessions existed correctly
raised `immutable_policy_transition`. Fixed in the test harness; production guard
retained. Existing preview gate/lease teardown remains. Test close is a dedicated
control, avoiding unsupported ordinary document-close routes.

The new browser spec retains initial geometry adoption, historical controls,
private preview cleanup, Cancel exact canonical/browser/redo equality, Apply once,
complete revision/native display adoption, independent proof and an empty console
error list. **The historical gesture assertions were not reached.** Their source
is delivered; they are not passing evidence or completed desktop acceptance.

## Actual checks and bounded browser evidence

| Check | Actual result |
|---|---|
| `just test-focused tests/test_deformation_history_app.py` | Initial 8 pass/1 fail (teardown ordering); final **9 pass**, 5.37 s |
| `just validate-safe frontend/node_modules/.bin/vitest run --root frontend src/test-helpers/deformation_history_launch.test.js` | **4 pass**, 344 ms total |
| Changed-file Ruff, `node --check frontend/e2e/sealed_history.spec.js`, `git diff --check` | Pass |

**13 unique focused checks pass.** No full frontend/smoke rerun: no frontend runtime
behavior changed. Existing FastAPI ORJSONResponse deprecation warnings remain.

Exactly two serialized browser invocations, both using:

```
NADOC_HISTORY_E2E_SEALED=1 just validate-safe uv run python scripts/run_deformation_history_e2e.py
```

1. `/tmp/__e2e__history-_90m6s52`: Bend and Twist each timed out at 60 s. The final
   cleanup request used an already-closed Playwright request context and obscured
   the primary failure. The captured Bend page showed the feature log with native
   bundle/Bend and “Design readiness: Check unavailable”. No pass claimed.
2. `/tmp/__e2e__history-uk8xpvw1`: diagnostic local waits reduced to 15 s (the
   global budget was not raised); teardown preserves the primary failure. Both
   cases pass the initial nonempty-geometry wait, then fail at **readiness handoff
   completion**, Bend 21.3 s / Twist 21.1 s total. The query remains present.
   No Open/evaluate/Cancel/Apply action is reached. Both cases fail; zero browser
   passes across four executions. The two-invocation cap is exhausted.

Final request logs show 403 on these exact GET paths:

- `/api/design/readiness`
- `/api/design/view-volumes`
- `/api/design/dimensions`
- `/api/vr/references`
- `/api/jobs/active`
- `/api/collaboration/peers/status`

Console records repeated HTTP 403 errors. They were neither filtered nor declared
expected. The source confirms the primary causal chain:
`design_readiness_boot.js` restores design/geometry through existing reads;
`design_readiness_host.js` calls `/api/design/readiness` and consumes the readiness
query only after an available report. The strict route table does not admit that
read. Thus geometry presence is evidence of initial loading, not full native
adoption parity or editor qualification. Other refused polls remain separate debt;
readiness alone cannot make the empty-console acceptance pass.

## Artifact safety and retained debt

Before both invocations, the inventory covered the fresh isolated workspace/logs,
TMPDIR browser profiles/downloads, Vite/UV/Playwright caches and Playwright output.
All lived beneath the printed root; screenshot/trace/video disabled, no shared
credentials or hosting service. Storage preflight passed on `/tmp` (661 GiB free).
Each outer launcher finally stopped owned processes and removed its root, including
failed-run error context. Independent checks confirmed both roots absent, no
accessible process carrying either marker, no repository workspace fixture file,
and 8004/5177 accepting server-style binds. 31 protected environments unreadable.
Useful diagnostic facts are retained here; raw disposable output was removed.

Own pytest-1/2 scratch removed after accessible cwd/open-file/memory-map checks
(zero references, zero regular files/bytes; 31 protected processes unreadable).
Its current symlink and task-local documentation script removed; absence verified.
Unrelated pytest-0 and user data preserved. Frontend share-test scratch uses its
existing finally cleanup.

`just test-smart --dry-run` still classifies accumulated changes as FULL then FAST
after deferral. **Zero broad tests ran**, no FAST pass or broad debt clearance.
Literal deferral:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

The same 19 historical timing candidates remain; prior triage is unchanged. No
new focused timing offender, guard/threshold adjustment or scientific selection.
Memory lint: 0 errors/0 warnings. Current local plan/report/memory link targets
pass; ledger verifies 38 unique milestones, 21 Done and 58 U checkpoints. Exactly
one successor (S30) and matching current issue/manual records verified. Historical
issue-ledger artifact links outside the changed entry were not re-audited.

## Sole successor and counts

**S30 — bounded sealed readiness read**, fully specified in the
[handoff](session_handoff.md), is unstarted. It must preserve ordinary readiness
facts and matching read-only job-completion evidence without claiming scientific
validation, exposing request-controlled paths or adding compatibility fallback.
This is a concrete internal implementation gap, not a user-authorization blocker.
No readiness implementation or other polling repair was begun in S29.

S29 stays **partial**; the remaining gesture/console acceptance is retained in the
acceptance matrix, ISSUE-100 and MV-48. Plans, ledger and project memory agree.
**21/38 complete; 17 remaining (8 core,9 parked), delta +0/+0. U1–U58 unchanged.**
No U59 for test-harness/diagnostic work. FH-20 remains growth flagged at four
engineering checkpoints with its fixed release exit intact. Production immutable,
preview, history and creation gates remain false. No commit/push; goal active.
