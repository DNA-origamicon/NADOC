# S39 — Closed strict active-job HTTP reads

October 17, 2026; HEAD `96ab701e` unchanged, unrelated work preserved.
`/api/jobs/active` GET now has an exact strict handler backed by S38's bounded
catalog. No request delegates to the ordinary collector or repairs job state.
This delivers supported-scope HTTP admission, not general activity qualification.

`part_strict_activity_reads.py` captures the strict document/session/policy, selects
the workspace only from the host, and acquires the existing shared verification/
geometry slot without queuing. The existing cancellation-draining thread wrapper
retains that slot until actual file work returns, even on repeated cancellation.
Evidence checks the cancellation event and the existing five-second deadline,
including time spent awaiting thread admission. Busy requests return 429. The
slot releases in a final cleanup guard even if watcher cleanup is interrupted.
No new worker pool, persistent cache, job store or lifecycle owner was introduced.

Closed query validation permits only the existing single `doc` parameter; method,
body and media admission remain with the strict dispatcher. Successful output is
the ordinary `{jobs, count, any_running}` shape, preserving each supported active
summary's source/resource fields and omitting proven terminal/inactive jobs.
Unknown jobs or unqualified source/ETA/archive/preparation/remote evidence return
409 `activity_evidence_incomplete`, never a successful empty list. Budget refusal
is 413; elapsed work is 408; unavailable workspace is 503. Refusals do not disclose
partial job metadata. Response graph/wire bounds reuse the existing status helper.

Policy and session identity are checked atomically before/after work and again
after encoding. Workspace configuration and device/inode identity are checked
around work/encoding. Missing or replaced workspace cannot be mistaken for a
complete empty catalog. Request cancellation reaches evidence checkpoints; body
acquisition and input framing remain bounded by the existing dispatcher.

The five-second deadline is **cooperative between filesystem calls**, not a hard
syscall timeout. A blocked local filesystem operation retains its slot until it
returns; no result is accepted after the deadline. Host-selected local workspace
and finite admitted metadata remain prerequisites. This does not qualify arbitrary
mount latency, archive liveness, source fallback, NAMD/oxDNA ETA or separate
preparation/remote owners. These remain explicit refusals, not weakened acceptance.
All production feature/publication gates remain false; the ordinary route is
unchanged. No Design materialization, remote request, native solver, metadata write,
archive refresh, status reconciliation or new runtime lock occurs on this path.

## Validation actually run

Sequential guarded `just test-focused TARGET`: **150 distinct passes**.

| Target | Result | Seconds |
|---|---:|---:|
| `tests/test_part_strict_activity_reads.py` | 26 passed | 3.26 |
| `tests/test_active_job_observation_boundary.py` | 4 passed | 3.34 |
| `tests/test_part_strict_service_reads.py` | 28 passed | 3.67 |
| `tests/test_part_strict_http.py` | 61 passed | 3.84 |
| `tests/test_activity_catalog.py` | 27 passed | 2.96 |
| `tests/test_jobs_active_all_engines.py` | 4 passed | 2.86 |

Initial 22-case strict activity run passed. Final cases add post-encoding identity
checks, structured work-budget refusal, cancellation evidence and repeated-cancel
slot retention. Tests use real strict dispatch, isolated native job files and fake
process inventories; empty/live/terminal/cache responses, unknown archive/source/
preparation/malformed metadata, missing/changed workspace, session/policy changes,
closed method/body/query, shared admission and wire/time/work limits are covered.
The old S34 blanket-403 assertion now proves an isolated empty catalog bypasses the
legacy collector. Its three heavy-effect characterization cases remain unchanged.
Ordinary all-engine regressions and other strict status routes remain green.

An initial Ruff check found one unused test import; removed. Final changed-source/
test Ruff and `git diff --check` pass. No test failures, new slow candidate, browser,
frontend suite, broad backend suite or scientific run. Main.js S39 delta: zero.

`just test-smart --dry-run` selects FULL for accumulated main.py changes, then FAST
fallback without a dedicated session. **Zero broad tests executed.** Nineteen
historical timing candidates and prior broad-suite failures remain debt. Text:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

“Ran” is boilerplate, not a FAST execution claim.

## Sequencing

S40 is the sole unstarted successor: repeat the existing sealed Bend/Twist desktop
campaign now that every S29-observed polling path has an admitted supported read.
The [handoff](session_handoff.md#next-bounded-task) owns the bounded campaign contract.
Do not infer browser success from these HTTP tests. S34 broader activity semantics,
S29 desktop acceptance and ISSUE-100/MV-48 remain open. No external blocker for S40.
Counts: 21/38 Done,17 remaining (8 core/9 parked), delta +0/+0; U1–U60 unchanged.
This adapter wiring earns no U checkpoint or milestone credit. No gate enablement,
scientific/golden change, commit or push.

## Final records and cleanup

`just lint-memory`: 0 errors/0 warnings; current report/plan/memory links resolve.
Ledger checks find 38 unique FH rows, 21 Done and 60 U rows. Handoff has one current
ID, S40; affected issue/manual records agree. All four feature/publication gates
remain false. Final changed-source lint and diff checks pass.

Pytest pruned earlier owned runs. Remaining owned roots `pytest-5`, `pytest-6`,
`pytest-7` and three S39 logs were checked for active cwd/open-file/mapping references:
none accessible, 31 processes inaccessible/exited. Removed 25,662 logical bytes /
241,664 allocated bytes from those roots and 12,709 summarized log bytes. All paths
independently absent; dangling current link removed, unrelated `pytest-0` retained.
No active validation handle or test-created user-workspace artifact remains.
