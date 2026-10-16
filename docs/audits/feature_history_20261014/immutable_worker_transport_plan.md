# Strict immutable worker transport: internal implementation and qualification

The internal transport and existing host wiring are implemented. This is not
latency qualification or public enablement: storage and registered-batch gates
remain false. The transport foundation passed 64 focused cases and the host
continuation passed 147 distinct cases; see
[validation evidence](validation_immutable_worker_transport_p6.json).

The current immutable source already has one exact canonical byte payload and a
private scope seal. Preparation checks full JSON roundtrip, reviewed source
scope, ordinary 30k-node/2 MB authoring admission, native work, and recovery and
transport limits. The preceding HTTP preparation decoded that payload
and walked its projection before starting the worker. Moving this work outside
the state lock has shortened lock holds, but Python/GIL and garbage collection
can still delay unrelated requests or exhaust the 25 ms projection allowance.

## Implemented internal boundary

Retain the exact sealed source and scalar session/revision/policy/request bindings
under the state lock. Validate the bounded public request and constant-size seal
metadata there, then admit the existing single worker slot. A private worker
constructor accepts the exact handle and canonical bounded request; neither a
saved JSON label nor a public request can select this input mode.

Use a versioned internal envelope containing the canonical source bytes and
bounded operation. Preserve the existing mutable capture/pickle path. Its 2 MB
pickle input ceiling cannot simply accept a complete strict document: that
document also retains up to 8 MB of recovery and has a separate 16 MB full-payload
ceiling. A strict raw-byte transport must state these separate limits explicitly,
without widening ordinary authoring admission. Allocate and populate its shared
input buffer only after admission, under the existing supervisor lifetime.

In the child, perform exact full-document decode/roundtrip and the shared owned
projection, retaining the same 30k-node/2 MB/25 ms accounting and prospective
batch scope/work checks before any native command. Recovery text remains excluded
from replay inputs. A source scope seal is not proof: existing source proof and
native executor composition still run. A deadline refusal becomes a nonpublishing
job result; there is no retry or relaxed budget hidden in this change.

Bind envelope format, source digest and canonical request digest to the child
result. The parent checks them against its private admission, not caller labels.
Existing session/source identity, policy generation, cancellation, expiry and
exact candidate transport checks remain required at publication. No seal is
restored from a serialized Python token and no mutable source mirror is stored.

## Required evidence

- Differential tests compare ordinary captured and strict-byte evaluation for
  the same complete authored source, including poisoned recovery and defaults.
- Bad envelope versions, lengths, source/request digests, JSON representations,
  oversized input and unsupported families fail before native execution.
- Stale source, close/reopen, policy change, cancellation during child decode,
  child failure, and result substitution never grant publication authority.
- Buffer cleanup and the existing two-result retention limit remain exact under
  spawn failure, cancellation, expiry and worker termination.
- Measure admission, shared-memory allocation/copy, child startup/decode/projection,
  candidate decoding/sealing, publication and concurrent lightweight HTTP
  requests separately at the existing workload boundaries.

Account for retained immutable source/history, shared input/output buffers,
decoded child graphs and private candidate results. Removing a parent traversal
does not prove a lower peak-memory bound. Candidate decode and sealing still run
in the parent at commit; this proposal does not eliminate their CPU/GIL cost or
claim a hard end-to-end latency guarantee.

## Provisional finite qualification decision

These engineering targets were agreed before measuring the byte-transport host.
They are measured acceptance criteria on this workstation, not runtime deadlines
or hard real-time guarantees. They do not change capture, recovery, command,
worker, transport or retention limits, and do not replace the existing paired
5% plus 0.05 ms regression gates for unchanged local/compatibility operations.

| Measurement, evaluated separately for each fixture | Proposed acceptance |
| --- | --- |
| Actual start → worker → commit samples | 30 successful cycles; no retry, fallback or omitted refusal |
| Independent correctness | Exact authoring, feature IDs, source bytes, revision and undo; independent cold proof for every fixture |
| State lock hold during start and commit | p95 ≤1 ms; observed maximum ≤5 ms |
| Start HTTP response | p95 ≤10 ms; observed maximum ≤100 ms |
| Concurrent revision HTTP during start | p95 ≤10 ms; observed maximum ≤100 ms |
| Parent commit HTTP response | p95 ≤100 ms; observed maximum ≤250 ms |
| Concurrent revision HTTP during commit | p95 ≤25 ms; observed maximum ≤100 ms |
| Complete ordinary strict job | Every sampled job completes within 10 seconds; existing 180-second supervisor deadline unchanged |
| Controlled cancellation/reaping cases | ≤2 seconds; no leaked process/buffer or released slot while a child is alive |
| One-active-operation peak memory | Parent plus live child RSS ≤ idle parent RSS after admitted retained state +256 MiB; exact payload retention remains separately bounded |

The latency sampler must cover actual lifecycle requests and concurrent scalar
reads, with enough overlapping reads to report each phase independently. Report
the idle scalar baseline, first-start costs, p50/p95/max, observed worker duration,
lock wait/hold, and cleanup. Retain all GC-overlap samples in the verdict; never
subtract GC time, force collection, disable GC, change thresholds, or retry an
operation to obtain a passing result. Traced allocation runs are separate from
latency runs. A normal process exit or correct aggregate output alone is not a
qualification pass.

The default four-case harness preserves the earlier before/after workload: up to
32 commands, mixed DNA/gold/grouping, 50,000 authored residues and 64 total rows.
Those sources are only approximately 42–307 KB. They do not qualify the full
storage/retention envelope. The separate optional retention stress must include
opaque recovery text near the existing 8 MB bound, current/undo handles near the
existing 32 MB allowance, and both existing result slots occupied. Such recovery
text is storage stress only: it is never decompressed or treated as proof, and
native geometry and command inputs stay unchanged. Report exact retained/result
bytes; two occupied slots do not by themselves qualify two maximum-size results.

Memory evidence must cover retained immutable handles, shared input/output,
parent candidate decoding/sealing and child decode/projection/evaluation. Parent
Python tracemalloc alone excludes native and worker allocations; process lifetime
RSS high-water includes earlier fixture construction and cannot be called an
incremental operation peak. Use a separately scoped sampler/baseline and retain
these limitations. The +256 MiB target is for one active operation on the measured
host, not an application-wide heap cap across all documents. Weak-reference and
catalog/process cleanup checks establish ownership release; allocator RSS need
not return immediately to its initial value.

Durable create/flush/restart/restore/edit correctness has separate focused
evidence. Its actual filesystem latency remains a distinct qualification subject
to repository artifact/storage rules. Public gates stay false until all relevant
scope, correctness, lifecycle, latency and memory evidence is reviewed explicitly.

## Measured byte transport checkpoint

The corrected four-case run completed120 publications and four independent cold
proofs at30 repetitions per case, without retry or dropped GC samples. All
predeclared latency targets passed for those42–307KB sources. Start p95 was at
most6.99ms; commit p95 at most69.59ms; concurrent commit-read p95 at most21.34ms.
Maximum observed state-lock hold was0.30ms. The scoped3-repeat RSS diagnostic
recorded all12 operations within the existing +256MiB target.

Separate near-retention stress retained31,995,904 bytes across four sealed
handles, one7,998,976-byte source and two ready results of321,517 bytes each.
All three publications, independent cold proof, exact undo eviction and cleanup
passed. Scoped RSS increased at most178,237,440 bytes, with sampling gaps up to
57.41ms; this is sampled evidence, not a hard heap guarantee. Commit concurrent
reads reached p9554.53ms, exceeding the declared25ms criterion. Public gates
remain false. Two occupied small results do not qualify two16MB results.

The next review concerns removing a full source materialization used solely for
non-proof metadata preservation. Any replacement must derive only from the
exact host seal, retain ID/annotation state, enforce an explicit closed source
scope and fail closed when preservation requirements expand. No thresholds or
input limits are raised.
