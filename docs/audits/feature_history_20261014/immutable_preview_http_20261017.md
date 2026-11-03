# S27/U57 — Strict sealed historical preview HTTP admission

Parent FH-20; supports FH-28/FH-27. HEAD remains `96ab701e`. Current handoff,
repository instructions, scoped API rule, module-first rule, artifact policy,
project memory, ledger and relevant acceptance/host contracts read. The recorded
S27 prerequisite matched the source: the private sealed lifecycle existed, but
strict dispatch rejected its paths. Prior and unrelated dirty work preserved.

## Delivered boundary

`part_strict_deformation_preview_http.py` provides five thin POST handlers at the
existing historical Prepare/Evaluate/Apply/Cancel/Status paths. The strict closed
route table selects them without compatibility fallback. Both preview and immutable
gates remain false by default. Creation remains unlisted. Existing bounded JSON
acquisition captures document/session identity, exact sealed source, revision and
policy before reading the body and rechecks before dispatch. The existing source
context follows thread work into host admission and publication; it is reset on
exit. A successful Apply response is not invalidated by its own revision advance.

Prepare and source-current checks in the shared lease host now honor captured HTTP
ownership. No new host, worker queue, lease registry or storage format. Cancel
retains catalog-only nonce/lease semantics after HTTP admission: it cannot publish
or undo and remains callable during commit. An initially added state-lock check in
Cancel was removed during review because the existing commit callback may call
Cancel while holding that non-reentrant lock. Existing commit tests remain intact.
Request cancellation drains bounded work rather than becoming implicit lease Cancel;
publication outcome remains recoverable with Status. Existing byte/time budgets,
scientific behavior, locked constants and golden files are unchanged.

## Validation

Serialized `just test-focused TARGET` runs (final passing results):

| Target under `tests/` | Passed | Seconds |
|---|---:|---:|
| test_part_strict_deformation_preview_http.py | 22 | 17.26 |
| test_part_strict_http.py | 61 | 3.65 |
| test_part_strict_geometry_http.py | 19 | 6.37 |
| test_part_deformation_preview_routes.py | 13 | 3.82 |
| test_part_deformation_preview_sessions.py | 29 | 5.07 |
| test_part_deformation_preview_receipts.py | 12 | 3.83 |
| test_part_immutable_preview_apply.py | 16 | 27.23 |

**172 unique focused tests pass.** New HTTP tests launch real native children for both
families, independently verify published content, recover the exact receipt, undo
to the exact source, and test Cancel with unchanged canonical/history/redo state.
They cover disabled-before-body, unlisted methods/paths, malformed/authority-bearing
bodies, five acquisition changes, reopen between handler and host admission, and
request-task drain. The drain test substitutes a bounded blocking function; it is
not a browser disconnect campaign. Existing immutable Apply tests cover actual
child/shared-memory cleanup and Cancel during commit.

Initial new tests passed 19/19 (11.42 s), then 22/22 (17.34 s); another 22/22 run
passed (17.45 s). An earlier process's terminal output was unavailable after context
compaction; no result credited to it. Compatibility regressions exposed one obsolete
assertion: strict preview previously returned blanket 403/construction_policy;
now the closed adapter refuses its disabled immutable gate with exact
409/immutable_geometry_unavailable before parsing malformed JSON. First correction
updated status but missed the following code assertion; both failed runs had
12 passes/1 failure. Final test requires the exact new status and code, retains the
host-never-called assertion and all other refusal checks. No acceptance weakened.
FastAPI emits its existing ORJSONResponse deprecation warning; explicit thread-side
bounded response serialization is preserved.

Changed-file Ruff and `git diff --check` pass. `just lint-memory` finishes with
0 errors/0 warnings; an intermediate run correctly reported the not-yet-written
evidence file as two missing links, resolved by completing this report.

`just test-smart --dry-run` classifies accumulated changes as FULL then selects
FAST after deferral. **Zero broad tests ran; no FAST pass or debt clearance.**
The first classification attempt was refused because focused validation still
held the test lock; it ran no tests and was retried only after completion.
Literal selector deferral:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

“Ran” is selector boilerplate, not execution evidence. The same 19 historical
unmarked timing candidates remain; the previously applied
[triage skill](../../../.claude/skills/triage-slow-tests/SKILL.md) classification
and failed broad-run debt remain open. This task's final new HTTP cases stayed
below the existing five-second per-test limit (maximum 4.30 s). No timing guard,
scientific selection or resource budget changed.

Own pytest-11/12/13 trees were removed after accessible cwd/open-file/memory-map
reference checks (zero references; 32 protected process records unreadable).
They contained zero regular files/zero bytes at cleanup; earlier own trees were
auto-pruned by pytest. Their current symlink and task-local documentation script
were removed; absence verified. Unrelated pytest-0 remains untouched. No browser
or user-workspace artifacts created. Current plan/report/memory link targets and
38 milestone/21 Done/57 checkpoint counts checked; historical issue-ledger links
outside the changed current entry were not re-audited.

## Remaining exit and one successor

No browser/app, production rollout, larger-part latency/resource or broad-regression
qualification. `/api/design` and `/api/design/geometry` remain unlisted for strict
sources. `refreshCommitted` in `frontend/src/api/deformation_preview_endpoints.js`
requires these reads between two exact Status receipts plus a revision check.
**S28** is the bounded sealed read-adapter task defined completely in the
[handoff](session_handoff.md); not started here. No external blocker for that task.

**21/38 milestones complete; 17 remaining (8 core,9 parked), delta +0/+0.** U57 is
engineering checkpoint 3 on still-open FH-20; task growth flagged. Fixed exits and
38-milestone denominator unchanged. U1–U57 total57 checkpoints have closed four
milestones since B1; this task closes none. ISSUE-100/MV-48 remain open. Plans,
ledger, project memory and their current issue/manual records agree. No commit or
push; the user-authorized milestone goal remains active.
