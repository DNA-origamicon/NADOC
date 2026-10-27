# Feature-history stopping-point handoff
Binding: [operating_contract.md](operating_contract.md); current user instructions take precedence.
Sessions since last gate flip or milestone close: 5; user explicitly renewed this optimization scope after the counter3 report.

October 27, 2026: **Move/Rotate functional scope is complete for clusters and existing individual-nucleotide operations; both production transform gates are ON. Ordinary large previews are faster; the nominal500ms target and variable posed-design latency remain open.**
**Original four tools done: 4/4 (Bend, Twist, Extrude, Sweep); Move/Rotate and Fine Routing also qualified.
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
ISSUE-126 occupancy correction is complete. The user explicitly authorized the
shared Move/Rotate optimization/refactor after the counter3 stop-loss, and asked
for a complete process/bottleneck map. The transform plan now maps Prepare,
evaluation, transport, private rendering, Apply and Cancel with measured costs.
Work remains on the same nominal500ms performance task; do not revive retired
grouping requirements or select an unrelated milestone from this authorization.
Remaining core work is cluster membership/deletion and references, ordinary
connections, complete reference repair, aggregate desktop qualification and host
lifecycle closure (FH-18/25/26/27/28); none was started in this performance task.

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

## Regression limits — prior Move/Rotate acceptance
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

## October 26 status reconciliation
Documentation-only reconciliation; no gate or milestone changed. Earlier S/U
queues and pending tool labels are historical. MV-50/51 and ordinary ISSUE-100
are closed against existing acceptance; MV-48 retains cluster/integration gaps.
MV-49 old-file recovery is outside required completion under contract §10.
ISSUE-126 now refuses duplicate occupancy in native construction/replay and
ordinary publication. The user requires completely collision-free results even
for previously invalid sources: partial repairs and conflicting undo/redo refuse.
FH-28 concerns retained production lifecycle gaps, not restarting sealed-host
rollout. The contract’s R3 migration is not evidence of a missing tool gate.

## ISSUE-126 correction and verification
Shared native execution refuses duplicate slot ownership before returning a
candidate; finite construction checks before lineage observation. Cold proof
identifies the offending connection feature. Ordinary mutation, replacement,
crossover batches and undo/redo require completely collision-free output.
Invalid files remain inspectable; complete atomic repair is allowed. No merging,
polarity flipping or molecular-placement change. Sparse interval sweeps count
unique conflicting slots; references remain non-physical overlays.
Focused occupancy12pass, native connection proof17pass, preview52pass/2deselected.
Initial connection regression392pass; final policy regression313pass/1test-only
failure (deque/list comparison), corrected and covered by the12pass rerun.
Final `just test-smart`: FAST19436pass/19skip/84fail: exact83 baseline IDs plus
`test_native_auto_proof[merge]` synchronous verification408; whole-file focused
rerun8pass. FULL deferred without a test-dedicated session; no broad green claim.
Guard370s, zero per-test violators; prior guard384s. Triage found aggregate
real-worker/fixture cost; no budget/marker changes. Lint/diff pass. No app run.
Evidence: `.development-artifacts/feature-history-focus/issue126-*.log`.
Initial smart98fail included15 obsolete raw-invalid-output expectations, now
corrected to early refusal; compatible dsDNA cold proof remains a positive test.

## Shared Move/Rotate performance refactor — October 27
The transform plan contains the full process map and prior measurements.
Prior commit `eddc10e7`: boundary sweep, array-retaining slabs, graph accounting
and browser string accounting; ordinary large p95749/727ms, posed972/909ms.
Current user request explicitly renews optimization of the costly shared native
geometry path and reuse of earlier solutions. General `_geometry_for_helices`
now reuses the compact path's `native_slab_poses_for_arrays` before discarding
arrays. Only emitted unposed native rows enter that batch; posed residues,
authored sources, bridges and extensions retain final record authority.
No molecular formula/tolerance change, new persistent cache or invalidation rule.
Six alternating same-process pairs per fixture against incoming HEAD: geometry
median ordinary133.59→120.63ms, posed132.51→117.83ms; all12 packets byte-identical.
Focused123pass; exact placements across deformations, loop/skip copies, partial
occupancy, tails, outside-helix domains and moved copies; error identities retained.
Record/schema/occupancy validation and response accounting remain major costs.
Final browser3pass: small/large/posed move p9576/733/760ms, rotate69/696/735ms;
Apply435/2667/2973ms, Cancel46/51/52ms; exact posed reopen/cold replay pass.
FAST19456pass/19skip/84fail: baseline83 plus verification408; isolated file2pass.
FULL deferred: no test-dedicated session; parked in .nadoc-slow-pending.
Guard373s, zero per-test violators; existing worker/fixture costs, no marker changes.
All5 scratch roots absent; scripts deleted; `native-followup-*.log` retains evidence.

## Shared-worktree boundaries
Incoming HEAD: `eddc10e7`. Commit only this task's explicit paths/own hunks.
Pre-existing API/VR/simulation/test/memory changes are preserved. Issue/fix-log
and MV-54 corrections were committed as selective hunks; project memory’s current
ISSUE-126 note remains uncommitted because its surrounding hygiene/reconciliation
changes are mixed. Prior unrelated/audit hunks remain unstaged. No push/reset/
stash/restore. Temporary audit preimages removed; retained only bounded logs.
No molecular constants, manifests, geometry goldens or rollout gates changed.
