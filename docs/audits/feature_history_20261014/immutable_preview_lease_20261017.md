# S25 / U55 — Sealed historical preview leases, October 17, 2026

Parent FH-20 checkpoint 1; supporting FH-28/FH-27. Current instructions/handoff,
project memory, ledger, scoped API rule, artifact policy and relevant lease/native
contracts read. HEAD `96ab701e` unchanged; prior staging/projection and unrelated
dirty work preserved. S24 was progress; this task does not close a fixed milestone.

## Delivered

A closed `part_immutable_deformation_preview` adapter uses the existing preview
catalog, nonce/lease/timer/tombstone/sequence handling and work slot. Sealed sources
require strict immutable geometry policy; mutable behavior stays on its original
compatibility path. Only historical Bend/Twist is admitted. Sealed Apply, creation,
Sweep/transform previews explicitly refuse. No public route or editor gate changed.

The child receives sealed bytes through the existing bounded immutable transport,
checks storage and editable-loadout scope, reconstructs the true historical prefix,
and calls existing native preparation/evaluation/DTO functions. Only a scalar
operation identity survives as the prepared lease; no mutable prefix/model cache
or second registry. Each Evaluate reconstructs its prefix in the child; performance
of this strategy is not qualified. Existing five-second worker and 60-second lease
bounds remain. Cancel/expiry sets the per-lease event; the shared supervisor reaps
and unlinks before releasing resource admission. Source/session/revision/policy,
sequence and catalog membership are rechecked before returning a packet.

The packet remains feature-stage, downstream_evaluated false and physical_validity
false. S24 final-revision components are not substituted for prefix controls.
No preview packet grants proof or publication authority; no source conversion,
formula/phase/topology/golden or private gate changes.

## Checks actually run

Serialized `just test-focused` runs, final results:

| File | Result | Duration |
|---|---|---|
| test_part_immutable_deformation_preview.py | 21 passed | 26.88 s |
| test_part_deformation_preview_sessions.py | 29 passed | 4.72 s |
| test_part_deformation_preview_receipts.py | 12 passed | 3.56 s |
| test_part_deformation_creation_transport.py | 8 passed | 3.75 s |
| test_part_sweep_preview_sessions.py | 15 passed | 3.82 s |
| test_part_transform_preview_sessions.py | 31 passed | 4.11 s |
| test_part_transform_preview_computation.py | 35 passed | 4.27 s |

**151 distinct focused tests pass.** Creation HTTP emitted six existing FastAPI
ORJSONResponse deprecation warnings. No scientific sampling or simulation ran.
New native tests compare exact Bend/Twist prepare/evaluate packets to the existing
service on a history with a later bundle replacement: controls contain original
helices 0_0/0_1 while the final source has 6_6. Feedback-only Evaluate preserves
identity/feasibility without geometry. Source/revision/history/nonempty redo remain
unchanged; sealed Apply refuses. Eight invalidations during both Prepare and
Evaluate cover revision/source/session/policy/gate/cancel/expiry/sequence. Real
child closure and both shared-memory names' absence are independently asserted.
Parent capture/decode is forbidden in the parity tests.

Initial 10 tests failed at fixture construction because an ad-hoc extrusion row
lacked a versioned contract. Changed fixture to the existing native bundle recipe.
Next run failed one assertion that incorrectly assumed the suffix appended helices;
its native bundle replaces them. Corrected to exact prefix/final identity sets.
Then 10 cases passed, expanded 20 passed, final 21 passed. No production contract
was weakened to resolve those fixture errors.

Changed-file Ruff and diff pass. `just test-smart --dry-run` selects FAST after
FULL routing from accumulated changes; zero broad tests ran. Literal debt:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

The “ran” text is boilerplate, not an executed FAST result. Same 19 historical
candidates remain under the previously applied [triage skill](../../../.claude/skills/triage-slow-tests/SKILL.md).
No new scoped >5 s offender or threshold/marker change. Broad debt is not cleared.

## Cleanup and remaining work

No browser, captures or user-workspace output. Own pytest-1…8 trees auto-pruned;
remaining pytest-9/10/11 were empty (0 regular files/0 bytes), removed after
accessible cwd/open-file/mapping checks; 31 protected processes unreadable.
Absence and pytest-current cleanup verified; unrelated pytest-0 retained.

NOT VERIFIED IN APP. Strict HTTP dispatch still does not admit this preview
router, and public editor/route gates remain false. S26 solely integrates sealed
Apply and recoverable receipt lifecycle using the existing immutable host/permit/
replacement transaction. Creation, HTTP/editor bridge, named/preserved/routing
coverage and representative latency/resource acceptance remain open.

**21/38 Done; 17 remaining (8 core/9 parked); milestone delta +0/+0.** U55 records
this private integration as FH-20 checkpoint 1, 55 engineering checkpoints total;
it is not a completed milestone. Original fixed exits unchanged. ISSUE-100/MV-48
remain open. No commit or push.

Closeout checks: memory lint 0 errors/0 warnings; changed-file Ruff and diff
whitespace pass. Current plan/report/memory file targets resolve (anchors not
exhaustively checked); ledger has 38 unique milestones/21 Done and 55 unique U
checkpoints. Handoff has exactly one S26 successor.
