# S45 passive readiness admission — October 18, 2026

Parent: FH-20, supporting FH-27/FH-28. Baseline remains `96ab701e` in the
accumulated dirty worktree. This task changes readiness admission and adds focused
regressions; prior changes are preserved. No scientific output, gate, worker
capacity, deadline, frontend behavior or composition-root LOC is changed.

## Reproduction and correction

A real readiness worker held through its cleanup phase prevented historical
Open from reserving foreground admission. The pre-fix focused
`test_foreground_waits_for_real_annotation_cleanup[prepare-readiness]` failed
with HTTP 429, `A part history operation is already running` (one failed,
30 deselected, 4.06s). This proves the classification conflict, but does not
identify the uninstrumented holder in S44's browser failure.

`part_immutable_display_reads.py` now explicitly classifies readiness alongside
view-volumes and dimensions as passive. These reads use the existing nonqueued
background lane. A historical Open/Apply may reserve the one foreground turn
and starts only after the real background worker and buffers drain. Other polls
still fail honestly with 429 while occupied/reserved. The same five-second
end-to-end budget, source/session/policy checks and cancellation owner remain.
Navigation-triggered readiness is also observational and uses this lane.

Current consumer inspection found that readiness already cancels superseded
requests with AbortController/generation checks and schedules the next poll only
after completion. Annotation consumers have in-flight flags; activity has its
existing in-flight promise/cache. No new pending-poll queue or timing lock is
introduced. No frontend edit is needed for the demonstrated backend conflict.
This does not promise that all competing desktop requests succeed or that all
startup capabilities are qualified.

## Executed validation

Serial guarded `just test-focused` invocations, with
`TMPDIR=/tmp/nadoc-s45-j2gsib`:

| Target | Result |
|---|---|
| `tests/test_part_work_admission.py` | 31 passed, 33.31s |
| `tests/test_part_immutable_readiness.py` | 30 passed, 21.53s |
| `tests/test_design_readiness.py` | 40 passed, 2.87s |
| `tests/test_part_immutable_preview_apply.py -k waits_for_background` | 8 passed, 28 deselected, 29.05s |
| `tests/test_part_strict_deformation_preview_http.py -k waits_for_passive_readiness` | 2 passed, 22 deselected, 8.84s |

These cover controlled native Open/combined-display/Apply overlap, HTTP
Open/Apply against real readiness, honest second-poll overload, foreground
reservation exclusivity, worker/shared-memory cleanup, cancellation and stale
source/session/policy retirement, ordinary readiness parity and fail-fast
admission. Native Apply checks both Bend and Twist and exact publication/proof.
Pre-fix failures are retained as reproduction evidence, not passing checks.
Frontend source is unchanged; S44's frontend results are historical, not a new run.

The additional focused invocation
`tests/test_part_immutable_preview_apply.py -k waiting_apply_retires` passes9,
27 deselected in15.38s, covering waiting Apply cancellation, source/revision/session,
policy/gate/sequence changes and expiry/deadline. Total:120 distinct passing checks.

## Browser evidence and remaining work

Command: `NADOC_HISTORY_E2E_SEALED=1 just validate-safe uv run python scripts/run_deformation_history_e2e.py`.
One invocation, workers1/retries0, two executed cases, zero full passes/two failures.
No harness assertion, timeout, console filtering or click behavior changed.

| Fixture | Adoption after Apply response | Executed successful checks | Final failure |
|---|---|---|---|
| Bend | 3376ms | Open/edit/Cancel exact preservation; Open/edit/Apply; revision+1, history+1, redo0; browser design and geometry equality; verified proof | Empty-console assertion:47 HTTP403 and86 HTTP429 errors;53.4s case |
| Twist | 4407ms | Same checks, including native proof | Empty-console assertion:40 HTTP403 and72 HTTP429 errors;42.6s case |

Both diagnostics show browser/canonical revision2,84 nucleotides, history1,
redo0 and zero private preview roots. These are tiny-fixture measurements, not
near-limit resource qualification or a general performance guarantee. S44's
unreached two-family timing and final geometry/proof checks are now satisfied
in this invocation; full desktop acceptance is still failed.

The bounded last40 response events identify429s on `/api/design/view-volumes`,
`/api/design/dimensions`, `/api/design/readiness` and `/api/jobs/active`;403s on
`/api/simulate/jobs`, `/api/simulate/recommendation`, `/api/md/jobs`, `/api/oxdna/jobs`
and (Twist) `/api/design/placement-integrity-status`. This is a last40 window,
not a complete startup endpoint inventory. Console totals above cover each full
case. Cross-consumer polling still competes; per-consumer in-flight flags do not
coordinate distinct routes. This is the specific remaining part of S45's broader
objective, selected as S46. No second identical diagnostic run was needed.

S46 is the sole unstarted successor: bounded coordination of supported passive
reads through the existing client request owner. Its full objective, files,
deliverables, acceptance/exclusions and stop condition are in the
[current handoff](session_handoff.md). Startup403 capabilities remain later work;
no fake report, endpoint allowlisting or console suppression is authorized.

## Guards, cleanup and status

Storage preflight used `/tmp` with661GiB free. The launcher owned workspace/project
stores/logs, profiles/downloads, caches and Playwright output under
`/tmp/__e2e__history-votzvb7u`; captures off, installed browser cache read-only.
Launcher cleanup completed after both failures. Independent inspection finds the
root absent, no accessible process with its marker, no8004/5177 listeners and
successful SO_REUSEADDR binds on both ports;31 protected/exited environments
could not be read. No user workspace fixture or installed dependency was removed.

`just test-smart --dry-run` selected foundational FULL scope and FAST fallback;
zero tests executed by that command. Its retained debt is verbatim:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

The boilerplate “ran” is not execution evidence. The19 historical timing candidates
remain separate; no new over-budget test was reported in these focused checks.
No broad sweep, CPD campaign, scientific simulation, gate change, commit or push.
`just lint` passes. Final memory/link/count/diff and scratch cleanup follow below.
Fixed milestone count remains21/38 Done,17 remaining (8 core/9 parked),delta+0/+0.
U1–U60 unchanged; FH-20 at5 and FH-28 at11 remain growth flagged. This routine
admission correction earns no new U number and does not close ISSUE-100/MV-48.


Final closeout: `just lint-memory` reports0 errors/0 warnings;336 current-document
local links resolve; ledger checks confirm38 rows/21 Done/60 U checkpoints;
`git diff --check` passes. All four production gates remainfalse; main.js LOC delta0.
Owned scratch `/tmp/nadoc-s45-j2gsib` held100,970 bytes of disposable test/log/script
output. After all command handles finished, `/proc` cwd/fd/maps inspection found
zero references (31 protected/exited processes unreadable); the exact owned root
was removed and independently confirmed absent. Historical timing candidates
remain19 with none from this task's test files. No successor implementation began.
