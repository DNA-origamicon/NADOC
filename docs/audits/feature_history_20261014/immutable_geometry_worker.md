# Immutable native extrusion worker

U46, October 17, 2026. FH-28 checkpoint 2; no milestone closed. This completes
private worker evaluation on the U45 storage scope. Live publication, undo and
ordinary editor integration remain the next boundary, not a claimed delivery.

## Implemented boundary

`part_immutable_geometry_worker` reserves the exact sealed extrusion source
without decoding or projecting its authoring in the parent. Its distinct
`NADOC-G1` frame retains the existing bounded immutable-byte transport and hashes
the exact source bytes and original edit request. The old batch worker cannot
accept this frame or ticket; the geometry worker cannot accept a batch frame.
Scope checks occur again at encoding, not merely when a ticket is reserved.

The child validates an exact operation envelope, explicit revision, document,
feature identity, kind and extrusion contract. The selected feature must match
the captured source. It normalizes the requested patch against that source's
parameters, preserving output identities and protected receipts. No arbitrary
identity/version patch, generated extrusion or routing-child edit is admitted.
The normalized request stays inside the child; result binding remains to the
original request sent by the host.

The existing owned extrusion evaluator then proves the entire source and
regenerates the edited suffix with the native prefix binder. The candidate gets
an independent Design schema and storage-scope check before transfer. Recovery
payloads remain non-authoritative. No native builder, molecular constant or
definition schema was changed. No permit, session mutation or public gate was
added in this checkpoint.

The original immutable process runner now shares its fixed framing/lifecycle
code with the new worker. It releases the child's shared input handle after
owning the bounded bytes and before preparation. A request cannot choose a
Python evaluator or process target. Both workers retain existing result size,
exit-code, digest-binding and cleanup checks. There is no additional queue or
independent publication path.

## Validation

126 unique focused backend tests passed, without warnings:

- 22 native/transport geometry-worker tests and 30 existing immutable-worker tests:
  52 passed in 18.52 s after the final runner lifetime change.
- 22 geometry-scope, 27 immutable-evaluation and 24 recovery-transport tests:
  73 passed in 6.08 s.
- One additional runner input-lifetime regression passes separately.

All seven extrusion families were edited in actual spawned workers. Each result
preserves feature identities and downstream definitions and independently
regenerates with poisoned recovery. Additional tests refuse altered document,
revision, feature or kind, unknown headers, wrong operation, child edits,
missing revision, protected identity patches, invalid input types, mismatched
transport, corrupted materialized source and substituted result binding.
An injected cooperative deadline still refuses in the child. Parent reservation
and encoding are tested with source decode/projection forbidden.

This is software evidence, not latency qualification: the child still has a
25 ms capture deadline and may refuse under GC/scheduling pressure. Parent
hashing, worker startup and commit preparation still need app measurements.
The new worker is not yet wired to live ordinary editing, so U44's production
responsiveness defect remains open. No mutable document is automatically sealed
or migrated, and no field/history/resource bounds are raised.

Changed-file Ruff and diff whitespace checks pass. `test-smart --dry-run` reports
the accumulated FULL selection and FAST fallback; zero broad tests ran. Its
literal notice, not an assertion that FAST executed:

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

NOT VERIFIED IN APP. No frontend behavior or machine-specific VR validation.
FH-28 durable creation/recovery/publication and retained-state qualification,
FH-27 app performance and the remaining standard-tool catalog remain required.
Memory lint remains at its baseline six errors and 59 warnings; project head is
200 lines. Cleanup removed 133 completed pytest directory/symlink entries with
zero regular-file bytes after no readable same-user process references were
found. PIDs 435/436 remain uninspectable. Pytest scratch and shared memory are
empty; user designs and existing caches were preserved.
