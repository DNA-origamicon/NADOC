# Strict immutable worker transport: proposed next increment

This is a read-only design proposal, not an enabled transport or a claim of
latency qualification. Public storage and registered-batch gates remain false.

The current immutable source already has one exact canonical byte payload and a
private scope seal. Preparation checks full JSON roundtrip, reviewed source
scope, ordinary 30k-node/2 MB authoring admission, native work, and recovery and
transport limits. Repeated HTTP preparation nevertheless decodes that payload
and walks its projection before starting the worker. Moving this work outside
the state lock has shortened lock holds, but Python/GIL and garbage collection
can still delay unrelated requests or exhaust the 25 ms projection allowance.

## Proposed boundary

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
