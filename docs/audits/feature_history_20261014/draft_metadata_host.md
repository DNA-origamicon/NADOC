# P5c definition capture and metadata preparation

The original slice added pure host foundations. Design persistence and explicit
metadata routes are now wired; see [the API contract](../../part_repair_drafts.md)
and `draft_document_boundary.md`. Source staging, draft-bound evaluation/apply
and UI remain separate work. The preceding schema and fingerprint foundation
is documented in `draft_persistence.md`.

`core/part_repair_capture.py` copies private root/feature input headers, including
overlay inputs and routing parent/child identities. Snapshot/diff bodies,
materialized geometry and presentation/physical fields are not read. Mutable
JSON is cloned with cooperative 25 ms / 30,000-node / 2,000,000-charged-byte
limits and a 2,000-entry bound. Source strings are charged before retaining the
existing immutable `EmbeddedInput` record. Only descriptors named by published
commands or proposed typed input patches select source bytes. No source decode,
hash, filesystem access or numerical call occurs during capture.

`core/part_repair_planning.py` is the shared action planner used by draft
preparation/source discovery and `api/part_recipe_repair.py`. It owns target/path
resolution, original-value expectations, overlap/protected-input guards, private
patched inputs and final schema checks. `core/part_repair_proposal.py` is its thin
draft adapter. Numerical old-pin checking is shared; new pin selection and replay
remain exclusively in the existing isolated numerical worker.
Action conflicts retain feature/child/path diagnostics. Aggregate command-schema
errors identify the target without guessing which of several patches caused it.

The temporary worker/draft equivalence corpus has been replaced by direct
expected-behavior tests in `test_part_repair_planning.py`; it no longer compares
two implementations. Existing repair evaluation tests retain the execution
oracle. Worker error codes/messages/statuses and its public RepairInputError
alias remain compatible. No numerical manifest-listed file was changed during
this extraction; the CPD, duplex and coating manifests omit repair orchestration.

`core/part_repair_draft_host.py` defines required design ID, revision, draft ID
and generation guards. Creation explicitly expects no draft and receives its
new identity from the host. Update replaces proposed actions while retaining a
matching base; stale bases require explicit rebase. Rebase either rechecks the
saved actions or checks caller-supplied replacement actions, including their
explicit `expected_old` values. It never infers new expectations. Discard needs
only metadata capture and never fingerprints a broken/oversized recipe.

Preparation returns a new bounded `RepairDraft` or None. It never mutates the
captured/live model. A host still must recheck captured document identity,
revision, draft identity and generation atomically before publication. Captures
are private mutable containers despite their frozen top-level wrapper; never
publish them as models or let another thread mutate them during preparation.
Missing source bytes remain saveable; malformed descriptors/targets fail closed.

Source upload is a separate pending raw-binary transport seam. A source's base64
representation can exceed the 256 KB operation envelope even when its scientific
command is admitted. No source blobs belong in draft actions or these request
schemas, and these helpers do not raise operation/capture limits. Staged bytes
must be independently bounded, verified and attached to the existing source
table before a host captures a proposed source dependency.

Root selected draft editing independently of geometry undo. The eventual
metadata transaction should increment the revision for autosave/client ordering
without creating a feature row or taking a whole-model undo snapshot. Ordinary
geometry undo retains current draft metadata; explicit discard/consumption must
not be inferred from historical geometry snapshots.

Remaining seams: add the coordinated Design/ownership field; exclude it from
proof, numerical inputs and per-feature recovery; preserve it in ordinary
publication and whole-document/loadout/project/package persistence; add the
failure-atomic metadata transaction and endpoints; stage sources separately;
wire explicit evaluate/apply with matching draft generation; expose compact
derived pending/stale state and bounded source warnings. No hash or source decode
belongs on polling, normal rendering, or ordinary editing paths.

The [Onshape repair panel](https://cad.onshape.com/help/Content/Document/repairing.htm)
provides historical reference views while editing the current definition.
[Paused regeneration](https://cad.onshape.com/help/Content/PartStudio/features_and_parts_lists.htm)
separates deferred edits from displayed geometry. These inform the explicit
proposal/apply distinction; NADOC's durable base guards and independent draft
undo policy are implementation choices, not claims about Onshape internals.

## Metadata publication transaction foundation

`api/part_repair_draft_transaction.publish_draft` now accepts the host's current
lock-owned session and the privately captured session/source objects. It checks
session incarnation by object identity, document context, Design ID, revision
and draft identity/generation before transferring an already prepared proposal
into a shallow Design replacement. Close/reopen cannot reuse a stale capture
even when the same model object and revision were reinstated. It checks only
scalar preparation invariants, assigns one revision and rolls back the exact
source object, revision and request markers on exceptions or cancellation.

The helper owns no session registry or lock and imports no Design/state module.
No action, geometry, history, snapshot, source decode or fingerprint is traversed
while publishing. Its 35 focused cases use a small host schema while the
production Design boundary remains frozen. State/routes/Design persistence are
still pending; this helper alone is not a public draft API. Initial Apply will
retain the proposal; explicit discard is separate until generation-bound
consumption has its own reviewed transaction.
