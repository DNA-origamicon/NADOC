# S23 — Private immutable geometry staging, October 17, 2026

Parent FH-20, supporting existing FH-28/FH-27 exits. Current handoff, repository
instructions, scoped rules, ownership report, typed deformation integration,
project memory and ledger read. HEAD remains `96ab701e`; existing dirty work
preserved. S22 was verified progress, not milestone closure.

## Delivered

Existing `_change` is separated into `_stage` and immediate publication, in the
same host. `_stage` preserves worker admission, request ownership/digest, shared
slot, native proof, preservation validation, off-lock sealing and final context
check. It returns a frozen internal record containing only sealed candidate plus
admission/context, weak session/source bindings, hashes, identifiers, original
cancellation event and deadline. No live mutable Design or publication permit is
retained in that record. No new registry, worker queue or storage format.

Edit and append both call this seam; under the existing lock they recheck source,
session, revision, policy, gate, cancellation and expiry before issuing the existing
permit and publishing once. A closed/collected session fails closed. Existing
error normalization and undo/publication machinery are preserved. There is no
public staged-commit endpoint, new caller authority or implicit mutable conversion.

Two real subprocess/native Bend/Twist tests prove private staging leaves source,
revision, history and nonempty redo unchanged; candidate inputs/identity are exact
and independent replay passes. Seven additional tests invalidate authority in the
new staging/publication gap, each refusing before permit issuance. Existing tests
exercise changes during work/preparation, failure atomicity, native edit/append,
exact-handle undo/redo, persistence/recovery and strict HTTP lifecycle.

## Validation

Serialized `just test-focused` runs:

| File | Result | Duration |
|---|---|---|
| tests/test_part_immutable_geometry_host.py | 46 passed | 7.35 s |
| tests/test_part_immutable_deformation.py | 23 passed | 7.97 s |
| tests/test_part_immutable_geometry_append.py | 18 passed | 8.46 s |
| tests/test_part_strict_geometry_http.py | 19 passed | 6.34 s |

**106 distinct focused tests pass.** Initial host run: 44 pass/2 fail because new
tests named AdmissionContext.expected_revision instead of source_revision; fixed
test assertions, no weakened contract. An attempted multi-file test-focused call
was rejected by its single-target parser before any tests ran; corrected to four
serial invocations. Changed-file Ruff passes; no frontend/runtime-browser change.

`just test-smart --dry-run` routed accumulated changes to FULL, fell back to FAST,
ran **zero broad tests**, and printed literally:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

The “ran” wording is selector boilerplate, not an executed FAST result. Its guard
also reported 19 historical timing candidates. Applied the required
[triage skill](../../../.claude/skills/triage-slow-tests/SKILL.md): read candidate
report and scoped offender source. `test_real_http_workers_and_durable_acknowledgement`
performs real recovery/edit subprocesses and save; current focused call 2.54 s,
historical 5.17 s. Current new native stage calls 1.28/1.23 s. Other candidates
are unrelated prior broad debt; no guard, threshold or classification changed.
Full broad acceptance remains unverified, not cleared by this focused evidence.

## Cleanup and limitations

No browser/captures or user-workspace files. Scoped fixture output used pytest
scratch. Own pytest-3/4 trees had already auto-pruned; remaining pytest-5/6/7
removed after accessible cwd/open-file/mapping reference checks: 58 files,
422,993 bytes; 31 protected processes unreadable. Absence and pytest-current
cleanup verified. Unrelated pytest-0 retained.

This is an internal staging seam, NOT VERIFIED IN APP and not a complete preview.
Remaining: bounded native display projection, historical-prefix controls, preview
lease ownership/HTTP/editor integration, safe Apply from current authority, full
named/route/preserved lifecycle and representative resources. Existing mutable
preview limits and private immutable gate remain unchanged. Native replay checks
do not authorize scientific changes. No constants, formulas or goldens changed.

21/38 Done, 17 remaining (8 core/9 parked); delta +0/+0; U1–U54 unchanged because
this is a small extraction. ISSUE-100/MV-48 remain open. Sole successor S24 supplies
bounded display projection through existing native worker/serializer owners.

Closeout checks: changed-file Ruff and git diff whitespace checks pass; memory
lint 0 errors/0 warnings. Current plan/report/memory file link targets resolve
(anchors not exhaustively checked); 38 unique milestone rows/21 Done and one S24
successor. No commit or push.
