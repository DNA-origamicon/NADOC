# Pending connection metadata: recording cost and recovery options

Status: read-only design review, 2026-10-15. No recovery format or recording
policy changes are authorized by this note. Pending ordinary-overhang CRUD
latency remains unqualified. Assemblies are outside this work.

## Immediate checkpoint

Move exact native selection/preparation before the recording transaction,
while retaining the same document lock and source identity. Missing or
ambiguous endpoints, mismatched saved selections, and unsupported input syntax
must fail before `_snapshot_copy`, snapshot encoding, UUID/time allocation,
callback execution or publication. The prepared selection is private to that
uninterrupted transaction; it is not a reusable source/proof cache.

The measured missing-endpoint path currently pays for an undo copy and PRE
encoding before returning 404. The paired initial report is
`benchmark_pending_overhang_connections_initial.json`; observed slow refusals
include generation-2 GC overlapping `_snapshot_copy`. Early rejection removes
unnecessary work without changing GC policy, undo ownership, recovery contents,
or the successful edit's validation/rollback behavior. Remeasure this change
before pursuing a new representation.

Successful compatibility edits still need an independent undo image. The live
`Design` has mutable aliases and later compatibility callbacks may mutate in
place. Retaining a shallow old model would therefore weaken undo and rollback.
No change in this note authorizes that optimization, out-of-lock reads of a live
model, or reuse of a prior snapshot merely because a feature/revision matches.

## Existing diffs do not remove this cost safely

- `api/feature_recording.py:record_feature` writes independent PRE and POST
  snapshots. `record_minor` still writes a full POST snapshot on every edit and
  a full PRE snapshot when opening a routing group.
- `core/design_diff.py:_DIFF_FIELDS` excludes `connection_versions`.
  `MinorOpSubtype` does not include pending connection CRUD. Reclassifying the
  operation would change timeline grouping and still retain substantial full
  encoding work. Existing child diffs are also not a complete inverse document
  representation or an exact ordered-list replacement.
- `SnapshotLogEntry` has assembly diff and `pre_state_from_previous` fields,
  but standard-part `_seek_snapshot_base`, revert and edit consumers require
  actual full payloads. Enabling those flags alone would lose recovery behavior.
- `part_recipe_edit.regenerate` and `part_recipe_prefix.ReplayPrefix` deliberately
  regenerate complete recovery payloads. Proof never consumes these payloads.
  A new live encoding alone would not automatically reduce regeneration cost.

## Smallest possible future recovery increment

If measurements justify a separate checkpoint, consider an explicitly
versioned **part** recovery representation with one actual PRE snapshot and a
bounded, exact ordered PRE/POST replacement of `connection_versions`. POST
recovery would decode that anchor and apply the recorded replacement; it would
not execute a command or accept the replacement as proof of native construction.
The existing `overhang-bulk` feature identity and editable command inputs would
remain unchanged.

This first representation would remove one full encoding, not the owned undo
copy or all full-document work. Avoid a chain of references to preceding rows:
unlogged compatibility changes, removed/evicted anchors, seeks and restored
documents make a previous POST insufficient authority for the current PRE.
Each new representation needs its own complete actual anchor. Existing saved
rows must retain their current meaning; no silent migration or assembly-codec
reinterpretation is acceptable.

The metadata replacement must include all affected records and their order.
Native create can also name earlier blank candidate rows through
`assign_default_names`; recording only the new/selected row is incomplete.
An explicit empty replacement still represents an authored no-op. Deleted
records require their full PRE definitions, not IDs alone.

Require the closed metadata command policy before selecting this codec. Its
effect contract must prove that every other snapshot field is unchanged, with
documented treatment of excluded feature-log, loadout and draft fields. A generic
legacy callback cannot receive this privilege. Do not rely on equal IDs,
recursive string rewriting or an unauthenticated saved marker.

## Integration seams and acceptance tests

A future implementation needs a small shared standard-part recovery reader;
adding branches throughout the large CRUD router would compound existing debt.
Audit and route all relevant readers through it: seek before/after the row,
snapshot revert/edit/delete, old recovery-dependent rebase helpers, full reload,
and snapshot consumers that determine changed topology. Regeneration/prefix
recovery writers must either deliberately retain full output or implement the
same reviewed codec. Recovery byte accounting, response slimming and persistence
must recognize its payloads without treating them as executable inputs.

Before any format switch, tests must establish:

1. Exact full restored snapshot parity with today's PRE/POST format for create,
   sparse patch, delete and no-op, including earlier blank-name assignments and
   exact candidate-list order. Independent undo/redo must preserve all source
   state and remain one user action.
2. Mixed old/new rows, rootless/import roots, overlays, routing children,
   backward/forward seek, save/reload and subsequent compatibility mutations.
   No recovery read may run a geometry builder or topology postprocessor.
3. Corrupt/unknown codec, unavailable anchor, duplicate IDs, mismatched expected
   PRE, unknown fields and payload-budget exhaustion fail explicitly without
   partial state. Existing saved rows remain readable without migration.
4. Injected encode/decode/validation/publication/cancellation failures restore
   the exact history, redo, revision and request markers. Identity/time allocation
   occurs only after successful admission. Invalid selection takes no copy.
5. Independent root regeneration and cold proof ignore poisoned recovery while
   input edits preserve stable feature/output identities. Changed recovery
   representation never upgrades an unsupported receipt.
6. Paired natural-GC measurements report successful and refused route latency,
   copy/encoding/validation stages, recording-lock time, concurrent lightweight
   requests, retained history and cleanup separately. Keep failed reports and
   current limits. A correct format is not a latency qualification.

The strict host's immutable authoritative revisions already address a broader
source/undo ownership problem. Compare the cost and scope of extending that
qualified path against maintaining another compatibility recovery codec before
committing to this optional work.
