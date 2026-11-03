# S37 — Remaining local-engine observational parity

October 17, 2026; HEAD `96ab701e` unchanged, accumulated unrelated work preserved.
S37 delivers bounded observation for oxDNA, LAMMPS, CanDo and SNUPI. All six engine
families now have local observation adapters. This is not strict HTTP admission.

`activity_local_engines.py` reads existing native ownership/output evidence without
calling reconciliation, saving a job, creating a runtime lock, loading a Design,
extracting output or invoking a solver. Ordinary reconcilers remain authoritative
for repairs. The observer returns an action and explicit facts; unavailable evidence
returns unknown with the required fact and a bounded reason.

| Family | Native predicate preserved |
|---|---|
| LAMMPS | Running only; live runtime/thread or recorded PID whose command contains lmp/lammps; otherwise stopped. Cached output does not supersede that rule. |
| CanDo | Running only; live owner first, then display-cache existence, otherwise stopped. |
| SNUPI | Running only; owned runtime first; legacy PID liveness only when the runtime has no known ownership metadata; cache/stopped fallback. |
| oxDNA | Running/stopped recovery; runtime ownership and running orphan detection; native stage specs, expected energy-line count and last-conf existence; failed stages stay failed. Stopped resumed stages additionally require the success log phrase and native banked-attempt step accounting, excluding diverged current attempts. |

Preparation/remote lifecycle handling remains explicitly unknown/separate-owner.
Nonbusy terminal/queued decisions remain unchanged. oxDNA completion means its
native metadata completion predicate, not a new scientific validity or extraction
claim. Partial stopped jobs remain unchanged/resumable. Native helpers accept
optional bounded reads; their ordinary defaults and arithmetic are unchanged.

S36's one request-local process inventory now also records bounded PID/command
facts and oxDNA commands. It is shared across all families. Incomplete negative
inventory cannot prove a PID absent; exhausted work cannot return cached positive
PID evidence. Thread/runtime ownership uses the existing workspace-scoped registry
and nonblocking regular-file opener; `runtime.known` accepts an optional existence
probe without changing ordinary behavior. No persistent cache, queue or owner.

Existing bounds are retained: 8 MiB cumulative evidence bytes, 16 KiB whole text
reads, pre-parse JSON depth 64, at most 128 oxDNA stages/spec records, bounded
scalar names/step integers/PIDs, 4096 directory entries and 4 KiB commands, 30,000
cooperative work checks and a five-second cooperative deadline. Energy and log
files beyond the text cap yield unknown, never a partial-count completion verdict.
Native resumed-log interpretation is unchanged for admitted complete text. Models
and local paths must already be selected by the host; model discovery/loading,
filesystem syscall latency, source-path recovery, ETA and aggregate HTTP response
bounds remain unqualified. Process observations are snapshots, not future liveness
guarantees. No gates or public response schema changed.

## Validation actually run

Sequential guarded `just test-focused TARGET`: **120 distinct passes**.

| Target | Result | Seconds |
|---|---:|---:|
| `tests/test_activity_local_engines.py` | 49 passed | 3.40 |
| `tests/test_activity_observation.py` | 41 passed | 3.33 |
| `tests/test_simulation_runtime.py` | 13 passed | 3.54 |
| `tests/test_jobs_active_all_engines.py` | 4 passed | 2.87 |
| `tests/test_oxdna_relaxation.py::test_load_stage_specs_ignores_removed_fields` | 1 passed | 3.19 |
| `tests/test_oxdna_relaxation.py -k reconcile` | 7 passed, 251 deselected | 3.09 |
| `tests/test_lammps_runner.py -k reconcile` | 2 passed, 19 deselected | 3.67 |
| `tests/test_snupi_job.py::test_reconcile_completed_when_pid_dead_and_display_cached` | 1 passed | 2.82 |
| `tests/test_snupi_job.py::test_reconcile_stopped_when_pid_dead_and_no_cache` | 1 passed | 2.81 |
| `tests/test_snupi_job.py::test_reconcile_leaves_running_while_worker_alive` | 1 passed | 2.91 |

Initial 41- and 47-case observer runs also passed. Final 49 cases add the reviewed
post-inventory budget guard. New tests compare native reconciler outcomes on copied
fixture jobs after asserting observer file/model equality and absence of new locks.
They cover live registry/runtime/PID priority, SNUPI known-runtime exclusion of a
legacy PID, recycled LAMMPS PID, all four preparation/nonrunning branches, cached
completion, oxDNA complete/failed/done/partial/resumed/diverged stages, missing
specs/inventory, permission, stage/byte/work/deadline/entry budgets and one inventory.
No solver, native simulation, user job operation or Design extraction ran. Existing
runtime regressions use isolated worker/lock fixtures. One existing FastAPI
ORJSONResponse deprecation warning occurred in the oxDNA route regression.

Changed-source/test Ruff and `git diff --check` pass. Main.js S37 delta is zero.
No browser, frontend suite or broad backend suite ran. `just test-smart --dry-run`
selects FULL for accumulated main.py changes, then FAST fallback; **zero broad
tests executed**. Nineteen historical timing candidates remain, with no new focused
test over five seconds. Retained broad failures/debt are unchanged. Required text:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

“Ran” in that selector boilerplate does not claim a FAST execution.

## Sequencing and limits

S38 is the sole unstarted successor: bounded native job catalog and activity-summary
projection. Its objective, inputs, relevant files, acceptance, exclusions and stop
condition are in the [current handoff](session_handoff.md#next-bounded-task).
No external blocker for that task. Preparation/remote owners, source fallback/ETA,
HTTP identity/resource acceptance and S29 browser lifecycle remain obligations.
ISSUE-100/MV-48 remain open. This internal adapter earns no U checkpoint or milestone
credit: 21/38 Done,17 remaining (8 core/9 parked), delta +0/+0; U1–U60 unchanged.
No commit/push, scientific/golden change or production gate enablement.

## Final records and cleanup

`just lint-memory`: 0 errors/0 warnings; local plan/report/memory links resolve.
Ledger verification: 38 unique FH rows, 21 Done, 60 U rows and one current handoff
ID, S38. Relevant issue/manual records agree. All four production gates remain
false. Final diff/changed-source checks pass; main.js unchanged by S37.

`/tmp` preflight showed 662 GiB free. Earlier owned pytest runs were pruned by
pytest retention; remaining roots `pytest-10`, `pytest-11`, `pytest-12` and four
S37 logs were checked for active cwd/open-file/mapping references: none accessible,
31 processes inaccessible/exited. Removed 45,522 logical bytes / 270,336 allocated
bytes in those roots and 16,054 log bytes after summarizing evidence. All paths
are independently absent; dangling current symlink removed, unrelated `pytest-0`
retained. No user workspace artifacts or active validation handles remain.
