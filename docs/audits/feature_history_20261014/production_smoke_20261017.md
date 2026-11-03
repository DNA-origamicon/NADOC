# S18 — Production smoke qualification, October 17, 2026

Parent FH-20, supporting FH-27. Current handoff, milestone ledger and project
memory reread after S17 closeout; HEAD unchanged at `96ab701e`, S17 and unrelated
worktree changes preserved. Target before editing: execute existing `just smoke`
with guards/assertions/budgets intact, exact disposable artifact inventory and
independent cleanup, maximum two smoke invocations, stop on further defects.

Preflight found workspace paths already honor NADOC_WORKSPACE, including assembly
fixture save and global teardown. Vite still used shared checkout cache/config
bundle paths; corrected only harness isolation: existing history launcher's new
`--smoke` mode executes the unchanged `just smoke` recipe. Same storage/browser
preflight, process ownership and finally cleanup. Smoke config uses fresh root
output and a smoke-only Vite config preserving production plugins/feature gates,
with runner config loading and scratch cache. Ordinary smoke behavior is unchanged
without that explicit root. No downloads (UV_NO_SYNC/npm offline), RunPod
connection disabled, sharing autostart disabled, native CUDA/torch cache redirected.

## Pre-launch output inventory

R is the fresh printed `__e2e__smoke-*` root. Workspace saves, auto-save project
history, md_jobs/library/session metadata, and playback are under R/workspace;
fixture names use `__e2e__`. Browser profile/downloads and viewer-bridge credentials
use R/tmp; share control uses R/share-control.json. Playwright failure traces/
screenshots and last-run use R/playwright. Vite cache uses R/vite-cache; runner
loading avoids node_modules/.vite-temp. UV/XDG/Playwright/CUDA/torch caches use
R/cache. `.owner-start` marks process ownership. Global teardown cleans known
fixtures and bridge credentials; outer finally stops all provably marked processes
and removes the entire root on normal exit/failure/interruption. Existing managed
jobs and user workspace are not used. Installed dependencies/browser remain read-only;
no report or cache cleanup deletes pre-existing checkout paths. Ordinary guard
lock/debt files remain per policy. Production startup performs normal CUDA
initialization but launches no requested scientific simulation.

The representative Example is read-only for load/render smoke; its digest is
recorded before/after. No screenshot/trace retained after compact results.

Preflight checks: 25 launcher tests pass in 4.59 s via `just test-focused
tests/test_deformation_history_launcher.py`; three smoke-config tests pass in
294 ms via guarded Vitest. Scoped Ruff, config syntax and diff checks pass.
Ports 8001/5174 free. Example SHA256 before launch:
`76ab2011be7f088e7c73bd2a42fffff5f7851a505699dab9a318aa9ea8a1f34a`.
Command: `env -u NADOC_IGNORE_SIM_GUARD just validate-safe uv run --no-sync python scripts/run_deformation_history_e2e.py --smoke`.

## Result and cleanup

**23/23 smoke cases pass in 2.6 minutes**, one invocation, production default
feature gates unchanged. Assembly-exit case 21.6 s; Close Session 33.6 s under its
existing 60-second budget. The production startup/render/teardown gate is now
executed, clearing the required S17 smoke check. It does not qualify gated
Bend/Twist resource behavior or all release workflows. Existing benign-noise
filters in the smoke spec were unchanged; S17's separate targeted end-menu cases
retain strict empty console. Server ORJSON deprecation and Node color warnings
remain. No broad/backend/scientific rerun or full frontend rerun in S18; only
launcher/config code changed, and its focused tests above pass.

Root `/tmp/__e2e__smoke-cq_j0hz4` independently absent after automatic cleanup;
no accessible marked process, no workspace `__e2e__*` artifact, no listeners on
8001/5174 and both ports bind successfully. 31 protected environments unreadable;
not claimed inspected. Global teardown removed six fixtures and one project store.
Sampled root usage during run was 96 MiB, not a peak or exact deletion measurement.
Example SHA256 unchanged. Ordinary `frontend/test-results` and `playwright-report`
absent. Launcher-test scratch `/tmp/pytest-of-joshua/pytest-3` contained three files,
16 logical bytes; removed after no accessible cwd/fd/mapping references were found
(31 protected processes unreadable), verified absent. No user artifacts touched.

**21/38 complete; 17 remaining (8 core, 9 parked), delta +0/+0; U1–U54 unchanged.**
S19 Twist end-menu creation parity is the sole successor in the handoff, unstarted.
Full FH-20/FH-27 qualification, larger-host/resources, failure/recovery matrix,
polymer/all-target and routing/Sweep workflows remain open. No gate enablement,
legacy pruning, geometry change, commit or push.

Final closeout checks: memory lint 0 errors/0 warnings, diff check and both smoke
JavaScript syntax checks pass. 289 current plan/evidence/memory file targets
resolve; anchors not exhaustively checked. Ledger remains 38 unique rows, 21
Done, 9 Parked, 8 open core; exactly one successor definition S19. `main.js` delta
0 across S17/S18. Active goal remains incomplete and active, with S19 unstarted.
