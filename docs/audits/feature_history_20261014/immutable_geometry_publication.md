# Private immutable extrusion publication and history

U47, October 17, 2026. FH-28 checkpoint 3: **task growth flagged**. This is the
third prerequisite checkpoint on the immutable geometry path, not closure of
FH-28 or a new milestone. Fixed remaining exits and the 38-milestone total stand.

## Delivered boundary

`part_immutable_geometry_host.edit` connects U46's native worker to the existing
one-shot permit registry and failure-atomic replacement transaction. It owns the
bounded request, reserves the exact source under the document lock, and performs
worker evaluation, candidate decoding and immutable preparation outside that
lock. It retains the existing shared operation slot/supervisor, five-second
transaction budget, result/resource bounds and exact source/session/revision/
policy checks. Worker failure diagnostics propagate to the caller.

The separate `immutable_extrusion_edit_v1` publication scope checks the exact
admission/request, candidate handle, authoring/recipe digests, unchanged history
row count and preserved-document digest. The old batch permit remains closed to
these sources. Gate, policy, expiry and cancellation are checked again after undo
retention preparation, immediately before assignment. Successful publication
consumes the permit and creates one immutable undo entry; failures restore the
exact source handle, both stacks, revision and request markers.

Explicit private undo/redo restores only retained handles in the same storage
scope and document. It performs no model copy, materialization or regeneration.
It checks exact current revision and bounds the combined stack count, preserves
monotonic revisions and rolls back an assignment failure. An edit after undo
clears redo through the existing replacement transaction.

One trusted switch, `part_immutable_geometry_publication.ENABLED`, defaults false
and is checked under registered-only host policy. No HTTP endpoint, saved flag,
environment variable or request property enables this path. No public document
is converted or migrated. Test setup installs private sealed fixtures directly;
this is not evidence that creation/recovery/editor routes are integrated.

## Validation

151 unique focused tests pass without final warnings:

- 34 host tests + 31 immutable-state + 34 permit tests: 99 passed in 5.19 s.
- Final 37 host tests + 22 geometry-scope + 27 immutable-evaluation tests:
  86 passed in 7.56 s; 34 host cases overlap the preceding run.

All seven extrusion families pass full host publication, independent poisoned-
recovery replay and exact-handle undo/redo through controlled native transport.
One case also uses the real spawned worker through commit. Tests cover off-lock
candidate preparation, preserved annotation state, original request ownership,
revision/source/session/policy/gate changes during evaluation and preparation,
cancel/deadline refusal, permit request/digest/candidate substitution, one-shot
consumption, retention refusal, redo invalidation, revision-failure rollback and
final liveness checks after retention preparation. Scratch and worker cleanup
are checked separately.

The first run had 25 passes and one invalid test expectation: replacing semantic
content inside the trusted worker result was expected to be independently caught
without another proof. Input hashes bind the worker to source/request; they do
not protect against malicious replacement of the worker implementation itself.
That test was corrected to exercise malformed candidate schema, which is the
claimed transport boundary. No production validity check was weakened. Arbitrary
same-process Python execution remains outside the security boundary; scripts
using public interfaces must still use registered, editable feature commands.

Changed-file Ruff and diff whitespace checks pass. `test-smart --dry-run` reports
the accumulated FULL selection and FAST fallback; zero broad tests ran. Literal
selector notice (its wording is not evidence of execution):

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

## Containment and remaining exit

The three private boundaries are now implemented: storage, worker evaluation,
publication/history. Continue through the existing lifecycle rather than adding
another transaction or result queue:

1. Bind explicit source creation/recovery and durable lease/commit to this scope;
   do not auto-convert mutable user files or reuse batch recovery authority.
2. Connect source-bound editor HTTP and result/history controls to that lifecycle,
   retaining the ordinary editor's complete inputs, diagnostics and cancellation.
3. Extend complete standard-tool/preserved-state coverage, then qualify actual
   desktop latency/memory, durability, cancellation and retention before rollout.

These remain FH-28/FH-29/FH-27 work, not new scope. The earlier GC capture refusal
is still a production issue: ordinary editing has not switched to this private
host. No performance improvement or desktop verification is claimed. Assembly,
machine-specific VR and parked asset priorities remain unchanged.

Memory lint remains at its baseline six errors and 59 warnings; project head is
200 lines. Cleanup removed 218 completed pytest directory/symlink entries with
zero regular-file bytes after no readable same-user process references were
found. PIDs 435/436 remain uninspectable. Pytest scratch and shared memory are
empty; user designs and existing caches were preserved.
