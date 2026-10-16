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
Effort is separate: U1–U11 are 11 engineering checkpoints since B1, closing one
additional milestone; nine went to still-open FH-18. The unchanged 38 is not an
estimate of commits/messages. The post-U11 source/sequence audit earns no credit.
Engineering update U2 closed **FH-19 after two checkpoints**. Current
counts are **18 / 38 complete, 20 remaining (11 core, 9 parked)**, delta
for latest update U11 **+0 completed, +0 total**. U11 is **FH-18 checkpoint 9**:
ordinary authored PATCH, admitted identity-group dissolution and auxiliary
recording are implemented; private separate organization/native replay and gated
owned HTTP transactions now work. Named native deformation selection, qualified
domain lineage and Fine Routing recovery now agree. U9 adds extrusion/crossover
lineage; U10 adds passive resize/domain-shift tracking. U11 connects named
preview/repair/comparison and owned publication. Generated consumers, visible
Groups/Placements and new-group movement keep FH-18 open.
**Task growth is flagged.** The containment decision and five finite batches are
in the [organization/placement migration plan](../docs/audits/feature_history_20261014/group_placement_migration_plan.md).
Separate organizational membership from the existing ordered placement list;
preserve that list as the sole numerical authority and expose its owners as
editable placement features. No hidden replacement group, per-residue expansion
or coordinate baking. New-group move/frame/extension semantics remain a required
integration exit. Recorded conversion → posed dissolve → regroup is implemented;
finish its typed consumer/repair/UI adapters next. Do not
inflate counts by splitting batches or accumulate more identity-only subsets.
No total-growth trigger or estimate change; the full original FH-18 exit stands.

**FH-18 U11 consumer checkpoint:** batch A is implemented privately; B/C advance,
D/E remain open. Named `part_group` targets resolve on the owned native prefix
into existing frozen ranges, independently of explicit placement `cluster_ids`.
Upstream edits re-resolve the named selection during replay; later topology/group
edits retain already evaluated ranges. Missing references diagnose; dissolution
with a live named deformation consumer refuses. Legacy selector grammar is unchanged.
The 25-kind lineage adapter preserves actual contributors through native retry
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
and native authoring refuse; named deformation, the 25-kind lineage subset,
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
The rest of the consumer matrix, visible Groups/Placements and
new-group move semantics remain B–E work. All milestone exits remain unchanged.
Before serialization, metadata admission charges each group and domain-reference
occurrence so shared-container aliases cannot hide expanded JSON work. Bounds
remain 30k metadata nodes/2 MB, 2k groups; source identity indexes each admit at
most 30k records. These are not latency/heap measurements.

Five captured CPD/duplex generations and four coating entries retain the U10
direct-edge policy (14 entries/14,216 bytes, 16-entry/16KiB limits); U11 changes
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
**967 focused / 8,601 frontend passes, one skip**; [U11 evidence](../docs/audits/feature_history_20261014/validation_named_deformation_lifecycle.json).
`main.js` delta 0. Archive is unmounted; app acceptance remains open. Selector
dry-run runs no suite; aggregate fast/FULL debt remains. Existing gzip inflation
precedes decoded-wrapper admission, not a whole-payload memory bound.

## Working boundaries and next step

Prioritize ordinary extrude, sweep, bend, twist, move/rotate and Fine Routing
resize/ligate/nick/crossover/loop-skip workflows. A registered builder is not a
finished tool: recording, preview/cancel/Apply, downstream editing, undo/reload
and ordinary controls must agree. Nanoparticle/protein/assets and their remaining
benchmarks are parked; ordinary DNA connections are core. Assemblies and VR
remain separately deferred. The persistent P3–P6 goal stays active.

Next: visible Groups/Placements with complete selection/style/visibility,
ordinary deformation and guarded placement-commit adapters, then remaining
generated consumers and new-group movement/frame semantics. The [post-U11 caller audit](../docs/audits/feature_history_20261014/group_placement_migration_plan.md#post-u11-caller-audit-and-next-delivery)
found no ordinary core caller needing a new generic scope compiler first.
GeneratedHistory serves NP orchestration; shared merge also serves branch/section
commands. Keep generated compatibility explicitly open in FH-18, not silently
transferred to FH-36. No tenth engineering checkpoint or exit change. Partial named scopes
cannot use the existing whole-helix loop/skip planner. U11 qualifies historical
frozen range display; current axis/membership validation stays strict. Do not
enable organization until B/C/D adapters and E's applicable checks pass.
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
