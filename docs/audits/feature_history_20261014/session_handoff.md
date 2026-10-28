# Feature-history stopping-point handoff
Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Sessions since last gate flip or milestone close: 8 (per contract, only a gate flip resets this counter).
User selected FH-18 and explicitly directed continuation until fully closed on October27,2026, superseding the one-task/stop-loss limit for this work.

**Tools done: 4/4 (Bend, Twist, Extrude, Sweep); Move/Rotate and Fine Routing also qualified.**
CAD ledger: **23/34 complete, 11 remaining (4 core, 7 parked)**.
**FH-18 is fully closed at the current user-selected cluster scope.** ISSUE-99 is resolved at that scope; MV-48 retains aggregate FH-27 integration/resource debt. No production gate changed.

## Delivered behavior
- Make Cluster v3 preserves existing native nucleotide and axis geometry, including posed whole-helix and domain selections. Existing placed owners retain their scope; an eligible identity default can surrender whole helices. The new cluster starts at identity, and moving it remains a separate Move/Rotate feature.
- Adding/changing a cluster that would alter an existing Bend/Twist arm refuses with the dependent feature identified. This preserves native geometry rather than changing deformation formulas.
- Dissolve lists all live incoming owners (including frames, children, joints and deformations), with readable names and structured identities. Its existing finite admission remains: posed, repivoted, child/duplex-owned, deformation-dependent or pose-overlapping groups refuse atomically.
- Sidebar and context-menu creation/membership edits, rename/style, dissolution and Cluster Unassigned Components are recorded and replayable. Style preview stays local; a failed commit restores authoritative style, and closing after debounce does not record the same edit twice. Failed rename restores the label; creation/repair failures explain why.
- V3 recovery rebuilds metadata from the selected decoded topology checkpoint. Evicted/missing recovery returns HTTP410 without changing the document, revision or undo/redo. Independent native proof still uses authored inputs, with recovery payloads poisoned in regression tests.
- Historical-cursor edits explicitly refuse. Ordinary undo/redo, save/reopen, cold proof, repeated real-thumb seeks, source preservation and native axes are qualified. V1/v2 replay stays unchanged; component repair keeps its existing v2 contract.

See [bounded qualification evidence](group_placement_migration_plan.md#fh-18-lifecycle-qualification--october-27-2026).

## Validation and limits
- 9 cluster browser scenarios qualified across the final eight-case pass and corrected single historical-refusal rerun; clean console except exactly asserted refusal responses. 23 smoke cases pass, including loaded-design and teardown gates.
- Visual inspection of the reopened native 6 × 84 bp honeycomb bundle confirms intact geometry and a separate Make Cluster row. An unrelated Dimensions-save toast remains aggregate integration debt, not a cluster failure.
- Small/large native recipes: 6 × 84 / 18 × 504 bp, 1042 / 18270 rendered nucleotides. Make Cluster 163/734 ms; style Apply 110/600 ms; preview p95 36/132 ms (40 samples including first); rename Cancel 19/14 ms. Software GPU raster excluded, as in existing transform acceptance.
- Initial large timings incorrectly included repeated transfer of the entire geometry to the test process. Final latency checks poll only scalar adopted state and stub unrelated readiness/jobs in the fixture harness; no cluster route is intercepted.
- Focused backend runs: 50 reference, 188 lifecycle, 92 placement/recovery, 49 seek/ownership, final 55 placement/version cases pass (overlapping runs). The last run includes the four corrected version expectations and nucleotide/axis equality.
- `just test-frontend`: **9463 pass/1 skip**, all 787 files pass. `just lint`, JavaScript syntax and task diff checks pass.
- `just test-smart`: decision **FAST (fast suite only)**; **19521 pass/19 skip/87 fail**. Four failures were stale version expectations (headless creation, two generated joined cases, unknown-version capture); corrected and passed in the final focused run. The remaining 83 match the persistent baseline. No broad rerun is claimed after the test-only assertion fixes.
- DEFERRED: this change would have needed the FULL suite, but no test-dedicated session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
- Slow-test triage: 387 s aggregate, zero per-test violators. Existing real-worker preview/publication/cleanup fixtures and relaxation totals dominate. No marker/budget changes. Broad suite remains red and belongs to FH-27.
- Evidence: `.development-artifacts/feature-history-focus/fh18-*`. Browser scratch roots include saved files, profiles, caches and screenshots; all independently verified absent after success and failure. No original workspace design was changed.

## Single next task
FH-25: continue the existing [ordinary connection completion plan](ordinary_connection_completion_plan.md), starting with its finite supported matrix and ordinary controls/source profiles. ISSUE-143 is the separate unequal-direct connection defect. Do not reopen completed cluster/Move-Rotate qualification or the retired PartGroup migration.

## Retained scope
Transform gates remain ON; no Move/Rotate performance task remains. Clusters own geometry among grouping constructs; Staple Groups organize strands. Both organization gates stay OFF. PartGroup migration, arbitrary named-group motion/compiler rollout, old-file conversion and simulation/agent provenance remain excluded.
ISSUE-126 collision-free publication/repair/undo policy remains complete. Remaining core milestones are FH-25/26/27/28; seven asset/import/connection milestones remain parked.

## Shared-worktree boundaries
Incoming HEAD: `12382f9d`. Commit only explicit FH-18 implementation, tests and closure-record hunks. Pre-existing API/VR/simulation/test/memory-hygiene/audit edits remain preserved. No push, reset, stash, restore, dependency download or original workspace mutation. `main.js` unchanged.
