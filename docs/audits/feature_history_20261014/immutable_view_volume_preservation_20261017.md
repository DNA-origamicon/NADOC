# S32/U60 — Bounded geometry-only view-volume preservation

October 17, 2026. Delivered against unchanged HEAD `96ab701e`; unrelated dirty
worktree changes preserved. S31's populated-view read acceptance is now complete.
This is one-field preservation/lifecycle acceptance, not FH-28 closure.

## Implementation and acceptance

`part_view_volume_preservation.py` checks exact list/model/dictionary/schema types
before traversal, at most 128 records, id/name strings at most 1024 characters
each, exact finite numeric tuples/scalars, booleans and closed enum values. It
revalidates ordinary ViewVolume bounds, quaternion and opacity rules only after
bounded shape admission. It projects every existing persisted field in order,
without invoking model serializers or reading a canonical source model.

`part_immutable_preservation.preservation_digest` opts geometry into that projection;
its default remains the old batch restriction. Geometry revision preparation and
metadata hashing opt in explicitly. Geometry scope alone exempts the validated
field from its empty-presentation check. Batch admission and all other preserved
fields remain unchanged. The existing v1 digest for empty volumes is identical;
no format, version, saved-data migration or digest rewrite was needed.

The first real Apply test correctly failed with `revision_preservation_changed`:
ordinary proof capture excludes presentation, so candidate regeneration had lost
the volumes. The geometry worker now transfers only this validated field from its
private decoded source into the owned evaluator input. It charges that field first
and subtracts its cost from the existing **30,000-node/2,000,000-byte** capture
allowance. Existing time/transport/output bounds are unchanged. Ordinary native
publication carries the field forward; the parent checks the exact preservation
digest before sealing/commit. Dropped, changed or reordered candidates refuse.
No source decode, mutable canonical alias or new preservation cache is introduced.

Tests compare the digest against an independent full-model projection and verify
complete serialized fields/order after seal, native Bend/Twist Apply, geometry
edit/append, exact-handle undo/redo, typed-file save/close/recovery, and populated
annotation GETs. Parent source decoding is explicitly trapped in the Apply tests.
The S31 storage-refusal cases were replaced by populated parity rather than kept
as an artificial product restriction. Other scope/refusal tests remain intact.

Limits are explicit: records beyond the bounded field envelope refuse; this does
not qualify near-limit interactive latency, arbitrary presentation state, named
organization, routing, assembly or a production rollout. Scientific construction,
locked constants, thresholds and goldens are unchanged.

## Validation actually run

All executions used sequential `just test-focused TARGET` guards. Final distinct
coverage: **260 passes**; the 22-case geometry scope target also passed a second
time after adding its exact-Design precheck.

| Target | Result | Seconds |
|---|---:|---:|
| `tests/test_part_view_volume_preservation.py -x` | 19 passed | 16.32 |
| `tests/test_part_view_volume_recovery.py` | 2 passed | 13.94 |
| `tests/test_part_immutable_annotation_reads.py` | 35 passed | 16.22 |
| `tests/test_part_immutable_preservation.py` | 32 passed | 3.11 |
| `tests/test_part_immutable_revision.py` | 49 passed | 2.83 |
| `tests/test_part_immutable_geometry_scope.py` | 22 passed, repeated 22 passed | 3.09 / 3.06 |
| `tests/test_part_immutable_geometry_worker.py` | 23 passed | 12.77 |
| `tests/test_part_immutable_geometry_host.py` | 46 passed | 7.43 |
| `tests/test_part_immutable_preview_apply.py` | 16 passed | 27.46 |
| `tests/test_part_immutable_geometry_recovery.py` | 16 passed | 7.61 |

The initial preservation run had 14 passes/1 failure (5.85 s), exposing the capture
omission described above. It was fixed before the final passes; acceptance was not
weakened. Deprecation warnings (including ORJSONResponse) remain.

Following the repository [slow-test skill](../../../.claude/skills/triage-slow-tests/SKILL.md),
the new recovery test's 5.02/6.02 s cases were classified in `_SLOW_TESTS` and mapped
to `headless`. They run four native workers plus typed-file persistence, so this
is intentional integration cost. Source selector leaves cover the new preservation
module and shared preservation module; geometry already routes to headless.
Guarded `--collect-only -m slow` and `--collect-only -m headless` each selected both
cases. No budget or test-session guard changed; no broad timing pass is claimed.

Changed-file Ruff and `git diff --check` pass. `just lint-memory`: 0 errors and
0 warnings. Current local links, unique 38 milestone rows/21 Done, 60 engineering
rows, one S33 successor and issue/manual current records checked.

`just test-smart --dry-run` selected FULL from accumulated `main.py` changes then
FAST fallback without a dedicated session. **Zero broad tests ran**; nineteen
historical timing candidates remain debt. Required selector wording (the “ran”
phrase below is boilerplate, not execution evidence):

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

No browser, full frontend, broad backend or scientific run. S29 desktop lifecycle
remains partial; the three observed service polling refusals remain pending.

## Cleanup and sequencing

Local `/tmp` had 662 GiB free. Own final pytest roots 10/11/12 were removed after
cwd/open-file/memory-map checks found no accessible references (31 inaccessible
or exited records limit inspection). Root11 contained 16 files/220,697 bytes;
roots10/12 were empty. Pytest retention removed earlier S32 roots. Own roots are
absent; unrelated `pytest-0` remains. Disposable logs and the documentation script
were removed after recording their outcomes. No app server or user simulation was
launched; no user workspace fixture was created.

**21/38 milestones Done; 17 remaining (8 core,9 parked); delta +0/+0.** U60 is
engineering checkpoint60, FH-28 checkpoint11 (growth flagged). Other preserved
fields and full immutable/resource/desktop exits remain open. ISSUE-100/MV-48 stay
open. All four production gates remain false. No commit or push.

The sole successor is **S33**, strict desktop session-status reads for VR references
and collaboration peers, with active-job reconciliation excluded. Its objective,
parent, deliverables, files, checks, exclusions and stop condition are in the
[current handoff](session_handoff.md#next-bounded-task). S33 is unstarted.
