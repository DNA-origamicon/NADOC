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

### U20 integration checkpoint — FH-23 remains open

This checkpoint follows pushed `46477edd`. Counts remain **20/38 complete, 18 remaining
(9 core, 9 parked)**; no completion credit is claimed here. This is the third
engineering checkpoint on still-open FH-23. The containment review retains the
original exit: finish the existing isolated movement workflow and explicit linked
outputs in this checkpoint, then address the remaining native-prefix and new-group
integration cases below. Do not rename those cases as optional enhancements or
transfer standard-core movement into parked nanoparticle work. There is no estimate
change and no new milestone.

The new `placement-poses` v1 snapshot records a primary owner, ordered selected
owner IDs, and every accepted selected/auxiliary absolute pose. Each pose includes
translation, quaternion, pivot, exact parent ID and duplex-driver overhang ID in
the existing native frames. Inputs admit at most 64 unique owners within the
shared 10,000-node/256 KiB operation envelope; the private display's separate
32-owner allowance remains unchanged. The existing ordered placement list stays
the numerical authority. All references and frame bindings resolve before any
pose is applied through the unchanged `cluster_op` overlay in source-list order.
There is no solver rerun or intermediate reconciliation/retry.

`authoring` retains `mode` (`free`, `joint`, `tethers`), `joint_id`, fixed owner IDs
and the native `pivot_id` choice (`centroid`, a joint, `ssdna`, `dup:taut`, or an
owned `dup:root:<overhang>`). Those controls describe how the accepted pose was
authored; they do not become a persistent follow-root or constraint-solving feature.
Unknown or missing referenced controls refuse. The absolute numbers are replay
inputs, not an assertion that the constraints are physically satisfied.

Old `cluster_op` v1 remains single-owner. Explicit upgrade uses a closed
`{upgrade_to:'placement-poses-v1', expected_definition_sha256, definition}` request.
The digest covers the complete original typed row retained by Prepare, including
its provenance. The server supplies that receipt in `control_context.placement_upgrade`;
the client must not hash a newer canonical row. Upgrade preserves feature ID,
autogenerated provenance, old source label and all coauthored name/member/style
fields. The caller cannot replace those inherited fields. The primary owner is
the fixed anchor for subsequent normal compound edits; repairing a missing anchor
needs a future explicit replacement contract. Existing single-owner target-edit
semantics are unchanged.

Lease `command_kind` remains the original selected role. Every transform display
packet additionally reports `evaluated_command_kind`; an explicit upgrade may
therefore have `cluster_op` → `placement-poses` without changing lease identity.
The family host supplies the retained original row to projection. The renderer and
controller must require the locally requested upgrade before accepting that change.
Apply independently reproves source inputs and rebuilds the whole suffix with one
publication/undo. Prepare/Evaluate remain feature-stage display, not full proof.

The only numerical-manifest member changed for this engineering schema addition is
`models.py`: one `SnapshotOpKind` literal. The captured before manifests and exact
prior 17-edge policy are retained in
`placement_poses_schema_compatibility_before.json` and
`placement_poses_schema_compatibility_prior_policy.json`. The reviewed live policy
contains 20 direct old→exact-current edges under the unchanged 32-edge/32 KiB cap.
Engine contracts/helper, molecular calculations, template/runtime checks and saved
pins are unchanged. This is schema admissibility, not a historical-binary oracle.
Root alone runs the software/native regression checks. The compact
[validation record](validation_transform_history_integration.json) records actual
runs and retained failures; app/performance qualification remains open.

| Fixed exit | U20 implementation scope | Remaining obligation |
|---|---|---|
| Ordinary placement and residue controls | Shared existing panel/gizmos, complete native private display/companions, source-owned controls and lifecycle integration are connected. | Complete actual gesture/source-frame matrix and desktop acceptance; bounded real-Three and Python→JS checks do not replace those exits. |
| Linked output completeness (ISSUE-125) | Explicit upgrade and complete absolute multi-owner feature, stable primary, selected/fixed/auxiliary and native frame references. | Qualify actual linked gesture→definition→full suffix/save/cold proof; do not infer neighbors or silently discard auxiliary poses. |
| Historical prefix families | Existing bounded ordinary prefix contracts are reused. | Producer histories for all required extension/connection/CPD cases remain explicit; projection of a current model is not proof of its construction history. |
| Arbitrary named new-group motion | No new placement interpretation in this checkpoint. | Original FH-18/FH-23 whole/partial/multiple/overlap/unowned/frame/driver/extension matrix below remains required; molecular authorization applies if native consumers must change. |
| Delivery qualification | Gates remain off; no browser or bulk artifacts while Archive is unavailable. | FH-27 desktop/latency qualification remains separate. This does not close FH-23's implementation exits. |

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

1. **Native edit/preview primitives — U18 baseline.** Admit the four roles
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

## U21 native-prefix and constraint acceptance

The finite producer/gesture batch remains the same FH-23 exit. This checkpoint
adds prospective admission to the shared prefix replay, retaining1024 sites,
16 helices,64 operations and existing coordinate-span/time limits. It charges
sequence growth, domain/insert walks, backing-helix allocation and bounded saved
native topology before builders allocate. Terminal sequences/modifications count
in the existing site allowance. Accepted admission grants no replay authority;
unchanged native builders still resolve identities and topology.

| Original acceptance area | U21 boundary / remaining work |
|---|---|
| Ordinary native producers | OH extrusion, sequence/rotation, subdomains/bindings, finite connection versions/Apply, ordinary linkers and duplex lifecycle use bounded native prefix admission. Saved bound topology is charged before the existing parser/restorer. |
| Terminal extensions | New top-level input commands record ordinary CRUD/batch, protect created IDs and expose typed strand/extension failures. Valid duplicate batch termini retain last-item-wins, but every item validates first. Delete remains synthetic-only and skips reconcile/retry; upsert retains that native postprocessing and a conservative dependency barrier. No fake import root is introduced for old documents. |
| Terminal history UI — OPEN | Ordinary terminal controls append recorded edits. A dedicated earlier-row input editor and repair reference selectors remain in the existing Fine Routing/core repair milestones FH-24/FH-26; backend input regeneration alone does not qualify those controls. |
| Actual native constraints | Empty-root source fixtures include flexible tethers, historical joints, movable duplex links, SS/compatible DS linkers and driver-child root/taut pivots. Real renderer/gizmo drafts enter owned host Apply, later features, one undo and cold proof. Constraint wiring is tested separately from physical correctness. |
| Flexible display | Verify the actual native flexible companion before crediting its consecutive bonds; preserve missing/unrelated-junction refusals. Suppress duplicate cross-helix and same-helix rigid chords only in the private display, leaving native record poses/metadata unchanged. |
| Joint gestures | Native capture/live composition supplies interim world poses; native pending poses supply final release. Accepted packets do not replace a gesture's baseline. Active-drag Apply refuses; retired/locked/replaced gestures cannot emit late completion. No joint solver math changes. |
| Long numerical producers — OPEN | Native CPD conversion/relax and duplex-relax need existing owned-worker Prepare/Apply integration. Fast prefix replay cannot call expensive solvers. Current-model render/import-root fixtures do not close native-empty-root producer replay. |
| Arbitrary organizational groups — OPEN | Retain original shared FH-18/FH-23 movement/frame/generated exits. Extension creation before conversion and delete after conversion replay; upsert after conversion remains refused pending conserved lineage and actual placement-owner qualification. Whole-helix tests cannot certify arbitrary domain ownership under legacy reconciliation. |
| Qualification — OPEN | Existing FH-27/MV-52 app, complete HTTP/render/lock/memory acceptance and broad regression debt remain. Archive is absent; no browser/bulk scratch fallback or rollout. |

<a id="issue-130-proposed-extension-upsert-v2-integration--not-implemented"></a>

### ISSUE-130 extension-upsert v2 integration — implemented privately

The versioned command and owned ordinary workflow below are implemented for the
existing FH-18/FH-23 terminal-extension exit. The preceding U21 table records the
older refusal boundary; v2 now supplies the explicit extension-only path after
conversion. This does not resolve arbitrary organizational-group motion, enable
rollout, or earn milestone completion credit. Software results and limitations are recorded in
[U25 evidence](validation_organized_extensions.json).

The implementation preserves the distinction that motivated the version change:

- `backend/api/part_extension_commands.py::build` changes only `extensions`.
  It validates complete entries, explicit create/update intent, unique
  identities/termini and live strand references. Updates retain the original
  strand/end; output IDs survive historical input edits through
  `backend/core/part_edit_identity.py`.
- Saved **v1** upserts retain global placement reconciliation and pending-ligation
  retry in `feature_recording.py` / `part_proof_commands.py`, together with their
  conservative dependency barrier. V1 remains refused after conversion; saved
  rows are not silently upgraded. `cluster_reconcile._compute_domain_membership`
  can select one direction-blind overlapping owner, while native ligation can
  coalesce domains and migrate/remove terminal annotations. Those old semantics
  have not been reinterpreted or changed.
- **V2 owns extension annotations only.** Its replay returns from the existing
  pure builder before reconciliation or ligation retry. Domain ordinals, ordered
  placement membership/poses, parent/driver references, empty frame owners,
  organization and every other authoring field remain unchanged. Organizational
  lineage is not used as a substitute for preserving numerical placement owners.
- V2 upsert and existing v1 delete both read/write the shared
  `Resource("part", "extensions")` inventory in addition to their specific
  references. This conservatively orders extension edits, including deletion and
  recreation with a different ID at the same terminus. It is neither a topology
  barrier nor a claim of exact per-terminus independence. V1 upsert retains its
  original barrier contract; delete retains its extension-only execution.

The distinction is a versioned command/transaction decision, not a new molecular
rule inferred from CAD grouping semantics. Native tail, atomistic/export
placement, polarity, contour, constants and solvers remain unchanged. In
particular, `design_geometry._strand_extension_geometry` uses terminal positions,
normals and tangents from native cluster/deformation placement, but populates its
anchor map before the later per-residue transform pass. V2 does not establish
that independently moving a terminal residue moves its extension. The display
helper `part_group_display.js` retains terminal-domain precedence (or whole-helix
membership when there are no domain selectors). Arbitrary member motion and its
companion/frame ordering still require the original full acceptance and molecular
authorization where applicable.

The implemented connected workflow is:

1. **Versioned input and replay.** The closed parser, local version predicate,
   capabilities and replay dispatch accept upsert v1/v2, with new organized
   authoring emitting v2 in the existing Snapshot kind. Existing operation-input,
   aggregate batch and native geometry-work bounds apply. No model field,
   operation literal, numerical manifest or stored pin changes are required.
   Legacy/rootless documents gain no fabricated root or native certificate.
2. **Owned ordinary publication.** `part_extension_owned_recording.py` captures a
   bounded owned source, prepares outside the state lock and publishes through
   `part_extension_publication.py`'s registered `extensions_v1` authority. The
   evidence is `owned_extension_edit`, not a full historical recipe proof. Only
   extensions and one recorded row/recovery pair may change; source history,
   physical/presentation fields and all other authoring fields are retained.
   Document, session incarnation, source object, revision, policy generation and
   request bind admission and final publication. Cursor/loadout/CPD guards,
   cancellation/liveness rechecks, one undo and failure rollback remain in force.
   Unchanged requests return the unchanged source/revision and create no undo.
   Generic active-document callbacks and strict-policy bypasses remain closed.
3. **All five existing ordinary URLs.** Single POST/PUT/DELETE and batch
   POST/DELETE under `/design/extensions` use the shared input resolver and
   recorder. The organized path requires the captured revision and uses v2 for
   upserts; the legacy path preserves v1 behavior. The bounded transport checks
   the original document/session/source again after request-body reading and at
   publication. Complete upsert geometry or the existing exact synthetic-delete
   response comes from that candidate, without a replacement-document GET.
   The shared frontend adapter and dialog retain draft/context ownership across
   requests, refusals and document reset. The organization rollout gate remains
   disabled. Dedicated earlier-row terminal controls and reference picking are
   still FH-24/FH-26 work; input regeneration alone does not complete them.

The focused acceptance files are `tests/test_part_extension_commands.py`,
`tests/test_part_extension_history.py`,
`tests/test_part_extension_placement_preservation.py`,
`tests/test_part_extension_owned_recording.py` and
`tests/test_part_extension_publication.py`, alongside ordinary HTTP/frontend
coverage. They cover strict version/field admission, the conservative inventory
edge, both termini and sequence/modification forms, actual overlapping and
opposite-direction owners, parent/driver and empty-frame owners, v1/v2 pending
ligation behavior, native producer/conversion/suffix replay, undo/reload/cold
proof and denied/stale/cancelled publication. Native existing-material/tail
comparisons use unchanged builders rather than a second geometry formula. Full
results, exact exercised cases and remaining qualification limits are in the
[U25 evidence](validation_organized_extensions.json); this section does not claim app, latency or physical
qualification, nor completion of the arbitrary-group movement exit.

Pruning replaces duplicated extension route mutations with the shared recorder
and updates the two existing fast-delete tests to actual recorded routes and
partial synthetic geometry assertions. The scientific/native movement helpers,
legacy public placement path and guarded release boundaries remain in use.
Two new model operation literals have captured prior manifests/policy and23
exact direct compatibility edges for the three numerical engines. No pin,
calculation, template, runtime, constant or golden is rewritten.

Next numerical-prefix batch uses the existing lease host: `_prepare` already
reserves an exact source/session/revision/policy-owned entry before family work.
A bounded child operation can rebuild the prefix using the existing long native
executor, thread cap, transport and supervisor; return typed prefix data plus
exact selected definition/binding to that same lease, with cancellation on removal
or supersession. Evaluate remains selected-command-only. Apply also needs the
existing worker edit/rebuild executor and decoded candidate before final source
checks/one-undo publication; fixing Prepare alone cannot close the exit. Reuse the
existing entry catalog and worker transport rather than introduce another registry.
Acceptance requires native-empty-root CPD and duplex numerical producers through
actual Prepare/gesture/Apply/cold proof, plus cancellation/stale policy/session
and unknown-engine refusal with no publication. Numerical fixtures and any needed
scratch must obey existing source/Archive rules; no physical simulation run is
required or authorized by this integration plan.
Keep the existing budget distinction explicit: pure Prepare currently1s, Apply5s,
lease TTL60s; public numerical jobs have a separate180s allowance. Worker reuse
alone does not authorize replacing ordinary budgets with that allowance. First
measure genuine tiny native histories; if they cannot fit, choose and research an
explicit asynchronous interaction with a revertible checkpoint, rather than
silently block the normal editor or weaken its timing tests.

## U22 numerical worker boundary and researched lifecycle decision

The private worker pair now implements both prefix Prepare and full-proof Apply.
It is intentionally not routed through the live lease host yet. Both native
empty-root numerical families have exercised the pair, including CPD conversion
and subsequent relaxation, and actual duplex relocation followed by relaxation.
The original capture, selected definition and explicit patch each bind a result;
typed reference failures retain their feature IDs and paths. Prepare carries no
source-equivalence certificate. Apply proves the original source independently
and rebuilds the suffix. Repeated Evaluate executes only the selected transform.

The child reuses the existing memory-only bounded transport and one-thread native
policy. Numerical execution is limited to CPD create/relax and duplex-relax;
ordinary prefix commands retain their prospective admission. Existing site,
helix, operation and command bounds remain. Capture graph limits cannot bound
expanded JSON aliases, so the existing occurrence-based serialization guard now
runs before capture hashing, output dumping and prefix decoding. Exact candidate
decode checks remain shared. No numerical manifest, pin, formula or golden changes.

Initial real worker measurements, including startup and transport, were CPD
Prepare46.59s/Apply46.01s, duplex Prepare1.42s/Apply1.46s; repeated selected-only
evaluations were roughly0.9–1.5ms. These are tiny-fixture measurements, not complete
HTTP/display/lock/heap latency or representative-design performance guarantees.
Final rerun measurements and all red/green outcomes are in
[U22 evidence](validation_transform_numerical_workers.json).

These measurements rule out reusing the ordinary1s/5s deadlines. They also expose
a concrete lifecycle incompatibility: the current client conservatively subtracts
the entire request time from the remaining60s lease, which is already measured
after server preparation. Long Prepare would expire prematurely. A successful
commit near lease expiry can also lose its scalar recovery receipt. Raising only
an HTTP timeout or TTL is not an acceptable integration.

Onshape normally previews the edited feature at its historical stage and offers
a separate Final result including downstream work. Its Performance Panel reports
regeneration timings and identifies features exceeding10s; that is a warning,
not a documented execution cutoff. SOLIDWORKS permits stopping regeneration,
with general rebuild cancellation taking effect after the current feature;
supported command cancellation returns to prior controls. These are interaction
precedents, not vendor evidence for NADOC's internal worker design or deadlines.
[Onshape dialogs](https://cad.onshape.com/help/Content/Home/dialogs.htm),
[Performance Panel](https://cad.onshape.com/help/Content/Home/performance_panel.htm),
[SOLIDWORKS interruption](https://help.solidworks.com/2026/english/SolidWorks/sldworks/c_Interrupt_Regeneration_of_Parts.htm)
(reviewed October16,2026).

The next integration decision is an explicitly cancellable numerical computation
within the existing lease catalog, with three distinct bounded lifetimes:

1. Computing: a pending operation with its own declared deadline and phase/elapsed
   status; the existing180s numerical ceiling is the proposed maximum. No invented
   percentage or silent extension of ordinary edits. Cancellation must reap the
   child and unlink buffers before releasing admission.
2. Ready: a fresh60s editable prefix lease after successful preparation, with
   bounded pending-result retrieval. No indefinite heartbeat renewal. Dragging
   remains selected-only. Apply independently enters a bounded computing phase.
3. Published: a separate bounded scalar-receipt recovery window after successful
   one-undo publication. A transport loss must never trigger automatic recommit.

Connect removal, expiry and sequence supersession to child cancellation; keep
source/session/revision/policy/request checks through final adoption/publication.
The existing supervisor owns the proof slot through cleanup; the host must
transfer ownership exactly once and retain its private work ownership until
decode/adoption finishes. Preserve the two-entry/nonqueued admission boundaries;
do not add another job registry or assume that async alone qualifies responsiveness.
ISSUE-132 fixes the shared supervisor's premature release after repeated dead-child
buffer cleanup failures. Persistent cleanup failure visibly retains admission.

This is containment of the existing numerical-prefix integration batch, not a new
milestone or a finished editor. Real pending Prepare/Apply cancellation, stale
policy/session/source rejection, result/receipt retrieval, unknown-engine refusal
through the host, native gestures and FH-27/MV-52 app/performance qualification
remain required. New-group movement stays the same shared FH-18/FH-23 exit.


## U23 — numerical computation in the existing editor host

The researched three-lifetime decision is implemented privately. Only transform
histories containing CPD create/relax or duplex-relax select numerical computation,
including numerical commands after the selected feature. Ordinary Prepare1s and
Apply5s limits remain; slider evaluation remains selected-only. No new registry:
the same two-entry catalog and single nonqueued work slot own preparation and
publication. The existing supervisor retains proof admission until reaping and
buffer cleanup; host work ownership persists through decode and adoption.

Prepare acknowledges its exact origin/lease/role and sequence0, then Status returns
the existing bounded display packet. Apply acknowledges its exact request sequence,
then Status returns the scalar receipt or a typed known refusal. Computation is
bounded by180s; ready prefixes, terminal errors and receipts have fixed60s windows.
Only a successful new operation starts a new phase window; polls never extend it.
The ready display is retained only until an accepted edit, cancellation or expiry;
its wrapper and result share the existing whole-response bound. Old timer callbacks
are bound to their own deadlines. Background threads preserve document context.

Cancel/removal signals the exact worker. Source/session/policy/sequence changes
prevent result adoption; full source proof and suffix rebuild still run on every
Apply. A timer failure after canonical publication preserves the authoritative
receipt. Lost Apply or Status responses retain uncertainty and cannot authorize a
second submission. Only validated terminal refusal can restore editable state.
OS cleanup can outlast its computational allowance; admission remains held until
it succeeds. The private wire currently reports the owned operation, not a
separate cleanup subphase; do not promise a hard cleanup deadline.

Frontend polling is finite and abortable, with validated scalar acknowledgements,
local final-read timing and independent controller checks. An owned modal appears
before Prepare and during Apply, showing elapsed time without invented percentage
or ETA. Cancel, close and Escape work before the main controls are created.
Completion/reset/disposal removes its timer and listeners; a late old operation
cannot close a replacement dialog. Ordinary controls retain unknown-result/status
recovery when the modal closes. No main.js growth or legacy live-tool pruning.

[U23 evidence](validation_transform_numerical_lifecycle.json) records tests,
measurements and cleanup. Native numerical gesture and full desktop/HTTP/render/
lock/heap acceptance, arbitrary new-group movement and post-conversion extension
upsert remain required. Both rollout gates stay false; FH-23 is still open after
six engineering checkpoints. No milestone exit is weakened or moved to parked work.

The U23 handoff specified that the next numerical gesture check reuse `test_part_transform_numerical_host.py`'s
real recipe/supervisor helpers and `test_part_transform_gesture_contract.py`'s
`gesture_draft` bridge. That bridge already drives the private renderer, tool,
gizmo and native events. Its current fixture assumes `placement-poses`; numerical
recipes select `cluster_op`, so exercise the existing explicit Upgrade control
and submit its actual emitted definition. Do not fabricate pending poses. The
joint oracle must bind the numerical fixture's real relaxed pose and30-degree
limit instead of inheriting the bridge's identity-pose/25-degree assumptions.
This is the remaining acceptance substep, not a new fixture framework or milestone.


## U24 — real numerical-prefix gesture qualification

The existing native bridge now opens a real numerical host packet, explicitly
upgrades its single-owner feature through the actual control, and submits only
the native gizmo's emitted definition. CPD free motion and relaxed-duplex root,
taut and joint gestures pass through selected-only evaluation, asynchronous
full-proof Apply, one undo/redo, save/reload and independent spawned cold proof.
A separate duplex case retains the original same-kind single-owner host Apply.
CPD Escape cancels the private gesture after upgrade without a late motion draft.

Joint expectations pin the ordinary historical25-degree and numerical30-degree
limits independently of the packet. The world-point oracle handles the real
nonidentity relaxed baseline and checks both intermediate and released poses.
Duplex-root checks the actual driver's exact native rest-frame pivot and its
recorded identity. Taut movement deliberately exceeds contour and requires a
native correction. These are software/constraint-use checks, not molecular
validity or convergence claims. Every child, shared-memory buffer, supervisor
thread, timer and admission is checked at teardown, including failed bodies.

[U24 evidence](validation_transform_numerical_gestures.json) records executed
checks and fixture corrections. No production code, scientific manifests, pins,
constants, goldens or rollout settings change. Ordinary native gesture regression
remains; app/HTTP/render/lock/heap qualification stays FH-27/MV-52.

**20/38 complete;18 remaining (9 core,9 parked);+0 completed,+0 total.** FH-23
remains open after7 checkpoints and FH-18 after13. The finite extension proposal
above and member-motion consumer matrix in the organization plan describe the
remaining integration; neither is implemented by this qualification checkpoint.
Next implement the complete extension-only v2 contract/owned transaction, then
resolve arbitrary member motion through its isolated native-consumer comparison.
No milestone split, exclusion or new completion credit.
