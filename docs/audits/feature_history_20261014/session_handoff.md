# Feature-history stopping-point handoff
Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Sessions since last gate flip or milestone close: 0.

October 26, 2026: **Move/Rotate is complete for clusters and existing individual-nucleotide operations; both production transform gates are ON.**
**Geometry tools done: 5/6 (Bend, Twist, Extrude, Sweep, Move/Rotate); Fine Routing qualified separately.
CAD ledger: 22/34 complete, 12 remaining (5 core, 7 parked).** FH-23 closes; FH-18 and aggregate FH-27 remain open.

## Delivered behavior and qualification
- Single/multiple cluster Apply publishes one complete-pose command, feature,
  revision and undo step. It carries existing individual poses through the final
  cluster frames once and adopts authoritative native geometry. No sequential
  gizmo PATCH commit remains. Native historical rows dispatch to the enabled editor.
- ISSUE-158: undo/redo pose recovery takes priority over topology classification;
  simultaneous staple reclassification no longer omits other moved helices from
  a partial display response. Actual single-posed menu/shortcut regressions now pass.
- Existing entry controls, historical edits through downstream topology, exact
  Cancel, joint/linked constraints, error/blocked attribution, dependents, mid-log
  refusal, undo/redo/save/reopen/cold replay qualified.18 functional browser cases
  pass; final creation/recovery5pass and latency3pass. MV-52 closes at this scope.
- Backend cluster publication9pass; render-diff23pass; tether5pass. Exact geometry
  record parity against HEAD on five fixtures, including both18270-record designs.
  Serialization and lazy ownership lookup only; native builders/constants unchanged.
- Full frontend787files/9447pass/1skip; smoke23pass; lint/whitespace pass.
  `main.js`7349lines, delta0. All13 retained-log browser scratch roots independently absent.
- C8 small6×84 / large18×504 / posed-large18×504: translation p9576/889/909ms;
  rotation67/877/890ms; Apply421/2670/3059ms; Cancel59/59/77ms.
  Posed-large undo2130ms/redo2446ms.40 samples per preview direction, first included;
  GPU raster excluded (SwiftShader), unrelated readiness/jobs stubbed in timing
  harness only. Production tool/history/geometry/publication routes remain live.
- **One deferred Move/Rotate performance task:** reduce large-preview p95 to the
  nominal500ms target. Current values pass the authorized2× allowance; do not
  create another performance task or relax budgets.
- Logs: `.development-artifacts/feature-history-focus/move-final-*.log`;
  [transform plan](transform_history_editor_plan.md) records acceptance and limits.
  Failed intermediate timing/recovery runs remain evidence, not passing claims.

## Scope and next task
The requested Move/Rotate task is finished; no successor was started.
Remaining core work is cluster membership/deletion and references, ordinary
connections, complete reference repair, aggregate desktop qualification and host
lifecycle closure (FH-18/25/26/27/28). Select the next tool with the user.

Clusters own geometry among grouping constructs. Staple Groups organize strands
(names/colors/selection), with no transform ownership or persistent geometry targets.
The experimental PartGroup / Groups and Placements migration and arbitrary named-
group motion/compiler/consumer rollout are retired requirements. Both organization
gates stay OFF; authoring controls are removed. Referenced internal helpers remain
retirement debt, not a Move/Rotate completion requirement. Experimental organized
files remain refused by the normal cluster sidebar.

Retain these user decisions and completed repairs:
- Single-nucleotide Move/Rotate moves only that nucleotide. Tails move only when
  selected. Tail/insert identity aliases, bridge reconstruction, terminal resize
  capture and opposite-strand ownership expansion are repaired.
- Chronological cluster motion carries preceding individual poses. Reset removes
  the individual component while retaining earlier cluster motion. The original
  F3–F11 sequence matches independent Full/atom arithmetic (max3.2e-15nm).
- Complete linked moves transport saved member poses once through final frames;
  differential-end rigid-insert movement still refuses. No topology rules changed.
- Attached Sweep refuses occupied source-strand separation; detached construction
  remains admitted. Never silently convert displaced staples to overhangs/linkers.
- Explicit Unpair preserves scaffold/3D, assigns separated staple segments new
  cadnano rows and follows stable pose IDs through history.
- Manual examples remain `workspace/move_rotate_axes_overhang_focused.nadoc` and
  `workspace/move_rotate_pose_reset.nadoc`. Use UI names and `F1: Extrude 1 [detail]`.
- Older ordering/tail experiments retain individual counterexamples only; their
  original phase-sweep claims were withdrawn because phase_offset was ignored.
  Do not infer molecular approval from ordering approval.

## Regression limits
Final `just test-smart` decision: FAST;19429pass/19skip/83fail. Failure IDs exactly
match `compound-final-test-smart.log`: no additions or removals. The earlier
lease-TTL assertion passes this time but remains known timing debt.
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
Slow-test triage: guarded384s, zero >5s tests; below prior387–400s, no new shared
slowdown evidence. No budget/marker changes. Broad suite remains non-green.
Bend/Twist/Sweep gates ON; Extrude delivered; Fine Routing enabled and qualified
across22 native forms. Source repair/suppress/reorder/dependency viewer retain
established behavior. Feature-row actions use right-click/Shift+F10.
Seven parked CAD milestones remain NP connections/fitting, biotin, imports and
asset composition. Legacy conversion and simulation/agent provenance are outside scope.

## Shared-worktree boundaries
Incoming HEAD: `98ec4cd9`. Commit owned feature-history paths explicitly;
`frontend/src/api/client.js` includes unrelated passive-read changes, so stage
only the cluster endpoint import/export. Existing API/VR/simulation/memory/test
edits are untouched. Mixed `issues_ledger.md`, `issues_fix_log.md`,
`manual_validation_debt.md` and `memory/project_feature_log_overhaul.md` retain
this task's updates uncommitted. No push, reset, stash, restore, broad staging,
phase-constant edit, lock or golden regeneration.
