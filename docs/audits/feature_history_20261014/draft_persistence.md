# P5c repair draft persistence

## Foundation implemented, host integration pending

`core/part_repair_inputs.py` owns the existing version-1 action/request schemas.
`api/part_recipe_repair.py` re-exports their former public names; evaluation,
protected identities, numerical upgrades and molecular algorithms are unchanged.

`core/part_repair_draft.py` defines one bounded proposal for a part/loadout:
version, draft ID/generation, base Design ID, versioned root/command/source
fingerprints, repair version and actions with `expected_old`. The complete JSON
envelope uses the existing 64-action, 256,000 charged-byte, 10,000-node and
depth-64 bounds. It has no geometry, recovery, session revision, job ID,
diagnostics or saved verification status. Nested action JSON still requires
ownership/copying by its eventual host; frozen top-level fields alone do not
make nested lists/dictionaries immutable.

`core/part_repair_fingerprint.py` computes a separate version-1 durable base:

- Root: the declared root input, not materialized Design fields.
- Commands: ordered feature types/IDs, routing parent IDs and child boundaries,
  normalized command kinds/inputs, and the cursor. Labels, timestamps and saved
  output/diffs are excluded. The ordinary proof fingerprint flattens children,
  so it cannot replace this repair-target identity contract.
- Sources: only named descriptors returned by `command_source_bindings`, their
  actual availability/integrity and the exact encoded-byte digest. The existing
  immutable-source decoder validates canonical base64, decoded size and SHA-256.
  Missing/corrupt evidence receives a stable identity so it can be repaired.
  Unreferenced retained inputs, including draft-only proposed sources, are not
  visited. Shared bytes are hashed/checked once per source/size.

Structurally malformed source descriptors are a deliberate narrower boundary:
`command_source_bindings` rejects them, and no durable fingerprint is returned.
This slice does not infer an invalid binding by recursively searching raw
parameters. Missing/corrupt **bytes for a valid descriptor** remain fingerprintable.
The eventual draft host must expose this refusal rather than claiming all broken
definitions can already be saved as fingerprinted drafts.

Call this helper explicitly on **stable captured definitions** outside the
session lock. It does not capture a live mutable Design. Defaults bound input
work to 2,000 feature/group entries, 30,000 nodes and 2,000,000 charged bytes;
source inspection retains the existing 256-source/cumulative encoded-source
bound. Decoding reuses existing source limits, one source at a time. A
checkpoint supports cancellation between traversal/hash/decode operations;
native base64 decoding is not a hard-deadline operation. These limits neither
raise nor replace proof capture, worker or recovery admission limits.

A matching hash identifies the same definitions/evidence, **not** a successful
regeneration, valid geometry, supported command contract or publishable result.
The helper can identify a missing root, but the existing repair evaluator still
rejects rootless/unsupported history. Runtime revision and source-object guards
remain necessary around capture/publication; revisions are not durable across
reloads. A proposed reference has no geometry authority until complete replay.

## Remaining integration seams and completion gates

1. Add an optional Design field with a distinct `repair_draft` ownership role.
   Explicitly exclude it in `part_verification_capture`, import-root inputs and
   per-feature `state.encode_design_snapshot`; explicitly preserve it in
   `part_recipe_publication` and ordinary same-document recovery/publication.
   Whole-document JSON, session recovery, loadout snapshots and project revisions
   must retain it. This model/contract change affects numerical implementation
   pins; checkpoint and use the existing explicit upgrade path, never repin.
2. Add a bounded definition-only capture and metadata transaction. Save a draft
   with revision/design/draft-generation compare-and-swap, bump revision for
   persistence, and avoid a whole-model copy, geometry validation or feature row.
   Compute/check base hashes on explicit create/check/rebase/evaluate/load work;
   polling only returns compact cached state. Ordinary edits invalidate cached
   checks cheaply and retain proposals. Explicit rebase must check every old
   value; it must not silently replace expectations or inferred references.
3. Resolve proposed source descriptors through patched typed command inputs.
   Keep bytes in existing deduplicated `input_sources`, with existing limits.
   Add draft-specific source audit/load warnings; unavailable draft-only bytes
   must remain saveable and must not become fatal published-recipe portability
   dependencies. Retained bytes are already saved by `portable_sources`.
   Current proof capture copies the retained source table: staging additional
   bytes may exhaust its limit. Do not silently prune sources or increase limits.
4. Wire saved actions into a fresh transient RepairRequest and the existing
   isolated evaluator. A result belongs to the current document/revision and
   exact draft generation. Apply publishes once and may explicitly consume that
   same draft. Failure/cancellation/staleness retains published geometry and the
   proposal. Nothing restores a publishable evaluation result from disk.
5. UI: pending proposal and unchanged displayed model must be visibly distinct.
   Provide check/evaluate, explicit rebase, apply and discard. Slim ordinary
   `_design_response` to a draft summary; full inputs belong to an explicit read.
   Draft edits should not create full-model undo snapshots. Recommended initial
   policy is separate draft editing from geometry undo and preserve the current
   proposal on ordinary undo/redo. If Apply-and-clear must undo both geometry
   and proposal consumption, add an explicit typed undo event; do not infer that
   intent from an empty draft field. Settle this host policy before wiring.

Host completion tests must cover JSON/session/loadout/project/package roundtrips;
missing draft-only bytes; proof/recovery exclusion; edit/delete/revert/undo
preservation; stale reload and explicit rebase; generation-matched apply/clear;
failure-atomic metadata/publication; and polling that never decodes or hashes.
Foundation tests cover strict bounded data, API schema compatibility, durable
identity changes, source corruption/restoration, exclusions, cancellation and
resource refusal. No host persistence or UI completion is claimed by this slice.

## CAD precedent

Onshape's [repair workflow](https://cad.onshape.com/help/Content/Document/repairing.htm)
keeps a healthy historical state visible separately while editing broken current
references, supports explicit replacement and limits propagation when matching
is ambiguous. Its [paused regeneration workflow](https://cad.onshape.com/help/Content/PartStudio/features_and_parts_lists.htm)
distinguishes deferred edits from displayed geometry and offers regenerate/discard
actions. These support separating a proposal from regenerated geometry. NADOC's
durable, explicitly applied draft is a design choice; the cited docs do not
establish an identical persistence or undo contract. In particular, Onshape
automatically applies paused edits when switching tabs/closing the document;
that behavior is not proposed for NADOC repair drafts.
