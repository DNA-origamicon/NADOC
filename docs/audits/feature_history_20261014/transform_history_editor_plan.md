# Move/rotate history editor — FH-23

October 16, 2026. Planning baseline follows U17: **20/38 milestones complete**.
FH-23 is open. This plan neither changes the estimate nor awards completion
credit. The fixed exit remains complete parameter controls, guarded publication,
downstream editing and undo/persistence parity. Desktop and measured interaction
qualification remain FH-27. Assemblies and machine-specific VR are deferred.

The first checkpoint (U18, `909f2de5`) delivered a backend primitive across four existing
roles: `cluster_op`, `nucleotide-transform`, `nucleotide-transform-batch` and
`nucleotide-transform-delete`. It provides strict input normalization, protected
identity binding, reference checks and owned feature-stage preview. The existing
native history-edit API uses the same selected-row binder, including reset target
receipts and explicit placement target replacement. It does not deliver a display
DTO, preview host lifecycle, new HTTP route or UI, and cannot close FH-23.
No molecular builder, constant or numerical manifest change is authorized by
that checkpoint.

### U19 audit decisions — retained full movement scope

The shared host remains the sole session catalog, work slot and publication owner.
A closed family-work adapter selects deformation, Sweep or transform preparation,
evaluation and projection; it does not register arbitrary callbacks. Transform
identity is the stable feature plus its command kind. A batch or reset has no
single deformation output, so its wire contract must not invent `deformation_id`.
Existing deformation/Sweep envelopes retain their established shape.

The transform projection needs its own versioned ordinary-DNA inventory. Existing
comparison and deformation projection contracts deliberately exclude extensions,
flexible strands, CPD display fields, duplex drivers and inserted-base poses.
Weakening those schemas or emitting only their accepted subset would silently
omit geometry. The complete transform component must carry native records and
the topology needed by the existing companion renderers. Projection tests on
an owned model are distinct from actual historical-prefix admission: a family
with no input-defined replay command is not made regenerable by displaying it.
The extension/connection/CPD replay matrix remains explicit integration work.

The native mixed-end root-to-root DS linker fixture has duplicate directional
bridge occupancy (ISSUE-126), already recorded by prior connection-route evidence.
The transform projection must refuse that whole display. Compatible native DS
inputs retain positive parity coverage; do not weaken the inventory or modify
scientific topology to make the invalid example pass. Connection admission/repair
remains FH-25's existing exit.

The audit also found **ISSUE-125**: `_paintLinks` queues additional placement
poses, but the old history Apply branch edits/clears only `editCtx.clusterId`.
Displayed linked movement can therefore be absent from the edited feature and
leave pending state behind. The separate flexible-relax snapshot records only
cluster IDs, so it cannot supply an input-only coupled-movement contract either.

The implementation direction is an explicit, versioned **multi-owner pose
feature**: distinguish the primary selected owner from all solver-assisted
affected owners, retain every accepted absolute pose with its original native
frame, and publish the complete operation atomically. Replay applies those
authored poses through unchanged native placement mechanics. This is not a
claim that a persistent constraint solver reruns on every upstream edit. Such
behavior would need its own driver/constraint inputs and versioned contract.

Old single-owner rows keep their recorded meaning. An edit that acquires linked
owners needs an explicit replacement/upgrade definition; never infer historical
transaction membership from neighboring rows, timestamps or proximity. Until
that definition is implemented and tested, linked controls must refuse the
unsupported write rather than paint it and commit only the primary owner. This
temporary refusal does not close FH-23 or transfer the work to assemblies/assets.
Required acceptance covers selected, linked and fixed owners, parent-local frames,
joint bounds, missing anchors, complete cancellation, atomic failure, downstream
edits and cold regeneration. New organizational-group motion remains the separate
existing FH-18/FH-23 integration exit below.

CAD evidence supports the distinction between explicit transform outputs and
constraint inputs. SOLIDWORKS Move/Copy Body separates Translate/Rotate from
Constraints and explicitly selects bodies allowed to move. Onshape Mates and
Named Positions describe constraint degrees of freedom versus absolute placement;
these are assembly precedents, not evidence of Part Studio implementation details.
Onshape's manipulator origin does not by itself create a persistent mate. NADOC's
multi-owner contract above is an engineering inference, not a copied CAD API.
Sources retrieved October 16, 2026:
[SOLIDWORKS Move/Copy Body](https://help.solidworks.com/2023/english/solidworks/sldworks/t_Move_Copy_Body_PM_features.htm),
[Onshape Mates](https://cad.onshape.com/help/Content/Assembly/mates.htm),
[Onshape Named Positions](https://cad.onshape.com/help/Content/Assembly/named_positions.htm),
[Onshape manipulator](https://cad.onshape.com/help/Content/Home/triad_manipulator.htm).

## Complete existing control and role matrix

| Role/control | Existing behavior to preserve | Owned history requirement |
|---|---|---|
| Explicit placement pose | `ClusterOpLogEntry` replaces absolute translation, quaternion and pivot on an existing ordered placement. A child pose retains its parent-local interpretation. | Preserve feature identity, explicit placement reference, source/provenance and any coauthored name/member/style fields. Target replacement must be explicit; ordinary gizmo selection cannot silently retarget history. Preserve unrelated authored fields during pose editing. |
| Numeric placement controls | XYZ translation in nm; XYZ Euler angles in degrees; per-axis minus/plus 45 degrees; world/local gizmo frame and 45-degree rotation snap. Quaternion is the persisted/internal representation, not a current text control. | Reuse `rotation_math.js` and existing composition conventions. Opening, unchanged Apply and reset preserve the original quaternion/pose; do not introduce conversion drift or a mandatory quaternion UI. |
| Placement gestures | Translate/rotate handles, Tab mode switch, axis picking, rotation rings; ordinary multiple-placement selection applies a common delta about the combined centroid and stores separate absolute poses. | Private display and picking context. A selected historical row cannot silently become a multi-placement transaction or retarget when canonical selection changes. Existing batch/linked records need an explicit consistent edit contract. |
| Pivot/frame | Saved pivot, centroid rebasing, duplex driver/driven root choices. Placement order, parent and driver references are numerical context. | Resolve against the fixed prefix/candidate. Pivot rebasing remains a private calculation until Apply; no ordinary pivot POST during preview. |
| Joint constraint | Joint selector, numerical angle, constrained rotation ring and axis translation, angular limits and locked joints. | Prefix joint axes and ownership, existing solver/math, complete limit/locked-state feedback. Missing or ambiguous dependencies refuse visibly. |
| Flexible/duplex constraints | ssDNA tether and duplex-taut choices; movable link solver can queue transforms for other placements. | Prefix-generated payloads, no latest-document queries. Specify how auxiliary moved placements are represented by the historical feature; never preview them and silently publish only the primary row. |
| Selected nucleotide transforms | Exact base direction/copy address or extra-base address; single/batch transforms distinguish compose from replace. Base/End/Domain/Strand selections expand to exact addresses, including CPD pairing. Ordinary panel is gizmo-only for this role. | Preserve authored address lists, ordering, transform IDs and compose semantics. No rediscovery from current selection, proximity or latest topology. Loop copies, extra bases and CPD scope have explicit native controls. |
| Nucleotide pose deletion | Recorded deletion/reset of one saved transform, with native CPD restrictions. | Resolve its exact historical transform/target; no invented pose knobs or silent target substitution. Display and replay the reset effect with honest missing-reference diagnostics. |
| Group/placement creation | `cluster_create` is birth/membership/ownership, not merely a pose. Organizational creation is separate again. | Classify these rows explicitly in the feature list. Preserve creation dependencies during pose editing; do not claim a pose editor repairs or replaces group creation. |
| Lifecycle | Apply, Cancel, Reset, toolbar/keyboard entry, selection changes, camera changes, document reset and undo. | One owner, source/session/revision/stable-feature binding, no canonical preview writes, cancellation/expiry/supersession, retained refused draft, unknown-publication recovery, one guarded publication and one undo. |

The full eventual placement matrix includes whole-helix and domain scopes,
overlapping ordered owners, child/parent frames, duplex drivers/driven children,
empty frame owners, extensions and other extra geometry affected by the existing
native pipeline. Projection limits or current preview-family exclusions are
admission facts, not permission to remove these cases from the milestone exit.

## Audited live hazards and reuse seams

Source locations below describe the pre-FH23 audit, not executed reproductions.

- `frontend/src/app/feature_editor.js:183` rejects all organized `cluster_op`
  history edits. For legacy earlier poses, it seeks the canonical design first,
  then retains a numeric row index, placement ID and restore cursor rather than
  an owned source-bound history session.
- `frontend/src/scene/translate_rotate_tool.js:553` handles history Apply
  separately from the better-guarded ordinary Apply path. It clears edit context,
  ignores null `editFeature` responses, clears pending poses and closes. Later
  seek/rebake work is not guarded by the ordinary path's document/reset checks.
  Refusal must not be reported as a saved edit or consume the draft.
- `translate_rotate_tool.js:494` restores optimistic preview by publishing a
  canonical store update. Historical Cancel can also seek the old cursor. The
  owned editor must instead dispose only its private render/gesture resources.
- `frontend/src/scene/move_rotate_panel.js:172` reads current placements/joints;
  its duplex pivot choice calls the ordinary mutating rotation-point endpoint
  at line 377. `scene/flex_relax.js:98` obtains current-document tether/link
  payloads. These are not historical-prefix data sources.
- `frontend/src/scene/move_rotate_subscriptions.js:17` resets fields, pivots and
  constraints from canonical selection. The shared panel needs exclusive owned
  session binding so those subscriptions cannot overwrite private controls.
- `frontend/src/scene/cluster_gizmo.js` already contains the required pose,
  centroid, pivot-rebase, joint and constraint mechanics. Its injected store and
  live-paint callbacks currently target the canonical renderer; its detach also
  writes active selection. Reuse those mechanics through a private context,
  not a second numerical implementation or canonical preview mutation.
- `frontend/src/ui/feature_log_panel.js:1425` has no edit entry for the three
  nucleotide-transform snapshot kinds. The generic move/rotate branch at line
  1560 also catches `cluster_create`, whose Edit reaches no corresponding handler
  in `feature_editor`. Fix the role classification, not just the button label.
- `feature_log_panel.js:922` judges a historical placement missing using the
  latest placement map. A placement deleted later can still be valid at the
  selected feature's prefix. Prefix diagnostics must distinguish these cases.
- `scene/nucleotide_transform_tool.js:78` supplies the ordinary residue gesture
  contract and native address expansion. Its optimistic renderer ownership is
  not an isolated history session. Reuse input/gesture mechanics while retaining
  exact prefix targets and the shared publication lifecycle.

Reuse `createDeformationHistoryController`, the closed endpoint-family adapter,
the existing lease/status/receipt host, and private native display infrastructure.
`app/sweep_history_editor.js` demonstrates the current owner/view separation.
An `app/transform_history_editor.js` can be constructed from dependencies already
available in `feature_editor`; the target is **`main.js` delta 0**. The singleton
move/rotate panel must expose a scoped session/view binding, not install a second
set of listeners on the same controls. Final ownership review covers camera,
raycaster, keyboard, picker, pending requests and teardown before the full suite.

## Four finite implementation batches

1. **Native edit/preview primitives — current checkpoint.** Admit the four roles
   above with closed fields and strict scalar/vector/quaternion validation. Bind
   exact authored identities and protected metadata, check referenced targets on
   an independently reconstructed prefix, and evaluate the selected command on
   owned models. Preserve compose versus replacement and complete native batch
   semantics. A deletion remains a deletion. Test missing targets, malformed
   inputs, false/extra fields, poisoned recovery, repeated evaluation isolation,
   full native parity and source immutability. No DTO/host/UI or gate enablement.
   Existing native history API edits share this binder and retain full proof,
   suffix regeneration and one guarded publication; malformed edits cannot
   silently coerce values or ignore fields. Reset target metadata is derived
   from its selected prefix, not carried over from the previously selected pose.
2. **Owned host and complete display/control contract.** Add the closed transform
   family to existing lifecycle infrastructure. Supply bounded native components,
   original input values, prefix placement/joint/frame and native constraint
   context. Resolve pivot and auxiliary-link behavior explicitly. Bind stable
   feature identity across Prepare/Evaluate/Apply/Cancel/Status, and preserve
   exact session, revision, policy, latest-cursor and protected-loadout checks.
   Apply proves the full source and rebuilds the suffix before guarded publication.
   Source unchanged after failed Apply means the draft remains usable. Independent
   status/receipt recovery must never automatically recommit an unknown result.
3. **Complete ordinary history controls and entry points.** Connect the shared
   owner to placement and nucleotide history rows, existing panel/gizmos, private
   camera/picking context and source-bound control data. Preserve every matrix
   row, including constraints and reset. Explain fixed targets and missing
   dependencies. Keep legacy compatibility explicit; no fallback after native
   selection. Test real controls/gestures and actual Python-to-JavaScript packets,
   not only mocks agreeing with each other. No canonical seek/PATCH/PUT/pivot POST
   during an owned preview.
4. **End-to-end closure, pruning and integration review.** Exercise earlier edits
   through later poses/topology/deformations, exact downstream failure locations,
   undo/redo, save/reload and independent cold proof. Cover current and stale
   sources, held Prepare cancellation, same-ID reset/ABA, takeover by a newer
   camera/picker/session, expiry, refusal and unknown Apply. Finish the named-group
   integration exit below rather than declare an explicit-placement-only result
   complete. Publish exact automated evidence and remaining FH-27 desktop/latency
   debt; keep client/server gates coordinated and closed until qualification.

These are implementation batches, not four new milestones. Preserve the fixed
FH-23 exit. At **three major checkpoints on unfinished FH-23**, report cumulative
effort, the remaining exit and containment/refactor/re-estimate before continuing,
as required by the [existing ledger](remaining_standard_part_checkpoints.md#reporting-and-scope-control-rule).
Do not hide effort by renaming batches or shifting unfinished group work to parked
assets. This document does not update the ledger or memory.

## Explicit FH-18/FH-23 new-group movement exit

Editing an existing placement does not define movement of an arbitrary
`part_group`. Equal text IDs, coincident membership or the first overlapping
placement cannot make the namespaces interchangeable. Nor may a group move be
implemented as an invisible replacement owner, frozen output geometry or a
per-residue expansion that omits axes, frames, extensions or future topology.

Keep the [group/placement migration contract](group_placement_migration_plan.md)
open through this shared exit. The required matrix covers a group equal to one
owner, a partial/domain subset, multiple owners, overlaps, unowned members,
parent/driver/child composition, extensions and frame/deformation consumers.
The operation needs an explicit scope, frame and pivot, visible historical
provenance, source-bound preview, downstream replay and undo/persistence parity.
Changing or dissolving organization must preserve existing placement semantics.

Current native consumers differ in composition/ownership treatment, notably
ordered child/whole/domain placements, arm/frame selection and extension pose.
Applying a new rigid delta to arbitrary grouped material may therefore require a
scientific consumer change. That remains behind the repository's molecular
authorization gate: produce an isolated same-frame A/B atom/geometry artifact,
identify affected atoms/bonds/rings and per-junction numeric deltas, and obtain
explicit authorization before changing normal display/export/simulation behavior.
Do not change constants, numerical locks or goldens as part of the proposal.
The Archive outage prevents producing that bulk/visual evidence now; it does not
erase the integration obligation or authorize a guessed placement formula.

## Work budgets, acceptance and safe pruning

Prepare reconstructs a bounded prefix once. Drag evaluation changes only the
selected operation on owned input; no full-history proof or live-document
serialization belongs in a frame callback. Admission must bound input bytes,
nodes, commands, selected targets and prospective native sites before allocation,
including sparse spans, repeated domains/loop copies and extra-base geometry.
Reuse existing preview/output budgets where applicable; document any narrower
admitted scope instead of silently truncating targets or geometry. DTO/envelope
charging occurs once at the appropriate boundary. Cooperative deadlines and
resource counts are not measured latency or heap guarantees.

Successful native replay must not add a second per-target occupancy scan. Check
unique owner identities and duplicate requested addresses before the unchanged
builder; enrich only its exact missing-target failure using the native predicate.
Direct prefix binding still checks slots. Neither this staging optimization nor
the bounded tests qualify large-batch latency; the native predicate itself still
walks strand domains and connector lists. CPD partner expansion retains native
constraints; implicit-partner diagnostics need their complete later contract.

Reuse regression coverage in `move_rotate_panel.test.js`,
`cluster_gizmo.test.js`, `cluster_gizmo_commit.test.js`,
`translate_rotate_tool.test.js`, `move_rotate_subscriptions.test.js`,
`nucleotide_transform_tool.test.js`, `tests/test_group_placement_ui_host.py`,
`tests/test_group_rotation_point_recording.py` and `tests/test_nucleotide_transforms.py`.
Add the missing history/lifecycle/native-geometry cases; do not replace the
ordinary controls with six-field-only mocks. Root runs validation serially.
Archive remains unavailable; no application, representative performance or
desktop interaction claim follows from the initial primitive checkpoint.

Pruning requires a whole-repository caller inventory and replacement coverage.
After native dispatch, eliminate its canonical seek/restore, ignored-null commit
and manual rebake path. Retain genuinely used legacy recovery callers and their
compatibility tests until replaced; gate-off behavior must remain deliberate.
Do not prune ordinary placement commits, nucleotide commits, shared joint/tether
math, public staging guards or scientific refusal branches simply because the
new history host bypasses them. Correct stale comments claiming drag PATCHes or
creation-as-pose behavior only with the corresponding behavior/caller evidence.

## CAD workflow evidence and NADOC's decision

Onshape's Transform documentation makes the selected part and transformation
basis explicit: XYZ translation, direction-based translation, axis rotation and
mate-connector transformations have distinct inputs; manipulators complement
numeric controls. This supports retaining explicit target/frame/pivot controls,
not inferring a placement owner from a group label. It does not establish DNA
placement semantics or require adding Onshape's scale/copy tools to FH-23.
[Onshape Transform](https://cad.onshape.com/help/Content/PartStudio/transform.htm)
(retrieved October 16, 2026).

Onshape's repair workflow uses a historical reference view or last healthy feature
state to expose missing references and lets the user explicitly replace them;
downstream propagation is a deliberate option with stated limits. NADOC's
corresponding design decision is prefix-based diagnostics and reviewed reference
repair, followed by native downstream regeneration, rather than nearest-geometry
substitution or a latest-state missing-ID heuristic. The source does not describe
NADOC's ownership/transaction internals.
[Onshape Repairing](https://cad.onshape.com/help/Content/Document/repairing.htm)
(retrieved October 16, 2026).
