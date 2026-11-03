# S34 — Active-job polling admission stopped at reconciliation boundary

October 17, 2026. **Diagnostic stop; endpoint acceptance incomplete.** HEAD is
still `96ab701e`. No production source or strict allowlist changed in S34.
Existing unrelated work was preserved. This follows the handoff's explicit stop
condition for an unsafe reconciliation side effect; it is not an external blocker.

## Evidence and why direct admission is insufficient

`routes_jobs.list_active_jobs` coalesces callers and runs `_collect_active` in a
thread. The collector scans six engine families, calling their ordinary status
reconcilers before constructing activity rows. Output bounding alone would occur
after these effects; coalescing does not bound a scan or make it observational.

| Path inspected | Reachable effects relevant to admission |
|---|---|
| NAMD `reconcile_job_status` | Reads manifests/process/output evidence; writes preparation/interruption/segment state; appends metrics and health JSONL; invokes `run_health_check`; advances segments and calls `_finish_job`. Finalization can run electrode equilibration checks before persisting terminal state. |
| mrDNA `reconcile_mrdna_status` | Scans/adopts ARBD process identity and saves state. For apparently completed raw output, loads a saved Design and calls `_finalize_outputs`: result extraction, display/bead/curvature file generation and completion publication. |
| oxDNA reconciliation | Reads stage expectations/output evidence, including energy progress, and persists recovered stage/job state. This is not simply reading saved status. |
| LAMMPS/CanDo/SNUPI reconciliation | Checks runtime/process/cache evidence and persists stopped/completed state or stage changes for orphaned work. |
| RunPod branch in collector | Queries live pod names; when absence is established, persists recoverable paused/orphan metadata. Unknown remote evidence retains the existing record. No new remote query ran in this task. |
| `simulation_runtime.reconcile_guard` | Acquires the existing runtime owner and can create persistent `.runtime.lock`; refreshes managed metadata under that owner. The lock inode must not be casually unlinked during operation. |

Job enumeration, archive access, output scans and result computation have no
request-level aggregate work bound in this collector. Some effects are ordinary
status bookkeeping; NAMD health/metrics and mrDNA extraction/cache publication
exceed the bounded observational route selected by S34. Skipping reconciliation
and returning persisted statuses would lose current liveness/completion behavior;
returning no jobs would hide active work. Neither substitute was implemented.

## Executable characterization

New `tests/test_active_job_observation_boundary.py` uses temporary job metadata,
fake liveness/raw-progress evidence and interceptors at the heavy call boundaries.
A sentinel derived from `BaseException` escapes the collector's broad `Exception`
catch before extraction/health/finalization executes. It demonstrates:

- The actual collector enters mrDNA `_finalize_outputs` from the real reconciler.
- The actual collector enters NAMD `_finish_job` for exhausted segments.
- A completed NAMD segment reaches metrics append then `run_health_check`.
- Strict `/api/jobs/active` still returns 403 before the collector is entered.

No physical sampling, output extraction, health calculation, process launch, user
job read/write or remote probe ran. Fake numerical values only route the test to
the existing call boundary; they do not change any scientific assertion or verdict.
Tests assert all existing fixture file bytes unchanged and the exact additional
empty `.runtime.lock` created by ordinary reconciliation. These tests record an
admission gap, not a permanent desired status-GET contract.

The first diagnostic run failed because its fixture assertion expected no new
file; it exposed the runtime-lock creation. The assertion was corrected to require
that exact observed write while continuing to protect every existing metadata byte.
No production acceptance or runtime guard was weakened.

## Validation actually run

Sequential guarded `just test-focused TARGET`: **15 passes** in the final runs.

| Target | Result | Seconds |
|---|---:|---:|
| `tests/test_active_job_observation_boundary.py` | 4 passed | 2.95 |
| `tests/test_jobs_active_all_engines.py` | 4 passed | 2.86 |
| `tests/test_jobs_active_execution_target.py` | 6 passed | 4.15 |
| `tests/test_jobs_active_resource_class.py` | 1 passed | 2.91 |

Initial diagnostic: 1 failed in 3.09 s (lock-file expectation, explained above).
Existing activity tests retain ordinary contracts; they do not prove safe strict
admission or bounded full-engine coverage. New-file Ruff and `git diff --check`
pass. `just lint-memory`: 0 errors/0 warnings. Current links, 38 unique milestone
rows/21 Done, 60 engineering rows, issue/manual status and sole successor checked.

`just test-smart --dry-run` still selects FULL from accumulated `main.py` changes,
then FAST fallback without a dedicated session. **Zero broad tests ran.** Nineteen
historical timing candidates remain debt; no new over-budget diagnostic test.
Required selector text (the “ran” phrase is boilerplate, not actual execution):

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

No browser, full frontend, broad backend or scientific run. S29 Open/Cancel/Apply
acceptance remains pending. No production gate, threshold or golden changed.

## Cleanup, progress and sole successor

Own final pytest roots 3/4/5 were removed after cwd/open-file/memory-map checks found
no accessible references (31 inaccessible/exited records limit inspection).
They contained respectively 9 files/3,909 bytes, 9 files/21,106 bytes and 3 files/
4,469 bytes. Pytest retention removed older task roots. Own roots are absent and
unrelated `pytest-0` remains. Disposable logs/documentation script removed after
recording outcomes. No user workspace artifacts or services were created.

**21/38 Done, 17 remaining (8 core,9 parked), delta +0/+0.** U1–U60 remain 60
engineering checkpoints. Diagnostic work earns no U number or milestone credit.
ISSUE-100/MV-48 and the milestone goal remain open. No commit or push.

**S35**, unstarted, is the single successor: separate bounded NAMD/mrDNA activity
assessment from the demonstrated heavy finalization effects, within existing
owners and with ordinary reconciliation parity. It must preserve explicit unknown/
finalization-required evidence rather than invent terminal statuses. S34's remaining
full engine-family/resource/HTTP acceptance is not waived or counted complete.
The [handoff](session_handoff.md#next-bounded-task) supplies objective, parent,
deliverables, files, checks, exclusions and stop condition. S35 has not begun.
