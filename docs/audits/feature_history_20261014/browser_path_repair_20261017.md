# S07 browser-path repair — October 17, 2026

**S04's launcher blocker is resolved. Browser lifecycle acceptance is still blocked
by a newly observed timeout.** No download or user action was needed.

HEAD remains `96ab701e`; unrelated dirty changes preserved. Only the launcher,
its focused tests and status/evidence records changed. All rollout gates remain
false, scientific rules/test guards unchanged; no commit/push.

## Repair and validation

`scripts/run_deformation_history_e2e.py` queries the installed Playwright registry
in the caller's environment, before replacing XDG_CACHE_HOME. It verifies the
headless-shell executable exists/is executable, then passes the resolved absolute
registry directory as PLAYWRIGHT_BROWSERS_PATH. Playwright itself resolves platform,
revision, explicit environment/npm settings, relative paths and `0` package-local
installation. No machine path or browser revision is hardcoded. Runtime caches
still use the disposable root. Missing executables refuse before allocation or
services, with no fallback/download. Registry internals are version-sensitive;
resolution errors fail closed, and focused tests exercise installed registry code.

Executed sequentially:

- `just test-focused tests/test_deformation_history_launcher.py`: **23 passed in
  4.38 s**, including actual Node registry lookup for default/explicit/relative/0,
  missing executable refusal, isolated runtime paths and prior cleanup tests.
- `uv run --no-sync ruff check scripts/run_deformation_history_e2e.py tests/test_deformation_history_launcher.py`: passed.
- `just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py --check-storage`: passed, `/tmp`, 661 GiB free.
- Same guarded command without `--check-storage`: **2 failed**, one worker,
  zero retries, unchanged spec. Chromium launched from its existing installation.
  Both Bend and Twist exceeded the unchanged 60,000 ms test budget. Final errors:
  `apiRequestContext.delete: Target page, context or browser has been closed`,
  at `frontend/e2e/deformation_history.spec.js:108` in finally.

The first timeout's wait location is obscured by teardown. Bend's disposable page
snapshot showed the loaded NADOC shell and `F0 — initial` feature sidebar. This is
not proof of the cause or evidence of completed Open/edit/Cancel/Apply checks.
The earlier suggestion of a readiness failure remains a hypothesis, not a finding.
Warnings: NO_COLOR/FORCE_COLOR and existing FastAPI ORJSON deprecation.

The remaining blocker cannot be responsibly corrected from this evidence alone:
it requires exposing the primary error and checking fixture/document adoption,
network/console state and the first stalled step. Raising timeouts or bypassing
readiness would weaken acceptance. S07's bounded contract explicitly stops after
one unchanged-spec attempt; no second browser run or speculative app fix occurred.
[S08](session_handoff.md#next-bounded-task) is the sole unstarted successor to
collect that evidence and repair a proven harness fault, or specify a production
fix separately. This is not a claim that the timeout is inherently unfixable.

## Output and cleanup

Reviewed the existing persistent-output inventory before launch. Fresh root
`/tmp/__e2e__history-0659ky4m` owns workspace fixtures/project metadata/playback,
`.owner-start`, tmp browser profiles/downloads, XDG/UV/Playwright and Vite caches,
and Playwright results/error context. No screenshot/video/trace collection,
share/viewer credentials, browser installation or production startup. Whole-root
finally remains failure-safe after process shutdown; installed browser is a
read-only dependency outside the output root.

Launcher printed cleanup verified absent. Independent post-check: root absent,
no accessible process carrying the exact run marker, ports 8004/5177 free,
no `workspace/**/__e2e__history-*` files. 31 protected process environments could
not be inspected; no claim of examining them. Disposable error snapshots removed
with the root after review; no bulk evidence retained, deleted bytes not metered.
Focused pytest scratch `/tmp/pytest-of-joshua/pytest-0` contained only this file's
fixtures/workspace isolation trees. After checking accessible cwd/open-file/maps
references, removed 3 files/16 logical bytes plus directories/scratch symlinks;
verified absent. Unrelated user data and runtime installations preserved.

No backend/frontend product behavior change, broad suite, scientific validation,
representative resource qualification or milestone acceptance. Counts remain
**21/38 complete; 17 remaining (8 core, 9 parked); delta +0/+0; U1–U54 unchanged**.

Closeout: memory lint passed (0 errors/0 warnings), `git diff --check` passed;
scoped handoff/report local links and ledger/single-successor checks passed.
