# S40 — Sealed desktop rerun exposes shared-slot contention

October 17, 2026; HEAD `96ab701e` unchanged. Campaign completed at its two-invocation
cap; desktop lifecycle acceptance remains incomplete. No production code, gate,
scientific constant, resource limit or golden changed. The only test change adds
the bounded (2048-character) Open refusal body to the existing failing assertion.
No assertion, timeout or console check was removed or weakened.

## Actual browser results

Both invocations used the exact guarded command:

```text
NADOC_HISTORY_E2E_SEALED=1 just validate-safe uv run python scripts/run_deformation_history_e2e.py
```

| Invocation / owned root | Case | Result and reached boundary |
|---|---|---|
| 1 · `/tmp/__e2e__history-8g8mr217` | Bend | Failed, 13.6 s. Initial design/geometry and readiness handoff pass; Open preview POST returns 429. Evaluate/Cancel/Apply not reached. |
| 1 · same root | Twist | Failed, 38.0 s. Initial geometry and readiness handoff pass; Open preview POST returns 429. Evaluate/Cancel/Apply not reached. |
| 2 · `/tmp/__e2e__history-1132tq52` | Bend | Failed, 14.7 s. Readiness passes; Open refuses with the exact shared-slot body below. Evaluate/Cancel/Apply not reached. |
| 2 · same root | Twist | Failed, 17.8 s. Initial `/api/design` returns 429; existing 15 s nonempty-geometry wait expires. Readiness/Open/Cancel/Apply not reached. |

**Zero browser passes, four failed executions.** Second invocation was diagnostic:
the test now reports `Open HTTP 429: {"detail":"A part history operation is already
running"}` instead of only true/false. No production retry/fallback was introduced.

S29's readiness boundary is now crossed in three executions, which changes the
next action. It does not establish a successful desktop lifecycle. Cancel identity,
Apply-once history/redo, final geometry adoption and proof assertions have not run.
Console cleanliness also fails: real HTTP 403/429 errors remain, unfiltered.

## Concrete production gap and source evidence

Preview Open (`POST /api/design/features/deformation-preview`) competes with
background annotation and activity reads for `part_history_verification._slot`.
`part_immutable_deformation_preview.run` acquires it nonblocking and produces the
observed refusal text. `part_immutable_display_reads.read` uses the same slot and
returns geometry_busy on contention; S39 activity reads also share that admission.
The native worker cap is doing its job. The desktop has no qualified foreground
admission behavior for these overlapping requests.

`scene/view_volumes.js` polls once per second; `scene/dimension_persistence.js`
refreshes immediately and once per second. Each prevents its own overlap but does
not coordinate with the other or foreground sealed reads/previews. Repeated
view-volumes/dimensions requests alternate 200/429 while activity polling also sees
429. Existing `whenOperationIdle` is explicitly diagnostic, not a lock, with a
bounded 2 s wait; raising it is not an accepted fix. The second Twist failure shows
the same contention can block initial design adoption, not only Open.

Distinct observed unsupported calls also remain (separate from the 429 cause):
GET md/setup-presets, oxdna/available, oxdna/live/available, library/files,
primitives, vr/status, design/placement-integrity-status, library/disk-usage,
md/run-dir-status, engines/status, oxdna/jobs, simulate/jobs and
simulate/recommendation; POST design/animations. These are real 403 console errors.
Do not blanket-allow the routes, return fabricated empty data or filter console
errors to pass the harness. Their client/strict-capability contracts need separate
qualification after the foreground admission correction. S34's unqualified
activity archive/source/ETA/preparation/remote cases remain open as well.

## Validation and cleanup

Before launch: current handoff/instructions/startup records and harness/config/
fixture controls read; HEAD/status reconciled. Portable storage preflight passed
on `/tmp` with 661 GiB free, no preexisting history root, ports 8004/5177 available.
Installed Chromium was resolved read-only; no browser download. One worker, no
retries, existing 60 s test timeout and 15 s adoption/readiness waits retained.

Persistent inventory was declared before Playwright: per-run workspace/project
files/logs, temporary browser profiles/downloads, Vite/Playwright/UV caches and
Playwright result metadata all under the fresh owned root. Screenshots, traces and
video disabled. Test controls use `__e2e__history-*` documents; fixture close and
launcher finally stop owned servers/processes and delete the root on failure.
After invocation 1, independent checks found its root absent, no accessible marked
process, 31 protected/exited environments and available ports. After invocation 2,
both roots independently absent, no accessible marked process, 32 protected/exited
environments and both ports available for server-style binds. Raw roots were
removed by the launcher; evidence retained here is textual only.

`node --check frontend/e2e/sealed_history.spec.js` and `git diff --check` pass.
No backend unit tests, Vitest/full frontend or broad backend sweep ran in S40;
no production behavior changed in this iteration. Existing FastAPI deprecation
and Node color-environment warnings appeared. No scientific/native simulation ran.
Main.js S40 delta: zero. Selector/memory/link/count closeout is recorded below.

## Exactly one successor

S41: correct foreground shared-slot admission under annotation/activity polling,
using the existing resource/lifecycle owner and fixed limits. Its full objective,
files, acceptance and stop condition are in the [handoff](session_handoff.md#next-bounded-task).
Do not start it in this iteration. Unsupported background calls remain a distinct
later obligation, not additional S41 scope. This is an actionable production gap,
not an external permission blocker. ISSUE-100/MV-48 and fixed FH-20 remain open.
21/38 Done,17 remaining (8 core/9 parked), delta +0/+0, U1–U60 unchanged. The campaign
earns no U checkpoint or milestone credit. No commit/push or rollout gate enablement.

## Final closeout

The exact slot holder was not individually instrumented; the observed 429s and
shared-owner source establish contention, not a measured per-request ownership
trace. S41 must reproduce the overlap deterministically before correcting it.

`just lint-memory`: 0 errors/0 warnings; current report/plan/memory links resolve.
Ledger checks: 38 unique FH rows, 21 Done, 60 U rows; one current handoff ID, S41.
Issue/manual records agree. All four production gates remain false. Syntax/diff
checks pass. Three disposable S40 logs were summarized, checked for file/mapping
references (none accessible, 32 processes inaccessible/exited), and removed:
30,446 bytes, all independently absent. No validation handle remains live.

`just test-smart --dry-run` selected FULL for accumulated main.py changes, then
FAST fallback without a dedicated session. **Zero broad tests ran.** Nineteen
historical timing candidates and earlier broad failures remain debt. Required text:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

“Ran” is selector boilerplate, not a FAST execution claim.
