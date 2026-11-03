# S24 — Native staged-revision projection, October 17, 2026

Parent FH-20, supporting FH-28/FH-27. Current handoff, instructions, scoped API
rule, project memory, ledger and worker/display contracts read. HEAD `96ab701e`
unchanged; previous staging and unrelated dirty work preserved. S23 was progress.

## Delivered contract

`_project_staged` runs a fixed native projection target through the existing
immutable input reservation/frame/result binding and supervisor. It reacquires
the existing slot, retains staging's original deadline/cancellation and checks
source/session/revision/policy before work and before returning display. No new
queue, lease registry, storage or public endpoint. No publication permit issued.

Only the child decodes sealed bytes. It requires a closed projection operation
and exact design/feature identity, a typed Bend/Twist feature, geometry storage
scope, complete display admission, prospective work limits and combined output
accounting. It calls the unchanged native deformation display serializer. The
internal packet is explicitly `stage: staged_revision`, `physical_validity: false`,
with one component and exact design/feature IDs. It has no historical controls,
proof certificate or publication authority. Existing feature-prefix DTO assertions
are preserved; a suffix-replayed full candidate cannot masquerade as a prefix.

Both new projection and ordinary evaluation reuse `ImmutableEvaluationWorker`
transport and `supervise`, including digest-bound responses, bounded buffers,
reaping/unlink and slot retention through cleanup. Existing 16-helix/1024-slot,
2 MB display accounting and worker limits remain unchanged. Over-limit refusal
is not larger-part qualification.

## Validation actually run

Serialized `just test-focused` commands:

| File | Result | Duration |
|---|---|---|
| tests/test_part_immutable_geometry_projection.py | 21 passed | 8.04 s |
| tests/test_part_immutable_geometry_worker.py | 23 passed | 11.98 s |
| tests/test_part_immutable_geometry_host.py | 46 passed | 7.76 s |
| tests/test_deformation_preview_native_display.py | 14 passed | 5.03 s |

**104 unique focused tests pass.** Initial 10 projection cases passed in 5.38 s,
then expanded with in-flight invalidation/cleanup and malformed operation checks.
New Bend/Twist projection tests launch real children, compare exact native component
output, forbid parent materialization/decode/permit issuance, preserve nonempty redo
and canonical state, and check process closure plus both shared-memory names absent.
Staging in those tests uses the existing synchronous native fixture; separate host
tests exercise real evaluation workers. Seven preflight and seven in-flight changes
cover revision/source/session/policy/gate/cancel/deadline. Output-budget and malformed
identity/authority refusal tests pass. Native renderer tests exercise existing DTO
wire→Three.js geometry parity; no browser or scientific-validation claim.

Changed-file Ruff and diff checks pass (removed one unused test import). No formulas,
locked phases, native placement, golden or gate changes. No full frontend/smoke run.
`just test-smart --dry-run` routes accumulated changes to FULL then selects FAST;
**zero broad tests ran**. Literal selector debt:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

“Ran” is boilerplate, not a FAST pass. The same 19 historical timing candidates
were reported. Existing [triage skill](../../../.claude/skills/triage-slow-tests/SKILL.md)
and report remain applicable; this turn's scoped tests introduce no >5 s per-test
offender. No thresholds/classifications changed; broad debt remains.

## Cleanup, limits and next task

No browser, captures, user design output or cache migration. Own pytest-1/2 trees
auto-pruned; remaining pytest-3/4/5 were empty (0 regular files/0 bytes), removed
after accessible cwd/open-file/mapping checks; 31 protected processes unreadable.
Absence and pytest-current cleanup verified. Unrelated pytest-0 retained. New real
projection tests independently verify child/buffer cleanup on success and refusal.

NOT VERIFIED IN APP. Prefix controls, sealed preview lease/HTTP/editor integration,
Apply/creation and larger-part resource acceptance remain. S25 solely integrates
sealed historical Prepare/Evaluate/Cancel through existing ownership, using true
prefix semantics rather than reusing this final-revision component as controls.

21/38 Done, 17 remaining (8 core/9 parked), delta +0/+0; U1–U54 unchanged.
ISSUE-100/MV-48/FH-20/FH-27/FH-28 remain open. No milestone credit, commit or push.

Closeout: memory lint 0 errors/0 warnings; current plan/report/memory file links
resolve (anchors not exhaustively checked); 38 unique milestones/21 Done and one
S25 successor. Changed-file Ruff and diff whitespace checks pass.
