# S52 six-family Extrude desktop matrix — October 18, 2026

Parent FH-27/MV-50; FH-21 implementation credit unchanged. HEAD96ab701e unchanged.
S51 was verified progress; current handoff selected the fixed six-family matrix.
Existing dirty work preserved. No production behavior, molecular builders,
constants/goldens, gates, commits or pushes changed. main.js LOC delta0.

## Delivered and per-family evidence

Each explicit-root fixture has poisoned/evicted recovery, one selected native
extrusion and a later independent recorded Extrude. Real-worker HTTP edits match
independent native reconstruction, complete authoring and nucleotide geometry.
The app checks exact Cancel/source/history/redo, one source-bound Save, persisted
patch values, unchanged later inputs/row IDs, exact shared native placement,
undo/redo/save/load, reopened inputs and cold proof. All final consoles are empty.

| Family | Committed inputs in this matrix | Final browser |
|---|---|---|
| Segment | length14, cell[4,5], separate-fresh false, offset1.5nm, staples, ligation false | pass11.2s |
| Continuation | Segment inputs plus explicit base source frame, extend-in-place false | pass12.8s |
| Deformed Continuation | length14, cell[4,5], separate-fresh false, explicit reference helix and derived source bp10 | pass11.3s |
| Frame | length14, cell[4,5], separate-fresh false, independent translation[3,2,1], name; identity quaternion | pass10.6s |
| Circle | cell[4,5], length14, separate-fresh false, offset1.5nm, staples, ligation false | pass11.2s |
| Overhang | length14 and reuse-existing false, retained valid authored endpoint/neighbor | pass33.9s |
| Bundle regression | S51 length/name edit through Bend/Sweep | pass16.5s |

Changing cells legitimately changes selected output identity according to native
inputs; later recorded row identities/inputs are preserved. No hidden rebasing
or scientific placement correction was introduced.

## Actual validation

- `just test-focused tests/test_extrude_matrix_desktop.py`: preliminary6 passed
  in10.10s; after adding committed cell/organization inputs, final6 passed in10.01s.
  Six existing ORJSONResponse warnings per run; real-worker calls1.20–1.31s final.
- `just test-focused tests/test_deformation_history_app.py`:19 passed in5.33s,
  three existing ORJSONResponse warnings, all new fixture counts/proofs checked.
- Guarded installed Vitest runner for extrusion_feature_editor,
  extrusion_history and deformation_history_launch:42 passed/3 files in1.87s.
- Storage preflight passed: /tmp661GiB free.
- `NADOC_HISTORY_E2E_GREP='Extrude matrix' just validate-safe uv run python scripts/run_deformation_history_e2e.py`:
  first5 passed/1 timeout (4.2m total). Overhang exceeded60s after Save and geometry
  checks; timeout surfaced at the following proof request with a disposed context.
- Read-only diagnosis: Node test worker remained CPU-active, while the backend
  answered a28,627-byte checkpoint with8 helices/14 strands and committed length14.
  The worker exited before an attempted inspector attachment; no inspector started.
- The placement helper previously created a separate Playwright assertion for
  every field of every nucleotide, blocking the timer with synchronous work.
  It now counts missing fields across every row and asserts zero once. Exact
  values, sorting, comparison, console checks and60s per-case deadline are unchanged.
- `NADOC_HISTORY_E2E_GREP='Extrude matrix|Bundle Extrude history Cancel' just validate-safe uv run python scripts/run_deformation_history_e2e.py`:
  final7 passed in1.9m, including Overhang33.9s and Bundle regression.
- Ruff, JS syntax and git diff checks passed.

No full frontend/backend selector/broad suite or smoke rerun: test-only changes.
Historical FULL debt retained. Case durations do not qualify interactive latency.

## Limits and successor

This completes the initial seven-family desktop lifecycle matrix, not all
possible input/source modes or complete MV-50. Alternate frames, direction/endpoint
choices, further committed Bundle options, failures/races, larger parts/resources,
sealed-host and rollout remain open. Existing scientific contracts are unchanged.
S53 Sweep independent/attached-start/detached-origin matrix is the sole unstarted
successor. S47 sealed startup console debt persists.
21/38 Done,17 remaining (8 core9 parked), delta0; U1–U60 unchanged.
ISSUE-100/MV-48/MV-50/MV-51 stay open.

## Cleanup

Launcher removed both roots:
`/tmp/__e2e__history-a0nhkr00` and `/tmp/__e2e__history-u0al4294`.
Independent final checks follow below.

Independent final check: both browser roots absent; no accessible process
cwd/fd/maps/environment references to them or owned pytest-1/2/3
(32 protected/exited processes unreadable). Removed those inspected
workspace-only pytest roots (0 file bytes) and their current symlink;
earlier pytest roots and shared caches untouched. Ports8004/5177 accept server-style
binds. 17 current handoff/S52 evidence links resolve; seven current status
records and both tool plans select S53. Ledger retains21 Done rows.

Final memory hygiene:0 errors/0 warnings. Ruff, JS syntax and diff checks pass;
HEAD remains96ab701e and all six production gates remain false.
