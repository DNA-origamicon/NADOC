# Feature-history integration review — November 3, 2026

Integration branch: `integration/feature-history-master-20261103`.
Original branch: `checkpoint/feature-history-pause-20261015` at `288c3c45`.
Working changes were preserved in snapshot commit `9517c534` before merging
`origin/master` at `97e6befb7bebad690bbd5610cd1339398f353f9d`.
The original working tree is untouched; all 533 captured changed paths were
verified against their pre-integration SHA-256 manifest.

## Conflict resolution

Resolved all 28 conflicted files. Retained atomic native feature recording,
strict reference validation, asynchronous document ownership checks, and the
new feature-log editing/dependency workflows. Incorporated master's reference,
visibility, VR, residue-axis, and dependency updates. Combined issue/manual-debt
and memory records without removing their deferred items.

Validation exposed semantic conflicts beyond conflict markers: annotation archive
schemas lacked master's new fields; residue-axis carving erased ranges needed
by master's pose projection; optional native VR reference reads conflicted with
strict service reads. These were reconciled with focused regression coverage.
Frontend fixes preserve desktop Sweep callback compatibility, scene deselection,
Unapply's retained version target, and release-time right-click tests. Trajectory
budget expectations now count actual typed-array storage. Production resource
limits and the publication guard were not weakened.

The test harness now gives each isolated module its own memory-admission directory.
Previously parallel workers contended on the production default directory and two
otherwise-fast tests waited 41–58 seconds. Focused verification passed within the
unchanged per-test and aggregate guards.

## ISSUE-171: development review required

See [the issue ledger](../../issues_ledger.md) and
`tests/test_agent_structure_guard.py::test_saved_main_loadout_requires_a_recorded_publication_contract`.

Read-only audit of the existing `workspace/test.nadoc` (SHA-256
`9579b0cebdffc807d9697c81b898bf4d737a95049ad7f018bcd4a73c70dacc17`):
its three-command native history verifies, and its embedded Main branch independently
passes the full agent audit, including physical references, without recovery snapshots.
The enclosing saved document fails on `active_loadout_id, loadouts`. Its bytes remain unchanged.

Actual `refresh_active_revision` persistence creates that Main wrapper. Native
CAD proof intentionally excludes physical/loadout state; the stricter publication
guard includes it. There is no recorded user-facing loadout lifecycle to replay.
Development must define Save/branch lifecycle provenance, portable revision inputs,
active selection, and independent verification of each retained branch, including
protected simulation branches. Do not infer historical actions, strip loadouts,
exclude physical fields, or fabricate a diagnostic feature to close this issue.
The regression establishes the current fail-closed boundary; ISSUE-171 stays open.

## Validation

Compact logs and the unchanged-source manifest are in
`.development-artifacts/merge-readiness/` in the integration worktree.
Fresh isolated dependencies installed with `uv sync --frozen` and `npm ci`.

Initial `just test-smart` chose FAST: 20,342 passed, 83 failed, 94 skipped,
two collection errors. This is the initial result, not a final clean-suite claim.
Missing PyMuPDF was resolved by the isolated frozen dependency install.
The focused integration rerun passed 296 tests (one CPD case deselected), including
archive, native history, strict reads, residue axes, publication, and timing regressions.
The native-placement review gate is clear.

The broad-suite deferral remains verbatim:

```text
  DEFERRED: this change would have needed the FULL suite, but no test-dedicated
  session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
  This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
  Only request `just test-session` when a broad/full sweep is actually needed.
```

No scientific simulation or physical-headset validation was performed. Existing
explicit deferrals remain in force. Master-imported screening CSV trailing
whitespace was retained with its historical data.

Final checks:

| Check | Result |
| --- | --- |
| Full frontend suite | 857 files passed; 10,015 passed, one skipped |
| Focused merged backend contracts | 296 passed; one CPD case deselected |
| Browser feature editing/dependencies/scrubbing | Six passed, including Save/reopen and replay |
| Lint and production frontend build | Passed; existing large-chunk warning remains |
| Native-placement review gate | Clear |
| Remaining backend failure families | 141 passed, 23 failed in the focused follow-up |

Browser output `/tmp/__e2e__history-_4ua8tvo` was removed by the launcher and
verified absent after owned processes stopped.

## Remaining readiness blockers, separate from explicit deferrals

The 23 failures are reproducible with the merged frozen dependencies. Their test
files match master; that alone does not establish whether each failure predates
integration. Do not claim a clean backend suite or change scientific expectations
merely to match output.

- Two Slurm tests have CPU memory requests exceeding the partition envelope.
- Two ensemble tests disagree with current duration/HMR preparation behavior.
- Seven cutoff tests and one preparation-cancellation test encounter new preparation/
  resource contracts before the behavior their fixtures intend to exercise.
- Four signature tests still search for the former direct `prepare` AST call;
  the implementation now supplies the memory-budget wrapper through `prepare_args`.
- One local-timing test gets no compatible timing evidence; one deposition test
  supplies a bare object where the implementation now requires a design.
- Four extra-base sample tests depend on an absent local workspace fixture.
- One YggDNAsil retained report pins an outdated router source identity. Its proof
  must be regenerated/reviewed truthfully, not updated by replacing the digest.

Additionally, ten native representation tests in the initial sweep could not find
`native/vr_viewer/build/nadoc-vr-viewer` in this isolated worktree. Build the merged
native viewer and rerun that file before declaring those checks clear; a stale
binary from the active workspace was not substituted. The initial sweep also
selected one CPD frontend-contract case despite the experimental exclusion; it
was not rerun or treated as authorization for CPD development.

ISSUE-171 remains open for the provenance contract described above. The merge
resolves conflicts and passes the main feature-history integration checks, but is
not an unconditional readiness approval. No push or master-branch update was made.


### Document-provenance follow-up

The subsequent document-provenance FAST sweep also exposed six unresolved
residue-axis/history display tests: two in `test_move_history_scrubbing.py` and
four in `test_transform_unpair_history.py`. They concern split-axis expectations
and rejection of master's `residue_transformed` axis field by native transform
projection. These files were unchanged by the provenance task; add them to the
integration blockers above. The ordinary newly recorded loadout publication
boundary now has the [semantic document contract](../document_operation_provenance.md);
legacy missing history and protected simulation loadouts remain refused.

### Sweep edit and continuation end-window follow-up

The user's last-point edit to `(8,38,36)` reproduces a 409 at Auto-scaffold:
the continued tracks shorten from 232 to 221 bp, while the preferred matched-end
route extends eight tracks by 22–26 bp beyond their structural far ends. The
existing honeycomb window permits 21 bp. Automatic seamed routing now retries
the existing closed local route on fresh input, subject to every original
continuity/closure/clearance/window check. Explicit matched requests still refuse.
The window uses structural reset bounds so repeated routing cannot ratchet it.
No molecular placement formulas or locked constants changed; `main.js` LOC delta 0.

Validation: 87 routing/continuity/integrity tests pass. The browser reproduces
new loadout → edit endpoint → Apply → closed dialog → save/reopen → independent
replay; Main remains unchanged. One browser test passes (39.1 seconds including
the temporary visual-review pause); the rendered reopened result was inspected.
The test pauses continuous headless rendering during interactions and renders a
single review image, avoiding setup/rendering timeouts without raising timeouts.
All five browser scratch roots, including the image and failed attempts, are gone.

The required `test-smart` selected FAST: **20,422 passed, 40 failed, 100 skipped**.
The explicitly deferred experimental CPD parameter case was deselected. Thirty-nine
failures match the preceding integration failures. The remaining loadout-audit
test mocked the obsolete getter; it now uses a real isolated document session and
the actual branch publisher. Its final source-audit/document-provenance/routing
follow-up passes **37 tests**. This is not a claim of a clean broad suite: the
39 prior failures remain unresolved. FULL remains deferred with the exact notice
above; no test session was opened.

Timing triage: 487 seconds elapsed for the broad wrapper (450.79 seconds pytest),
no per-test violators, slowest 4.3 seconds. The retained report covers 20,560 test
timings with 1,683.8 aggregate test seconds across workers; the longer files have
many native/software cases, not a single over-budget offender. No timing budgets,
test markers or guards were changed. Compact logs and timing/cleanup summaries
are under `.development-artifacts/merge-readiness/sweep-routing-*`.

### Feature-log controls follow-up (November 3)

User-authorized filter UI: `repair` now matches feature-row typography with 6px
spacing before F0; adjacent `filter` opens keyboard-accessible checkboxes for Fine
routing (on), Document ops (off), and disabled Annotations and visuals. Preferences
last for the panel session. Document operations display the actual ordered journal
below the geometry timeline, without autosave rows or geometry seek targets.
Filtering routing preserves feature indices and canonical recipe/cursor state.
Saved repair proposals remain indicated in the button tooltip. main.js LOC delta: 0.

Validation: full frontend 857 files / 10,016 passed, one skipped (395.73s);
actual-app filter/provenance cases 2 passed (19.6s), including computed font/spacing,
checkboxes, Escape/outside dismissal, unchanged recipe and native history proof;
smoke 23 passed (2.4m). Initial browser run passed routing but its outside-click
assertion targeted F0's popup-covered center; corrected to an exposed edge and
reran both cases successfully. No production change was needed for that test fix.
Memory lint: zero errors, three existing length warnings. `git diff --check` passed.
Logs and pre-run artifact inventory: `.development-artifacts/merge-readiness/feature-filters-*`.
Launcher cleanup verified all three owned roots absent, including the failed run:
`/tmp/__e2e__history-k0nlpcb8`, `/tmp/__e2e__smoke-k5ha4frx`,
`/tmp/__e2e__history-fdv1sv63`. Existing running app remains unchanged.


### Backend failure resolution (November 3)

All 39 remaining backend failures are resolved in
`integration/feature-history-master-20261103`:

- 10 native representation checks required the actual viewer validator. Built
  `native/vr_viewer/build/nadoc-vr-viewer` with the bounded single-job CMake target;
  all ten now exercise the binary successfully. No tests were skipped to hide it.
- Two replica-duration failures exposed missing per-segment timestep metadata.
  The segment now records the resolved production timestep, matching its NAMD
  configuration. Regression coverage checks 1, 2, and 4 fs; no integrator changed.
- Five native history previews rejected the existing `residue_transformed` axis
  flag. The transform-specific validator now admits booleans and rejects other
  values, preserving domain coverage and unknown-field rejection. One old axis
  assertion now checks the retained independently posed base and surrounding
  segments. No molecular placement algorithm or locked constant changed.
- Seven early-stop fixtures and one preparation-cancellation fixture now supply
  controlled resource estimates while retaining real memory reservation. Two
  Slurm fixtures explicitly request a CPU partition within its RAM envelope;
  oversized-request refusals remain covered. The timing fixture stubs CPU
  identity and checks mismatch rejection. The wall-plane fixture mocks the
  current configuration-aware anchor resolver.
- Four protocol-signature checks resolve the current conditional preparation
  wrapper while still checking the actual forwarded keyword set.
- Four sample-audit tests no longer depend on `workspace/2hb_1xT.nadoc`. Their
  tiny native bundle/crossover/insertion construction has five recorded operations,
  uses `agent_structure_guard.publish`, then reopens and independently audits the
  saved file. No unrecorded or private diagnostic authoring was introduced.
- Regenerated cylinder screening from current sources: all 748 records and 166
  witnesses are exactly unchanged. Only the seamed-router and constants source
  hashes changed; no geometry golden or numerical acceptance bound was updated.

Validation: the original failures pass (34 focused cases, four sample-audit cases,
plus the cylinder check within 120 related regressions). Required `just test-smart`
selected FAST: **20,468 passed, 100 skipped, zero failures** in 451.86 pytest seconds.
The experimental CPD parameter remains explicitly deselected as before. A final
fixture/rejection refinement passes eight targeted checks. Changed-file Ruff and
`git diff --check` pass; memory lint has zero errors and three existing length warnings.

```text
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

Timing triage followed `.claude/skills/triage-slow-tests/SKILL.md`: the wrapper took
494 seconds and triggered the aggregate backstop, but there were zero per-test
violators (slowest 4.65 seconds). Aggregate test time was 1,689.3 seconds versus
1,683.8 previously. The largest files retain essentially the same costs (258
oxDNA workflow tests: 72.4 versus 72.3 seconds; 45 mocked headless workflow tests:
71.3 versus 70.4 seconds). The leading routing case performs native construction,
editing and independent replay; headless timeline cases use controlled mock-engine
trajectories. This is existing aggregate suite cost, not evidence of a newly leaked
heavy test. No registry, guard, worker limit or timing budget was changed.

Evidence is under `.development-artifacts/backend-readiness/`. This closes the
39-failure barrier, not the merge itself: fetched `origin/master` commit `75b7f622`
remains to be integrated, and the follow-up changes remain uncommitted.

Cleanup: the task-owned pytest roots 0–5 are absent (older roots had already been
pruned by pytest; the remaining three were removed after checking for live locks).
This deleted 12,499 disposable files / approximately 2.77 GB; compact logs,
timing and cleanup summaries remain in the evidence directory. The integration
checkout’s `workspace/` directory has no tracked or untracked changes, and no
unresolved index conflicts remain. The running app in the original checkout was not restarted or modified.
