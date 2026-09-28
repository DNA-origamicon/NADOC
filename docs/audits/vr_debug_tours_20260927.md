# Debug VR tour menu — 2026-09-27

Desktop Debug → VR Tours & Tests provides six keyboard-accessible categories:
Overview, Left sidebar, Right sidebar, Controls & layout, Properties · Dimensions,
and Tools · Authoring. All twelve desktop sidebar tabs have individual full-page
scanning tours, in addition to the complete/quick tours, focus/cards/scrollbars,
grip frames, dimension interaction and dimension persistence workflows.

Demo runs use steady_fast. Validation runs use all four unmodified motion profiles.
Quick tours explicitly state partial coverage. The maintained authoring demo stays
terminal-only and describes its owned-viewer/review-file prerequisites. Every card
has a copyable command. Direct runs display status, output and evidence paths;
Stop targets only the current owned process group. Closing/reopening the dialog
preserves status; backend teardown stops its owned live process. Active native
viewers are rejected. A request cannot provide an executable or arbitrary arguments.

Verification:

- Focused backend tour tests: 5 passed; catalog coverage, fixed argv, locality, active-viewer
  and duplicate guards, cancellation ownership, and shutdown cleanup.
- Frontend: 546 files; 7,085 passed, one skipped.
- Real Chromium dialog exercise passed: every category, tab-specific validation
  command, clipboard, visible launch conflict and dialog teardown. The conflict
  response is deliberately intercepted; this does not claim a live VR run.
- Native sidebar catalog drift check and changed-file Ruff check passed.
- `just test-smart` selected FAST: 9,285 passed, 92 skipped, one failure in
  `test_geometry.py::test_the_scalar_and_loop_skip_fast_paths_agree`, also observed
  before this change. No geometry code was modified for this task.
- `just lint` reports one unused Path import in the unrelated
  `tests/test_cpd_shape_revision_v2.py`; the new backend/tests lint cleanly.
- `just smoke` could not bind occupied port 5174. The same two smoke spec files
  were rerun using the normal isolated Playwright config (8002/5175), without
  replacing the existing service or bypassing the simulation guard. All 23 passed;
  teardown removed six test artifacts and one project history; no test files or
  Playwright output directories remain.
- No new physical headset tour was run: this task exercises the desktop launcher;
  prior SteamVR compositor failure and through-lens validation debt remain.

Evidence logs are `.development-artifacts/vr-tours-*.log`. The browser menu check
creates no designs or tour outputs. Smoke uses __e2e__ designs and the established
global teardown; reports/traces use the cleanup reporter.

DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
