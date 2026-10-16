# Group organization and placement: finite migration plan

Architecture proposal, October 16, 2026; source baseline `3aa2529a`. The U6–U8 status
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
| `frontend/src/ui/cluster_panel.js`, group style/selection helpers, `scene/cluster_gizmo.js`, `move_rotate_panel.js`, Join/joint tools | Group lists/picking/style read organization; placement editing reads visible placement owners. Restore selection across response/undo/load without confusing equal string IDs in different namespaces. Preserve existing controls; no monolithic `main.js` implementation. |
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
`MutationReport.strand_id_renames` and `new_domain_origins` currently have no
producers. Pending-ligation retry can change topology after that reconciliation.

| Priority / consumer | Required adapter and finite exit |
|---|---|
| Typed selection boundary | Resolve `part_group` separately from numerical `cluster`, including equal string IDs across the namespaces. Share organization-to-native membership resolution across authoring, preview and replay. Never pass organization IDs into `resolve_cluster_scope`: unknown IDs are dropped and an all-missing selection becomes unscoped. Preserve `DeformationOp.cluster_ids` as placement/fitting context. |
| Explicit placement pose; bend/twist | Pose-only `cluster_op` already preserves the organization wrapper. The native deformation overlay also carries it without changing placements; qualify explicit primitive targets and intentional placement selectors first. Organizational selection needs the resolver above, with unchanged frozen-target editing semantics and an explicit dependency policy. |
| Loop/skip, sequence and whole-helix routing | Leaf builders retain existing member identities, but qualify the complete native executor, including reconciliation and retry. Whole-helix groups may remain unchanged while their helix IDs survive; deletion or unresolved ownership changes must refuse or use an explicit membership edit. |
| Extrude/continuation/sweep | Keep native lattice-frame, source-helix and ordered-placement inheritance exactly. New numerical placement owners must not recreate dissolved organizational groups. State any new-group membership addition as explicit authoring input. Domain references need lineage handling even when only a sweep continuation prepends a domain. `bundle-create` remains a replacement/root operation, not an append after conversion. |
| Domain-based FineRouting | Add a shared organization-only membership adapter after all native postprocessing, using command-specific split/merge/prepend/resize lineage. Preserve overlapping and opposite-direction selections independently. Refuse ambiguous lineage rather than infer nearest overlap; do not modify the existing placement reconciliation algorithm. Cover nick→ligation, resize inline-tail split/merge, sweep prepend and pending retry. |
| Legacy grouping, generated producers, pattern and Join | Keep combined placement/group mutations blocked until each producer emits the separate roles deliberately. Do not mechanically replace `cluster_create` or placement membership writes with organizational commands. |

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
