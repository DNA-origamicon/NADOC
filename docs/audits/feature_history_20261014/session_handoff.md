# Feature-history stopping-point handoff
Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Sessions since last gate flip or milestone close: 6; user explicitly renewed scope to audit the prior attempt and finish Move/Rotate.

October 27, 2026: **Move/Rotate functional scope is complete for clusters and existing individual-nucleotide operations; the nominal500ms preview target is now met. Both production transform gates remain ON.**
**Original four tools done: 4/4 (Bend, Twist, Extrude, Sweep); Move/Rotate and Fine Routing also qualified.**
CAD ledger: **22/34 complete, 12 remaining (5 core, 7 parked)**. FH-23 remains closed; no gate flip or additional CAD milestone in this performance task.

## Audit and corrective measures
The prior session (`eddc10e7`, `8795cb31`) stayed within the requested shared-native optimization scope and accurately reported the500ms task unfinished. Functional C1–C9 had already passed the authorized2× allowance. The last change saved13–15ms in native geometry while the end-to-end deficit was still200–260ms; another complete regression cycle could not close that gap.

Corrections: measure the app baseline first; remove repeated representation/validation work across the costly stages; keep exact geometry and rejection checks; reserve the broad regression run for a candidate meeting the nominal target. Keep one task and unchanged40-sample measurements, including the first input. Intermediate misses remain evidence, not passes. Details and commands are in the [transform plan](transform_history_editor_plan.md#completion-audit-and-corrective-measures--october-27-2026).

## Delivered performance and preserved behavior
- Ordinary in-span DNA stays in native arrays through lossless transport. Sparse nucleotide poses still use the existing record pose/slab authorities. Companions, extensions, overhangs and out-of-span domains retain the general projection.
- Independent occupancy, final slab registration, finite coordinates, axes and bounds remain checked. Exact packet comparisons cover straight/bend/twist/sweep, loops/skips, partial occupancy, references, child/frame placements and posed copies; six large/posed comparisons also matched byte-for-byte.
- The existing lease retains isolated occupancy/topology/controls. Occupancy reuse requires exact source equality and keeps current admission/reference/type/pose checks. Negotiated topology/control deltas omit only equal fields; older callers still receive full fields. Browser restoration requires the current lease and deeply frozen validated data, and rechecks every fresh coordinate/frame.
- Scalar-domain copying preserves isolation and aliases; per-projection axis input reuse keeps identical arithmetic. Large safe-ASCII blocks retain exact stdlib JSON byte accounting without repeated escaping. No placement formulas, tolerances, manifests, scientific goldens, gates or safety budgets changed.
- Final strict run: `NADOC_TRANSFORM_NOMINAL=1`, three app cases passed. Small6×84 / large18×504 / posed-large18×504;1042/18270/18270 records.40 samples per direction, first included; GPU raster excluded (SwiftShader). Only unrelated readiness/jobs are stubbed in the timing harness.
- Preview p95: small Move/Rotate **48/55ms**; ordinary large **452/444ms**; posed large **469/459ms**. Today's incoming baseline was87/59,715/734,774/746ms respectively. The single nominal-preview performance task closes; no allowance or sample rule changed.
- Apply small/large/posed **442/2488/2689ms**; Cancel **52/55/47ms**. Posed undo2028ms/redo2065ms; exact save/reopen and independent cold replay pass.
- Final evidence: `.development-artifacts/feature-history-focus/move-audit-qualified.log`. Earlier candidate logs retain the653/611,559/515,534,511 and505ms misses. All browser scratch roots are checked for cleanup; scripts and bulk fixtures are disposable.

This task is complete; no remaining Move/Rotate action or successor CAD task is selected. The local `history: finish Move Rotate nominal preview performance` commit contains only this task's20 paths.

## Functional acceptance retained
- Single/multiple cluster Apply publishes one complete-pose command, feature, revision and undo step; saved individual poses are carried through final cluster frames once. No sequential gizmo PATCH publication remains. Native historical rows dispatch to the enabled editor.
- Existing toolbar/menu/shortcut/history controls, exact Cancel, linked/joint constraints, error/blocked attribution, dependents, cursor refusal, undo/redo/save/reopen and cold replay were qualified at gate-on. C4 retains refuse-with-reason and preserves canonical state/draft; no new failure semantics.
- ISSUE-158 recovery takes priority over topology classification, so staple reclassification does not omit moved helices from partial undo responses.
- Single-nucleotide movement affects only that nucleotide; tails move only when selected. Stable tail/insert identities, bridge reconstruction, terminal resize capture and opposite-strand ownership expansion remain repaired.
- Chronological cluster motion carries preceding individual poses. Reset removes the individual component while retaining earlier cluster motion. The F3–F11 example matches independent Full/atom arithmetic (max3.2e-15nm).
- Complete linked moves transport saved member poses once; differential-end rigid inserts still refuse. Attached Sweep refuses occupied source-strand separation; detached construction remains admitted. No silent conversion of displaced staples to overhangs/linkers.
- Explicit Unpair preserves scaffold/3D, gives separated staple segments new cadnano rows, and follows stable pose IDs through history.
- Manual examples: `workspace/move_rotate_axes_overhang_focused.nadoc` and `workspace/move_rotate_pose_reset.nadoc`. Use UI names and `F1: Extrude 1 [detail]`.

## Scope boundaries
Clusters own geometry among grouping constructs. Staple Groups organize strands (names/colors/selection), without transform ownership. Experimental PartGroup / Groups and Placements migration and arbitrary named-group motion/compiler/consumer rollout remain retired. Both organization gates stay OFF; authoring controls are removed. Referenced internals remain retirement debt. Experimental organized files remain refused by the normal sidebar.

ISSUE-126 is complete: construction/replay/publication reject duplicate occupancy, including partial repairs and conflicting undo/redo. Invalid files remain inspectable; complete atomic repair is permitted. No merging, polarity flipping or molecular-placement change. ISSUE-143 remains a separate unequal-direct connection defect.

Remaining core CAD work is cluster membership/deletion and references, ordinary connections, complete reference repair, aggregate desktop qualification and host lifecycle closure (FH-18/25/26/27/28). None was selected by this request. Seven parked CAD milestones remain NP connections/fitting, biotin, imports and asset composition. Legacy conversion and simulation/agent provenance are outside scope. Old S/U queues, original named-group exit clauses and sealed-host rollout are not an active tool queue.

## Regression limits
- Focused backend143pass; focused frontend188pass; exact large/posed packet comparisons6pass. Lint passes. Full frontend787files/9457pass/1skip.
- Strict timing3pass; active-scope functional browser19pass across initial18pass and corrected cursor1pass; smoke23pass. The existing cursor test still expected retired PATCH and old toast wording; corrected to current batch POST/current message, preserving all state/Cancel assertions.
- `just test-smart`: FAST19500pass/19skip/84fail =83 baseline failures plus unrelated exact-float TTL assertion (`6.999999999999545 != 7`). Isolated whole comparison file31pass; prior intermittent verification408 passes in this run. Broad suite is not green.
- DEFERRED: this change would have needed the FULL suite, but no test-dedicated session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
- Required slow-test skill triage:399s aggregate, zero per-test violators; existing real-worker preview/cleanup fixtures and relaxation totals dominate. No shared-stall evidence or marker/budget changes.
- All13 owned scratch roots independently absent; three diagnostic scripts removed (6100bytes). Compact `move-audit-*.log` evidence retained; no bulk captures or original workspace changes.

## Shared-worktree boundaries
Incoming HEAD: `8795cb31`. Commit only this task's explicit paths. Pre-existing API/VR/simulation/test/memory and audit changes remain untouched. No push, reset, stash, restore, dependency downloads or original workspace mutation. `main.js`7349lines, delta0.
