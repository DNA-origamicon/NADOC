# S41 — foreground admission under sealed background polling

Parent: FH-20, supporting FH-27/FH-28. Bounded correction delivered; no fixed
milestone closed. HEAD remains `96ab701e` with accumulated unrelated changes
preserved. Current instructions and S40 handoff matched source: the shared
`BoundedSemaphore(1)` refused every overlapping request immediately. S40's exact
Open 429 and initial-design 429 remain historical browser evidence, not a claim
about the identity of the particular background holder in that campaign.

## Delivered contract

`part_history_verification._slot` remains the one shared work owner, now backed by
`WorkAdmission`. It has one active slot and at most one foreground reservation.
Only immutable view-volume/dimension reads and strict active-job reads mark their
ownership as background. Sealed design/geometry/readiness and historical preview
prepare/evaluate opt into bounded waiting behind such an owner. A foreground
holder, an existing reservation or ordinary contention still refuses immediately.
There is no work queue, source copy, native input allocation or result cache for a
waiting request. Requests already hold their original context/lease references.
New polls cannot overtake the reservation, including during cleanup/release.

Checks run outside the admission condition lock, preserving state/catalog lock
order. Cancellation, source/revision/session/policy/gate changes and deadlines
retire the reservation. A cancellation cannot release another request's slot.
Waiting consumes the existing five-second operation allowance (and preview lease
expiry); the supervisor gets only the remaining time. Full-duration background
work or slow cleanup may exhaust that allowance: the foreground request honestly
refuses rather than extending limits. Native concurrency remains one. The existing
supervisor still owns release only after child and shared-buffer disposal; activity
still drains its thread and disconnect watcher before release.

Ordinary verification, ordinary preview and other slot consumers retain immediate
refusal. Frontend polls, stale-response consumers and diagnostic operation timing
are unchanged. No scientific geometry, constants, goldens, storage format, gates,
worker counts, existing resource limits or cleanup rules changed. `main.js` LOC Δ0.

## Validation

Final guarded focused result: **249 passed**, zero failures across nine separately
serialized targets, each `TMPDIR=/tmp/nadoc-s41-1jG8Dk just test-focused tests/<name>.py`:

| Target | Passed | Duration |
|---|---:|---:|
| test_part_work_admission | 27 | 23.93 s |
| test_part_immutable_display_reads | 25 | 18.74 s |
| test_part_immutable_deformation_preview | 21 | 25.99 s |
| test_part_strict_activity_reads | 26 | 3.20 s |
| test_part_immutable_annotation_reads | 35 | 14.61 s |
| test_part_verification_jobs | 14 | 3.78 s |
| test_part_history_verification | 26 | 2.86 s |
| test_part_deformation_preview_sessions | 29 | 4.61 s |
| test_part_immutable_geometry_host | 46 | 7.16 s |

`just lint` passes repository-wide (zero findings). `just lint-memory` and final
link/count/diff checks are recorded at closeout below. Focused warnings are the
existing ORJSONResponse deprecation; no new timing offender appeared. No broad
suite, browser, Vitest, native build or scientific sampling was run.

`just test-smart --dry-run` selects FULL from accumulated `backend/api/main.py`
changes and prints FAST fallback. It executes **zero tests**; its boilerplate
“ran” must not be reported as an actual fast-suite pass. Verbatim debt:

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

The guard still reports the 19 historical unmarked candidates from the existing
report. Prior triage remains applicable; this focused correction adds no timing
candidate and does not reclassify unrelated tests or clear failed broad debt.

The new admission tests use real annotation and preview workers, hold annotation
cleanup open, start a foreground request, and prove that both later background and
excess foreground requests refuse. They verify native progress within the original
budget, exact preserved source/history/redo, process closure and removed named
shared memory. Separate native activity overlap, waiter cancellation/staleness,
shortened test-only deadline, charged supervisor time, ordinary fail-fast and
asynchronous cancellation/draining tests cover the admission contract.

Initial development run: 22 passed, two failed assertions expected409 where the
existing preview source/session removal contract returns403 construction-policy.
The assertions were corrected to preserve that contract; production refusals were
not weakened. Next run:26 passed. Final run adds asynchronous waiter cancellation.
One attempted focused invocation rejected unsupported `--basetemp` before running
any tests; subsequent runs use supported `TMPDIR` isolation.

## Remaining boundaries and sole successor

S41 does not establish desktop lifecycle/console/latency acceptance. Background
requests still return honest429 when busy; unsupported startup routes retain403.
S40's zero passes/four failed browser executions remain the latest sealed desktop
verdict. No frontend polling policy, deduplication or retirement behavior changed.

Source review of `part_immutable_geometry_host._stage` confirms sealed preview
Apply still uses `_slot.acquire(blocking=False)` before staging. S42 is the sole
unstarted successor: qualify that exact Apply seam with the same bounded admission,
source/lease/deadline checks and native publication/receipt tests. See the
[current handoff](session_handoff.md#next-bounded-task) for its full contract.
Do not infer a browser Apply failure: S40 never reached it. Startup capability
qualification remains later work, outside both this correction and S42.

ISSUE-100/MV-48 and FH-20/FH-27/FH-28 remain open. **21/38 complete;17 remaining
(8 core,9 parked), delta+0/+0; U1–U60 unchanged.** This is a bounded admission
correction, not another major milestone checkpoint. No permission blocker,
rollout enablement, legacy pruning, commit or push. The explicit milestone goal
remains active.

## Closeout checks and cleanup

- `just lint`: pass, zero findings; `just lint-memory`: zero errors/zero warnings.
- `git diff --check`: pass. All328 links across current task documents and affected
  issue/manual paragraphs resolve. An initial overbroad whole-issue-ledger scan
  found19 unrelated historical artifact links missing; preserved, not repaired or
  counted as current-task failures. Milestone rows independently counted38, Done21;
  U1–U60 counted60. The first U-row regex missed the date separator; corrected check
  confirms the ledger rather than changing its accounting.
- All four production gates remain false. No frontend source changes; main.js Δ0.
- `/tmp` had662GiB free. Final focused runs used `/tmp/nadoc-s41-1jG8Dk` for logs
  and test scratch. Initial two test runs owned `pytest-1` and `pytest-2` under
  `/tmp/pytest-of-joshua`; unrelated `pytest-0` was preserved.
- After all tool/test processes completed, two `/proc` checks found zero accessible
  cwd/open-file/mapping references to these three roots (31 protected/exited
  processes unreadable). No runtime configuration referred to the scratch root.
  Removed37,553 file bytes, all three roots and the owned pytest-current symlink;
  independently confirmed roots absent. Real-worker tests verify child closure
  and named shared-memory removal. No browser/server/capture was created in S41.

The handoff, implementation/acceptance plans, fixed milestone ledger, project
memory and ISSUE-100/MV-48 current paragraphs all identify S42 as the only
unstarted successor. S42 implementation has not begun.
