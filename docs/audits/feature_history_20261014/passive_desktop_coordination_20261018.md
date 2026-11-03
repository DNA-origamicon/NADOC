# S46 passive desktop coordination — October 18, 2026

Parent: FH-20, supporting FH-27/FH-28. HEAD remains `96ab701e`; the accumulated
worktree is preserved. The preceding S45 turn was progress: native/HTTP admission
checks and both tiny-fixture lifecycle/latency results were verified, with remaining
cross-consumer429 and unsupported403 console failures. Current handoff selects S46.

## Acceptance target and implementation

Coordinate supported passive readiness, view-volume, dimension and activity reads
through the existing client request owner. Preserve finite capacity, foreground
priority, cancellation, stale response retirement, ordinary behavior and honest
errors. Qualify both fixtures at the unchanged five-second adoption assertion;
unsupported startup403 capability implementation is explicitly outside this task.

A focused `passive_read_scheduler.js` factory sits behind `_request`; it also
coordinates readiness's raw-fetch adapter. It admits one passive transport, at
most four queued passive keys, sixteen subscribers per queued key and sixteen
foreground waiters behind a passive transport. Equivalent queued reads coalesce.
Foreground calls retain their existing mutual concurrency and outrank queued
passive work; completed transports trigger dispatch via microtasks, independently
of operation timing. There is no backend queue, storage format or capacity change.

Cancellation retires an individual subscriber. It does not release an active
passive transport until its response/body drains; queued abandoned work never
starts. Document reset retires passive subscribers; source revision checks reject
stale queued or completed client reads. Readiness retains its controller's source
and generation checks, independent subscriber signal and a finite15s transport
timeout (previous raw fetch had no timeout). Backend five-second bounds remain
unchanged. The activity helper no longer waits on diagnostic `whenOperationIdle`;
its existing short-lived display cache and in-flight promise remain compatible.

The readiness dismissal test now asserts that an abandoned transport remains alive
until drained, while still checking that its response cannot resurrect the widget.
New factory and client-integration tests cover priority, shared dispatch, duplicate
subscribers, cancellation, stale results, reset, bounds and failure release.
No frontend composition-root LOC or scientific output changes.

## Validation record

The first focused invocation was malformed by shell/recipe argument expansion:
it ran from the repository root with a newly npm-downloaded Vitest5.0.5, rather
than installed frontend Vitest4.1.11. Its40 passes/one environment collection failure
are not qualification evidence. Subsequent invocations use the installed runner
explicitly from `frontend/` under `scripts/validation_guard.sh`.

Early installed-runner checks exposed timer-based queue dispatch stalls and the
old dismissal transport assertion; both were corrected without weakening stale
adoption checks. The last preliminary focused run passed40 tests across three
files in1.63s. Full frontend, browser and final hygiene results follow at closeout.

First full `just test-frontend`:9293 passed,1 skipped,2 failed across773 files
in353.20s. The two routing held-response failures exposed an added microtask before
immediately admitted foreground dispatch. The scheduler now invokes immediately
admitted work synchronously and keeps async settlement/drain ownership; no routing
assertion was changed. Queued foreground dispatch also rechecks document generation,
so a pre-reset mutation cannot bind to a replacement document. The subsequent
installed-runner focused check passed30 tests across scheduler/client integration,
routing and readiness-host files in2.18s. A new full run remains required.

The malformed first invocation's exact npm runner directory and invocation log
were removed after process-reference checks (38,644,855 bytes). Nineteen cache
files bearing its exact06:18:25UTC execution timestamps were separately checked
for open/mapped references and removed (459,561 bytes). Earlier cache metadata,
installed dependencies and shared npm content-addressed cache remain intact.

First browser invocation: root `/tmp/__e2e__history-k73nkpey`, two failures at the
strict console assertion. Both cases pass lifecycle/state/geometry/proof; adoption
Bend4868ms /Twist3201ms. Each records38 HTTP403 and7 HTTP429 console errors, compared
with S45's86/72 busy errors. The seven busy responses all occur after adoption,
while the final geometry assertion uses Playwright's separate HTTP client, outside
the page scheduler. That is evidence of an observer-induced race, not proof of a
remaining in-page scheduling failure. The final geometry assertion now requests
through the page's API owner, without adopting its response, changing expected
geometry, filtering errors or relaxing timing. A second browser run tests this
explanation. Native proof remains independent, and strict console checks remain.
First root independently absent; no marked processes or8004/5177 listeners, both
ports bind;32 protected/exited process environments unreadable.

Final full frontend run: `just test-frontend` passes9,296 tests,1 skipped across
773 files in361.31s. This includes all nine new scheduler/client checks, all
routing regressions and the readiness-host dismissal contract. No backend source
changed; no new backend suite/selector execution is claimed. S45's recorded FULL
debt remains unchanged and is not cleared by frontend checks.


## Final browser result and successor

Second invocation uses root `/tmp/__e2e__history-3zxo52wj`. Two executed cases,
zero full passes/two failures at the strict console assertion. Both pass exact
Open/edit/Cancel preservation, Open/edit/Apply, revision+1/history+1/redo0, adopted
design/geometry equality, zero private preview roots and verified native proof.
Bend adoption3363ms; Twist3292ms. Both recordzero429 and37 HTTP403 console errors.
This supports the first run's out-of-band geometry-observer explanation; the
observer now participates in actual client admission rather than suppressing errors.
The page scheduler is tab-local; it does not promise to coordinate unrelated HTTP
clients or other tabs, and backend overload remains honest.

Independent cleanup finds the second root absent, no accessible marked processes,
no8004/5177 listeners and successful binds;31 protected/exited environments unreadable.
The last40 response window still contains forbidden simulation/job-list and
placement-integrity reads. Full startup capability qualification is outside S46.
S47 is the sole unstarted successor: explicit capability-aware background consumers,
with truthful unavailable states, source/policy invalidation and ordinary compatibility.
Its objective, parent, deliverables, files, acceptance, exclusions and stop condition
are in the [current handoff](session_handoff.md). No successor implementation began.

No gate or milestone advanced:21/38 Done,17 remaining (8 core/9 parked),delta+0/+0;
U1–U60 unchanged. FH-20 remains at5 and FH-28 at11, both growth flagged. ISSUE-100
and MV-48 remain open. No broad/scientific run, commit, push or legacy pruning.

## Smoke and final hygiene

`just validate-safe uv run python scripts/run_deformation_history_e2e.py --smoke`
runs the required `just smoke` in isolated storage:23 passed in2.5m, including
assembly exit, real-design empty-console and loaded-design Close Session teardown.
The launcher owned `/tmp/__e2e__smoke-o6n_tt3w`, including any failure screenshots/
traces, logs, profiles, caches and workspace/project files. Global teardown removed
one test revision store and six prefixed artifacts; the outer launcher removed the
root. Independent final inspection finds all three browser roots absent, no
accessible marked process, no8001/5174/8004/5177 listeners and successful binds on
all four ports (31 protected/exited process environments unreadable).

`just lint` passes; memory lint reports0 errors/0 warnings;338 local links resolve;
ledger verification confirms38 milestone rows,21 Done and60 U checkpoints.
`node --check` for scheduler/spec and `git diff --check` pass. All four production
gates remainfalse and main.js LOC delta iszero. No successor code was started.

All command handles reached terminal status. Final `/proc` cwd/fd/maps checks
foundzero references to owned scratch/logs (31 protected/exited processes unreadable).
Removed `/tmp/nadoc-s46-tCfTkt` (563,024 bytes) and four exact npm invocation logs
(3,363 bytes); all independently confirmed absent. Together with the earlier
mistaken-runner/cache cleanup, disposable cleanup totals39,670,803 bytes, excluding
launcher-deleted browser roots. Shared dependency caches and unrelated files remain.
