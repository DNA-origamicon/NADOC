# S36 — Bounded NAMD/mrDNA activity evidence

October 17, 2026, HEAD `96ab701e`; unrelated accumulated changes preserved.
The two-engine evidence task is delivered. S34 HTTP admission remains incomplete.

`activity_evidence_io.py` owns one request-local byte/work allowance and lazy
process inventory; `activity_observation.py` supplies explicit facts to the S35
shared decisions. Neither calls reconciliation, loads a Design, finalizes output,
evaluates health, saves metadata, launches jobs, or creates runtime locks. Existing
runtime ownership is probed using its native read-only function with an optional
regular/nonblocking opener. Existing runner registry handles retain ownership.
There is no persistent observer, queue, cache or second lifecycle owner.

Native NAMD XSC/minimization/output predicates and mrDNA DCD/progress predicates
accept optional bounded readers. Ordinary defaults remain unchanged. The observer
retains live priority, exhausted/complete-segment finalization-required results,
minimization/checkpoint resume, log/no-log outcomes, cached completion and raw
three-phase finalization-required outcomes. Native malformed/absent-file fallbacks
remain; permission, encoding, non-regular input and exhausted budgets produce
explicit unknown plus the missing fact. Preparation/remote ownership and unavailable
archives explicitly remain outside the local decision contract. No scientific
threshold or terminal status is manufactured by the observer.

Bounds apply before parsing/traversal: 8 MiB cumulative bytes, 16 KiB per text
file (also bounds possible JSON nodes), 64 JSON nesting levels checked before
parsing, 4 KiB process commands and path strings, 4096 directory entries including
non-process entries, 30,000 work steps, at most 128 segments without traversing the
list, bounded scalar names/step integers, and a cooperative five-second deadline.
DCD reads consume only the 12-byte header, at most three headers for one job.
One inventory is reused across both families; an incomplete inventory cannot prove
absence of a process. Snapshot races remain possible; a process can exit after
observation. Host-selected local paths and already-loaded exact native models are
prerequisites. This does not bound model loading or arbitrary filesystem syscall
latency, and is not yet a qualified HTTP boundary. No user job/process scan ran in
new tests; process inventories are fake directories.

## Validation actually run

Sequential guarded `just test-focused TARGET`: **120 distinct passes**.

| Target | Result | Seconds |
|---|---:|---:|
| `tests/test_activity_observation.py` | 41 passed | 3.01 |
| `tests/test_simulation_runtime.py` | 13 passed | 3.53 |
| `tests/test_activity_assessment.py` | 21 passed | 2.83 |
| `tests/test_activity_reconciliation.py` | 7 passed | 2.81 |
| `tests/test_md_resume.py` | 25 passed | 2.83 |
| `tests/test_md_min_orphan.py` | 4 passed | 2.81 |
| `tests/test_active_job_observation_boundary.py` | 4 passed | 2.71 |
| `tests/test_mrdna_jobs.py::test_job_progress_states` | 1 passed | 2.77 |
| `tests/test_mrdna_jobs.py::test_fine_job_progress_uses_actual_dcd_frames` | 1 passed | 3.12 |
| `tests/test_mrdna_jobs.py -k reconcile` | 3 passed, 28 deselected | 2.75 |

Initial run: 31 passed/1 failed because a deeply nested manifest was accepted by
Python and fell through to the native malformed-metadata fallback. Added the
pre-parse nesting guard; subsequent 32-, 40- and final 41-test runs pass. An initial
combined `-k` expression lost quoting through the just recipe and was rejected
before collection; replaced by the explicit nodes and simple selector above.

Tests cover native metadata parity, live/owner/cache priority, stale/no-output
states, byte/nesting/work/deadline/entry/process/segment limits, encoding/permission/
FIFO refusal, missing inventory, header-only reads of sparse large trajectories,
one shared inventory, unchanged job objects/files and absent newly-created locks.
Native finalizers and Design loading are intercepted. Existing runtime tests use
isolated worker/lock fixtures; NAMD process tests use disposable sleep executables,
not simulations. No browser, broad frontend/backend or scientific validation ran.

Changed-source/test Ruff and diff checks pass. Final memory/link/count/cleanup and
selector results are recorded at closeout below. Main.js delta for S36: zero.
All four production gates stay false. ISSUE-100/MV-48 remain open.

## Sequencing

S37 is the sole successor: bounded observational parity for oxDNA, LAMMPS, CanDo
and SNUPI, using their native status predicates and existing owners. Do not open
strict HTTP or add a second status authority. Its complete contract is in the
[current handoff](session_handoff.md#next-bounded-task). Job discovery/projection,
preparation/remote handling, aggregate HTTP/resource acceptance and S29 desktop
lifecycle still remain. This internal evidence seam earns no U checkpoint;
21/38 milestones complete, 17 remaining (8 core/9 parked), delta +0/+0, U1–U60.

## Final closeout

`just lint-memory`: 0 errors/0 warnings. Changed-source/test Ruff and
`git diff --check` pass. Local report/plan/memory links resolve; ledger verification
finds 38 unique milestone rows, 21 Done (including checkpoint-qualified Done rows),
60 U rows and exactly one handoff task ID, S37. Current issue/manual status agrees.

`just test-smart --dry-run` selected FULL for accumulated `main.py` changes, then
FAST fallback without a dedicated test session. **Zero broad tests ran.** Nineteen
historical timing candidates remain; no new focused test exceeded five seconds.
The retained broad failure/debt is not cleared by these focused passes. Required
selector text (the “ran” phrase is boilerplate, not a FAST execution claim):

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

Scratch preflight: `/tmp` had 662 GiB free. Pytest pruned earlier owned runs;
remaining owned roots `pytest-13`, `pytest-14`, `pytest-15` were checked for cwd,
open-file and mapping references before removal: none accessible, 32 processes
inaccessible/exited. Removed 2,148 logical bytes / 28,672 allocated bytes from
those roots; all are independently absent, dangling current link removed, unrelated
`pytest-0` preserved. Large sparse trajectory fixtures belonged to earlier runs
and were already removed by pytest retention. Disposable S36 logs were summarized,
checked for references and removed; no active validation handle remains. No user
workspace or job artifacts were created. No external blocker for S37; HTTP and
browser acceptance remain unqualified.
