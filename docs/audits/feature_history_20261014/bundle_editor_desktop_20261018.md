# S51 Bundle Extrude history through Bend/Sweep — October 18, 2026

Parent FH-27/MV-50; preserve FH-21 implementation credit. HEAD96ab701e unchanged.
S50 was verified progress; current handoff/worktree selected S51. Existing shared
dirty work preserved. No production source behavior or additional gate changed.
No scientific constants/goldens, commits or pushes; main.js LOC delta0.

## Delivered

The existing ordinary native extrusion editor is reachable via the feature log
and source-bound edit route; no test-only Extrude gate was necessary. A test-only
variant of the S48 Bundle→Bend→attached Sweep fixture poisons/evicts Bundle recovery.

A real-worker HTTP regression edits length42→48 and name. Independent reconstruction
from the empty native root matches complete authoring/nucleotide geometry. Later
Bend inputs, Sweep parameters, feature IDs and helix IDs persist. One undo plus
undo/redo/JSON reload and cold proof pass.

The browser opens the actual Bundle modal, changes length/name, adds/removes a
cell and changes plane/lattice/strand/ligation/organization draft controls, then
cancels with exact canonical source/history/redo preservation. Reopen restores
saved inputs. Save commits only length/name, preserving downstream definitions.
Exact shared native nucleotide placements, cold proof, undo/redo/save/load and
reopened inputs pass. The strict console assertion is empty.

## Validation actually run

- `just test-focused tests/test_extrude_history_desktop_fixture.py`:1 passed
  in4.17s (real-worker call1.37s), one existing ORJSONResponse deprecation warning.
- `just test-focused tests/test_deformation_history_app.py`:13 passed in5.31s,
  three existing ORJSONResponse deprecation warnings.
- `../scripts/validation_guard.sh node node_modules/vitest/vitest.mjs run src/ui/extrusion_feature_editor.test.js src/ui/extrusion_history.test.js src/test-helpers/deformation_history_launch.test.js`
  from frontend:42 passed across3 files in1.90s.
- Storage preflight passed: /tmp661GiB free.
- `NADOC_HISTORY_E2E_GREP='Bundle Extrude history Cancel' just validate-safe uv run python scripts/run_deformation_history_e2e.py`:
  1 passed,37.7s case/42.7s total, clean console.
- Ruff, JS syntax and git diff check passed.

Test-only additions; no full frontend/backend selector/broad suite or smoke rerun
claimed. Existing FULL debt remains. Test durations are not interactive latency
qualification. No production fix was required.

## Limits and sequence

Only Bundle length/name publication in this tiny ordinary chain qualifies.
Other options were exercised as cancelled drafts; their committed variants,
remaining six families, failures/races and representative resources stay open.
S52 is the fixed remaining six-family desktop control/lifecycle matrix, unstarted.
S47 sealed startup console debt is unchanged. MV-50 partially exercised, not closed.
21/38 Done,17 remaining (8 core9 parked), delta0; U1–U60 unchanged.
ISSUE-100/MV-48/MV-50/MV-51 stay open. Six existing production gates remain false.

## Cleanup

Launcher removed its single root `/tmp/__e2e__history-jp3637ln`.
Independent final checks follow below.

Independent final check: browser root absent; no accessible process cwd/fd/maps/
environment references to it or owned pytest-1/2 (31 protected/exited
processes unreadable). Inspected and removed the exact workspace-only pytest roots
(0 file bytes) and their current symlink; earlier pytest roots/caches untouched.
Ports8004/5177 accept server-style binds. 17 current handoff/S51 evidence links
resolve; seven status records and both tool plans select S52; ledger retains21 Done
rows. Final diff check passes. HEAD and six false production gates unchanged.

Final memory hygiene:0 errors/0 warnings.
