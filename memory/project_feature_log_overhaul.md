---
name: Feature Log Overhaul + Tabbed Sidebar
description: Architecture, critical files, and design decisions for the snapshot-bearing feature log, edit endpoint, broken-delta detection, and the three-tab left sidebar. Read before touching feature_log, mutate_with_feature_log, _seek_feature_log, or the left sidebar tab strip.
type: project
originSessionId: 9f1bf930-958e-498b-bcf5-3b65f7fbdd52
---
# Feature Log Overhaul + Tabbed Sidebar (commit 873f3e6, branch feature-log-update, 2026-05-02)

## Current delivery status (2026-10-16)

**Mandatory progress reporting (user request, October 16):** after every major
engineering update, report completed / estimated total, remaining, changes since
the previous report, and why scope changed. Baseline B1 is **17 / 38 complete**,
**21 remaining (12 core-priority, 9 parked assets/provenance)** through `2c15e747`.
The stable FH-01–FH-38 milestone ledger and exit criteria are in the
[delivery map](../docs/audits/feature_history_20261014/remaining_standard_part_checkpoints.md#progress-baseline-and-mandatory-update-counts--october-16-2026).
These are completed implementation milestones, some gated, not percentages of
user-ready functionality or time. Assemblies and machine-specific VR validation
are excluded; desktop qualification is included. Planning/test reruns/commits do
not earn extra credit. Keep the baseline fixed, log every estimate change, and
decrement completed if an exit reopens. Flag three major checkpoints spent on
any still-open milestone (cumulative even across alternating work), or total
growth to 42 (more than 10% over B1).
Update the ledger and these current counts before each major final response.
Effort is separate: U1–U32 are **32 engineering checkpoints** since B1, closing
**four milestones** (FH-19/FH-21/FH-22/FH-24). FH-18 remains open after13 checkpoints;
FH-23 after9. Both are **task-growth flagged**. Current counts: **21/38 complete,
17 remaining (8 core,9 parked); U32 +0 completed,+0 total**. Fixed exits remain.
U27 implements the complete [22-kind Fine Routing editor](../docs/audits/feature_history_20261014/fine_routing_history_editor_plan.md):
pre-child native references, closed inputs/identities, stable batch add/remove/
reorder, original-source proof and full sibling/downstream regeneration.
Source-bound HTTP/isolated evaluation reuse the owned host, one undo and exact
source/session/revision/policy checks. No field/viewport replay; bounds unchanged.
Seven annotation roles plus apply-loop-skips preserve organized native lineage.
ISSUE-136 fixes ordinary loop ownership and duplicate crossover calculation;
ISSUE-137 fixes failing-child attribution; ISSUE-138 sends rebuilt suffix recovery
for owned routing/extrusion/pattern edits instead of stale browser cache bodies.
Native51, lineage56, HTTP60 and worker38 cases pass; full frontend9,257pass/1skip.
See [U27 evidence](../docs/audits/feature_history_20261014/validation_fine_routing_history_editor.json).
NOT VERIFIED IN APP: servers stopped, Archive unavailable; FH-27/MV-53 desktop,
latency/memory and broad backend acceptance remain. All rollout gates stay off.
`main.js`7350; U27 delta0. No molecular builders, pins, constants or goldens changed.
FH-25 checkpoint5: shared deterministic native direct construction, stable IDs
and complete equal/unequal parity;188 focused passes. **Task growth flagged.**
[Matrix/evidence](../docs/audits/feature_history_20261014/ordinary_connection_completion_plan.md): next direct equal/unequal contracts, applied metadata,
organization and qualification. All gates off; preserve finite v1 and full scope.
full FH-18/FH-23 movement/qualification remains required, not parked.
U26 rejects ordinary owner insertion/unconditional final passes for chronological
movement. Later tails already use moved construction frames. ISSUE-135 Full/
atomistic tail disagreement remains open, without molecularly approved correction.
A disposable derived placement program with bounded material/birth/frame provenance
remains unimplemented; no second saved pose authority or per-frame full proof.
Full companion/constraint/axis matrix remains required. U25 extension-only v2 and
U24 native CPD/duplex qualification remain implemented. ISSUE-125/126 remain open;
ISSUE-130 is corrected privately. FH-18 retains Groups/Placements, native lineage,
named deformation preview/repair/creation, visibility and organized patterns.
Its original movement/generated/qualification exits remain open. Containment is
the five finite batches in the [migration plan](../docs/audits/feature_history_20261014/group_placement_migration_plan.md).
Keep organization separate from ordered numerical placement; no hidden group,
per-residue expansion or baking. No split-batch credit, lowered exit or estimate change.
**FH-18 consumer status:** batch A is implemented privately; B/C/D advance,
E and incomplete consumer exits remain open. Named `part_group` targets resolve on the owned native prefix
into existing frozen ranges, independently of explicit placement `cluster_ids`.
Upstream edits re-resolve the named selection during replay; later topology/group
edits retain already evaluated ranges. Missing references diagnose; dissolution
with a live named deformation consumer refuses. Legacy selector grammar is unchanged.
The bounded lineage adapter preserves actual contributors through native retry
and resize/shift merge/re-split, without reviving removed tails or selecting
unrelated new material; ambiguity refuses. See the [U10 contract](../docs/audits/feature_history_20261014/group_placement_migration_plan.md#u10-passive-resizedomain-shift-contributors).
Owned transactions retain source/session/revision/policy checks and one undo.
Generic callbacks and unrelated permits stay closed. U11 adds no public rollout.

`Design.group_organization` is either legacy `None` or a closed version-1 wrapper
of typed `PartGroup`/`GroupDomainRef` metadata. Its `part_group` resource namespace
is distinct from the unchanged numerical `cluster` owners. Conversion derives
group metadata from the rebuilt prefix and checks complete ordered placement IDs;
it does not pin poses. `group-organize/create/update/dissolve` v1 are top-level
Snapshot commands. Native organization edits preserve all ordered placement inputs
and derived geometry; earlier pose edits regenerate through them. Creator output
IDs and conversion output namespace are protected, consumer references editable.
These organization commands remain top-level; qualified routing children now
carry bounded complete PRE/POST organization replacements with exact baseline checks.

Typed identity/remap/structure inventories include organization; legacy None adds
no strand walk. The exact oxDNA archive schema still admits legacy documents and
explicitly refuses active organization. Unadapted generated composition/removal
and native authoring refuse; named deformation, the 31-kind lineage subset,
pose-only placement and three numerical families work privately. Explicit load/startup restore,
branch/save/undo/redo paths admit the mode only under the disabled host rollout
flag. Generic writes and unrelated permits remain refused even with that flag.
Rootless active organization also skips `Design.from_json` and install-time legacy
inference; it still has no invented recipe provenance. There is no public switch.
This is a staging boundary, not a sandbox against arbitrary privileged Python.

Recovery substitutes the selected snapshot's wrapper, including F0 and actual
33-row optimized seek. Capture/cold proof carries the authoring field independently
of recovery payloads. Recovery now checks closed inputs, IDs, metadata/storage
budgets and complete non-evicted PRE/POST bodies before decoding; malformed or
unavailable bodies give actionable errors. Full snapshot revert/edit publication
remains closed until authoring-only bodies preserve physical/presentation state.
The rest of the consumer matrix and
new-group move semantics remain B–E work. All milestone exits remain unchanged.
Before serialization, metadata admission charges each group and domain-reference
occurrence so shared-container aliases cannot hide expanded JSON work. Bounds
remain 30k metadata nodes/2 MB, 2k groups; source identity indexes each admit at
most 30k records. These are not latency/heap measurements.

Five captured CPD/duplex generations and four coating entries retain the U10
then-current direct-edge policy (14 entries/14,216 bytes, 16-entry/16KiB limits); U11 changes
no numerical manifests, stored pins, calculations or goldens. ISSUE-108 native
crossover-growth metadata loss remains open. Prior lineage timing and worker
evidence stays in the [U10 report](../docs/audits/feature_history_20261014/validation_group_resize_lineage.json).

U11 pure named bend/twist targets edit on the owned prefix, retaining numerical
cluster placement context. Repair exposes only existing `targets[i].id`, with
one bounded candidate inventory and exact saved expectations. Native Direction
capture is now explicitly supported; arbitrary enums remain refused (ISSUE-109).
Owned preview Apply and repair commit use distinct `organized_recipe_v1` permits
with exact source/session/revision/policy/request/candidate identity and rollback.
Metadata draft lifecycle is gate-checked again before publication.
DNA comparison v3 and preview component/envelope v2 retain historical frozen
addresses plus exact current group metadata. Selected scope is returned even
without geometry so private guides update from the native result. Current group
references/axis ownership stay live; prior intervals never re-resolve implicitly.
Capture does no group serialization. Existing node/byte/selector budgets remain.
U11 validation remains in [its evidence](../docs/audits/feature_history_20261014/validation_named_deformation_lifecycle.json).
Existing gzip inflation precedes decoded-wrapper admission, not a whole-payload memory bound.

## Working boundaries and next step

Prioritize ordinary extrude, sweep, bend, twist, move/rotate and Fine Routing
resize/ligate/nick/crossover/loop-skip workflows. A registered builder is not a
finished tool: recording, preview/cancel/Apply, downstream editing, undo/reload
and ordinary controls must agree. Nanoparticle/protein/assets and their remaining
benchmarks are parked; ordinary DNA connections are core. Assemblies and VR
remain separately deferred. The persistent P3–P6 goal stays active.
U26 containment: complete FH-24 Fine Routing; retain full FH-23/FH-18 movement;
generated compatibility retains the existing B–E exits. U13 completes the
private ordinary Bend/Twist creation adapter: same owned prefix, controller,
renderer and lease as history editing, no provisional canonical operation.
Toolbar mixed selection and all four end-menu actions retain native planes and
controls. End clicks choose planes and retain native placement defaults. Typed
toolbar selectors keep context separate: only explicit cluster refs supply owners.
Null-target creation permits native placement picker changes; typed selection
Change/Clear cancels and reprepares. Complete first evaluation precedes Apply.
Apply independently proves the fresh source and appends one typed feature using
the existing exact-source transaction/undo/receipt. Cancel never deletes a live op.
Reset during held Prepare now retires local opening immediately (ISSUE-112),
without allowing late replies to affect a replacement editor.
U14 Hide saves separate `hidden_part_group_ids`; current membership resolves on
snapshot changes, absent IDs remain dormant and old base/placement masks retain
their meaning. Show keeps explicit current-base exceptions. Save/export drains
queued visibility writes with document-reset guards. Strand queries use the
cached effective mask; native geometry and feature rows are unchanged. Earlier
placement editing remains gated until FH-23.
The [caller audit](../docs/audits/feature_history_20261014/group_placement_migration_plan.md#post-u11-caller-audit-and-next-delivery)
found no ordinary core caller needing a new generic scope compiler first.
Generated compatibility remains FH-18, not silently transferred to FH-36.
No fixed exit changed; FH-18 remains at checkpoint13 after U21. Full redraw for structural partial
updates and full undo copying under lock remain performance debt. No per-frame
history proof is introduced. Shared prefix admission and editor setup are reused;
live legacy authoring cannot be pruned until qualified rollout.
See [U15 evidence](../docs/audits/feature_history_20261014/validation_group_patterns.json)
for checks, failures and cleanup. Patterns require explicit `_organization_copy`
metadata on organized sources, use actual extraction ancestry, and retain stable
instance groups through count edits. Existing whole-helix placements determine
geometry; historical primitive deformation selectors are not rebound to current
ordinals. Native input history edits work with evicted recovery. The owned host
reuses source proof, worker/supervisor, exact candidate parity and one publication;
generic pattern append jobs refuse. Complete candidate geometry is embedded so
client adoption does not await an unbound geometry GET. Historical source/group
IDs are read-only in the dialog. Source/reset/refusal guards preserve drafts and
retire old previews. All three numerical manifests remain byte-unchanged in U15;
U14's 17 exact compatibility edges and 32-entry/32-KiB limits remain.
`main.js` delta is 0. Desktop and complete HTTP/heap latency remain unqualified.
All organization/preview/history/create
rollout flags remain false. Archive is unmounted, so application
and performance qualification remain open; software checks do not close them.
Do not enable organization until B/C/D adapters and E's applicable checks pass.
Research unresolved CAD workflow decisions before choosing semantics. Any
scientific placement change still requires the separate demonstrated-geometry
authorization process. Commit/push reversible checkpoints; no numerical repins.

Preserve the division between input proof, snapshot recovery, structural validity,
scientific validation and user editability. Full proof is explicit/background
work, never a slider or drag-frame operation. Keep source/session/revision/policy
ownership through private evaluation and one failure-atomic publication. Do not
silently bless imported roots or opaque generated receipts as native recipes.

Current architecture and finite work maps:

- [Architecture review](../docs/audits/feature_history_20261014/architecture_review.md)
- [Fixed milestone ledger](../docs/audits/feature_history_20261014/remaining_standard_part_checkpoints.md)
- [Organization/placement migration](../docs/audits/feature_history_20261014/group_placement_migration_plan.md)
- [Implementation ledger](../docs/audits/feature_history_20261014/implementation.md)
- [Historical implementation, recovery semantics and prior validation](project_feature_log_overhaul_archive.md)

The archive retains the earlier Fine Routing, delete/revert, snapshot seek,
identity lifetime and generated-feature notes. Read the relevant section before
changing those mechanisms; the current ledger supersedes old completion claims.
