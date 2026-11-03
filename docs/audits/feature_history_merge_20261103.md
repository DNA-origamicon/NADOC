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
