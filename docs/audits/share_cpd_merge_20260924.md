# Share and CPD branch integration — 2026-09-24

Target: `master` (the repository default branch).
Inputs: Share `7a1aaf0c`, CPD/VR `0fbcf3e8`, previous origin/master `cce80858`.
The original worktree and its uncommitted work were left intact.

Eight textual conflicts resolved by retaining both branches' functionality:
ignore rules, save revision acknowledgements, export compatibility diagnostics,
Design validators, test API hooks, issue histories and artifact-cleanup guidance.
Independent ISSUE-31/32 history identifiers are preserved with a collision note.

Integration corrections:
- Autosave uses the new revision tracker without replacing the current design.
- Lattice-frame undo snapshots use deep copies without rerunning import validation
  during intermediate cluster replacement; other snapshots retain the optimized path.
- Vitest allows repository-local image assets imported from backend/data.

Validation:
- Production build passed.
- Frontend: 542 files passed; 7,043 tests passed, 1 skipped (4 workers).
- Sharing service: 24 tests passed.
- Browser: mobile guest navigation, shared representations, and live design edits
  all passed (3 tests). Test project/design teardown completed; bridge credentials,
  __e2e__ artifacts and session artifacts were checked absent afterward.
- Focused backend: 175 passed, 3 skipped.
- Final `just test-smart --base origin/master`: FAST; 9,080 passed, 13 failed,
  98 skipped; 28 seconds, no slow-budget offenders.

DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Ask the user to run `just test-session` (their terminal), then `just test-slow`.

All 13 remaining backend failures reproduce on an unmerged parent:
- Share parent: scalar/array loop-skip precision; missing workspace or simulation
  fixture data in assembly flattening, CanDo snapshot and extra-base audit tests;
  oxDNA build guard failures (10 failures).
- CPD parent: two animation geometry comparisons and photoproduct schema-default
  round-trip expectation (3 failures).
These existing failures are not fixed or hidden by this merge.

Timing triage: initial 17.2s electrode compilation, 7.3s idle-interpreter test,
and 7.2s mocked steering test took 1.19s, 0.39s and 1.37s in isolation.
The final complete fast run had no offenders; no limits or slow markers changed.
Raw logs and final timing report are retained locally under
`.development-artifacts/merge-20260924/` in the integration worktree.
