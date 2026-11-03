# S31 — Annotation reads; populated view-volume acceptance blocked

October 17, 2026. **Partial**, not a completed engineering milestone. HEAD remains
`96ab701e`; S30 readiness and other existing dirty changes were preserved.

## Delivered and unmet acceptance

Two closed GETs in `part_immutable_display_reads.py` use the existing captured
sealed source, worker/transport, shared slot and supervisor:
`/api/design/view-volumes` and `/api/design/dimensions`. Both return complete
ordinary response fields and captured revision for admitted sources. Dimension
records preserve names, endpoints and visibility; view volumes currently must be
empty to enter this storage scope. The optional view-volume `document_id` and
required dimension `document_id` are checked against captured metadata before
worker launch. Mismatch, repeated query fields and unsupported inputs refuse.
The shared read parser also rejects repeated fields on existing display reads.
No compatibility fallback, parent model materialization or mutation permit.
Mutation methods remain refused; existing source/session/revision/policy/gate/
cancellation checks, five-second deadline, native scope, output bounds and cleanup
remain in force. No frontend or ordinary annotation handlers changed.

**Specific blocker:** `part_immutable_revision._prepare_revision` calls
`part_immutable_preservation.preservation_digest` before sealing. Its reviewed
`_EMPTY_LISTS` includes `view_volumes`; any nonempty list raises
`unsupported_revision_preservation` with “Strict preservation initially requires
empty view_volumes”. Both native Bend/Twist fixtures reproduce this. Dimensions
are admitted authoring state, so empty/populated dimension parity passes.

The stop condition explicitly permits documenting an unsupported persisted-state
conflict. This session did not widen the preservation contract, forge a sealed
fixture or discard populated volumes. S31's required populated-view parity remains
unmet, even though the two routes now serve supported sources. The diagnostic
refusal tests are temporary evidence of this gap, not a desired permanent product
restriction. Completing that acceptance needs a bounded exact preservation digest
and publication/lifecycle evidence, not simply a GET allowlist entry.

## Checks actually run

Sequential guarded `just test-focused TARGET` runs, **162 passes** total:

| Target | Result | Duration |
|---|---:|---:|
| `tests/test_part_immutable_annotation_reads.py -x` | 37 passed | 15.73 s |
| `tests/test_part_immutable_display_reads.py` | 25 passed | 18.96 s |
| `tests/test_part_immutable_readiness.py` | 30 passed | 23.44 s |
| `tests/test_part_strict_http.py` | 61 passed | 3.89 s |
| `tests/test_dimensions_persistence.py` | 5 passed | 2.85 s |
| `tests/test_view_volumes_api.py` | 4 passed | 2.82 s |

New cases cover native response parity (empty volumes, empty/populated dimensions),
parent ownership, unchanged canonical source/history/redo, optional/required
identity, mismatch/duplicates/unsupported input, gate and mutation-path refusal,
in-flight source/session/revision/policy/gate/cancel changes, worker/shared-memory
cleanup and output-budget refusal. Two cases verify the unresolved storage conflict.
Largest new test call was 1.34 s; existing slow classifications were retained.
Deprecation warnings remain (including ORJSONResponse); they are not app acceptance.
Changed-file Ruff and `git diff --check` pass. `just lint-memory` passes with
0 errors/0 warnings. Current links, one successor and ledger counts checked.

`just test-smart --dry-run` selects FULL for accumulated `main.py` changes and
FAST fallback without a dedicated session. **Zero broad tests ran.** Nineteen
historical timing candidates remain debt; no new over-five-second annotation test.
Required selector wording below is boilerplate, not a claim that FAST ran:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

No browser, full frontend, broad backend or scientific run. S29 Open/Cancel/Apply
remains unreached in its last browser evidence. VR references, active jobs and
collaboration status remain refused polling families; readiness/annotation HTTP
coverage does not qualify the browser console gate or release/resource exits.

## Cleanup, status and sole successor

Local `/tmp` had 662 GiB available. Own final pytest roots 4/5/6 were removed after
cwd/open-file/memory-map inspection found no accessible references; 32 inaccessible
or exited process records limit that check. Root5 had three files/225 bytes; roots
4/6 were empty. Pytest retention removed earlier task roots. All selected roots
are absent and unrelated `pytest-0` remains. Disposable regression/selector logs
and the documentation script were removed after their results were recorded here.
No app server launched and no user workspace artifact was created by this task.

**21/38 Done; 17 remaining (8 core,9 parked); delta +0/+0.** U1–U59 remain 59
engineering checkpoints, FH-20 checkpoint5 growth flagged. Routine adapter work
and this diagnosis receive no new U number. Fixed exits, ISSUE-100/MV-48 and the
milestone goal stay open. All four production gates remain false; no commit/push.

**S32**, unstarted, is the sole successor: bounded preservation of the one
`view_volumes` field for sealed geometry, including unchanged-candidate publication,
undo/save/recovery and populated annotation-read parity. Other preserved fields
remain excluded. The [current handoff](session_handoff.md#next-bounded-task)
contains its objective, parent FH-28, files, deliverables, checks, exclusions and
stop condition. No S32 implementation began.
