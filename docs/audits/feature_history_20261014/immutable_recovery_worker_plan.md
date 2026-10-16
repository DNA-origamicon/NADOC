# Move strict recovery preparation into its admitted worker

Status: implemented through owned handoff and bounded transport optimization,
2026-10-15; historical proposal and staged evidence retained below. The 30-cycle
in-memory diagnostic passes its sampled thresholds; durable-file/app qualification
remains open. Public strict storage/batch gates stay closed; assemblies and VR
remain deferred. Root owns serialized validation.

## Evidence and decision

[The phase diagnostic](benchmark_immutable_recovery_phases.json) completed six
native cold recoveries across three memory-only cycles. Parent `prepare_stored`
took approximately 164–187 ms: initial JSON decoding 24–26 ms, first canonical
encoding 29–39 ms, exact roundtrip 66–71 ms **including** another 23–28 ms encoding,
and recipe digest 28–36 ms. Ordinary authoring admission was approximately
0.12 ms. Concurrent scalar reads reached approximately 157.9 ms, with short
state-lock holds. Nested phase durations must not be added; interval overlap is
not a CPU/GIL trace. The evidence does not establish GC as the cause.

Move the complete existing preparation and native proof into **one** admitted
spawned recovery worker. Keep the current preparation algorithm as the reference
and initial child implementation. This removes the large decode/model/encoding
work from the parent without weakening its checks or adding a second worker,
queue, parser, numerical algorithm, or larger budget. Shaving one repeated pass
does not address the other substantial parent phases.

The initial [memory evidence](validation_immutable_recovery_memory.json) remains
valid for its old path only. Its sampled 256,552,960-byte maximum increase was
below the 268,435,456-byte target, but sampling gaps prevented a hard peak bound.
Neither diagnostic exercised a real file lease or durable commit.

## Existing seams

| Existing code | Preserve or adapt |
| --- | --- |
| `api/part_immutable_recovery.py:188` | `_run` owns the original admission, source/session/policy, storage owner, file lease and five-second deadline. Currently calls preparation in its parent supervisor thread before spawning proof. |
| `api/part_immutable_recovery_inputs.py:38` | `prepare_stored`: bounded manifest/hash, duplicate/nonfinite rejection, raw structure, model validation, full preparation, exact saved-byte equality and ordinary capture. Preserve as oracle and child implementation. |
| `api/part_immutable_revision.py:215` | `prepare_revision`: scope, work/count/byte limits, canonical full-document roundtrip and every metadata digest. Its local child seal never crosses the process boundary. |
| `api/part_immutable_worker.py:53` | Existing framed byte transport and input/result digest binding are the model. Its public boundary requires an already sealed source, so do not admit raw recovery through `reserve_input` or weaken `_project`. |
| `api/part_verification_worker.py:97` | Reuse bounded shared-memory allocation, spawn, completion sentinel, exit checking, reaping and unlinking. Ordinary pickle input/output limits remain unchanged. |
| `api/part_verification_jobs.py:67` | Reuse `supervise` and its final cancellation/session/policy checks. No slot is released while a child is alive. |
| `api/part_immutable_recovery.py:233` | Keep original qualification, permit and file-bound publication. Recovery bytes or a preparation seal alone still grant no publication authority. |

Paths above are under `backend/`; line numbers describe the reviewed checkpoint.

## Proposed private flow and trust boundary

1. Keep current HTTP admission and the shared operation slot. Read the bounded
   stored bytes and real lease through the original `StrictPersistence` owner.
   Parent retains the exact immutable payload and lease. Perform only fixed
   header/length/hash and context checks here; do not decode a `Design`.
2. Create a private recovery input ticket bound to that job's original admission,
   request digest, document/session/revision/policy, payload object and hash.
   Its wire frame has a distinct fixed recovery version and length/hash checks.
   Bound payload by the existing 16,000,000-byte ceiling, with a small separately
   bounded header. No HTTP field or saved label selects this transport.
3. In the same spawned child that will prove the recipe, verify the frame and
   execute unchanged `prepare_stored` semantics. The child receives bytes and
   manifest scalars, **not** a parent file lease or session. A small pure-byte seam
   may be extracted under the reference wrapper to avoid manufacturing a lease.
   Preserve explicit duplicate-key and nonfinite rejection before model loading;
   the existing sealed-source `_decoded_exact` alone is not the recovery parser.
4. Preserve the ordinary 30,000-node/2,000,000-byte/25 ms capture and native work
   limits. Also preserve the separate actual **2,000,000-byte pickle admission**
   currently performed by `VerificationWorker.__init__`: moving the handoff
   inside one process must not silently remove that limit. Reuse its bounded
   private serialization in the child, release the temporary bytes, then use the
   same native proof executor. Any removal of redundant copying is a later,
   separately proven optimization.
5. Return bounded JSON containing only the exact input/request binding, the
   preparation metadata and ordinary proof report. The existing 2 MB proof-result
   ceiling is sufficient; there is no need to return a second 16 MB candidate.
   No serialized `StrictPartRevision`, `_ScopeSeal`, `_Qualification`, Python
   object, `verified` shortcut or new geometry payload is accepted.
6. After observing the owned child exit successfully and validating its bound
   report, the parent creates a **nonserializable completion observation** tied
   to that exact worker, ticket, payload and admission. After successful final
   supervisor cleanup/context/deadline checks, a recovery-only factory consumes
   this observation to mint a fresh local scope seal around the original parent
   bytes. It then creates the existing job/candidate-bound qualification. A
   plain report dictionary cannot call that factory; observations cannot be
   copied between jobs or reused to seal another payload.

This deliberately makes the fixed, reviewed child preparation code part of the
trusted implementation, as native proof already is. Hashes bind a result to its
input; they **do not independently prove its computed metadata**. The parent
must not accept an arbitrary caller's purported worker report or private seal.
It must not repeat full decoding merely to create a local seal, which would
reintroduce the measured stall. Same-process arbitrary code execution and a
compromised worker implementation are not newly claimed security boundaries.

The host validates the exact `RevisionMetadata` field set, strict scalar types,
bounded nonempty ID/name, known lattice/storage/scope/preservation versions,
payload length, digest formats, history/recovery limits and Boolean presentation
flag before minting. Cross-check proof `authoring_fingerprint` against metadata
`authoring_sha256`. Do **not** equate proof `recipe_fingerprint` with storage
`recipe_sha256`: the former hashes executable commands, while the latter also
preserves full rows and opaque recovery. Exact metadata correctness is established
by the fixed child algorithm and differential tests, not by a new hash label.

The ticket initially has no trusted Design ID: a document ID is not necessarily
the Design ID. Keep failure reporting explicitly unresolved until validated child
metadata supplies it; do not decode the parent payload just to satisfy
`supervise`'s current `design.id` reporting convention. Keep any necessary adapter
narrow and preserve other supervision callers.

The deadline remains `job.created + 5.0`, including read, frame transfer, spawn,
preparation, proof and final eligibility. Pass only remaining time to supervision;
never restart five seconds at child launch. Termination/reaping can outlast a
deadline for safe cleanup as today. Keep two result slots, their existing expiry,
pending-file preservation, final empty-session CAS and publication rollback.

## Why not streaming or fewer passes first?

The project uses CPython 3.12. The [Python multiprocessing documentation](https://docs.python.org/3.12/library/multiprocessing.html)
explicitly describes processes as bypassing the shared interpreter lock; spawn
starts a fresh interpreter. The existing supervisor is a thread, so it does not
provide that isolation.

`iterencode` promises available chunks, not a time or chunk-size bound. The
[CPython 3.12.3 encoder](https://github.com/python/cpython/blob/v3.12.3/Lib/json/encoder.py#L360-L361)
encodes a string value before yielding it. One multi-megabyte escaped recovery
string can therefore remain one large chunk. The [JSON decoder API](https://docs.python.org/3.12/library/json.html#json.JSONDecoder.raw_decode)
decodes a document and reports its ending index; it supplies no resumable
incremental parser. A custom canonical streaming implementation would add
duplicate-key, Unicode, number, escaping and depth correctness obligations while
model validation and recipe hashing would still remain.

[Python documents that hashlib releases the GIL for inputs above 2047 bytes](https://docs.python.org/3.12/library/hashlib.html#hash-algorithms).
This supports retaining bounded raw-byte integrity hashing in the parent; it does
not establish a latency guarantee for hashing, allocation, shared-memory copies
or scheduling. Remeasure these after moving preparation. Avoid GC-policy changes,
retries, deadline increases or changing canonical bytes to improve the result.

Previously researched CAD immutable/versioned-input and asynchronous-result
precedents remain consistent with this proposal. They do not document an Onshape
or SOLIDWORKS Python/GIL/worker implementation, so no such vendor claim or new CAD
policy decision is needed for this execution-boundary change.

## Tests first and checkpoint sequence

1. **Reference parity before wiring.** Preserve `prepare_stored` and build
   differential fixtures for empty, gold and DNA/group recipes, ordinary recovery
   text, escaped control characters, Unicode names, annotations flag and supported
   metadata. Child preparation must match every metadata field and exact full
   bytes. Poisoned recovery remains retained but unused by proof; unlogged
   geometry never qualifies. Retain current parser/scope failures: duplicate keys,
   nonfinite/deep JSON, omitted fields that normalize, saved seal labels, unknown
   fields/commands, incorrect manifest and all existing budget boundaries.
2. **Transport and authority negatives.** Wrong lengths/hash/version, trailing or
   truncated bytes, swapped same-sized sources, other request/session/admission,
   forged/copied completion, child-supplied seal, malformed metadata, mismatched
   authoring fingerprint, report without successful exit and failed/overflowed
   proof must produce no host candidate or qualification. Parent full-document
   decode/preparation is tripwired in the real integrated worker test.
3. **Owned lifecycle.** Exercise cancellation/deadline during child preparation,
   process failure, constructor/start failure, cleanup failure, cache-owner change,
   close/reopen/policy ABA and source-file change. Preserve slot ownership through
   reaping, buffer unlinking, two-slot eviction/release and existing real small-file
   recovery/commit/rollback/retry tests. Keep the original five-second deadline;
   ordinary mutable verification and sealed batch worker tests must stay unchanged.
4. **Measured gate after correctness.** First rerun the same three-cycle in-memory
   diagnostic with natural GC and phase/RSS/concurrent scalar-read observations.
   Only after investigating any remaining stall proceed to the plan's 30 samples
   and unchanged lock/start/light-read/memory targets. Do not treat successful cold
   proof or a sampled memory peak as latency/publication qualification.

Memory-fixture correction is necessary for the new ownership path: two real file
reads allocate independent payloads, but the current substituted read returns
one shared fixture `bytes`. Returning parent input bytes as ready candidates would
then under-exercise simultaneous near-16 MB retention. The diagnostic must supply
independent payload allocations and keep the near-32 MB background source/undo,
without adding a redundant production copy. Report allocation in its real phase.
Large file qualification still requires Archive; memory-only reads cannot claim
durable commit coverage.

Likely implementation boundaries: new private recovery-worker/observation module,
narrow `_run` and revision-seal integration, reference preparation preserved, and
focused recovery transport/parity tests. No public API expansion, numerical pins,
geometry formulas, compatibility promotion, or storage-budget change belongs in
this checkpoint.

## Exact proposed callables: tests-first stage one

The module is `backend/api/part_immutable_recovery_worker.py`; it was absent
at the tests-first checkpoint. `tests/test_immutable_recovery_worker.py`
imports it lazily. Interfaces agreed with root:

```python
reserve_input(stored: StoredRevision, *, admission: EvaluationAdmission) -> RecoveryInput
encode_input(ticket: RecoveryInput) -> tuple[tuple[bytes, ...], dict]
evaluate_payload(payload: bytes) -> dict

class RecoveryWorker(VerificationWorker):
    def __init__(self, ticket: RecoveryInput): ...
    def result(self) -> dict: ...
    def take_revision(self, ticket: RecoveryInput, *, admission: EvaluationAdmission) -> StrictPartRevision: ...
```

`RecoveryInput` has a guarded constructor, frozen slots, `payload` retaining the
exact stored `bytes`, the actual registered `admission`, a fresh per-ticket string
`nonce`, and `id=None`. No file lease is transported. Reservation validates the
record's fixed manifest length/hash and document against the registered recovery
context without parsing its document. Encoding preserves the ticket and binds
at least transport version, `nonce`, `source_sha256` and `request_sha256`; the
ticket retains the original complete admission context. Stale policy/context or
an unregistered admission refuses transport.

`evaluate_payload` is the pure child implementation and returns only
`{"issues": [], "binding": ..., "metadata": ..., "result": ...}`. Metadata
matches `dataclasses.asdict(revision_metadata(reference_candidate))`; the result
is the existing ordinary proof report. Failure cannot produce a host seal or
candidate. No user JSON carries an admission object or supplies a nonce to the
parent reservation. A syntactically valid child frame remains data without the
parent's exact private ticket and completion observation.

Use the existing **2,000,000-byte total result envelope** for this slice, including
binding and metadata. This deliberately leaves slightly less space for the proof
report than a bare 2 MB report; overflow returns the bound `result_limit` refusal
without completion. Do not silently raise the ceiling. A hypothetical 4 KB
metadata allowance would not cover the currently admitted 1024-character Unicode
ID and name under canonical ASCII escaping. Output encoding/capacity and malformed
result-observation tests belong to the actual worker stage; the pure evaluator
returns its dictionary before that bounded encoding.

`result()` retains a private successful observation on the exact worker after
zero exit, binding and strict metadata checks; its public return is only the
ordinary proof dictionary. `_run` keeps the worker reference through a small
factory closure, allowing existing `supervise` to remain the lifecycle owner.
Only after successful cleanup, final supervision guards and the original recovery
checkpoint does `_run` call `take_revision` with the original ticket/admission.
That one-shot method requires a closed successful worker and consumes its private
observation; revision integration accepts that observation, never arbitrary
`(bytes, metadata)`. The existing job qualification is created separately.

Stage-one tests cover pure reference parity, poisoned recovery, metadata and
document-ID preservation, raw framing, untrusted JSON and scope refusal, existing
admission/pickle bounds, and refusal to mint from an unstarted or forged worker.
They start no process and write no cache file. Stage two adds malformed returned
reports/completion reuse, successful parent sealing, parent decode tripwires and
real supervised cleanup/context/publication regressions before host wiring is
claimed complete. Root runs the red target before production implementation.

## Stage-one checkpoint

The private worker is implemented and unmounted. Root first ran three existing
reference controls successfully, then observed the intended missing-module error
on the new parity target. All initial 40 cases passed after implementation;
18 additional framing/admission/lifetime-of-context negatives then brought the
target to **58 passing cases in 3.07 seconds**. Changed-file Ruff and whitespace
checks pass. No child process, disk cache or publication ran in this stage.

Reservation checks the actual empty session incarnation/revision and policy,
as well as the registered restore operation and scope. Exact manifest scalar
types reject bool/int and string-subclass equivalence. Independently corrupted
lengths, transport/storage versions, canonical content, unknown commands and
nonfinite/duplicate JSON refuse before proof. Empty, gold and DNA/group fixtures
match every reference metadata field and complete proof report, with saved
recovery poisoned. Existing capture and actual 2 MB pickle admission remain.

At the stage-one checkpoint, `take_revision` **always refuses** with `recovery_seal_unavailable`.
Positive worker completion, output overflow, zero-exit/cleanup, one-shot parent
sealing and host integration are not established by these pure tests. They are
the next separate checkpoint; existing parent preparation remains active. No
public gate, model, scientific helper or numerical pin changed. See
[the validation record](validation_immutable_recovery_worker_stage1.json).

## Stage-two host handoff

The host now sends the original stored bytes to the recovery child, which runs
the unchanged full canonical preparation and native proof. The result remains a
bounded JSON report. Only the exact worker's successful zero-exit observation,
after reaping and buffer cleanup, can seal those original parent bytes. The
revision entry accepts a worker/ticket/admission, never arbitrary bytes and
metadata. Completion has both worker ownership and self identity; one lock
serializes result observation and one-shot consumption. This rejects copied,
swapped, reused and concurrently recreated completions. Child metadata remains
trusted fixed-implementation output, not something proved solely by its hashes.

Recovery preserves the original `created + 5 seconds` deadline. After supervision
it checks that the exact job is still retained, its registered admission matches,
the storage owner is unchanged, and the document/session/policy is positively
current. Busy state probes refuse positive retention. It checks again after
revision taking before attaching the existing qualification. Original file-lease
ownership, final commit comparison and rollback are unchanged; no disk operation
runs under the job or completion lock.

Root observed **26 passes / 11 failures** in the 37-case worker target before
implementation: ten unavailable positive handoffs and one concurrent result-read
race. The new host target was **1 pass / 12 failures**, all from the old parent
preparation/unused worker seam. After integration, **144 cases across four files
passed in 19.37 seconds**, including real empty/gold/DNA child processes, parent
decode tripwires, exact complete metadata, crash/2 MB output overflow, original
deadline, cleanup failure, eviction and final publication guards. An additional
**240 relevant regressions** passed alongside 17 finite-linker cold replay cases
in a 257-case, 14.30-second run. No per-test budget was exceeded.

The old recovery test double was replaced with actual worker result validation
and cleanup at a controlled transport boundary; its existing file/commit/rollback
assertions remain. Obsolete host imports of parent preparation and the old worker
were removed. Public gates and all budgets are unchanged. Near-cap independent
read allocation, retained memory and HTTP response measurements remain the next
checkpoint. See [validation](validation_immutable_recovery_worker_stage2.json).


## Transport storage and paced measurement

The first worker diagnostic exceeded the 256 MiB incremental RSS target in two
of three cycles. Its tight-loop scalar probe also exhausted its 256 samples
before final result validation/cleanup/handoff. Both findings and the initial
report are retained. The local probe now spaces reads by 20 ms, stops promptly
with its operation and explicitly records exhaustion, sampling intervals,
uncovered tails and per-phase overlaps. Five focused sampler controls pass.

One common frame parser copies only the fixed header, exact source and bounded
context. It validates those immutable copies, releases every view, and the child
closes its input mapping before canonical preparation. A loader retaining only
buffer names/sizes avoids keeping a caller frame through proof. Platform mapping
padding is allowed, while declared size must fit the mapping and exactly match
the frame fields; this follows [Python's shared-memory contract](https://docs.python.org/3/library/multiprocessing.shared_memory.html).
A failed input close refuses before preparation. Parent input identity, all
canonical/proof checks, one-shot authority and resource limits are unchanged.

Before the change, 13 controls passed and nine cases failed on the intended
lifetime/copy/length defects. Afterward, 168 unique recovery cases pass across
five files, including the final 24-case transport target and real spawned
lifecycle/host/commit regressions. The overflow fixture now enlarges the actual
proof result, retaining the real bounded output encoder.

With identical paced harness hashes, three-cycle maximum sampled RSS increase
fell from 284,725,248 to 253,104,128 bytes. A further 30 cycles completed all 60
proofs and cleanup; all sampled increments stayed below 268,435,456 bytes
(maximum 255,447,040). Start p95 was 8.48/7.54 ms for first/second retained
results; completion-read p95 was 3.35/3.40 ms. Maximum state-lock hold was
1.304 ms and all completions remained inside the original five seconds.

These are diagnostic measurements, not hard peak/heap or full-app guarantees.
RSS gaps reached 24.22 ms; combined RSS double-counts shared pages. Late result,
cleanup and handoff phases overlapped reads in 4, 19 and 5 of 60 observations,
respectively; other intervals remain unmeasured for responsiveness. Per-cycle
idle RSS includes retained benchmark records and allocator state. Durable
leases, file reads/commit, large-file storage and app lifecycle remain separate.
Public gates/qualification flags stay false. See [validation](validation_immutable_recovery_transport.json).
