# S50 attached Sweep history editor — October 18, 2026

Parent FH-27/MV-51; FH-22's implementation exit unchanged. HEAD96ab701e remains;
dirty shared work preserved. S49 was progress and the current handoff selected S50.
No production source behavior, scientific constants/goldens, commits or pushes.
main.js LOC delta0.

## Delivered

The isolated app now temporarily enables/restores the existing Sweep HTTP gate.
Its Vite config transforms only the exact default-false Sweep editor declaration,
with drift refusal and unchanged disk defaults. The fixture is a five-helix native
Bundle→attached-end Sweep→later independent Extrude; recovery is poisoned/evicted.

The exact fixture's native host regression reconstructs authored commands from an
empty root and compares complete authoring and nucleotide geometry after editing
the Sweep path from4nm to6nm. Cancel preserves exact source/revision/history/
nonempty redo; one Apply retains later authored inputs and row IDs. Undo/redo and
JSON reload reproduce independent native proof and geometry.

The browser uses the actual Sweep history button, edits/adds/removes path points,
switches automatic/explicit orientation, retains drafts through Previous/Next,
toggles preview, and checks exact Cancel preservation. Reopen/Apply, save, undo,
redo, load and another editor reopen pass. Every shared native placement field
matches after Apply/reload; the later Extrude inputs/row identity persist.
Strict empty-console acceptance passes.

## Validation actually run

- `just test-focused tests/test_deformation_history_app.py`:12 passed in5.33s,
  three existing ORJSONResponse deprecation warnings; normal/failure gate restore.
- `../scripts/validation_guard.sh node node_modules/vitest/vitest.mjs run src/test-helpers/deformation_history_launch.test.js src/app/sweep_history_editor.test.js src/ui/sweep_history_panel.test.js`
  from frontend:23 passed across3 files in1.82s.
- `just test-focused tests/test_sweep_history_desktop_fixture.py`: first failed
  because the new oracle incorrectly used the overlay-row edit helper on a
  snapshot. Fixed only the test's independent authored input construction;
  rerun1 passed in2.91s (0.23s call).
- Storage preflight passed: /tmp661GiB free.
- `NADOC_HISTORY_E2E_GREP='attached Sweep history controls' just validate-safe uv run python scripts/run_deformation_history_e2e.py`:
  first failed at60s before Open due to the new spec's incorrect Bend/Twist
  button locator. Replaced with the actual Sweep title; unchanged deadline and
  assertions. Final1 passed,41.6s case/46.7s total, clean console.
- Ruff, JS syntax and git diff check passed.

No product defect was found. Only fixture/config/test changes; no full frontend,
backend selector/broad suite or smoke rerun claimed. Existing FULL debt retained.
Test durations do not establish interactive latency or larger-part acceptance.

## Limits and successor

One ordinary attached-end numeric workflow qualifies. Full source/control variants,
canvas gestures, failures/races, creation, sealed host and resources remain open.
S47 sealed startup console debt persists. MV-51 partially exercised, not closed.
S51 earlier Bundle Extrude through Bend→Sweep is the sole unstarted successor.
The stale Archive wording in MV-50 now follows current machine-local storage policy.
21/38 Done,17 remaining (8 core9 parked), delta0; U1–U60 unchanged.
ISSUE-100/MV-48/MV-50/MV-51 stay open; fixed exits and six production gates unchanged.

## Cleanup

Launcher removed both roots on failure/success:
`/tmp/__e2e__history-f5zeax21`, `/tmp/__e2e__history-xk23uge5`.
Independent final cleanup and documentation checks follow.

Independent final check: both browser roots absent; no accessible process
cwd/fd/maps/environment references to them or owned pytest-1/2/3
(31 protected/exited processes unreadable). Inspected and removed those
workspace-only pytest roots (0 file bytes) and their current symlink;
earlier pytest roots/shared caches untouched. Ports8004/5177 accept server-style
binds. 17 current handoff/S50 evidence links resolve; seven status records
and both tool plans select S51; ledger retains21 Done rows.

Final memory hygiene:0 errors/0 warnings. Final diff check passes; all six
production gates remain false and HEAD remains96ab701e.
