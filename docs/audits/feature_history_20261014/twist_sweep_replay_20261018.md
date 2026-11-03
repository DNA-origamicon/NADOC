# S49 Twist→attached Sweep replay — October 18, 2026

Parent FH-20, supporting FH-27. HEAD96ab701e unchanged. S48 was verified progress;
current worktree/handoff selected S49. Existing dirty work preserved. No production
source behavior, scientific constants/goldens, gates, commits or pushes changed.
main.js LOC delta0.

## Result

The existing chain fixture and tests now parameterize Bend and Twist. A tiny
ordinary bundle→Twist→explicit attached Sweep has poisoned/evicted Sweep recovery.
Historical edit/Cancel preserves exact source/revision/history/nonempty redo.
Apply independently rebuilds authored inputs, keeps downstream IDs/parameters,
matches full native geometry, supports undo/redo and JSON reload/cold proof.
The test uses the same fixture as the browser.

The current native Sweep attachment uses the source end's radial/tangent frame.
For this single straight helix, Twist changes the inherited radial basis and
Sweep nucleotide geometry while leaving origin and axial direction unchanged.
Full replay geometry comparison is exact; origin/axial invariance uses1e-12
absolute floating-point tolerance (zero relative tolerance). This documents the
existing native algorithm, not new physical/scientific validation.

The ordinary browser cases verify actual Open/edit/Cancel/reopen/Apply, save,
undo/redo/load, independent proof and every shared native nucleotide placement
field after Apply/reload. Strict empty-console checks pass for both families.

## Checks actually run

- `just test-focused tests/test_bend_sweep_history.py`:2 passed in3.06s.
- `just test-focused tests/test_deformation_history_app.py`:11 passed in5.37s;
  three existing ORJSONResponse deprecation warnings; gates/routes restore.
- `uv run python scripts/run_deformation_history_e2e.py --check-storage`: passed,
  /tmp661GiB free.
- `NADOC_HISTORY_E2E_GREP='edit replays attached downstream Sweep' just validate-safe uv run python scripts/run_deformation_history_e2e.py`:
  2 passed in44.9s; Bend20.3s, Twist19.4s case durations.
- `just lint`, JS syntax, `git diff --check`, `just lint-memory`: passed;
  memory0 errors/0 warnings.

No full frontend/backend selector/broad suite or smoke rerun: only test fixture/
coverage changes. Historical FULL debt remains. Test durations are not interactive
latency qualification. No sealed browser run or general startup repair is claimed.

## Remaining work and sequence

One ordinary Twist chain qualifies, preserving Bend. Full tool controls and
variants, Sweep/Extrude editor desktop qualification, sealed-host acceptance,
larger parts/resources and rollout remain open. S47 console debt persists.
S50 attached Sweep editor with downstream Extrude is the sole unstarted successor.
The Sweep plan's stale universal Archive prerequisite is reconciled to the
current machine-local scratch policy. No fixed milestone exit changed.
21/38 Done,17 remaining (8 core9 parked), delta0; U1–U60 unchanged.
ISSUE-100/MV-48/MV-51 remain open.

## Cleanup and final review

The launcher removed its single root `/tmp/__e2e__history-a72ri8fk` on completion.
Independent cleanup and documentation checks are recorded below.

Independent check: browser root absent; no accessible process cwd/fd/maps/environment
references to it or owned pytest-1/2 (31 protected/exited processes unreadable).
Inspected and removed those exact pytest roots with workspace-only contents
(0 file bytes) and their current symlink. Earlier pytest roots/caches untouched.
Ports8004/5177 accept server-style binds. 17 current handoff/S49 evidence link
targets resolve; seven status records and both tool plans select S50. Ledger has
21 Done rows. Final diff check passes and four existing rollout gates remain false;
Sweep's two production gates also remain false.
