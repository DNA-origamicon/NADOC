---
name: Feature Log Overhaul + Tabbed Sidebar
description: Architecture, critical files, and design decisions for the snapshot-bearing feature log, edit endpoint, broken-delta detection, and the three-tab left sidebar. Read before touching feature_log, mutate_with_feature_log, _seek_feature_log, or the left sidebar tab strip.
type: project
originSessionId: 9f1bf930-958e-498b-bcf5-3b65f7fbdd52
---

# Feature Log Overhaul + Tabbed Sidebar (commit 873f3e6, branch feature-log-update, 2026-05-02)

## Current state and navigation

November3 master integration: ordinary replayable scadnano import now honors the
optional rigid relaxation choice. Fitted cluster poses are applied in a private
session through the existing recorded Make Cluster and Move/Rotate operations,
then independently replayed before replacing the active document. The original
pinned import remains F1; replay uses explicit poses, not a rerun of the solver.
Unsupported fits retain the unrelaxed import and a visible skipped explanation.
Manual Relax Origami on a native recipe uses the same recorded operations, with
one atomic publication/undo and a current-source check after fitting.

November3 Sweep feedback: preview expiry preserves the preceding rebuild error
and its failing-feature attribution, appending reopen instructions instead of
erasing the error row. Expiry still disables Apply; Cancel releases the editor.
The reported `workspace/test.nadoc` source replays successfully. The user's
`(8,38,36)` endpoint reproduces a matched-end continuation-window refusal;
see [the routing follow-up](project_autoscaffold_single_strand.md).
These changes are in the integration worktree.
Validation: 10,016 frontend tests pass (1 skipped), the browser refusal/expiry/
Cancel check passes, and all 23 smoke checks pass; both browser scratch roots
were removed. `main.js` LOC delta 0.

November3 document provenance: meaningful metadata/loadout operations use a
separate journal; autosaves do not add feature rows. Ordinary newly recorded
loadouts have independent source/branch and portable revision verification.
Legacy missing history and protected simulation branches remain fail-closed.
See [the contract](../docs/document_operation_provenance.md) and
[user scope](feedback_document_operation_provenance.md). The filter now toggles
fine routing and document ops. November 6 adds explicit annotation/view-volume
checkpoints and their default-off filter; ordinary presentation autosaves remain outside history.

November2 scrubber representation fix: design-change notifications stop all
simulation panels. Idle CanDo/SNUPI controllers now leave the shared renderer
untouched; only a controller that prepared or hid the scene may restore it.
This prevents Full/Cylinder geometry reappearing over atomistic/surface views
after a seek. Pending compact loads retain cancellation/restore ownership.
Regression coverage: `frontend/e2e/feature_seek_representation.spec.js` and
the CanDo/SNUPI display unit tests.

**User scope decision, October25,2026:** clusters own geometry among grouping
constructs; Staple Groups organize strands (names/colors/selection). Retire the
experimental PartGroup / Groups and Placements migration and arbitrary named-group
Move selected members/compiler/geometry rollout from active requirements. Do not
revive historical “original full exit” clauses for it. Existing cluster and
individual-nucleotide Move/Rotate correctness, atomicity and qualification remain.
Experimental authoring controls are removed; referenced internals remain retirement debt.
Both organization gates stay off. October26: FH-23 closed and transform gates ON;
atomic cluster Apply and authoritative pose recovery are qualified. See the
[transform plan](../docs/audits/feature_history_20261014/transform_history_editor_plan.md#completion-audit-and-corrective-measures--october-27-2026) for the October27 audit, corrective measures and completed nominal-preview follow-up (`be9fe4aa`); no Move/Rotate performance task remains.

Make Cluster now records v3 placement-preserving intent; native geometry/axes,
recorded cluster lifecycle, dependency refusals and recovery are qualified under
FH-18. Posed/dependent dissolution remains an explicit refusal. See the
[current handoff](../docs/audits/feature_history_20261014/session_handoff.md)
for closure evidence and the next task; aggregate regression debt remains FH-27.

October28: FH-25 ordinary connection lifecycle and history-editor gates are ON.
Unequal direct Duplex registers now follow relocation/restoration without changing
molecular geometry; shared-host same-length sequence assignment preserves topology.
FH-26 core dependency repair and bounded native DNA candidate comparison are also
qualified; exact input receipts, prefix rebinding, Cancel and single Apply remain
mandatory. See the connection/repair plans and handoff for remaining core work.
FH-28 retained ordinary creation/recovery/publication is also qualified, including
autosave/disk restoration, post-restore editing and bounded repeated sessions.
Aggregate FH-27 regression acceptance remains open.

November1: FH-30, FH-34 and FH-35 close: ordinary NP application/pending alternatives,
scadnano source import and DNA-PDB conversion are qualified. The ordinary NP gate
is ON; both imports retain original bytes and explicit loss/identity contracts.
The follow-on campaign closes FH-33: bounded ordinary protein import and original-source
library placement are qualified, and the import gate is ON. See the
[protein contract](../docs/audits/feature_history_20261014/protein_free_import_contract.md#fh-33-source-and-placement-qualification--november-1-2026).
The next continuation closes FH-31/32/36 and enables their asset gates: ordinary
controls and historical edits use the existing worker, exact native ownership and
pinned sources. Generated recipes now compose native commands through final connections.
App/replay/undo/reopen and repeated bounded capture/publication evidence live in the
[current handoff](../docs/audits/feature_history_20261014/session_handoff.md); safe capture refusals remain disclosed.
Molecular candidates remain isolated pending separate review; aggregate FH-27 remains open.

The [current handoff](../docs/audits/feature_history_20261014/session_handoff.md)
owns progress counts, gate state, qualification evidence and the single next task.
Its current state supersedes the older S53/S54 queue, C8-open claims,
all-gates-off statements, and 38-milestone accounting in historical material.
The latest continuation request authorizes work; do not infer a recurring reviewer timer.

Follow the [operating contract](../docs/audits/feature_history_20261014/operating_contract.md)
with later user decisions recorded in the handoff taking precedence. Preserve native
replay, exact Cancel, single Apply/undo, independent cold proof, and scientific
geometry authorization. Old-file compatibility is excluded from current work.

Use the [fixed milestone ledger](../docs/audits/feature_history_20261014/remaining_standard_part_checkpoints.md)
for exit criteria. Historical implementation evidence below is not current sequencing
or new validation, and its gate/count claims must be read against the handoff.

## Retained implementation evidence

Current completion and residual work are recorded only in the handoff above.
The linked historical detail retains U/S checkpoints, including former gate-OFF,
PartGroup, sealed-host and old-file repair requirements. Those are not an active
queue. ISSUE-100, ISSUE-125 and ISSUE-135 are reconciled against ordinary-tool
acceptance and the user-selected locality scope. ISSUE-126 now rejects duplicate
occupancy in native execution and ordinary publication, including repairs and
undo/redo; partial repair of duplicate nucleotide slots is refused. The October30
user correction makes spatial collisions of repositioned overhangs advisory and
requires automatic fitting to preserve covalent root length; manual edits may stretch it.
ISSUE-143 remains a distinct unequal-direct connection defect.

- [Current delivery status (2026-10-17) — continued detail](details/project_feature_log_overhaul/01-current-delivery-status-2026-10-17.md)

<a id="working-boundaries-and-next-step"></a>
- [Working boundaries and next step](details/project_feature_log_overhaul/01-current-delivery-status-2026-10-17.md#working-boundaries-and-next-step)

- [Architecture review](../docs/audits/feature_history_20261014/architecture_review.md)
- [Fixed milestone ledger](../docs/audits/feature_history_20261014/remaining_standard_part_checkpoints.md)
- [Organization/placement migration](../docs/audits/feature_history_20261014/group_placement_migration_plan.md)
- [Implementation ledger](../docs/audits/feature_history_20261014/implementation.md)
- [Historical implementation, recovery semantics and prior validation](project_feature_log_overhaul_archive.md)

The archive retains the earlier Fine Routing, delete/revert, snapshot seek,
identity lifetime and generated-feature notes. Read the relevant section before
changing those mechanisms; the current ledger supersedes old completion claims.


November 3 live UI: Repair/filter and cadnano adapters now also exist in the served
/home/joshua/NADOC checkout. Filters persist per document and sync across windows.
Both editors use feature_log_panel and the shared native history transports.
