# Group organization and placement: finite migration plan

Architecture proposal, October 16, 2026; source baseline `3aa2529a`. The U6–U15 status
below records implementation after that proposal. FH-18 remains open. The
overhaul count remains **18/38 complete**, with **11 core and 9 parked milestones
remaining**. This plan and its implementation batches earn no separate milestone
credit. See the [fixed exits and ledger](remaining_standard_part_checkpoints.md).

FH-18 checkpoint 3 also addresses the two existing auxiliary publication paths;
those changes are owned separately from this plan. If FH-18 remains open at that
checkpoint, report the existing **three-checkpoint task-growth trigger**, the
remaining posed/regrouped exit and this containment plan. Do not increase the
estimate, split the milestone or call the admitted identity-only subset complete.

## Decision and user-visible contract

Separate **organizational groups** from **placement owners**. Retain the existing
ordered `Design.cluster_transforms` records as the sole authority for rigid
placement and its existing frame/parent context. Add a versioned organizational
collection whose records own selection, membership, names and group style only.
These are distinct responsibilities, not two copies of pose state. There is no
second pose array, duplicated pose order, mirrored transform or mutable cache.

An explicit recorded conversion activates this regime. Its absence means legacy
behavior. Conversion preserves every existing placement record's ID, membership,
translation, quaternion, pivot, order, default/arm role, parent and duplex-driver
ownership exactly. Organizational IDs can retain their existing strings in a
separate typed namespace; numerical owner IDs do not need rewriting. The exact
schema/name is to be frozen with tests before implementation; use a closed
versioned model, not a caller-controlled boolean bypass.

The user sees these responsibilities separately:

- **Groups** contain selectable members. Regrouping, removing members or
  dissolving a group changes organization without moving those members.
- **Placement / Transform features** remain visible, named and editable. A
  dissolved posed group leaves its actual placement feature visible, with its
  member scope and frame/constraint dependencies. This is not a hidden backup
  group, automatically renamed replacement group or invisible identity carrier.
- Removing a Transform is a different operation from dissolving a group. It can
  change placement and has its own downstream dependency decision. Dissolve must
  never remove a joint, frame, child or driver merely to satisfy a group deletion.
- Editing an earlier feature still regenerates its downstream dependents. This
  plan promises placement preservation for the explicit organization operation,
  not universal world-coordinate invariance under arbitrary upstream edits.

For an existing group, conversion copies its organizational definition into the
new collection while leaving the original placement record untouched. Later
organizational edits do not write the legacy record's membership/style fields.
Those retained fields are placement scope or legacy compatibility data, not a
second source for the new group UI. A default or empty placement owner referenced
by a lattice frame remains an explicit visible placement/frame owner.

This choice is preferable to tagging several new record types into the numerical
owner sequence: it avoids changing every numerical consumer's type dispatch and
keeps the exact current placement inputs intact. It still requires the complete
selection/UI/reference migration below before enabling the new regime.

## Why the smaller-looking alternatives are insufficient

| Alternative | Concrete problem |
|---|---|
| Copy the group pose into `NucleotideTransform` | That model addresses individual base/extra-base records and applies a final world-space delta after native placement. It does not own helix axes, lattice continuation or deformation frames, and expands a group into residue-count state. |
| Bake the pose into axes, nucleotide coordinates or saved geometry | Violates the topology/geometry separation and makes future native regeneration depend on sampled output. |
| Append one rigid transform after the current pipeline | Changes composition order, domain masks, endpoint-fit context and extension behavior. It is not equivalent to retaining the old owner. |
| Keep an invisible replacement `ClusterRigidTransform` | Preserves the coupling and conceals live ownership from the user. The recommended design retains the real placement owner visibly and removes only organization. |
| Add another pose list plus interleaving indexes | Creates two pose/order authorities and a new reconciliation problem. The existing ordered list is sufficient. |
| Treat all group IDs as interchangeable reference strings | Frame/parent/driver references mean placement; UI selection means organization. A generic recursive ID rewrite would silently change one of those meanings. |

Existing `NucleotideTransform` and group move tools can contribute UI and native
rigid-operation helpers, but neither is a drop-in persistence representation for
dissolving a group. No new placement formula is proposed here.

## Audited consumer inventory and required boundary

Paths below are relative to the repository. This is the finite set of consumer
families to close; a final search for direct `cluster_transforms` consumers must
classify each remaining caller before rollout. Do not mechanically replace every
occurrence, since several names also refer to compute clusters.

| Consumer | Existing behavior / required action |
|---|---|
| `backend/core/models.py::{ClusterRigidTransform,NucleotideTransform,DeformationOp}` | Keep legacy placement records and saved operation values intact. Add only the closed organization regime/records and explicit new command inputs. Distinguish organization IDs from placement IDs in typed inventories. |
| `backend/core/deformation.py::{_clusters_for_helix,_arm_filter_cluster,_apply_cluster_transforms_domain_aware}` | Continue receiving the identical ordered placement list. Child poses apply before parent-level poses; array order and domain masks matter. First nondefault owner also chooses the arm frame, even if its rigid pose is identity. |
| `deformation.py::{_bend_endpoint_pose,validate_bend_endpoint_fit,deformed_nucleotide_arrays,deform_extended_arrays,apply_deformations_to_atoms,deformed_helix_axes}` | Preserve fitting, scope, normal/axis and extension behavior. The extension path currently uses the first matching owner, unlike paths that compose all owners. Do not fix or generalize that behavior inside this migration. |
| `backend/core/design_geometry.py`, `backend/core/atomistic.py` | Ordinary scalar/array/atom output must agree before/after conversion and organization edits. Per-nucleotide transforms remain their existing final stage. Export/physical preparation consume the same native output, not a separate display correction. |
| `backend/core/lattice_frame_model.py`, `lattice_frames.py::{append_frame_bundle,append_frame_cell,register_created_bundle_frames}` | `placement_cluster_id` continues resolving the unchanged numerical owner. Continuation extends that owner's native scope as before. A group membership edit must not remove frame ownership. No field rename is needed merely to improve terminology. |
| `backend/core/cluster_reconcile.py`, `extrusion_clusters.py`, `cluster_autodetect.py` | Split topology-driven placement inheritance from organization maintenance. Existing frame/origin inheritance remains a placement operation; group CRUD does not invoke it to infer or recreate deleted organizational groups. Explicit regime prevents legacy group bootstrap. |
| `backend/core/duplex_cluster.py`, `cluster_join*.py`, flexible endpoints and saved driven topology | Preserve parent-local ordering, both Join attachments, joint local axes and `overhang_duplex_driver_id`. Classify each reference by role; organizational deletion is not deletion of these placement owners. Recognized saved definitions require the same typed treatment, without arbitrary JSON traversal. |
| `backend/core/part_scope_references.py`, `part_structure.py`, `part_group_dissolve.py` | Extend exact schemas/identity namespaces and bounded structural checks. Organizational incoming references need explicit retain/update/cascade decisions; placement references remain valid. Unknown grammar or ambiguous IDs fails before mutation. |
| `backend/core/part_overlay_commands.py`, `backend/api/part_group_recording.py`, `routes_clusters.py` | Keep old builders exact. New versioned conversion/group operations use the existing owned transaction, one undo/revision and exact-candidate response. They never mutate placement membership as a side effect of organization edits. Pose confirmation targets an explicit placement owner. |
| `backend/core/part_deformation_edit.py`, `backend/api/routes_deformation.py`, `routes_loop_skip.py`, preview evaluator/DTO | Group selection resolves through the new organizational collection into fixed native target membership. Keep numerical placement/frame context separate from group-picker provenance. In particular, `DeformationOp.cluster_ids` is also read during endpoint fitting; it cannot simply be replaced with new organization IDs. |
| `backend/core/feature_history_clusters.py`, `cluster_join_history.py`, pattern recovery and `backend/api/crud.py` seek | Distinguish organization lifetime from placement lifetime. Dissolving organization must not remove, resurrect or reapply a placement. Cover ordinary/optimized/F0 seek and same-ID recreation; do not decode more history or run geometry merely to classify the regime. |
| Proof/recipe/generated producers, repair metadata, capture/worker schemas and strict batch scope | Register explicit new versions/resources, transport all organization inputs, and preserve old versions. Unknown new roles fail closed. A document carrying new organization state must not receive a complete proof after that state was ignored. Generated authoring must not silently keep producing old group semantics in the new regime. |
| `frontend/src/ui/cluster_panel.js`, group style/selection helpers, `scene/cluster_gizmo.js`, `scene/move_rotate_panel.js`, Join/joint tools | Group lists/picking/style read organization; placement editing reads visible placement owners. Restore selection across response/undo/load without confusing equal string IDs in different namespaces. Preserve existing controls; no monolithic `main.js` implementation. |
| Bend/twist popup/editor, isolated preview controls and render input validation | Show organizational choices, retain explicit native scope/frame context and exact untouched inputs. Update closed DTO validators together. No canonical preview mutations or quiet enablement of currently gated preview/comparison features. |

### The nontrivial new-move boundary

An unchanged placement list is sufficient to prove that conversion, dissolve and
regrouping preserve existing output. It does **not** prove that appending or
splitting owners is a correct implementation of a new arbitrary group move.
`_arm_filter_cluster` and the first-owner extension branch make that a separate
semantic question. New groups must not automatically become geometric frame
owners, and moving a group must not silently select an unrelated old owner.

The next implementation must distinguish editing an existing visible placement
from moving a newly selected set of members. Reuse the current native rigid
operation only when its exact ownership semantics represent that request. Freeze
the required group-move matrix before changing this boundary; a mismatch remains
an explicit FH-18/FH-23 integration exit, not a reason to hide a carrier or claim
full closure. Any necessary generalization of frame/extension consumption is a
separately demonstrated scientific change, not a schema-only compatibility edge.

### Post-U11 caller audit and next delivery

Read-only source review at `2fbee2d7`, with independent architecture and UI
reviews. No production behavior, numerical contract, gate or test changed.
This is planning evidence, not a tenth FH-18 engineering checkpoint.

`backend/api/generated_history.py::build_recorded` is the only production
constructor of `GeneratedHistory` and invokes `two_np_build.materialize`.
`routes_generate_design.py` exposes that gold-nanoparticle workflow. Branch,
joined-section and connectivity generation feed it. Ordinary `part_batch*`
and `part_recipe*` do not emit `_generated_scope`. The generic merge helper also
serves `part_branch_commands.py` and `part_section_commands.py`, so its lifecycle
cannot be classified as exclusively NP or pruned as unused. The audit found no
ordinary extrude, sweep, bend/twist, move/rotate or Fine Routing caller requiring
a new generated-scope compiler before the visible core work.

**Sequence D next**, then the unresolved B/C consumer and movement obligations,
then E qualification. Existing generated prefixes retain v1/v2 meaning; active
organization composition keeps its explicit refusal until qualified. Generated
compatibility stays an open FH-18 exit, not a silent transfer to parked FH-36.
Ordinary linear/circular patterns are separate visible tools in the core consumer
inventory; U15 implements their explicit-placement organization adapter below.
Do not expand the NP planner or add an unused compiler
ahead of a concrete standard-tool caller.

The next visible delivery must cover the following connected paths, rather than
only changing the sidebar label or array:

| User action / caller | Required integration and fixed evidence |
|---|---|
| Explicit conversion and group edits: `ui/cluster_panel.js`, `api/client.js`, `routes_part_group_organization.py` | Use the existing revision-checked command host and shared response adoption. Conversion supplies the complete ordered placement-ID expectation. No load-time conversion or public gate change. |
| Select Groups versus Placements: `scene/selection_ref.js`, `selection_model.js`, `selection_manager.js`, sidebar wiring in `main.js` | A typed `part_group` selection resolves organization only; `cluster` remains placement. Reconcile selection/highlights/labels after response, undo and load. Equal text IDs must not cross namespaces. Keep placements visible in numerical order, including empty frame owners. |
| Create, regroup, rename, style and dissolve: sidebar and `selection_manager.js` context menu | Both entry points use organizational membership and the owned commands. Show dependency failures; retain canonical state on refusal. Preserve select/highlight, membership editing, color, opacity and hide controls. |
| Scene style and visibility: `scene/cluster_entries.js`, `helix_renderer/palette.js`, `color_util.js`, `visibility_controller.js` | Share one organization membership adapter; domain selection must not inherit the legacy mixed-placement interpretation. Preserve color precedence, minimum overlapping opacity and visibility union. Define a separate hidden-group identity/persistence path; do not reinterpret `hidden_cluster_ids`. Legacy absent organization retains its existing behavior. |
| Ordinary Bend/Twist: `scene/deformation_targets.js`, `deformation_tool_launcher.js` | Carry named organization selection through the ordinary launcher. Keep numerical placement/frame context separate. U11's private history support alone does not cover this entry point. |
| Existing placement motion: `scene/translate_rotate_tool.js`, `cluster_gizmo.js`, `move_rotate_panel.js` and subscriptions | Explicit placement selection retains XYZ/Euler, local/global axes, snap, joints, duplex pivot and Apply/Cancel/Reset. A newly regrouped set must not fall through the first-overlapping-placement heuristic. |

The commit path needs a pinned failure regression before adaptation:
`cluster_gizmo.commitPendingTransforms` awaits sequential `patchCluster` calls,
does not inspect null responses and then clears all pending transforms. The client
can return null on a failed request. Qualify refused/stale and partially accepted
results, retry/cancel behavior, source ownership and pending-state preservation;
do not describe this existing sequence as one atomic multi-placement transaction.
This is a source-audit finding, not an executed reproduction or completed fix.

Acceptance covers explicit conversion → posed dissolve → regroup with unchanged
native output; same-text group/placement IDs; empty, overlapping and domain-backed
groups; scene style/visibility adoption; both sidebar and context-menu edits;
ordinary named Bend/Twist; explicit placement motion; failure/stale/document-change
paths; undo, reload and cold replay. New-group motion still needs the distinct
ownership/frame matrix above. Editing an old placement cannot close that exit.
No per-frame history walk, proof or new molecular calculation belongs in this UI.
Full desktop/latency evidence remains FH-27; Archive availability and the public
gates remain release constraints, not evidence that the UI works.

For the later generated-consumer work, retain the audited hazards: untyped v1/v2
input IDs may coincide across resource families; nested organization needs explicit
extraction/merge; outside groups can retain a strand ID while domain ordinals
change; frozen deformation addresses are historical provenance, not live primitive
dependencies. A proposed v3 must preserve old-version meaning and establish
explicit complete ownership or validated lineage before native topology work.
No v3 format or ownership policy is approved by this planning review. The 25
qualified core commands alone do not qualify all generated producers; the latter
also contain branch/section routing, auto-scaffold, autostaple, constraints,
curvature, budget fitting and numerical placement/Join operations.

**18/38 complete; +0 completed, +0 total; FH-18 remains at nine checkpoints.**
Its growth flag, original five batches and full exit remain. Each subsequent
implementation must name the actual user action/caller it completes and the
remaining exit, so supporting infrastructure does not obscure unfinished work.

## History, authority and numerical compatibility

1. **Explicit conversion, no load migration.** Old `.nadoc` documents and old
   `cluster_create` v1/v2, `cluster_op` v1 and `cluster-dissolve` v1 rows retain their
   existing meaning. Normal loading neither enables the regime nor manufactures
   placement features. Add a dedicated native conversion command and versioned
   organizational commands; do not bump the global proof version.
2. **Native inputs, not client output.** Derive conversion's group definitions
   from the admitted owned native prefix. Record the regime version, exact input
   expectations and required deterministic output IDs once. No client-supplied
   replacement Design, arbitrary transform graph or snapshot-derived proof.
3. **Closed dependencies.** Organizational membership/name/style and placement
   pose/scope/frame ownership are different resources. Conversion is a deliberate
   barrier. New group commands declare typed member reads and organization writes;
   placement commands declare the actual placement dependencies. Conservatively
   preserve existing topology barriers rather than infer independence from labels.
4. **Whole-source classification.** Add the organization field to the positive
   authoring/capture/proof/transport inventories and exact DTO/schema catalogs.
   Preserve original metadata/recovery semantics separately. Current snapshot
   restoration remains a recovery mechanism, not native authority. Do not bypass
   ordinary node/byte/deadline limits to carry the new field.
5. **Purpose-aware references.** Frame, parent, joint, Join, flexible and driven
   owners keep existing placement IDs. UI/group-selection references use the
   organizational namespace. Existing deformation rows retain their exact
   numerical inputs; new authoring records selection provenance separately from
   the resolved placement context. Missing organizational references need explicit
   dependency repair/cascade, never resolution through a coincident placement ID.
6. **Exact numerical manifests.** `models.py` is in all three current numerical
   manifests. CPD and duplex manifests also include `deformation.py`,
   `design_geometry.py`, frame models and authoring classification; coating has a
   different executed closure. Audit the actual full-manifest delta per family.
   The preferred implementation changes schema/metadata classification only and
   leaves all kernels/data/runtime bytes unchanged. Compatibility edges must name
   exact old/current manifest hashes and their verified rationale; no wildcard,
   global repin, transitive acceptance or automatic policy-budget increase.
7. **Do not mislabel a broader delta.** A changed placement consumer, arm choice,
   transform order or native scope rule is not a schema-only transition. If it is
   required, stop the schema-only release, isolate the candidate and follow the
   [molecular authorization gate](../../../memory/feedback_geometry_change_authorization.md).
   Refactoring metadata alone does not authorize changed molecular positions.

The plan does not promise raw full-document JSON bytes remain identical after a
new schema is introduced. It requires exact legacy placement values/ordering,
unchanged saved-row semantics, honest full-document/digest schema handling and
independent reproduction under the explicitly admitted manifest transitions.
Existing persisted pins are never rewritten silently.

## Implementation batches and gates

**U7 implementation status:** the owned group/explicit-placement recorder and
bounded HTTP adapter now use the existing exact-candidate permit transaction.
Source capture is lock-owned; native preparation, validation and recovery encoding
are private and outside that lock. The final CAS preserves source-owned physical,
presentation, repair and historical recovery fields, with one undo/revision.
Explicit load/save/branch/undo/redo entry points support the staged mode; generic
mutation and unrelated permit paths still refuse it. The one host rollout flag
defaults false, has no request/environment/saved-document switch, and cannot
downgrade registered-only construction policy.

Organization-history recovery now admits all closed top-level inputs and requires
both full, non-evicted bodies before decoding. Input proof is independent. Rootless
organization loading preserves authored absence without inferring a recipe root.
Shared operation-body and serialization admission remove duplicated mechanics;
per-occurrence accounting prevents small shared object graphs from expanding past
the new path's serialization allowance. Full-source undo and scientific validation
costs remain unqualified, as do full-snapshot revert/edit preservation adapters.
The serialization allowance measures expanded structural work, not exact escaped
JSON bytes or peak process memory; encoded recovery retains its separate 8MB cap.
The fingerprint change from the load guard has twelve direct historical edges
under the unchanged policy bounds; previous policy bytes remain audited.

B/C are still partial: typed native selection and domain lineage, ordinary repair,
generated consumers and new-group movement remain. D and E are still open. See
[U7 evidence](validation_group_organization_recording.json); **18/38 complete,
20 remaining; +0 completed, +0 total; FH-18 checkpoint 5, task growth flagged**.

**U6 implementation status:** A is implemented privately. The exact schema is
`Design.group_organization: GroupOrganization | None`, with version 1 and typed
`PartGroup`/`GroupDomainRef` records in a distinct `part_group` namespace. Native
`group-organize`, `group-create`, `group-update` and `group-dissolve` v1 inputs
are top-level Snapshot rows. Conversion checks the complete ordered placement-ID
inventory, deriving organization from the independently rebuilt prefix without
pinning its poses. Output identities and command versions are protected during
input editing. Pose-only `cluster_op` can still target an explicit existing
placement in a private recipe; unadapted native operations refuse after conversion.

B/C have foundations, not completion: input editing/cold replay, typed reference
inventory, bounded diagnostics, selected-snapshot organization recovery, and
actual optimized/F0 seek are covered. Live transaction, remaining topology and
selection consumers, generated composition, full recovery-body admission and
new-group move semantics remain. D/E are open. Public canonical state ingress
and publication refuse active organization until those adapters are ready;
legacy `None` remains admitted. No UI switch, request flag or automatic loading
migration enables the new representation. See the [U6 evidence](validation_group_organization_representation.json).

The schema transition replaces nine historical-target policy entries with nine
explicit A/B/C→current entries, retaining support for every previously admitted
source generation. The exact prior policy is preserved separately for audit and
historical-target tests. Numerical kernels/data/runtime checks and policy bounds
are unchanged. Source model/contract deltas are enumerated per engine.

These are finite batches within **one FH-18 milestone**, not new completed slots.
Root owns sequencing and serialized validation. No prototype is enabled merely
because its pure tests pass.

| Batch | Concrete work and exit |
|---|---|
| A — representation and legacy proof | Freeze the organization schema, typed resource roles and native conversion inputs; add the pure converter/organizational builders. Assert placement records are unchanged, conversion is deterministic, old records/commands still replay, malformed/unknown regimes refuse, and full save/reload preserves both roles. Public authoring remains disabled. |
| B — complete native lifecycle | Implement create/regroup/membership/dissolve and explicit placement-owner editing through the existing transaction. Cover generated producers, native replay/edit/deletion, bounded dependencies, repair and cold proof. No blanket reconcile or hidden frame owner. Resolve the new-group move boundary explicitly before claiming the pose exit. |
| C — recovery and all consumers | Finish the inventory above, including frame continuation, driver/Join ownership, ordinary/optimized seek, same-ID lifetimes, undo/redo, import omission and rootless inference. Typed capture and proof must either fully carry the new regime or explicitly refuse it. No automatic legacy fallback once native work begins. |
| D — user-visible integration | Add actual separate Group and Placement/Transform surfaces, with existing useful selection/style/pose controls. Wire group/deformation selection and placement gizmos to their correct namespaces; apply/cancel and error handling retain source/revision/session guarantees. No hidden transforms, stale-index selection or canonical preview writes. |
| E — qualify and enable | Run the finite correctness/parity matrix below and the required serialized regressions. Confirm schema/pin transitions and dependency review; enable only after every consumer is accounted for. Integrated desktop/latency work remains the already allocated FH-27 exit, but any unexercised app path/gate stays stated rather than being called user-ready. |

Checkpoint 3 may close the two auxiliary paths without closing these batches.
That is task growth to report, not permission to add endless refusal subsets.
The next substantive delivery should be the complete conversion → posed dissolve
→ regroup vertical path, followed by the remaining matrix—not another isolated
identity-only admission expansion.

### Finite B/C native-consumer adapter order

The consumer audit distinguishes retaining the organization wrapper from retaining
what its domain selectors mean. Most native builders use `copy_with`, but a sweep
can prepend a domain while preserving the strand ID (`core/sweep.py::_join_sources`),
and nick/ligation/crossover routing can split, merge or reorder domains. A saved
ordinal may then select another domain while still passing structural validation.
`cluster_reconcile` repairs placement membership only; its direction-independent,
single-winner overlap rule is not suitable for overlapping organizational groups.
The unused strand-rename/domain-origin/deletion report fields were removed in
U9 after a repository-wide caller audit; they never supplied ancestry.
Pending-ligation retry can change topology after that reconciliation.

| Priority / consumer | Required adapter and finite exit |
|---|---|
| Typed selection boundary | Resolve `part_group` separately from numerical `cluster`, including equal string IDs across the namespaces. Share organization-to-native membership resolution across authoring, preview and replay. Never pass organization IDs into `resolve_cluster_scope`: unknown IDs are dropped and an all-missing selection becomes unscoped. Preserve `DeformationOp.cluster_ids` as placement/fitting context. |
| Explicit placement pose; bend/twist | Pose-only `cluster_op` already preserves the organization wrapper. The native deformation overlay also carries it without changing placements; qualify explicit primitive targets and intentional placement selectors first. Organizational selection needs the resolver above, with unchanged frozen-target editing semantics and an explicit dependency policy. |
| Loop/skip, sequence and whole-helix routing | Leaf builders retain existing member identities, but qualify the complete native executor, including reconciliation and retry. Whole-helix groups may remain unchanged while their helix IDs survive; deletion or unresolved ownership changes must refuse or use an explicit membership edit. |
| Extrude/continuation/sweep | Keep native lattice-frame, source-helix and ordered-placement inheritance exactly. New numerical placement owners must not recreate dissolved organizational groups. State any new-group membership addition as explicit authoring input. Domain references need lineage handling even when only a sweep continuation prepends a domain. `bundle-create` remains a replacement/root operation, not an append after conversion. |
| Domain-based FineRouting | Add a shared organization-only membership adapter after all native postprocessing, using command-specific split/merge/prepend/resize lineage. Preserve overlapping and opposite-direction selections independently. Refuse ambiguous lineage rather than infer nearest overlap; do not modify the existing placement reconciliation algorithm. Cover nick→ligation, resize inline-tail split/merge, sweep prepend and pending retry. |
| Ordinary linear/circular patterns | U15 copies declared group metadata through actual extraction ancestry and isolated input replay. Geometry still uses explicit whole-helix placements; qualification remains open. |
| Legacy grouping, generated producers and Join | Keep combined placement/group mutations blocked until each producer emits the separate roles deliberately. Do not mechanically replace `cluster_create` or placement membership writes with organizational commands. |

Use bounded membership indexes once per command, not per-nucleotide scans or a
full `Design` roundtrip on ordinary edits. Native parity, cold replay, upstream
editing and exact response ownership remain the exits; this audit adds no
milestone credit or performance qualification. Newly regrouped sets still need
the explicit move interpretation above: the current frontend's first-matching
placement lookup can move outsiders or only part of a group. Visible **Edit
Placement** is valid; arbitrary **Move Group** is not established by conversion
or dissolution parity.

### U8: named selection and final-entity lineage contract

New `targets: [{kind: "part_group", id: ...}]` retain named selection provenance.
The closed mixed grammar resolves on the owned native prefix into existing
`target_ranges` and `affected_helix_ids`; `cluster_ids` remains independently
authored numerical placement/fitting context. Equal text IDs never alias the
namespaces. Domain members take precedence over helix labels. Existing legacy
targets keep their native grammar and saved meaning. Later topology or group
edits do not refresh an existing operation's frozen ranges; editing an upstream
feature and replaying that deformation resolves its named inputs again.

Missing named groups are structural/reference errors. Group dissolution checks
bounded live deformation consumers and refuses with their typed paths; historical
rows refer to their own prefixes and are not counted as live incoming owners.
The ordinary preview/editor and comparison DTOs still need organization adapters;
historical frozen range domain addresses must not be mistaken for live membership.
The existing loop/skip planner consumes whole helices, so partial/directional named
scopes refuse before planning. No post-filtering or molecular formula change.

The lineage contract is **whole final entities at each registered command
boundary**, after placement reconciliation and pending-ligation retry:

- Split: every descendant retains every ancestor group's membership.
- Actual domain coalescence: each group containing any contributor selects the
  whole merged domain. This can broaden membership; it is not an exact material mask.
- Strand concatenation: separate domains keep their own ancestry. A newly swept
  domain on a new helix does not inherit membership through a surviving strand ID.
- Last selected-domain deletion: retain the empty group and clear both selector
  lists, preventing accidental expansion to whole-helix selection.
- Whole-helix groups retain surviving explicit IDs; fresh helices are not inferred
  members. Group order, identity and style remain unchanged.

The first qualified set is exactly `nick`, `nick-batch`, `ligate`,
`forced-ligation-create`, `forced-ligation-delete`, `forced-ligation-delete-batch`,
`crossover-delete`, `crossover-delete-batch`, `strand-delete`, `strand-delete-batch`,
`domain-delete`, `sweep`, `loop-skip-insert`, `assign-staple-sequences`.
Their reviewed effects conserve/delete directional material, except separate new
sweep helices. Bounded directional interval joins therefore establish ancestry;
same-direction overlapping occupancy, gaps or undeclared relocation/new material
refuse. No proximity guess, ordinal identity, object identity or per-base expansion.
This does not qualify resize/shift, crossover creation/movement, extrusion,
automatic rerouting, all loop/sequence tools or ordinary live publication.

Fine Routing stores an optional complete organization replacement in both
modified PRE and POST. Ordinary and composed recovery require the exact recorded
baseline even in defensive mode; a missing key on both sides keeps legacy behavior.
Inputs and decoded wrapper construction keep 30k-node/2MB admission. Existing gzip
inflation/JSON allocation is not bounded by that new metadata check. Native proof
never consumes these recovery bodies. Snapshot-only group commands remain top-level.

The helper bounds source/output metadata, relation edges and emitted memberships
across overlapping groups. Legacy absent organization adds no topology walk.
No native numerical manifests changed. The small isolated timing probe and full
focused evidence are in [U8 validation](validation_group_organization_consumers.json);
they do not establish desktop latency or heap limits for the complete transaction.

Onshape exposes configurable split/merge and partial-dependency tracking in its
[FeatureScript library](https://cad.onshape.com/FsDoc/library.html), and warns that
upstream edits may change selection cardinality in its
[feature UI guidance](https://cad.onshape.com/FsDoc/uispec.html). SOLIDWORKS provides
[model-associated persistent references](https://help.solidworks.com/2025/English/api/sldworksapiprogguide/overview/Persistent_Reference_IDs.htm).
These support explicit entity tracking rather than ordinal reuse. The whole-final-
entity and mixed-merge policy above is NADOC's chosen contract, not a universal
CAD behavior inferred from those sources.

### U9: extrusion and crossover correspondence

The qualified set adds `extrude-segment`, `circle-segment`,
`extrude-continuation`, `extrude-deformed-continuation`, `extrude-frame`,
`crossover-place`, `crossover-place-batch`, `crossover-move` and
`crossover-move-batch` (23 total). This is private native qualification only;
ordinary publication/preview and generated scopes remain closed.

Four extrusion families permit fresh helices while conserving old directional
coverage exactly. Ordinary continuation additionally permits growth and separate
new intervals on old helices, requiring every old interval and helix to survive.
An entirely new domain has no ancestor; a coalesced old-plus-extension domain is
selected as a whole. Frame, placement, cell proximity and strand ownership never
implicitly add organizational members. Native algorithms and placement inputs
remain unchanged across forward/backward, detached/in-place, mixed-cell, posed,
deformed, independent-frame and source-frame branches.

Crossover placement conserves directional material. Moves first prepare bounded
scalar domain/crossover receipts, resolving each selected adjacent pair uniquely.
Before reconciliation/retry, raw native output must retain the expected strand
identities/order, domain metadata and exact requested endpoints. Each source
domain is transported once to its actual final interval, including a batch moving
both ends to a disjoint interval; then common final-output ancestry resolves
survivors after retry. A move plan cannot skip this intermediate validation.
No original model objects or geometry arrays are retained in those receipts.

Duplicate/ambiguous selectors, inverted moved endpoints, overlapping output and
undeclared correspondence refuse. Existing native growth reconstructs helices
without some authored fields (ISSUE-108). Affected metadata-bearing helices whose
source/final domain envelope exceeds the stored extent remain unqualified and
refuse before native work. The envelope also covers native batch evaluation with
each original opposite endpoint. This preserves legacy behavior and states the
limitation without changing scientific output. Native growth must be corrected
and qualified separately before removing this boundary.

The next native pair is resize/domain-shift. Their internal inline-tail merge and
re-split must retain contributor segments rather than falsely coalescing them;
full tail removal must leave no descendants. Use passive observations at actual
native replacements, not a second implementation of terminal-branch arithmetic.
Any pinned-source instrumentation needs an explicit reviewed compatibility
transition; it must not be mislabeled a schema-only change.

[U9 evidence](validation_group_geometry_lineage.json) records 752 focused passes,
complete native model/geometry/axis parity, input-only reconstruction and the
timing limits. Four unused `MutationReport` fields and misleading docs were pruned;
the three used placement hints and all reconciliation calculations are retained.
This is FH-18 checkpoint 7, still flagged for growth; the five original batches
and full exit stand. No additional milestone credit, denominator change, public
enablement or desktop performance claim.

### U10: passive resize/domain-shift contributors

`strand-end-resize` and `domain-shift` bring the private qualified set to 25.
A small invocation-owned observer receives actual native endpoint replacements,
translations and inline-tail merge/split events. It never supplies geometry or
chooses native branches. Legacy calls construct no observer. The prepared source
and final receipts contain only immutable scalar identities/intervals; no Design,
Domain, geometry array or global trace is retained.

Temporary inline normalization retains piecewise original contributors. Growth
inherits the contributor at the edited endpoint; shrink clips removed material.
An inverted intermediate tail has no material but can retain its endpoint owner
if the same terminal regrows before normalization in the same invocation. Once
normalization removes it, later commands cannot revive the empty group. Native
normalization gaps have no invented ancestor. The final whole-domain rule still
applies to surviving contributors; temporary internal merging alone is not an
authored union. Domain translation carries its actual contributors even when
addresses become disjoint or exchange positions.

The raw observer receipt validates exact strand/domain identities and descriptors
before reconciliation/retry. Final output must conserve all observed directional
material (keys and interval coverage), separately from sparse contributor labels.
Missing/foreign/reused observations, ambiguous occupancy, final inversions and
budget overflow refuse without mutating the source. Existing node/byte/edge caps
also bound cumulative list shifts and contributor work; no per-base expansion.
The native molecular calculations, placements and branch predicates are unchanged.

`lattice.py` participates in CPD/duplex manifests. The disclosed transition is
`native-domain-lineage-v1`, explicitly passive instrumentation rather than a
schema-only change. Five captured generations per affected family have direct
exact edges to current manifests; coating's four policy entries are unchanged.
All prior policy bytes remain in the audit, stored pins are preserved, and the
16-entry/16KiB policy bounds remain (14 entries/14,216 bytes). Worker controls
verify the same installed calculations under current and historical pins; they
are not a historical-binary equivalence oracle.

[U10 evidence](validation_group_resize_lineage.json) records native model/geometry/
axis parity, cold input proof with poisoned recovery, upstream bundle edits with
named bend/twist consumers, ordinary/composed child seek and private undo restore.
The topology-only native-residue fixtures have no atomistic validity claim.
No public Ctrl-Z/app qualification or rollout is implied. Metadata-only shift
tracking at 500 domains measured 40.771 ms median and 88.415 ms maximum; complete
transaction/display acceptance remains open. FH-18 is still open at checkpoint 8,
with the same five batches and fixed exit: **18/38; +0 completed, +0 total**.

### U11: named selection preview, repair and historical display

The existing private bend/twist editor admits the four organization commands in
its independently rebuilt prefix. Pure named selectors can change through a
`targets` patch; mixed/primitive scopes stay protected. The native builder freezes
the resulting intervals and affected helices. Numerical `cluster_ids` remain
unchanged placement context. Controls-only evaluation also returns the resolved
scope, so private plane guides follow the same result without a client resolver.

Repair exposes only existing `targets[i].id` inputs of coherent typed bend/twist
rows. Its picker builds one bounded prefix index, excluding invalid, empty or
already-selected groups. The saved proposal uses exact old-value expectations;
the normal repair evaluator rebuilds the complete candidate from inputs. A closed
native `Direction` capture omission is fixed without admitting arbitrary enums.

The owned preview Apply and saved-repair commit use the same opaque publication
registry under a distinct `organized_recipe_v1` scope and `owned_recipe_rebuild`
evidence. Their exact source/session/revision/policy/request/candidate checks,
expiry, cancellation, failure rollback and one undo remain. Generic writes,
serialized authority claims and unrelated permits remain refused. The host-only
organization switch and public preview HTTP gate both remain disabled.

DNA comparison component v3 and preview component/envelope v2 carry closed group
metadata and interpret frozen strand/domain addresses as historical provenance.
Native geometry consumes the helix/direction/interval; current topology members,
axes and named group dependencies remain live. No prior operation is re-resolved
against later membership. Scoped native axis samples are preserved in both views.
Organization counts share the existing 512-selector limit, separately from the
64 numerical-operation allowance. Capture preflight does no group serialization;
full scalar schema validation occurs on bounded owned input outside the lock.

[U11 evidence](validation_named_deformation_lifecycle.json) records pure/native,
HTTP/job/permit and Python-to-actual-Three.js parity checks. New named controls
preserve placement context and update private guides even with geometry hidden.
Existing renderer color authority is unchanged; visible Groups/Placements remains
separate D work. Actual desktop interaction and complete latency acceptance remain
MV-48/FH-27. Tiny named feedback medians are 2.019 ms controls-only and 20.770 ms
with geometry; 500 empty-group preflight is 4.197 ms median versus 0.019 ms legacy.
These omit HTTP/publication/rendering and do not qualify desktop latency.
Remaining generated consumers, new-group movement and rollout are
still within the fixed FH-18 exit. **Checkpoint 9; task growth flagged;
18/38 complete; +0 completed, +0 total.**

## Finite acceptance matrix

| Case family | Required invariant / evidence |
|---|---|
| Whole-helix pose | Translation, arbitrary normalized rotation and nonzero pivot survive conversion/dissolve/regroup with identical placement input and native output. Empty frame owners remain explicit. |
| Overlap and order | Multiple overlapping owners retain original array order; domain/whole-helix ordering and selected/unselected members remain exact. No reordering based on group UI position. |
| Local/domain ownership | Partial domains, child/parent-local transforms and duplex-driven ownership retain their exact masks, ancestry and legacy overlay gating. |
| Deformation context | Bend, twist, sweep, endpoint fitting, scoped segment axes, loop copies and extra/extended bases preserve the original frame selection and output. Organization changes do not recompute old affected IDs. |
| Structural continuation | Lattice owner, subsequent cell/extrusion/continuation, joints, both Join attachments and flexible endpoints still resolve. New topology inherits the right placement independently of organizational membership. |
| Complete projections | Native object/array geometry, axes/normals and representative atomistic/export inputs agree. No authored axes, bases, strands or physical positions are baked or rewritten. |
| History and persistence | One transaction/revision/undo per operation; save/reload, input-only cold replay, upstream edit, explicit dependency failure, undo/redo and ordinary/optimized/F0 seek preserve role and lifetime. Cancel/failure changes neither source nor history. |
| New group movement | Existing visible placements remain editable. A newly regrouped member set has an explicit, tested ownership interpretation; no appended transform or owner splitting is assumed equivalent. Any required scientific change uses the separate authorization process. |
| Desktop and bounds | Actual Group/Transform selection and editing, empty/default groups, deform controls, stale/doc-change paths and useful failures. Report metadata, snapshot/undo, geometry and response costs separately; use natural GC, unchanged bounds and no retry-based success claim. App/latency acceptance stays linked to FH-27. |

Geometry parity is a representation invariant, not a new tolerance calibration.
Use the existing native outputs and exact unchanged pose inputs as oracles; retain
current numerical tolerances only where the existing oracle already requires
them. Any unexpected displacement is investigated before promotion. Never
regenerate molecular goldens or approve a placement from aggregate counts alone.
Assemblies and machine-specific VR validation remain outside this agreed scope.

## Primary CAD precedent and its limit

Onshape documents that composite creation does not change selected bodies and
that composites never own Mate connectors; individual parts do. Its
[composite-part workflow](https://cad.onshape.com/help/Content/PartStudio/composite_part.htm)
therefore separates organizational lifetime from body/frame ownership. The
[FeatureScript library](https://cad.onshape.com/FsDoc/library.html) separates
`opModifyCompositePart` membership from `opTransform`, while the
[Transform documentation](https://cad.onshape.com/help/Content/PartStudio/transform.htm)
requires selecting a connector/axis when it must move with a part.

Those are workflow precedents, reviewed by the CAD research agent. The proposed
NADOC schema and preservation contract are our architectural inference. The
sources do not establish that changing an earlier grouping feature preserves all
downstream world positions, nor do they supply a migration for NADOC's implicit
deformation frames. The finite native matrix above remains necessary.


### U12: private Groups/Placements interface and explicit placement Apply

The sidebar now separates Groups from ordered Placements. Typed group selection
runs through scene picking, highlights, labels, framing and atom/surface selection.
Both sidebar and context-menu edits use the revision-checked organization host;
unsupported mixed membership refuses. Browser-only group actions are suppressed
for active organized parts, with legacy/assembly behavior retained. Shared
membership/display/commit modules replace duplicated logic; main.js loses 14 lines.

Group color and opacity use exact domains when supplied; helix IDs are contextual
in that case. Extension display follows its actual terminal-domain ownership.
Overlapping opacity keeps the minimum. Hide/Show expands current members to the
existing base-address visibility state. This is a scoped current-member action without a new hidden-group schema: hidden_cluster_ids
continues to mean placements, and the UI says “current members.” It does not
promise that later added group members inherit an earlier hide action.
The earlier D requirement for persistent group-identity visibility remains open;
this adapter is not its completion or a quiet replacement of that exit.

Existing-placement Apply now calls one bounded multi-placement transaction
(maximum 64 unique explicit IDs), skips no-op rows, counts nested Fine Routing
children against the unchanged history cap, and publishes one undo/revision.
The response embeds matching complete native geometry. The client acknowledges
only adopted source-bound responses; the move tool avoids a second transform.
Null/failed/stale responses retain unaccepted local movement. Legacy sequential
publication reports partial acceptance instead of clearing the entire preview.
These paths use unchanged native placement arithmetic and ordered ownership.

This does **not** close D: ordinary new Bend/Twist still needs an isolated owned
creation adapter. Active organization refuses that legacy launcher before it
writes preview state. Earlier placement editing similarly refuses the obsolete
edit-in-place branch until its owned history editor is integrated. Private named
history preview/repair already works, but is not ordinary creation parity.
Generated consumers and arbitrary new-group motion/frame/extension semantics
remain the original B/C obligations. No v3 compiler or new placement semantics
were implemented here; no numerical source, pin, model or golden changed.

The next bounded delivery is the ordinary named-deformation creation adapter,
using the existing private preview lifecycle and native target resolution. Then
resolve new-group motion ownership and generated compatibility, with research
before uncertain semantics. Keep the five batches/fixed exit and do not move
unfinished compatibility to parked FH-36. Public gates remain false.

No history replay runs in a frame callback. Metadata-only group changes avoid
atomistic geometry fetch; membership indexes use immutable snapshots. Full
structural redraw fallback preserves original domain ordinals, but needs profiling.
Whole undo copying under lock, larger-design style/selection costs and actual
request/render tails remain qualification debt, alongside desktop acceptance.
[U12 evidence](validation_group_placement_ui.json) retains software outcomes,
observed failures, scope limits and cleanup. **18/38 complete; +0/+0; FH-18
checkpoint 10**, still flagged for task growth.


## U13 ordinary Bend/Twist creation — FH-18 checkpoint 11

The private ordinary creation workflow now shares the existing history preview
host, fixed native prefix, DTO controls, scene layer, popup and publication
receipt. The separate create Prepare request fixes future feature identity,
server operation identity, family, source revision and typed selection; it
returns before geometry without an invented operation or candidate. The first
complete planes/parameters draft must evaluate before Apply. Evaluate reuses
the owned prefix; Apply freshly proves the entire source recipe, rebuilds its
recovery and appends one native typed row with the unchanged publication guard.

Toolbar selections preserve mixed group/placement/strand/domain intent. End-menu
clicks supply plane hints with the existing whole/placement scope, not a new
single-domain interpretation. Only explicit toolbar placement selectors become
numerical context; end menus retain native active/single-placement defaults. Named/mixed selection Change/Clear cancels and prepares anew; explicit
null-target placement picker edits use native scope on the same prefix. Existing
angle/radius/direction, twist units/handedness, polymer count, plane input/drag,
preview toggle, failed Apply, Cancel and unknown-publication recovery are retained.

The shared prefix admission and common owner initialization remove duplicate
mechanics. No second preview framework, native formula or model schema was
introduced. Existing mutating authoring is still live behind the disabled
replacement gates, so it is not yet dead code eligible for removal. Historical
edit Prepare remains a separate closed variant. Same-ID reset during held
Prepare now retires the local opening immediately; late responses cannot replace
or tear down a newer tool (ISSUE-112).

This follows the observable create/edit preview and accept/cancel workflow in
[Onshape feature dialogs](https://cad.onshape.com/help/Content/Home/dialogs.htm)
and its [documented close action](https://onshape-public.github.io/docs/app-dev/messages/element-right-panel/#closefeaturedialog).
The fixed-prefix lease and independent append proof are NADOC engineering
choices, not claims about vendor internals. Named selection and numerical
placement remain distinct, consistent with treating saved selections as references
rather than new transforms; no scientific placement behavior is inferred.

[U13 evidence](validation_deformation_creation.json) distinguishes software
checks from unperformed desktop/latency checks. Public gates remain false.
Persistent group-identity visibility, arbitrary new-group movement/frame/extension
semantics, generated compatibility and qualification remain required in the same
five batches. No unfinished core exit moves to parked assets. **18/38 complete;
20 remaining (11 core, 9 parked); +0 completed, +0 total.** Eleven checkpoints on
FH-18 keep the task-growth flag active; this workflow earns no separate milestone.


## U14 persistent group visibility — FH-18 checkpoint 12

The U12 current-member-only hide contract is superseded for new named-group
Hide actions. `VisibilityState.hidden_part_group_ids` is a separate, default-empty
presentation list (at most 2,000 exact IDs, each 1–512 characters). It neither
changes `hidden_cluster_ids` nor infers intent from old hidden bases. Current
organization membership resolves the mask once when membership/geometry changes;
new members, loop copies and terminal extensions follow the hidden group. Removed
members lose only that group's mask. Missing IDs are dormant across dissolve and
history navigation, permitting undo/reload restoration without guessing an owner.
Newly created groups receive fresh IDs; equal text in the placement namespace is
irrelevant. This metadata is not a feature dependency or geometry suppression.

Hide rules combine by union, then explicit shown base addresses take precedence.
Show removes the selected group's rule and shows its current members using that
existing exception mechanism; it never deletes another group's rule. Empty hidden
groups retain their intent until members arrive. Show All clears every mask.
Local visibility undo/redo and owned server undo retain their existing roles:
publication has one server undo/revision but no feature row. Legacy three-list
requests remain accepted as complete replacements with an empty named list.
The new field is omitted only when empty, preserving prior canonical serialized
bytes and strict recovery; nonempty identity masks serialize explicitly. The
strict empty-state preservation digest keeps its original three-field encoding
after validating that the new list is empty. Unknown/missing-old-field decoding
still refuses. This uses the installed, documented [Pydantic field exclusion](https://pydantic.dev/docs/validation/2.12/concepts/serialization/)
mechanism; there is no general normalization exception.
The exact capture/preservation catalogs carry the new field; strict empty-state
batch admission still refuses nonempty presentation rather than discarding it.

Ordinary Save, Save As, native download and file-handle writes drain presentation
saves before reading the canonical design. They bind to the original document
incarnation, including same-ID reset; late replies cannot start a replacement
write, mirror, download or change the displayed path. Already dispatched server
writes or committed file closes are not retroactively cancelled. Existing
close-session draining and autosave dispatch are unchanged.

Repeated strand queries use the effective mask already prepared by the visibility
controller. Saved Join decorations use the same endpoint visibility callback as
Join selection and toggle existing line visibility without rebuilding geometry.
Native Join candidate generation/calculations are unchanged; organized Join
publication is still outside the admitted core matrix. No new per-frame history
walk, proof or molecular work is introduced. Larger-design interaction/memory
qualification remains open and is not replaced by scan-count tests.

### Explicit numerical compatibility capacity review

The new display field changes the full shared `models.py` source hash, although
no molecular input or calculation changes. At source `79c7bdee`, installed policy
contained 14 exact edges in 14,216 bytes. Preserving every admitted historical pin
and the three then-current pins requires **17 direct edges**; the old 16-entry
limit cannot represent this complete set. Deliberately raise only the host-policy
capacity to **32 entries and 32 KiB**. Exact-boundary and one-over tests cover both.
The diagnostic collector remains limited to three transitions; runtime/template checks, solver
settings and publication/capture/time/geometry limits do not change. Stored
authored pins are not rewritten; new authoring uses the current manifest hash.

The before manifests and prior policy are retained byte-exact. Every new edge
names one engine, one authored hash and one full current manifest. Actual newest
manifest deltas are only `models.py` and the compatibility helper's documented
capacity change. All older source/data/runtime distinctions remain explicit;
unknown pins, changed files/data and transitive-only chains refuse. No future
schema change is automatically authorized by spare capacity. Native checks use
the installed kernels in independent workers; they are not historical-binary
numerical equivalence evidence. See [U14 evidence](validation_group_visibility.json).

### Remaining movement decision and fixed matrix

Official [Onshape Transform](https://cad.onshape.com/help/Content/PartStudio/transform.htm)
requires explicit moved parts and transformation references. [SOLIDWORKS Move/Copy
Body](https://help.solidworks.com/2023/english/SolidWorks/sldworks/HIDD_DVE_FEAT_MOVE_SURF.htm)
moves selected bodies together while other bodies remain fixed. These support
separate **Edit placement** and **Move selected members** actions with explicit
scope/pivot/frame. They do not define partial DNA domains, first-arm ownership or
extension composition. The distinction between [SOLIDWORKS display states and
configurations](https://help.solidworks.com/2021/english/SolidWorks/sldworks/c_display_states_configurations_parts.htm)
also supports keeping visibility separate from physical changes/suppression.
Dynamic group membership and dormant IDs above are NADOC decisions, not claims
about vendor internals.

Before implementing arbitrary new-group motion, freeze evidence for:

| Case | Required result |
|---|---|
| Complete existing owner vs new selected set | Existing-owner edit stays explicit; new motion records its own selected scope. |
| Partial, overlapping/domain and multiple-owner selection | Precisely selected output moves; unselected output is unchanged. No first-overlap fallback. |
| Local/world axes and pivot/reference frame | Requested frame is explicit and survives replay/edit. |
| Existing Bend/Twist and parent/driver constraints | Ordered native composition and endpoint-fit context stay correct. |
| Terminal extensions and lattice continuation | No implicit first-owner reassignment or hidden carrier. |
| Membership/reference changes | Prefix-relative target resolution; missing references diagnose and permit reviewed repair. |
| Undo, save/reload, cold proof | Same authored inputs independently regenerate the complete design. |

[Onshape repair guidance](https://cad.onshape.com/help/Content/Document/repairing.htm)
supports explicit missing-reference replacement against healthy historical
geometry. It does not justify choosing a different numerical owner silently.
Any required molecular change still needs isolated A/B evidence and authorization.
Generated core compatibility and full qualification remain existing FH-18 exits.
**18/38 complete; +0 completed, +0 total; 20 remaining (11 core, 9 parked).**
U14 is the twelfth FH-18 checkpoint; its growth flag and original five batches remain.

## U15 ordinary patterns — FH-18 checkpoint 13

The connected workflow is conversion → explicit placement selection → linear or
circular pattern → copied named groups → edit/regroup → undo/save/reload/cold
replay. Geometry still comes from the native whole-helix placement contract.
Named partial-domain groups are metadata selections, not synthetic placements.
The complete existing linear 2D/custom/negative-spacing and circular axis/pivot
controls remain; unsupported native source shapes retain explicit refusals.

Recorded `_organization_copy: {version: 1, group_ids: [...]}` is mandatory on an
organized source; an empty list explicitly selects none. It cannot implicitly
convert a legacy source. UI choices default to intersecting groups and include
required named targets of copied deformations, even currently empty groups.
Copies retain name/style and actual extracted members, with fresh stable IDs
per feature seed/source/instance. They are not defaults or automatic inference.
Original memberships and ordered numerical placements remain unchanged.

The one native extraction supplies its actual domain split map. Group references
project through that map and the instance's helix/strand IDs. Primitive frozen
deformation strand/domain selectors retain their historical provenance uniformly;
only geometric helix ownership and declared live group roles relocate. Current
ordinal coincidence never rebinds a historical selector. Copy remapping also
preserves Sweep consumed-operation IDs, preventing earlier copied
bends/twists from being reapplied. Per-occurrence accounting includes aliased
target/range/vector/header lists; small Python graphs cannot hide expanded JSON.
Postprocessing lineage captures the raw copied result before ordinary reconciliation/retry, retaining
both source and copied groups. New crossovers retain the native rule excluding
them from pending-ligation retry. No numerical algorithm or golden is changed.

Ordinary organized append/edit uses one bounded capture, the existing isolated
worker/supervisor/shared slot, full source input proof, and one exact-source
publication/undo. Generic job append cannot manufacture this authority. The
ordinary five-second budget covers capture, proof and publication, not the later
HTTP geometry formatting cost; long prefixes can refuse with a time limit.
Native history edits regenerate even with evicted/poisoned recovery. Candidate
JSON authoring/recipe parity is shared with existing job commit rather than
maintained as a second decoder. Source/session/revision/policy/cancel checks stay
at publication. No per-frame proof, unbounded queue or new worker lifecycle.

Pattern responses carry exact-candidate current and straight geometry for one
client adoption. This avoids a second unbound geometry fetch and the partial
response mismatch for count-preserving history edits. Requests retain the source
shown when the tool opened, including document incarnation and feature identity.
Reset retires old previews; refusal keeps the draft. A dispatched server commit
cannot be recalled by closing/resetting a local dialog. Full response/lock/heap
latency and desktop behavior remain qualification work, not inferred from tests.

[Onshape linear patterns](https://cad.onshape.com/help/Content/PartStudio/linear_pattern.htm)
and [FeatureScript pattern instance queries](https://cad.onshape.com/FsDoc/library.html)
support explicit source and instance identities and distinguishing copied results
from reapplied features. [SOLIDWORKS selection sets](https://help.solidworks.com/2020/english/SolidWorks/sldworks/c_selection_sets.htm)
and [Onshape composite parts](https://cad.onshape.com/help/Content/PartStudio/composite_part.htm)
support separating organization from transformation. Clipped groups, visible fresh
copies and historical range provenance above are NADOC decisions, not claims
about vendor internals. Missing references remain explicit repair inputs.

**Containment stays fixed:** arbitrary new-group movement/frame/extension,
generated core consumers and qualification still close the original B–E batches.
The movement audit found first-owner deformation-arm selection, ordered overlapping
pose composition, separately evaluated terminal extensions and driver/endpoint
frames; assigning a new hidden carrier would change those semantics. Its finite
matrix above remains required. Any molecular placement change needs the separate
isolated A/B authorization path. Ordinary patterns do not close that exit.
U15 adds no milestone or denominator; the existing task-growth flag remains.
See [software evidence](validation_group_patterns.json) and MV-48 for acceptance.

## Post-U23 remaining member movement — finite completion sequence

This is a plan against `f225fe59`, not implemented movement or new validation
evidence. The ledger remains **20/38 complete**, with 18 remaining (9 core,
9 parked). FH-18 has 13 engineering checkpoints and FH-23 has 6; both task-growth
flags remain. The five original batches and their full exits are unchanged.
Numerical gesture qualification and organized extension upserts are connected
work already under way; neither substitutes for arbitrary new-group movement.
The steps below earn no additional milestone, denominator, or completion credit.

### What exists, and the missing operation

The separate organization model, prefix-relative named deformation selection,
membership lineage, explicit placement transactions, private native transform
renderer, complete linked-owner history edits, and cancellable numerical
Prepare/Apply machinery are reusable. They do not implement **Move selected
members**. `translate_rotate_tool.js` still explicitly refuses a named-group
selection; `placement-poses` validates and edits pre-existing placement owners.
Its `selected_cluster_ids` cannot express a new partial or overlapping material
selection. Removing the UI guard or finding an equal-text placement ID would
silently change the requested operation.

Keep two visible actions: **Edit placement** changes an existing numerical owner;
**Move selected members** authors a new feature referencing the selected named
groups. A group remains selection/style metadata. Movement must not add a hidden
backup group, modify unrelated owners' membership, bake displayed coordinates,
or expand the selection into one saved transform per residue.

[Onshape Query Variables](https://cad.onshape.com/help/Content/PartStudio/query_variable.htm)
provide an explicit named selection for downstream features, including Transform;
editing that selection updates downstream consumers. Its separate “Evaluate on
use” option distinguishes later reevaluation from the entities selected earlier.
[FeatureScript tracking](https://cad.onshape.com/FsDoc/library.html#makeRobustQueriesBatched-Context-Query-boolean)
also distinguishes identity tracking from following splits/merges. These support
an explicit reference contract, not a DNA placement algorithm. NADOC's proposed
rule is to resolve each referenced group on the move's **replay prefix**, retain
that named provenance, and record bounded resolved material ownership. Later
features must not retroactively widen an earlier move merely because a matching
text ID or domain ordinal remains present. Earlier membership edits do change
the later move when replay reaches it. Missing/empty selected scope must give an
actionable diagnostic, never the legacy empty-list-means-all interpretation.

### Concrete consumer boundary

The following is the finite production inventory that prevents treating a new
ordinary `ClusterRigidTransform` as a complete movement implementation.

| Existing seam | Current behavior and required disposition |
|---|---|
| [part_group_selection.py](../../../backend/core/part_group_selection.py), [part_group_lineage.py](../../../backend/core/part_group_lineage.py) | Reuse bounded typed group lookup, domain precedence, exact union and observed topology ancestry. The current resolver describes deformation ranges; extra-base and terminal companion ownership still needs an explicit movement contract. No lookup in placement IDs for named groups. |
| [part_placement_pose_commands.py](../../../backend/api/part_placement_pose_commands.py), [placement_commit.js](../../../frontend/src/scene/placement_commit.js) | Complete absolute poses address existing owners with exact parent/driver bindings. Preserve this operation and its native owner-list replay order. A new member-motion feature needs its own typed input/output identity rather than pretending to be an existing owner edit. |
| [deformation.py](../../../backend/core/deformation.py): `_arm_filter_cluster`, `_apply_cluster_transforms_domain_aware` | First nondefault owner influences deformation-arm scope. Poses are partitioned child, whole-helix and domain ownership; a domain mask miss can use the legacy whole-helix fallback. New motion must not become an inferred arm/frame owner or use this fallback. Existing rows retain their exact semantics. |
| Same module: `_apply_clusters_to_seg_point`, `deformed_helix_axes` | Axis segments combine overlapping domain ownership. Moving only one direction/domain cannot silently move its unselected partner's frame or leave a misleading single shared axis. The candidate must represent the selected frame explicitly and show what downstream frame queries receive. |
| Same module: `deform_extended_arrays`, `deformed_frame_at_bp` | Out-of-span scaffold-loop material and continuation frame queries currently use a first matching placement in their respective paths. These are separate from `StrandExtension` tails; appending a placement does not make their composition complete. Preserve existing frame owners and expose an explicit continuation/reference-frame choice where the moved selection has multiple frames. |
| [design_geometry.py](../../../backend/core/design_geometry.py), [native_full_placement.py](../../../backend/core/native_full_placement.py), [atomistic.py](../../../backend/core/atomistic.py) | Canonical site frames, full/slab and atomistic poses must derive from one placement contract. Saved per-residue transforms run after cluster/deformation placement; inserting a new group pose before them is not generally the requested final-world delta. No bead fitting, phase changes or independently reconstructed atom frames. |
| `design_geometry._strand_extension_geometry`, bridge and flexible companion builders | StrandExtension tails use terminal frames from native arrays, already including cluster/deformation placement. Their anchor map is built before the later per-residue transform pass. Bridge/flexible geometry uses its own endpoint rules. Qualify each companion's exact ownership/order; do not rigidly transform a newly derived connector twice or claim all terminal paths already share one ordering. |
| [cluster_reconcile.py](../../../backend/core/cluster_reconcile.py) and actual extension publication/replay | Named-group lineage does not repair legacy placement membership. Saved extension-upsert v1 retains its single-winner reconciliation, ligation retry and barrier, and remains refused after conversion. Implemented v2 changes only extensions and bypasses both postprocessors; its owned ordinary transaction preserves ordered membership/poses, parent/driver and empty frame owners. This explicit version boundary does not solve arbitrary member motion. |
| [part_transform_inputs.py](../../../backend/api/part_transform_inputs.py), [part_deformation_preview_sessions.py](../../../backend/api/part_deformation_preview_sessions.py), [part_transform_preview_computation.py](../../../backend/api/part_transform_preview_computation.py), [transform_history_editor.js](../../../frontend/src/app/transform_history_editor.js) | Reuse strict inputs/references, fixed-prefix work, private display, numerical worker lane and exact-source publication. Add explicit creation/append and history roles to this owner; no second lease registry, automatic Apply retry, or live canonical preview. |

### Terminal-extension v2 boundary — implemented privately

The connected extension-only workflow is now implemented, as detailed in the
[ISSUE-130 section of the transform plan](transform_history_editor_plan.md#issue-130-extension-upsert-v2-integration--implemented-privately).
All five existing ordinary extension URLs use shared input/recording paths; the
organized path uses the bounded owned transaction and exact-source publication
permit, with v2 upserts and existing v1 deletes. V2 performs no placement
reconciliation or pending-ligation retry. Its dependency contract shares a
conservative extension-inventory read/write edge with delete, so different-ID
same-terminus delete/recreate is ordered without claiming a topology barrier or
per-terminus independence. Legacy v1 saved inputs, replay and barrier remain
unchanged; no automatic upgrade or numerical formula/pin change is implied.

[U25 evidence](validation_organized_extensions.json) records contract, placement-
preservation, transaction, HTTP and frontend results. The
organization rollout gate remains disabled. This is not arbitrary group movement:
terminal tails still use the existing native cluster/deformation anchor path,
and later per-residue transforms, out-of-span scaffold loops, continuation frames
and derived connector ordering retain the separate obligations below. No original
A–E/FH-18/FH-23 exit or completion count changes with this extension boundary.

### Proposed implementation sequence within A–E

1. **Close the movement contract and isolated evidence (A/C).** Keep the existing
   ordered placement authority; investigate a separately identified, visible
   member-motion role within it, rather than an ordinary inferred arm owner or a
   second pose array. This is a candidate representation, not an approved schema
   or production geometry change. Define typed named inputs, exact union once,
   resolved material ancestry, explicit pivot/frame, deterministic feature/output
   IDs and composition order relative to legacy owners and saved residue poses.
   Existing owner records, order, parent/driver roles and absence-of-new-role
   behavior must remain exact. Show the complete matrix below in an isolated
   current/candidate comparison before choosing the production representation.
   If the candidate cannot meet a row, report that concrete contradiction; do
   not replace the exit with identity-only or whole-owner-only support.
2. **Implement the authorized native command and all consumers together (B/C).**
   After the molecular gate, add the closed versioned command and typed placement
   role, bounded prefix resolution, shared source/reference/dependency inventories,
   structural checks, lineage, repair and independent replay. Update every
   affected consumer in the table with one explicit composition contract. Reuse
   native rigid-transform arithmetic; preserve physical state separation. Add
   exact manifest transitions for actual changed sources after review. A changed
   placement consumer is not a schema-only transition, even if constants and
   matrix arithmetic are unchanged. No old pins, locks or goldens are silently
   regenerated and no budget increases are implied.
3. **Connect create and historical edit through the existing owned host (B/D).**
   Creation fixes named source references and a future feature identity before
   private preview; edit uses the feature's owned prefix. Reuse the existing
   transform family/controller, native component projection and ordinary versus
   numerical work lanes. Controls expose translation, rotation, local/world
   frame and pivot; constrained movement must list every linked/fixed write
   explicitly. A named selection is not automatically a joint/driver owner.
   Apply independently proves/rebuilds the source and suffix, publishes once,
   and preserves unknown-result recovery. Cancel/reset/context change remains
   local plus exact-lease cancellation. Complete sidebar, context-menu and
   history entry points in the same connected workflow.
4. **Prove the full matrix, including downstream edits (C/E).** Use independent
   expected rigid-delta/native-frame oracles, unchanged-unselected-output checks,
   real native gestures and Python → browser → host Apply where applicable.
   Exercise poisoned/evicted recovery, upstream member edits, missing-reference
   repair, undo/reload and cold proof. Retain numerical source/policy/cancellation
   coverage, output bounds and same-ID document reset. Desktop/latency
   qualification remains explicit when Archive or the app cannot be exercised;
   unit/native checks cannot substitute for it.
5. **Close the original exits, then remove replaced paths (D/E).** Require the
   complete movement workflow and existing generated-core compatibility/
   qualification obligations before marking FH-18/FH-23 complete. Do not move
   unresolved core cases to parked NP/assembly/VR work. Prune superseded canonical
   mutation/selection heuristics only after all real callers use the qualified
   path; inactive rollout-gated legacy paths are not yet dead code.

### Required acceptance matrix

| Family | Exit evidence |
|---|---|
| Existing owner and a newly created group with identical members | Both visible actions work with explicit identities; no automatic conversion of one action into the other. Identity transform is a control, not the admission boundary. |
| Whole helices, one domain/direction, partial domains, overlapping/multiple groups | Exact selected union moves once, domain precedence is retained, and unselected material/owners remain unchanged. Equal-text group/placement IDs never alias. |
| Multiple posed owners, nonzero pivots, parent/child and repeated moves | Ordered composition is recorded and reproducible; no first-owner approximation, new hidden carrier, membership rewrite or double transform. |
| Bend/Twist/Sweep and prior residue/CPD/duplex poses | Selected native site/atom frames follow the demonstrated composition; prior deformation arm ownership is unchanged. Incompatible rigid-unit selections are explicit scientific decisions, not silently expanded selections. |
| Joint, tether, flexible/taut linker and duplex driver gestures | Native constraints produce the complete selected/linked/fixed-owner result. No dropped auxiliary pose, implicit propagation to unselected owners, or stolen driver/frame ownership. |
| StrandExtension, out-of-span scaffold loops, crossover insertions and derived bridges | Each actual endpoint/material rule is tested separately in full and atomistic output; moved terminal frames and untouched endpoints agree, with no stale tails or double-moved companions. |
| Shared axes, lattice frames and continuation after partial motion | Frame/axis ownership is explicit and reproducible; an ambiguous multi-frame section cannot silently return the old first-owner frame. Existing saved lattice owner references remain valid. |
| Upstream group edit, nick/ligation/split/merge, later fresh material, group dissolve | Replay resolves named references at the move's prefix; later ancestry is explicit. Stale ordinals do not retarget material. Live consumers block dissolve or enter explicit repair/cascade; no global fallback. |
| Creation/edit preview, Apply failure/cancel/expiry, numerical computation and unknown response | Private panes agree with accepted native output; active source is untouched until one guarded commit. Status recovery never republishes. Undo/reload/cold proof reproduces the complete authored result. |

Typed namespaces, exact union, stable IDs, prefix resolution and reuse of the
owned host are software decisions supported by the existing task. DNA polarity,
partial rigid-unit motion, incompatible endpoint constraints and a genuinely
ambiguous physical/frame interpretation require user review when encountered.
That review must follow [the molecular authorization rule](../../../memory/feedback_geometry_change_authorization.md):
isolated current/candidate/displacement views in one frame, highlighted relevant
atoms/bonds/rings and per-junction deltas, including representative 2HB and phase
coverage. No ordinary rendering, saved `.nadoc`, export or simulation can consume
the candidate before authorization. Producing this evidence is the next concrete
step if the native-role investigation requires changed molecular placement; a
prose-only request for permission is not a completed prerequisite.

The member-motion sequence and acceptance matrix above remain proposed, not
implemented. The separately identified extension-v2 boundary has
software validation evidence; neither it nor this appendix adds app
validation, rollout enablement or milestone completion.

### U26 — native ordering counterexamples and implementation boundary

The isolated experiments in
[test_part_member_motion_order.py](../../../tests/test_part_member_motion_order.py)
reject two proposed shortcuts using actual empty-root native 2HB histories,
nonzero pivots and noncommuting transforms. They change no production geometry.

| Experiment | Observed result | Consequence |
|---|---|---|
| Saved nucleotide pose N, then a newly appended ordinary domain placement M | Native Full backbone differs from M applied to the displayed nucleotide by 6.935091655 nm forward / 6.336679237 nm reverse. The old residue pose still runs after the new owner. | List insertion order is not chronological world-motion order. An ordinary placement owner cannot implement the selected-material action. |
| Saved N, proposed M, then native composed world translation D | A final M pass yields M·D·N rather than D·M·N. The independently predicted difference is [1,-5,0] nm (norm 5.099019514) for backbone, base and slab points in both directions. | A new final pass alone is insufficient. Later compose, replacement and reset need explicit frame/event semantics. |
| Native sequence tail created after its terminal's existing whole-helix placement | Native tail points already equal the moved construction-frame result. Reapplying M displaces them another 3.396175550–4.056438217 nm. | Exclusion from an earlier target receipt does not imply construction in the original world frame. Material birth and construction-frame provenance are separate. |

The companion experiment
[test_part_motion_native_characterization.py](../../../tests/test_part_motion_native_characterization.py)
originally reproduced **ISSUE-135**: a terminal-nucleotide pose moved tail atoms
while Full tails stayed fixed. The user has now resolved the contract: unselected
tails stay fixed in both representations. Its four cases are now locality acceptance
tests across both ends and directions, including rotation. The broader
[selection-locality investigation](selection_locality_investigation.md) also found
insert/bridge reconstruction and terminal pointer-capture defects. This resolves
existing-material locality, not later-material birth or partial-frame ownership.

Existing selection and resize tests separately confirm that deformation ranges
include unoccupied helix directions and organization lineage can grow with an
extended domain. Reuse that evidence; do not mistake either representation for
an exact receipt of material that existed when a move executed. A later loop
copy, regrowth, or companion needs its own birth/ancestry decision.

**Representation conclusion:** preserve authored legacy owner inputs and their
exact v1 semantics. A visible typed member-motion role in the existing placement
list remains a candidate authored representation, not an approved schema. Its
execution needs chronological event/frame provenance absent from today's final
materialized owner/residue arrays. Prefer a disposable placement program derived
from feature inputs and native prefix results, with references to those authored
inputs; do not add another persisted pose array or expand saved selections into
one transform per residue. The experiments disprove the two shortcuts, but do
not prove that this proposed compiler satisfies the complete matrix above.

The next isolated implementation must settle all of these finite contracts:

- Exact selected-material union and native descendants, distinct from current
  named-group membership and from later fresh material at reused addresses.
- Event order and explicit local/world frame for mixed group, owner and residue
  edits, including replacement/reset; never reinterpret saved v1 composition.
- Construction frame at material birth and subsequent motion, so later tails,
  continuation and loop copies neither remain stale nor receive a delta twice.
- Full and atomistic companions, CPD rigid units, linked/fixed constraints, and
  shared-axis ambiguity under independently moved directional material.

Compile/admit the derived program once per owned prefix, with explicit work and
memory limits. Slider/drag samples must reuse it and transform bounded native
components; no full feature-history scan per frame. Apply still independently
proves the current source and rebuilds the suffix once. Existing work bounds
must not be raised to make the prototype pass. FH-27 must measure complete
interaction/HTTP/heap costs; these tiny tests are not performance qualification.

[Onshape Query Variables](https://cad.onshape.com/help/Content/PartStudio/query_variable.htm)
explicitly distinguish a captured selection from optional reevaluation on use,
and propagate upstream selection edits to downstream features. This supports
making NADOC's prefix selection policy explicit; it does not prescribe DNA
material birth, companion ownership or physical constraints. Onshape's
[reference repair](https://cad.onshape.com/help/Content/Document/repairing.htm)
also supports explicit replacement of failed references, not a silent fallback
to an entire owner. Both sources were checked October 16, 2026.

**Containment:** FH-23 has now consumed nine checkpoints and FH-18 thirteen;
both remain growth-flagged. Stop adding partial owner adapters to this unresolved
movement architecture. Advance the bounded
[FH-24 Fine Routing implementation](fine_routing_history_editor_plan.md) next,
while the full original member-motion exit remains open and required. This is
an execution-order adjustment, not parking core work or reducing its exit.
The isolated compiler and complete inspectable molecular comparison still
precede any production promotion. No user decision is requested from this
scalar evidence; it is not the required four-panel/phase-sweep artifact.

Existing out-of-span inventory correction (October20): whole-helix diagnostic
selection now includes all actual occupied ordinary residues beyond the physical
deformation window. Domain references retain exact domain/range matching.
Four regressions cover both directions and whole/domain scope; before repair,
both whole-helix cases omitted four residues. After repair:4pass; existing ordering
file23pass. Full/atom rigid oracles, unselected coordinates, bonds and source
immutability checked. Static native fixture only: no loop-producer, construction
replay or explicit tail-selection claim. Production deformation resolver unchanged.

Ordinary Move/Rotate C7 (October20): one real-app mid-log menu creation attempt
with translation and rotation receives native409 historical_cursor. Canonical
checkpoint/history remain exact; draft stays open, Cancel restores browser
design/geometry/revision exactly, and returning to tip re-enables historical edit.
Existing owner-edit app test already covers disabled historical editing at rollback.
App1pass; first harness attempt expected a specific toast incorrectly. Actual UI
shows a generic retained-movement refusal; store.lastError contains the cursor
explanation. No production changes. Owned scratch rilubkmq/l7zf1625 independently
absent. Log: feature-history-focus/transform-rollback-app-final.log. This ordinary
lifecycle evidence does not qualify unresolved named-member molecular semantics.
