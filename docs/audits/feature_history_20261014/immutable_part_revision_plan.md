# Immutable strict-part revisions: minimum migration

Reviewed migration plan, October 15, 2026. The pure immutable preparation and
materialization foundation passes 49 focused tests. The staged internal
session-content union and retention path now pass their focused regressions;
276 parent-run cases cover the state slice and existing permit, HTTP, scalar
read and cache behavior. The next internal evaluation adapter now passes 168
focused cases, including strict HTTP, real spawned batch publication and cold
verification. Public immutable creation remains disabled. Typed persistence,
qualified restore and responsiveness qualification remain pending. No
admission increase or baseline cache is included in this checkpoint. Compatibility
documents, assemblies and molecular algorithms remain unchanged.

The evaluation adapter retains the sealed source and actual session/revision/
policy under the shared lock. It materializes and applies the existing capture
profile outside that lock, then rechecks the exact context before admission.
Jobs retain the source handle, never the disposable decoded model. Candidate
transport still must retain both exact digests; non-proof state is carried from
a private source materialization before full candidate sealing outside the lock.
The existing private permit and atomic replacement publish the new handle with
the original handle as undo. Capture/transport/recovery/work limits and the false
public batch gate are unchanged. Repeated decode, allocation and GIL costs still
need measurement; outside-lock work alone does not establish responsiveness.

The obsolete test requiring evaluation to refuse immutable input was replaced
with the actual capture/commit lifecycle coverage. The old mutable verification
facade still refuses handles; strict verification uses the admitted evaluation
job path. See [evaluation validation](validation_immutable_evaluation_p6.json).

## Decision

Use one immutable serialized revision as the authoritative content of a new
strict-created empty/native-batch session. Do not retain both `session.design`
and supposedly authoritative bytes for the same revision. Mutable Design objects
exist only as private, disposable materializations used by the existing native
executor and validator outside the shared state lock.

This is a session storage variant, not a frozen flag on the current model graph.
Pydantic's frozen models still permit changes inside nested mutable containers;
that does not close NADOC's `Any` metadata, list and shallow-copy aliases.
[Pydantic model immutability](https://docs.pydantic.dev/latest/concepts/models/#faux-immutability)
Python `bytes` supplies immutable content, but authority still comes from a
host-owned handle and the publication permit, not a caller-supplied digest.
[Python bytes](https://docs.python.org/3/library/stdtypes.html#bytes)

## Single authority and representation

Prefer an explicit session-content union: empty, compatibility Design, or
`StrictPartRevision`. An alternative pair of fields is acceptable only with an
enforced exclusive invariant: exactly one of mutable Design/strict revision may
be present. Do not synchronize a mutable mirror, expose an automatically decoded
live getter, or replace every model with a new immutable schema.

A weak-referenceable frozen host handle contains:

- The canonical full Design JSON as immutable bytes, including normal recovery
  entries. This is the sole authored document content.
- Small immutable metadata derived by its private preparation factory: design
  identity/name/lattice, payload length, authoring/recipe digests, row/recovery
  totals and the versioned publication-scope qualification. These are derived
  indexes, not independently editable content.
- A private host identity distinct from byte equality. Equal content published
  twice is still a different revision. Session incarnation and monotonic revision
  remain on the host session; no file can restore their authority.

Use existing canonical encoding, model validation, exact transport projections
and scope checks when preparing the handle. Do not create another recipe codec.
Serialization and hash computation happen once outside the state lock; publishing
only verifies the private handle/seal and its bound context. Unknown versions or
unsupported fields are refused before publication. A loaded JSON label never
creates that host seal.

The initial handle admits only the currently reviewed strict batch envelope:
empty root, supported native rows, bounded authored work/recovery, and default
physical/presentation/source/draft state. Keep the public batch gate closed until
the complete lifecycle is measured. Representation changes cannot expand P4
coverage or grant independent replay evidence.

## Evaluation and publication path

1. Reserve the existing worker slot first. Under the state lock, validate trusted
   policy generation, document identity/revision and session incarnation, then
   retain the immutable source handle. This is constant-size work: no graph
   traversal, decoding, hashing, model validation or source snapshot.
2. Outside the lock, decode an owned Design from those immutable bytes and apply
   the existing capture projection/resource bounds. Exact authoring/recipe
   comparisons must catch any Pydantic normalization drift, including rotations.
   Recovery payloads stay excluded from the worker proof input. Decoding/copying
   can still be bounded or refused; it no longer owns the shared state lock.
   Python decoding and garbage collection may still hold the GIL and delay other
   request threads. Reduced lock holds are not proof of uninterrupted HTTP
   responsiveness; measure both independently.
3. Recheck the same source handle/session/revision/policy before spawning, then
   use the existing evaluator: source proof once, native commands, ordinary rows,
   recovery budget and validation. No extra solver, dispatcher or baseline-cache
   shortcut. Cancellation during materialization discards the private result.
4. After worker result decoding and exact transport guards, prepare the candidate
   revision bytes/qualification outside the state lock. In this first scope,
   `preserve_document_state` must operate only on the private decoded source; do
   not fetch a live mutable Design or alias any presentation/physical state.
5. Mint a permit bound to the source handle and exact candidate handle. Under the
   existing job-lock → state-lock ordering, recheck cancellation, expiration,
   incarnation, revision and policy; push the old handle for undo, swap the active
   handle, clear redo, bump once, then consume the permit. No mutable snapshot or
   whole-source scope scan remains in this lock section.

Do not pass a decoded source Design as the CAS identity. Update the existing
`AdmissionContext.source`, job source weak reference and
`verification_source_matches` to recognize the actual session-content handle.
The worker's private Design is only execution input. A closed/reopened session,
same-byte replacement or later revision must still invalidate old jobs.
Candidates and derived digests remain host-private until committed; poll never
exposes the handle or its payload.

## Reads, persistence and transitions

Strict revision/policy responses can use handle metadata under the lock. Future
canonical reads retain the bytes under the lock and send them outside it. Native
builders, renderer/export helpers and public response callbacks never receive a
shared decoded Design. Keep ordinary mutable getters for compatibility, but make
them explicitly reject strict storage instead of returning a mutable mirror.

Session-cache readers are mandatory migration seams, not optional background
work. `copy_doc_for_persist` currently deep-copies under the lock and
`session_cache._write_registry` uses `peek_design`. Add a typed persistence capture
that returns either the existing compatibility snapshot or the strict immutable
bytes plus revision; write outside the lock. Use a scalar metadata read for the
registry and document list. `list_doc_ids`, `has_design` and revision metadata must
recognize both representations. Avoid turning background flush into a hidden
large materialization or holding a live mutable alias across a lock boundary.

The cache audit found a lossy document mapping: `_doc_dir` sanitized characters
and truncated IDs to 80 characters, aliasing different raw identities and leaving
literal `.`/`..` intact. ISSUE-88 now rejects unsafe IDs without rewriting them,
before cache capture or strict HTTP body acquisition; 122 parent-run regressions
pass. Normal safe IDs retain their exact paths, and no existing file is moved
or deleted. Do not silently reintroduce arbitrary IDs or rename compatibility
paths. For typed strict persistence, prefer a separately versioned sibling directory,
outside `.session`, whose per-document component is the full SHA-256 of the exact
canonical document ID. A bounded typed manifest retains and verifies that exact
ID before read, write or restore. Digest/address equality without manifest
identity agreement is an error, not permission to overwrite. Existing legacy
cache files and path behavior remain untouched by this migration.

Startup pruning is another required seam: `start()` calls `_prune()` **before**
`restore()`, and `_prune()` recursively removes old or excess directories. Merely
skipping unsupported strict restoration would not preserve its file. The new
strict namespace must be outside that legacy traversal. Unadmitted/unsupported
strict files need a visible pending-recovery/quarantine status and a separately
reviewed retention policy; they must not be silently removed by the old age/count
rules. Bound new writes and refuse excess storage rather than deleting existing
user caches as an incidental migration. Do not nest the new namespace under a
legacy document directory where recursive pruning can erase it.

Restore is separate from flush: saved bytes and cached receipts do not recover
host publication authority. The current strict restore guard already refuses
generic installation. A future explicit restore path must validate size/schema,
regenerate the supported history independently, compare the materialized design
and qualify the scope before sealing it. Until that exists, leave cached strict
files intact and report unsupported restoration; do not silently discard them or
install them as native-authorized content. Do not advertise restart parity before
that path is implemented and tested.

Storage mode must not silently follow a policy configuration change. First-stage
recommendation: reject effective strict→compatibility transitions for a populated
strict handle, with an explicit conversion-required diagnostic; unchanged-mode
generation updates continue to invalidate jobs. Compatibility→strict does not
automatically adopt old mutable content. Existing documents may use bounded
nonpublishing verification, but immutable native publication requires explicit
qualified adoption or fresh strict creation. Closing a document retains host
policy bindings. A later trusted conversion should decode outside the lock,
CAS against the original handle/session/generation, and deliberately handle undo
history; it must never leave two authoritative representations.

## Cumulative undo and retention

Strict undo entries retain immutable handles rather than cloned graphs. This
removes the copy, not the memory cost. Keep the existing maximum step count and
add a separately measured cumulative serialized-byte allowance across current,
undo and redo handles. Count each retained handle once; no content-addressed
global cache is needed initially. Account for job/private candidate retention
separately under existing result/input limits.

Before publication, prepare the bounded retention decision outside the state
lock; revalidate against the same stack/version at commit. If necessary, discard
only the oldest eligible undo entries under an explicit documented policy,
preserving the immediate source for one-step undo. Refuse atomically when even
candidate plus immediate source exceed the fixed allowance. Do not select a
larger number from the existing per-candidate 16 MB transport bound: that bound
does not qualify 50 retained revisions. The exact cumulative allowance needs a
measured decision before public enablement.

Undo/redo remain unexposed until their own permit/effect contract exists. Tests
can validate retained stack identity and rollback now without granting a generic
snapshot-restoration bypass. After later admission, undo swaps a retained handle
and increments the host revision; it never restores an old session incarnation,
policy generation, permit or claimed cold-proof label.

## Small checkpoints and acceptance

1. Pure handle preparation/materialization tests: immutable payload, exact
   roundtrip, typed scope seal, malformed/oversize refusal, no model aliases.
2. Exclusive session storage with scalar/persistence adapters and explicit
   transition refusal. Keep native publication gated. Prove compatibility reads,
   snapshots, file formats and worker behavior unchanged.
3. Existing evaluation host adapted to source/candidate handles, including one
   undo and complete rollback. Bind request digest/session/policy exactly as now.
4. Qualify end-to-end strict empty creation plus mixed/max-command batch and
   retained history, then make an explicit gate decision. Cold replay and saved
   recipe editability remain independent acceptance oracles.

Required failures: source mutation attempts through every acquired materialized
model cannot change stored bytes; arbitrary saved JSON cannot mint a handle;
cross-session/same-bytes ABA; cancellation during decode/seal/commit; policy
changes before and after materialization; exceptions after stack/revision update
with permit retry; unsupported excluded state; byte-limit refusal without partial
stack eviction; absent-session reads never recreate; session-cache flush cannot
mutate or clone the authoritative graph.

Measure at least 30 samples per qualified boundary using actual HTTP start and
commit, concurrent lightweight revision requests and retained history. Report
lock wait/hold separately from outside-lock materialization, encoding, worker
startup/replay and publication. Include GC events, peak transient memory, retained
current/undo/result bytes, cancellation cleanup and cold proof. Keep failed
evidence and cooperative refusals visible. Immutable bytes remove a known alias
and lock-copy problem; they do not create a hard real-time or global heap guarantee.
