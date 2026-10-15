# Strict immutable recovery: publication prerequisite

The internal session-content union is staged behind a false public creation
switch. Switching strict creation requires this recovery path and the existing
evaluation jobs' immutable-handle adaptation. A private storage seal alone
cannot grant restore or publication authority.

## Durable record

Use a versioned sibling of the existing `.session` directory, never a child of
it. Legacy age/count pruning and close cleanup must not traverse this sibling.
Each record name is the full SHA-256 of its exact, already validated document
context identity. Normal compatibility paths and existing files stay unchanged.

One atomic record contains a fixed magic/version, bounded manifest length,
strict JSON manifest, then the unchanged canonical full Design bytes. Framing
the existing Design payload avoids a second recipe format and avoids the crash
window between independently replacing a manifest and its payload. The manifest
contains only storage version, exact document context identity, payload length
and digest; saved proof labels, session identities and policy generations confer
no host authority. Display metadata can be derived after bounded decoding.

The per-payload ceiling remains 16 MB. The manifest has its own small fixed
ceiling. A proposed namespace count cap is the existing 50-document cache count,
with refusal rather than automatic removal. This count is a bounded storage
proposal, not a measured process-memory allowance. Unknown records and failed
temporary writes remain visible and consume admission; they are never silently
deleted to make room. Final limits and refusal behavior require review before
public enablement.

Open the sibling directory without following a symlink and perform record/temp
operations relative to its directory descriptor. Files must be regular files;
reject symlinks and malformed record names before acquiring their contents.
Exclusive temporary creation, bounded writes, flush/fsync and atomic replacement
must preserve either the old complete record or the new complete record. A first
write uses atomic create-if-absent, never replacement of an unknown prior record.
No request supplies a filesystem path.

## Host ownership and overwrite prevention

The existing session-cache owner receives a new typed persistence capture. Under
the state lock it retains only the sealed handle and document/session/revision
scalars. Encoding and file work remain outside the state lock. Compatibility
captures retain their existing snapshot path; mutable getters never decode an
immutable document automatically.

One writer owns a bounded prior-record lease for each active strict document.
The lease binds the exact manifest, record identity and document identity, not a
client-provided digest. Updating a record rechecks that lease outside the state
lock and fails if the record changed. New writes cannot overwrite an unqualified
pending record from an earlier process. Cooperative writers need a defined
serialization mechanism; arbitrary external filesystem writes are not an
authentication or sandbox guarantee.

Fresh empty creation must first establish that its durable document identity is
unused. In particular, a restarted `__default__` with pending strict content must
refuse fresh creation and offer recovery or a different identity. There is no
discard/delete endpoint in this increment. Reserve the actual empty host session
before expensive preparation, then acquire/write against the absent-record lease
outside the state lock. Final publication still checks the exact reservation,
revision and policy generation. If the session closes during preparation or the
first durable write, preserve the record as pending recovery and never recreate
that session. Failed publication is not permission to delete durable content.

## Restore

Startup discovers a bounded set of manifests and reports pending recovery.
Corrupt, unsupported, oversized or unqualified records are preserved. Discovery
does not parse an unlimited directory, create a live Design, or infer authority
from saved labels. The explicit strict recovery status/read and restore route
must exist before the public immutable-creation switch is enabled.

Restore binds the current canonical document context and expected revision. It
requires an empty session with empty undo/redo and auxiliary state; it never
replaces an active document. Admission reserves that actual session identity
under the current strict host policy before reading/decoding the record outside
the state lock. A closed/reopened reservation invalidates the work.

Reuse the existing single `_slot`, `VerificationWorker` and supervisor. An
ephemeral restore job can bind source `None`, the reserved session identity,
revision and policy generation: the existing supervisor already checks those
against the actual empty session. No second worker queue, builder dispatcher or
mutable live placeholder is needed. The private decoded Design must pass
ordinary capture bounds and independent cold replay. Require a native `verified`
assessment, then prepare the immutable scope seal and issue a distinct
host-owned restore permit. The permit binds the exact candidate, reservation,
file lease and successful host-observed assessment; file metadata cannot mint it.

Publication uses the existing failure-atomic replacement transaction. It creates
one new host revision and no undo of an absent source. Policy changes, cancellation,
deadline expiry, changed files, nonempty sessions and session ABA refuse without
modifying either live state or durable records. A failed cold proof remains a
pending recovery result, not an empty part or a silently imported root.

## Acceptance and measurement

Tests use only owned temporary directories, with no application lifespan or user
workspace. Cover complete atomic write/read, unknown/truncated/corrupt frames,
digest/length/document disagreement, unsafe/symlink paths, bounded scans and
retained unknown files. Inject failures before replacement and after durable
write; the previous record or explicit pending record must survive intact.

Host tests cover restart discovery, pending-record fresh-create refusal, real
cheap native cold restore, poisoned recovery bytes, unsupported history, policy
change, cancellation, close/reopen ABA, one revision, permit one-use and complete
rollback. Existing compatibility cache/prune tests must remain green. A real
saved/restarted supported recipe must remain independently editable after restore.

Measure immutable capture, private decode/encode, actual durable flush/restore,
publication and concurrent lightweight HTTP requests separately. Removing model
copies from the shared lock does not remove Python/GIL or garbage-collection
latency, disk latency, or transient retained bytes. The public batch and immutable
storage gates remain false until their complete lifecycle evidence is reviewed.
