# S35 — Bounded activity decisions, ordinary reconciliation retained

October 17, 2026. Decision seam delivered against HEAD `96ab701e`; existing dirty
changes preserved. This does not complete S34 active-job admission.

`backend/core/activity_assessment.py` contains side-effect-free NAMD local-orphan
and mrDNA decision tables. Inputs are an exact dictionary of at most nine reviewed
keys (at most 32 characters), each holding an exact boolean or `None`. Containers,
model objects, subclasses, unknown keys and numeric substitutes refuse before
traversal. There are at most nine scalar validations and seven decision steps;
no unbounded graph, file, process scan, lock, native computation or serializer.
The byte/work envelope concerns these facts only, not their acquisition.

A missing observation yields `unknown` plus its required fact. NAMD decisions
preserve live/unchanged priority, exhausted-segment finalization, complete-output
segment finalization, missing minimization, checkpoint resume, unstarted segment
and failed-without-checkpoint branches. mrDNA preserves live > cached display >
raw-output finalization > stale running/nonrunning priority. `raw_mrdna_complete`
retains the exact original fine-step/progress>=0.99 predicate; no health or physical
validity threshold changed. The helper consumes native runner progress, while the
bounded decision interface consumes its boolean result.

Ordinary NAMD/mrDNA reconciliation now consumes these decisions at the demonstrated
branches. Existing readers, lazy branch order, runtime owners, metadata writes,
metrics/health work, extraction and finalizer success/failure behavior remain.
For mrDNA, finalizer failure or unavailable saved Design still takes the original
running-to-stopped/nonrunning-unchanged fallback. Raw completion alone is never
reported by the new assessment as successfully finalized output.

The pure seam cannot acquire facts itself and is not a public job-status schema
or publication authority. NAMD preparation/remote handling remains with its
existing owner. Existing process/file readers are not made bounded by this change.
A future observer must acquire reliable facts within a separate envelope; unknown
or finalization-required decisions cannot be silently converted to an empty job
list or a terminal status. S34 engine-family/output/resource/HTTP acceptance stays
open, and strict `/api/jobs/active` still refuses.

## Validation actually run

Sequential guarded `just test-focused TARGET`: **68 distinct passes**.

| Target | Result | Seconds |
|---|---:|---:|
| `tests/test_activity_assessment.py` | 21 passed | 2.80 |
| `tests/test_active_job_observation_boundary.py` | 4 passed | 2.70 |
| `tests/test_md_resume.py` | 25 passed | 2.80 |
| `tests/test_md_min_orphan.py` | 4 passed | 2.79 |
| `tests/test_jobs_active_all_engines.py` | 4 passed | 2.79 |
| `tests/test_mrdna_jobs.py -k reconcile` | 3 passed, 28 deselected | 2.93 |
| `tests/test_activity_reconciliation.py` | 7 passed | 2.79 |

Initial assessment run: 21 passed in 2.84 s. Final coverage includes all 128 NAMD
and 16 mrDNA boolean combinations against the original branch oracle; missing-fact
precedence; bounded exact-type rejection; no runtime access; native metadata and
fake liveness recovery; cached-output/live adoption precedence; and finalizer
success, failure and missing-Design fallback for running/queued jobs. Heavy native
finalizers are intercepted, not executed. Existing process-recognition tests use
an isolated copy of `sleep` named namd3 and terminate/wait in `finally`; no native
simulation, health calculation or user job operation ran.

Changed-source/test Ruff and `git diff --check` pass. `just lint-memory`: 0 errors/
0 warnings. Current links, unique 38 milestone rows/21 Done, 60 engineering rows,
issue/manual status and sole S36 successor checked.

`just test-smart --dry-run` selects FULL for accumulated `main.py` changes, then
FAST fallback without a dedicated session. **Zero broad tests ran.** Nineteen
historical timing candidates remain debt; no new over-five-second test. Required
selector text (the “ran” phrase is boilerplate, not a FAST execution claim):

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

No browser, full frontend, broad backend or scientific run. S29 desktop lifecycle
and S34 active-job endpoint remain pending. No rollout gates changed.

## Cleanup and sequencing

Own final pytest roots 6/7/8 were removed after cwd/open-file/memory-map inspection:
no accessible references; 31 inaccessible/exited records limit inspection. Roots
held respectively 9 files/3,910 bytes, 7 files/2,112 bytes and 15 files/5,005 bytes.
Pytest retention removed older task roots. Own roots are absent; unrelated
`pytest-0` is preserved. Disposable logs/documentation script removed after results
were recorded. No user workspace artifacts or persistent service launched.

**21/38 Done; 17 remaining (8 core,9 parked); delta +0/+0.** U1–U60 remain 60
engineering checkpoints. This internal extraction earns no new U or milestone.
ISSUE-100/MV-48 and the fixed milestone goal remain open. No commit/push.

**S36**, unstarted, is the sole successor: bounded read-only NAMD/mrDNA evidence
acquisition feeding these decisions. Objective, parent, deliverables, relevant
files, acceptance, exclusions and stop condition are in the
[handoff](session_handoff.md#next-bounded-task). No S36 implementation began.
