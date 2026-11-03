# S48 Bend→attached Sweep replay — October 18, 2026

Parent FH-20, supporting FH-27/FH-28. HEAD96ab701e unchanged; accumulated dirty
work preserved. Current user priority is complete Bend/Twist/Sweep/Extrude before
other areas. No production source changes, constants/goldens, gates or commits.

## Delivered result

One tiny ordinary native bundle→Bend→attached Sweep fixture uses explicit source
helix/end and a4nm path. Sweep recovery snapshots are poisoned/evicted. Host and
browser exercise the same fixture. The host test reconstructs every authored
command from an empty native root, independently of preview/Apply recovery, and
compares complete authoring and nucleotide geometry. Editing Bend changes the
downstream Sweep's geometry while retaining helix/feature IDs and Sweep parameters.

Cancel preserves exact source/revision/history/nonempty redo. Apply adds one undo;
undo/redo and JSON reload retain native proof and geometry. The app exercises
Open/edit/Cancel/reopen/Apply, save/undo/redo/load, independent proof and exact
shared native placement fields for every nucleotide after Apply and reload.
The strict empty-console assertion passes. No test assertion or gate was weakened.

## Validation actually run

- `just test-focused tests/test_bend_sweep_history.py`: first failed on a test-authoring
  mistake (`Design.name` instead of recipe-root name), corrected. Three subsequent
  invocations each passed1 test; final uses the exact app fixture and checks changed
  Sweep geometry (2.98s total,0.16s test call).
- `just test-focused tests/test_deformation_history_app.py`:10 passed in5.44s;
  three existing ORJSONResponse deprecation warnings. Includes the new two-helix
  chain and production-route/gate preservation.
- `uv run python scripts/run_deformation_history_e2e.py --check-storage`: passed,
  /tmp661GiB free.
- `NADOC_HISTORY_E2E_GREP='bend edit replays attached downstream Sweep' just validate-safe uv run python scripts/run_deformation_history_e2e.py`:
  first1 pass (11.7s case/18.7s total); strengthened final1 pass
  (21.4s case/26.6s total). Final includes complete shared placement comparison.
  These are test durations, not interactive latency qualification.
- `just lint`, JS syntax and `git diff --check`: passed.

No production behavior changed; no full frontend, backend selector/broad suite or
smoke rerun was needed or claimed. Existing FULL debt remains. main.js LOC delta0.

## Limits and next task

One tiny ordinary chain qualifies. Full Bend/Twist controls, Sweep/Extrude editor
desktop qualification, sealed-host chain admission, other dependencies, larger
parts/resource acceptance and rollout remain open. S47 sealed console debt persists.
No scientific validity beyond the existing native contract is claimed.
S49 Twist→attached Sweep is the sole unstarted successor; see the handoff.
21/38 Done,17 remaining (8 core9 parked), delta0; U1–U60 unchanged.
ISSUE-100/MV-48/MV-51 remain open.

## Cleanup

Both browser roots were removed by the launcher:
`/tmp/__e2e__history-6e16y2yh` and `/tmp/__e2e__history-zvwoar_g`.
Independent cleanup and final documentation checks follow below.

Independent check: both browser roots absent, no accessible process cwd/fd/maps/
environment references to either root or the three remaining owned pytest roots
(31 protected/exited processes unreadable). Ports8004/5177 accept server-style
binds. Removed exactly pytest-3/4/5 after inspecting their isolated workspace-only
contents (0 file bytes), plus their current symlink. Earlier pytest roots and
shared caches untouched. The earlier S48 pytest roots had already aged out under
pytest retention. All four rollout gates remain false.

Final documentation checks: memory hygiene0 errors/0 warnings; git diff --check
passes; 16 current handoff/S48 evidence link targets exist; ledger has21 Done
rows. Seven current status records and both tool plans select S49 consistently.
