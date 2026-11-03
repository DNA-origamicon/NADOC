# S08 history timeout diagnosis — October 17, 2026

**Delivered: the first timeout is demonstrated and the harness adoption fault is
corrected. Both browser cases now reach the final console assertion, which fails
on two share-link HTTP 404s per case. Neither spec is accepted.**

HEAD remains `96ab701e`. Startup reviewed CLAUDE.md, the current handoff, project
memory, ledger and relevant acceptance/source/rules. No AGENTS.md was found in the
repository or ancestor locations. Existing S02/S03/S05, scientific-test exclusions,
memory reorganization and other dirty changes were preserved. Only the existing
untracked history spec and current records changed. No production behavior,
geometry, constants, thresholds, gates, commit or push changed.

## Fixed target and demonstrated cause

S08's target was to expose the first stalled step, preserve the primary failure,
and validate a proven harness correction with at most two diagnostic invocations.
The 60-second budget, single worker, zero retries and lifecycle assertions remain.

The first invocation retained the bare `?doc=` navigation. Both cases failed at
`page.waitForFunction` waiting for adopted geometry, before fixture save or Open.
The test's finally also encountered a closed request context, but the original
wait and its stack remained the reported failure. Seed POST had passed. A read-only
GET during the Twist case confirmed one helix and two strands in that backend doc.

Current `frontend/src/main.js` explicitly clears browser persistence and boots at
welcome; a bare `?doc=` selects request identity, not design adoption. The spec
waited for geometry before its later `getDesign()` call, and never requested initial
geometry. This was a harness startup assumption, not a demonstrated editor failure.

The correction uses the existing `?doc=…&readiness=simulation` same-document handoff.
`ui/design_readiness_boot.js` GETs design then geometry; the host invokes the normal
welcome-dismiss/control-unlock callback. The readiness action only selects the
Dynamics sidebar (`design_readiness_actions.js`), not a calculation. The test waits
for that navigation to finish, then selects Feature Log as before. No direct store
injection, imported replacement design, cleared redo, or synthetic geometry is used.

Diagnostics retain the last 40 events, each capped at 400 characters: relevant
API responses, HTTP errors, request failures and console warnings/errors, plus
current step and original exception. After run one, routine job/VR polling was
excluded from response diagnostics so it cannot displace useful requests.
Teardown attempts both page close and document deletion (bounded at 5 seconds),
reports cleanup errors separately, preserves an existing primary failure, and
fails an otherwise successful test if cleanup fails. The launcher's independent
whole-root/process cleanup remains mandatory.

## Executed validation

All heavy checks ran sequentially through the existing validation guard.

- `node --check frontend/e2e/deformation_history.spec.js`: passed before each run.
- `just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py --check-storage`:
  passed on `/tmp`, 661 GiB free. Ports 8004/5177 were free before each invocation.
- `just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py`,
  invocation 1: **2 failed**, both original 60-second geometry waits. Primary error
  preservation demonstrated despite secondary cleanup-context errors.
- Same command, invocation 2 after adoption correction: **2 failed**, Bend 9.7 s,
  Twist 8.4 s. Both passed preceding private Open, displayed-matrix change, exact
  Cancel/backend/browser/saved-byte preservation, no canonical preview writes,
  reopen, single Apply, one revision/history increment, redo clearing, stable
  feature IDs, changed deformation and adopted revision assertions. Both failed
  the unchanged final `expect(errors).toEqual([])` with two resource errors.
  Diagnostics tie those errors to `404 POST /__nadoc_share/links`.
- `just validate-safe npm --prefix frontend run test -- src/ui/design_readiness_boot.test.js src/test-helpers/deformation_history_launch.test.js`:
  **9 passed across 2 files in 1.18 s** (6 read-only adoption/guard cases, 3 test-only
  gate-transform cases). These are existing focused tests, not a full suite.

No third invocation or share-link diagnosis/repair was performed. The final
console check remains strict; no errors were filtered out of its assertion.
Warnings included existing ORJSON deprecation, NO_COLOR/FORCE_COLOR, WebGL
ReadPixels stalls, and one aborted readiness request in Twist. Test durations do
not qualify interaction latency, visual correctness, broad regression or the full
FH-20/FH-27 exits. No backend product code changed; no backend suite, full frontend
suite, scientific campaign, download or external sharing service was launched.

## Artifact inventory and cleanup

Before each browser run, the persistent inventory was reviewed: the fresh root
owns workspace fixtures/project stores/playback, `.owner-start`, browser profiles
and downloads, XDG/UV/Playwright/Vite caches, results and error snapshots. Fixture
names retain `__e2e__`; no screenshot/video/trace. Installed Chromium is a read-only
dependency outside the root. Launcher finally stops services/owned processes,
then removes the entire root after either success or failure.

Roots `/tmp/__e2e__history-1z_4k866` and `/tmp/__e2e__history-d58pcv9f` were reported
removed by the launcher and independently verified absent. Ports 8004/5177 were
free, no accessible process retained either exact root environment marker, and
`workspace/**/__e2e__history-*` returned no files. 32 protected process environments
were unreadable; no claim of inspecting those. Disposable snapshots/caches/fixtures
were removed with their roots; deleted byte totals were not metered. Only this
compact report is retained as new evidence; no bulk output retained.

## Closeout and successor

S08 is complete within its diagnostic scope; FH-20, FH-27, ISSUE-100 and MV-48 stay
open. **21/38 complete, 17 remaining (8 core, 9 parked); delta +0/+0; U1–U54 unchanged.**
The sole successor is **S09**, the bounded share-link 404 isolation diagnosis and
proven harness repair specified in the [current handoff](session_handoff.md).
It is unstarted. Do not infer that returning a fake success or suppressing console
errors is an acceptable correction. Fixed release exits and broad-suite debt remain.

Final checks: `just lint-memory` passed with 0 errors/0 warnings;
`git diff --check` and scoped untracked-file whitespace checks passed. Checked 39
local link targets across handoff/report/matrix/project memory: none missing.
Ledger check confirmed 38 unique FH rows, 21 Done, and exactly one complete S09
successor in the handoff. Current summary sequencing agrees across plan, ledger,
acceptance matrix and memory. Final HEAD is still `96ab701e`.
