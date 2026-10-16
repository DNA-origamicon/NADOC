# P5c portable draft document boundaries

This increment adds `Design.repair_draft` with the distinct `repair_draft`
ownership role. The versioned, bounded proposal is document/branch metadata;
its presence or matching base fingerprint is not a verification certificate.
Metadata endpoints are now wired; proposed-source upload/audit and draft-bound
evaluate/apply remain separate integration work.

## Exclusion and publication

Proof capture skips the role before traversal. Authoring comparison and CPD /
duplex numerical source projections already select only authoring fields.
Import-root construction excludes the field before JSON serialization; replay
rejects non-null draft metadata supplied inside an import root. Per-feature
recovery snapshots omit the field before encoding. Child diffs already use an
explicit topology field list and do not include drafts.

Ordinary native recipe publication and replacement-style recording callbacks
preserve the current proposal, including explicit absence after discard.
Native publication keeps its candidate source table, so deliberate source
replacement is not overwritten by older live bytes.

The separate legacy recovery helper preserves the proposal and, while one
exists, merges available source records with **live records winning** for equal
digests. This retains newly staged bytes and does not resurrect older corrupted
records. It neither decodes nor hashes sources. The existing 256-source count
limit applies to the union; overflow returns a structured 409 before publication.
The four full-recovery seams (snapshot replay deletion, snapshot parameter edit,
snapshot revert and routing-child revert) also retain current loadout bookkeeping:
these are edits within a branch, not navigation to a snapshot's stripped branch.
Slider seek already copies selected topology onto the live document.

## Undo, persistence and responses

Geometry undo/redo preserves the current proposal and available staged sources
only when both Design ID and active loadout ID match. Crossing either boundary
restores the destination snapshot's proposal. The new restoration/source-union
check runs before either undo stack changes. This does not redesign pre-existing
undo behavior if later geometry validation or revision publication itself raises;
that broader transaction hardening remains outside this increment.

Whole Design JSON, server session cache, loadout snapshots, content-addressed
project revisions and portable packages retain drafts and available source bytes.
Missing bytes named only by a proposed action do not become published recipe
portability dependencies. No saved readiness/job result exists. Save As retains
the original base Design ID, requiring explicit rebase instead of rewriting it.

Ordinary responses exclude the full draft during model dumping and expose a
constant-size **top-level** summary: identity, generation, action count, pending
status and unchecked base status. This avoids traversing action JSON or putting
an invalid partial draft into the response's Design schema. No base hashing or
source decoding occurs during rendering/polling. Explicit full-draft retrieval
uses the explicit metadata GET; server persistence continues to serialize canonical Design.
Pinned caDNAno's fresh-empty host refuses a pending proposal rather than losing
it during replacement.

Initial explicit Apply will retain the proposal. Discard remains separate;
Apply-and-clear needs a later atomic matching-generation operation. Current
metadata preparation/transaction helpers back the
[explicit metadata routes](../../part_repair_drafts.md).

## Numerical pins and validation gate

Adding the Design field changes the model source hash in **all three** numerical
contracts: CPD, duplex relaxation and streptavidin coating. The ownership table
also changes CPD/duplex implementation fingerprints. No scientific algorithm,
polarity rule, placement constant or solver is modified. Old recorded pins must
fail with their existing diagnostics until explicitly upgraded; never rewrite
saved history or automatically repin it.

Focused new coverage lives in `tests/test_part_repair_document_boundaries.py`
and `tests/test_part_repair_persistence.py`: proof/recovery/import-root and
numerical-source exclusion; ordinary and legacy publication; branch-aware undo;
source retention and atomic count refusal; response exclusion; fresh-import
guard; and whole-document/session/loadout/revision/package roundtrips.
The new boundary and persistence files passed 23 and 16 cases respectively.
The metadata API passed 18 cases. Affected existing persistence/recovery suites
and independent CPD/duplex cold regressions also passed; see
`validation_draft_persistence_p5.json` for the full focused record.

The [Onshape repair panel](https://cad.onshape.com/help/Content/Document/repairing.htm)
and [paused regeneration](https://cad.onshape.com/help/Content/PartStudio/features_and_parts_lists.htm)
inform separation of proposed edits from displayed geometry. NADOC's durable
proposal, explicit rebase and independent geometry-undo policy are deliberate
implementation choices, not claims about Onshape's storage internals.
