# S28/U58 — Bounded sealed design and geometry reads

Parent FH-20, supporting FH-27/FH-28. Previous turn classified as progress: S27
implemented and tested the strict preview lifecycle. Current handoff, repository
instructions, API/state and module-first rules, artifact policy, project memory,
ledger and scoped acceptance/source contracts read. HEAD remains `96ab701e`;
recorded worktree/prerequisites agree. Prior and unrelated changes preserved.

## Delivered contract

`part_immutable_display_reads.py` supplies the existing GET `/api/design` and
`/api/design/geometry` wire contracts through the strict dispatcher. The immutable
gate remains false. Each request captures its sealed source, session incarnation,
revision and policy; the existing one-work-slot supervisor checks these through
native work. Only the child decodes source bytes. It uses existing scope/work
admission and display output accounting (2 MB combined response allowance).
Unsupported queries, content/scope and excess output refuse rather than truncate.
No implicit conversion, compatibility fallback, new host/queue/cache/storage or
publication permit. The read job carries only source/context, never authority.

Design serialization reuses `_design_response` with full feature recovery bodies,
no legacy normalization and an explicit captured revision. Its new optional
`revision` argument avoids reading worker-local session state; existing callers
retain their default behavior. Full recovery prevents old suffix bodies from
being merged from browser cache. Native geometry uses the same placement, axes,
overhang rotation and straight-position functions/arguments as ordinary full GET
geometry. Complete ordinary response parity is asserted for both native families.
No molecular equations, constants, topology, goldens or scientific assertions change.

Input/output binding, worker reservations, time limits and cleanup reuse the
immutable byte transport and supervisor. Final JSON encoding runs on the work
thread outside the state lock and is followed by another source check. Disconnect
or task cancellation reaches the worker event; the request drains/reaps child and
shared memory before returning. Read-only success preserves exact canonical,
history and redo handles. No browser/runtime frontend changes in this task.

## Checks actually run

Serialized `just test-focused TARGET`:

| Target under `tests/` | Passed | Seconds |
|---|---:|---:|
| test_part_immutable_display_reads.py | 25 | 18.49 |
| test_part_strict_http.py | 61 | 3.76 |
| test_part_strict_geometry_http.py | 19 | 6.25 |
| test_part_strict_deformation_preview_http.py | 22 | 15.77 |
| test_crud.py | 50 | 3.36 |

**177 unique focused tests pass.** Native HTTP tests exercise Prepare/Apply →
Status → design → geometry → revision → Status for Bend and Twist. Separate
current-deformation fixtures compare both read responses to ordinary native wire
output (including straight geometry); parent decode/materialize and permit issuance
are forbidden. Preflight and in-flight source/session/revision/policy/gate/cancel
refusals, invalid worker operations, output overflow, and real child disconnect
cleanup are tested. Child closure and shared-memory-name absence are asserted.
The strict regressions preserve no-body/no-fallback and source-acquisition checks.
CRUD covers default revision/serialization compatibility as well as ordinary edits.

Initial refresh failed a Python-object versus JSON-wire equality assertion after
both read endpoints succeeded. The oracle now compares exact ordinary serialized
wire values; no fields or tolerances were removed. The next 18-case run passed
(16.49 s), before seven additional parity/protocol/disconnect checks were added.
The strict regression initially had 59 passes/2 failures because its two formerly
unlisted GET paths now encounter the existing no-body media check first. Its
multipart-header cases now require exact 415/unsupported_strict_media instead of
blanket policy denial (or the initially assumed 409 gate error). Body-read and
no-session/no-fallback assertions remain. No unresolved focused failures.
Existing FastAPI ORJSONResponse deprecation warnings remain; explicit bounded
thread-side response encoding is retained.

The first full native refresh took 5.14 s (four real spawned workers). Applied the
[triage-slow-tests skill](../../../.claude/skills/triage-slow-tests/SKILL.md): registered
only `test_real_sealed_refresh_sequence` in `_SLOW_TESTS`, assigned this module to
headless, and mapped its source leaf to headless selection. Subsequent native
refresh calls were 5.11/4.86 s, final 4.73/4.78 s. Classification reflects genuine
integration cost, not accidental sleeps; per-request native limits are unchanged.
The 23 other new cases remain fast. No broad fast sweep was run to clear old debt.

Changed-file Ruff and diff checks pass. `just test-smart --dry-run` classifies
accumulated changes as FULL then selects FAST after deferral. **Zero broad tests
ran**; selector wording is not a FAST pass. Literal deferral:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

The same 19 historical timing candidates remain in the existing report; no claim
of broad validation, failure-debt clearance or test-guard relaxation.

## Closeout and remaining exit

`just test-focused tests/test_part_immutable_display_reads.py --collect-only -m slow -q`
collects exactly both native refresh cases (2/25; 23 deselected, 2.83 s). The first
attempt with the compound marker expression was rejected by the recipe argument
parser before collection; no test ran. Headless mapping/source leaf reviewed.
Memory lint passes with 0 errors/0 warnings; final diff/Ruff and current local
plan/report/memory link-target checks pass. Ledger has 38 unique milestones,
21 Done, 58 unique U checkpoints; handoff contains exactly one successor.

Own pytest-6/7/8 scratch removed (20 regular files, 261,022 bytes) after accessible
cwd/open-file/memory-map reference checks found no readers; 31 protected process
records were unreadable. Earlier own trees were pytest-auto-pruned. Current symlink
and the task-local documentation script removed; own-path absence verified.
Unrelated pytest-0 and user data preserved. No browser/workspace design artifacts
created. Retained evidence is this concise report and reusable source/tests.
No browser/app or representative resource qualification. Native HTTP timing is not
interaction latency. Production immutable/preview/history/creation gates stay off.
S29, fully specified in the [handoff](session_handoff.md), is the sole unstarted
successor: isolated sealed historical desktop integration. The current harness
seeds mutable sources and assumes compatibility checkpoint/save/cleanup behavior;
S29 must reconcile those explicitly without broadening the production strict table.

**21/38 complete; 17 remaining (8 core,9 parked), delta +0/+0.** U58 is FH-20
engineering checkpoint4, task-growth flagged; fixed exit/38 denominator unchanged.
U1–U58 are 58 engineering checkpoints closing four milestones since B1; this task
closes none. Plans, milestone ledger, memory and ISSUE-100/MV-48 current records
updated; issue/manual release debt remains open. No commit/push. Goal active.
