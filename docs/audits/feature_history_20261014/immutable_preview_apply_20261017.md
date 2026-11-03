# S26 / U56 — Sealed historical Apply, October 17, 2026

Parent FH-20 checkpoint 2, supporting FH-28/FH-27. Current handoff, instructions,
project memory/ledger and scoped ownership/artifact contracts read. HEAD remains
`96ab701e`; prior and unrelated dirty changes preserved. S25 was progress.

## Delivered

Prepare's bound worker response now supplies a scalar feature index beside its
existing display packet. The retained descriptor keeps index plus deformation ID,
never a model or proof. Apply passes index and exact feature identity to immutable
staging; the worker rechecks the actual selected source row, so a corrupted cached
index cannot select another command. A closed internal preview-patch mode runs
existing local native preview validation, then full independent source/suffix proof.
The mode is stripped before native authoring evaluation and is not a public input.

The existing shared preview `_publish` reserves committing, rechecks its catalog/
sequence/source/policy and publishes the exact sealed staged candidate using the
immutable one-shot permit and existing replacement transaction. The same helper
issues permits for ordinary immutable edit/append. Permit expiry is no later than
the original staging deadline or lease expiry. Preservation is already independently
checked by immutable staging; no mutable preservation/capture is run on sealed
content. No new host/queue/registry/storage or public commit capability.

The original Cancel-during-commit, rollback-to-ready and scalar receipt retention
code remains shared. Status checks the committed source and recovers the receipt;
it does not reissue Apply. Source, session, revision, policy, request, feature,
sequence, cancellation and expiry stay bound. Preview packets never supply proof.
No formulas, phase constants, topology, goldens or production gates changed.

## Validation actually run

Serialized `just test-focused` final results:

| File | Passes | Duration |
|---|---:|---:|
| test_part_immutable_preview_apply.py | 16 | 27.50 s |
| test_part_immutable_deformation_preview.py | 21 | 27.11 s |
| test_part_deformation_preview_sessions.py | 29 | 4.75 s |
| test_part_deformation_preview_receipts.py | 12 | 3.32 s |
| test_part_immutable_geometry_host.py | 46 | 7.34 s |
| test_part_immutable_geometry_worker.py | 23 | 11.74 s |
| test_part_immutable_deformation.py | 23 | 8.33 s |

**170 distinct focused tests pass.** Initial 12 Apply cases passed in 21.63 s
before four added negative cases; no failed run. New real native Bend/Twist Apply
checks exact feature inputs, full suffix replay, independent regeneration, one
revision/undo, exact-handle undo/redo, lost-reply Status/Cancel receipt and duplicate
Apply refusal. Child closure and both shared-memory names absent are asserted.
Other new cases cover eight staging/publication invalidations, Cancel during
commit, revision-assignment rollback, expired commit permit, corrupted cached index,
source authoring mismatch and invalid draft. Mutable lease/receipt tests and ordinary
immutable workers/edit/deformation lifecycle remain passing. No scientific sampling.

Changed-file Ruff/diff checks pass. `just test-smart --dry-run` selects FAST after
FULL routing from accumulated changes; zero broad tests ran. Literal selector debt:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

“Ran” is boilerplate, not an executed FAST result. Same 19 historical timing
candidates remain under the previously applied [triage skill](../../../.claude/skills/triage-slow-tests/SKILL.md).
No scoped >5 s offender, threshold/marker change or clearance of broad debt.

## Cleanup and remaining work

No browser, captures or user-workspace output. Own pytest-1…5 trees auto-pruned;
remaining pytest-6/7/8 removed after accessible cwd/open-file/mapping checks:
22 files, 123,278 bytes; 32 protected processes unreadable. Absence and pytest-current
cleanup verified; unrelated pytest-0 retained. Native child/buffer cleanup asserted.

NOT VERIFIED IN APP. Internal sealed historical lifecycle works on small fixtures;
strict HTTP still excludes preview paths. S27 solely adds gated, source-bound strict
HTTP admission using existing paths and host. Editor/read/adoption/creation support,
named/preserved/routing coverage and representative latency/resource/release acceptance
remain. All relevant gates stay false; no legacy preview pruning.

21/38 Done, 17 remaining (8 core/9 parked); milestone delta +0/+0. U56 is engineering
checkpoint 2 for FH-20, 56 total, not a completed milestone. ISSUE-100/MV-48 remain
open. No commit or push. Sole successor S27 is unstarted.

Closeout: memory lint 0 errors/0 warnings; changed-file Ruff/diff whitespace pass.
Current plan/report/memory file links resolve (anchors not exhaustively checked);
38 unique milestones/21 Done, 56 unique U checkpoints and one S27 successor.
