# S42 — sealed historical Apply admission

Bounded correction for FH-20, supporting FH-28. HEAD remains `96ab701e`; the
current S42 handoff matches the worktree. S41 had qualified foreground reads and
preview preparation/evaluation, but geometry staging still refused all overlap.
Existing unrelated changes are preserved. No fixed milestone exit is complete.

## Delivered behavior

The sealed preview adapter passes its existing lease check and expiry to private
geometry staging. That check binds the original document/source/revision/session,
policy generation and request sequence before waiting and after admission.
Staging uses S41's existing shared owner and one foreground reservation behind
background reads. Ordinary geometry requests retain immediate refusal.

The deadline starts before admission and is capped by lease expiry. Waiting,
worker computation and sealing consume that same allowance. A cancelled, stale,
superseded or expired request cannot allocate a worker while waiting. Staging
retains its existing native full proof, exact source capture and immutable
candidate checks. Publication still rechecks both the lease and staged authority
and uses the existing atomic transaction and recoverable scalar receipt.

No new queue, worker, lifecycle owner, storage format, gate or resource-limit
increase. No scientific computation/constant/golden change. `main.js` LOC Δ0;
frontend behavior and diagnostic timing are unchanged.

## Validation

Guarded focused targets run serially through `TMPDIR=/tmp/nadoc-s42-C3bGlB
just test-focused tests/<target>.py`. Results and cleanup are recorded below.
Native Bend/Twist cases overlap Apply with real view-volume/dimension reads and
strict activity reads. They hold background cleanup, assert no early publication
or second worker admission, then require one revision/history entry, cleared redo,
full native proof, receipt recovery and removed worker/shared-memory resources.
Waiting invalidation covers cancellation, source/revision/session/policy/gate,
sequence, lease expiry and computation deadline. Existing tests cover rollback,
undo/redo, receipt recovery, staged-publication gaps and ordinary regressions.

No browser or broad-suite result is claimed. S40 remains the latest sealed desktop
evidence: zero passes/four failed cases. Startup403s and background overload errors
remain visible; current task does not qualify startup capabilities or polling UI.

## Sole successor and milestone status

S43 is unstarted: at most two guarded sealed Bend/Twist browser invocations, with
unchanged lifecycle/console assertions and independent artifact/process/port
cleanup. This uses the now-qualified foreground admission seams to establish
actual browser progress and the next exact blocker. It is not authorization to
repair all startup routes. Full contract: [handoff](session_handoff.md#next-bounded-task).

ISSUE-100/MV-48 and FH-20/FH-27/FH-28 remain open. **21/38 complete,17 remaining
(8 core,9 parked), delta+0/+0; U1–U60 unchanged.** This admission correction earns
no major engineering checkpoint or fixed milestone closure. No external permission
blocker, rollout enablement, legacy pruning, commit or push. Goal remains active.

## Executed results

**158 distinct focused tests passed**, zero failures. Six serialized invocations
across five files; the three inflight tests were added and selected separately
with `-k inflight` (31 already-run cases deselected).

| Target | Passed | Duration |
|---|---:|---:|
| test_part_immutable_preview_apply | 31 | 58.63 s |
| test_part_immutable_preview_apply -k inflight | 3 | 6.98 s |
| test_part_immutable_geometry_host | 46 | 7.35 s |
| test_part_deformation_preview_sessions | 29 | 4.70 s |
| test_part_work_admission | 27 | 25.07 s |
| test_part_strict_deformation_preview_http | 22 | 17.87 s |

The inflight cases cancel, change policy or expire the supervisor deadline after
a native worker starts. They assert the shared slot remains unavailable during
close, no publication/history change occurs, and child/shared memory resources
are gone before final admission is available. The longest new test was3.91s;
existing five-second per-test classification guards are unchanged. Warnings are
existing ORJSONResponse deprecations. No new timing candidate.

`just lint`: pass repository-wide, zero findings. `just lint-memory`: zero errors,
zero warnings. `git diff --check`: pass.331 local links in current task documents
and affected issue/manual paragraphs resolve; ledger independently counts21 Done
of38, with60 U rows. Four production gates verified false; main.js Δ0.

`just test-smart --dry-run` retains FULL routing from accumulated main.py changes
and FAST fallback; it executes zero tests. Its boilerplate “ran” is not a test
pass. Verbatim debt:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

The existing19 historical timing candidates and failed broad validation remain;
prior triage is retained. No guard, broad-session marker or threshold was changed.

Cleanup: `/tmp` had662GiB free before these small focused runs. All logs and pytest
scratch stayed in `/tmp/nadoc-s42-C3bGlB`. After test/selector handles completed,
`/proc` inspection found no accessible cwd/open-file/mapping references to it
(31 protected/exited processes unreadable); no runtime configuration referred to
it. Removed26,446 file bytes and independently verified the root absent. Unrelated
scratch and user data were preserved. No browser/server/capture was created.

Handoff, both plans, ledger, project memory and ISSUE-100/MV-48 agree on S43 as the
only unstarted successor. S42 is complete as a bounded correction, with full
browser/console/latency and milestone qualification still explicitly incomplete.
