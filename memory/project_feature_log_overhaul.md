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
Engineering update U2 closed **FH-19 after two checkpoints**. Current
counts are **18 / 38 complete, 20 remaining (11 core, 9 parked)**, delta
for latest update U7 **+0 completed, +0 total**. U7 is **FH-18 checkpoint 5**:
ordinary authored PATCH, admitted identity-group dissolution and auxiliary
recording are implemented; private separate organization/native replay and gated
owned HTTP transactions now work. Complete consumer/repair/UI migration and
new-group movement keep FH-18 open.
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

**FH-18 U7 transaction checkpoint:** migration batch A is implemented privately;
B/C advance, D/E remain open. The owned recorder accepts four organizational
commands and explicit `placement-update`; it allocates creator IDs, records
complete native inputs and emits one undo/revision through existing opaque permits.
The HTTP route is `/design/group-organization/commands`, with closed kind/inputs/
expected_revision. Default-off host admission precedes body reads; strict policy
cannot be downgraded. Bounded JSON acquisition is shared with deformation preview.
Source capture is lock-owned; preparation, validation and encoding run outside
the lock; final source/session/revision/policy CAS preserves non-authoring state
and old recovery. No-op responses bind the accepted revision without new history.
The final admitted definition includes the new row and existing scientific gates.
Per-occurrence serialization admission prevents shared-container expansion before
encoding; the original full-source undo copy remains a latency/heap obligation.

`Design.group_organization` is either legacy `None` or a closed version-1 wrapper
of typed `PartGroup`/`GroupDomainRef` metadata. Its `part_group` resource namespace
is distinct from the unchanged numerical `cluster` owners. Conversion derives
group metadata from the rebuilt prefix and checks complete ordered placement IDs;
it does not pin poses. `group-organize/create/update/dissolve` v1 are top-level
Snapshot commands. Native organization edits preserve all ordered placement inputs
and derived geometry; earlier pose edits regenerate through them. Creator output
IDs and conversion output namespace are protected, consumer references editable.
No Fine Routing child can carry these commands while its diff omits the wrapper.

Typed identity/remap/structure inventories include organization; legacy None adds
no strand walk. The exact oxDNA archive schema still admits legacy documents and
explicitly refuses active organization. Unadapted generated composition/removal
and native authoring refuse; pose-only existing placement and three qualified
numerical families preserve metadata privately. Explicit load/startup restore,
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
The rest of the consumer matrix, live repair paths, visible Groups/Placements and
new-group move semantics remain B–E work. All milestone exits remain unchanged.
Before serialization, metadata admission charges each group and domain-reference
occurrence so shared-container aliases cannot hide expanded JSON work. Bounds
remain 30k metadata nodes/2 MB, 2k groups; source identity indexes each admit at
most 30k records. These are not latency/heap measurements.

All four historical numerical-schema generations have exact direct edges to the
new current targets: twelve entries/12,980 bytes under unchanged 16-entry/16KiB limits.
Prior historical-target policy is retained byte-for-byte for audit/tests. Numerical
kernels, data and runtime checks are unchanged; no stored pins rewritten. See
[U7 evidence](../docs/audits/feature_history_20261014/validation_group_organization_recording.json).
U6's representation evidence remains separately retained. U7's final focused
backend check passed **743 tests**, 38 warnings, 11.68 s; **three real native-worker
cases passed** in 86.43 s. No aggregate fast/FULL pass is claimed.
No frontend production change; `main.js` delta 0.
App/desktop/latency acceptance remains open; Archive is not mounted. Detailed
native-worker, selector and cleanup results are recorded in the U7 evidence.
Selector dry-run ran no suite; aggregate fast/FULL debt remains. Repo-wide memory
lint has six pre-existing unrelated errors; this active head is bounded and indexed.

## Working boundaries and next step

Prioritize ordinary extrude, sweep, bend, twist, move/rotate and Fine Routing
resize/ligate/nick/crossover/loop-skip workflows. A registered builder is not a
finished tool: recording, preview/cancel/Apply, downstream editing, undo/reload
and ordinary controls must agree. Nanoparticle/protein/assets and their remaining
benchmarks are parked; ordinary DNA connections are core. Assemblies and VR
remain separately deferred. The persistent P3–P6 goal stays active.

Next: typed organizational selection, whole-helix native lifecycle, then explicit
domain split/merge/prepend/resize lineage after all native reconciliation/retry.
Preserving a wrapper alone can silently select a different domain after sweep or
Fine Routing. Keep batch C's complete consumer inventory in view; do not
enable active organization until B/C/D adapters and E's applicable checks pass.
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
