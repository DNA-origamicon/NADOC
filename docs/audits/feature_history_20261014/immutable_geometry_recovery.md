# Explicit geometry recovery through the existing durable owner

U48, October 17, 2026. FH-28 checkpoint 4; **task growth remains flagged**.
No milestone closes and the total remains 38. This completes a private recovery
path on real small typed cache files, not public creation or editor integration.

## Implementation

The existing recovery job, bounded worker, closed-worker observation, exact
candidate qualification, one-shot publication permit and file-lease transaction
now support an explicit geometry scope. `start_geometry` is a private host entry;
ordinary `start` retains the original batch scope. Neither saved content nor an
extra request field can select the geometry path. Its host switch remains off.

The original wire context stays version 1. Geometry uses a closed version-2
context carrying the fixed `native_extrusion_v1` storage scope. Context hashing
binds that choice to the original host admission and request; parent result
validation checks returned metadata against the scope of that admission.
Version/scope mixing, substitution of batch metadata, gate changes and stale
admissions are refused before a completion can become publication authority.

Saved geometry receives the same bounded manifest/hash, duplicate/nonfinite JSON,
structural, exact canonical roundtrip, ordinary capture and independent native
regeneration checks as existing recovery. Only the storage preparation factory
differs. Scope admission alone remains insufficient: a nonreproducible saved
model stays pending and unmodified. No recovery payload becomes replay input.

Successful commit retains the original file lease through publication and binds
the recovered session to the existing `StrictPersistence` owner. Subsequent
edits and undo/redo use its existing captured-revision writer. This does **not**
make in-memory edit commit automatically durable: explicit writer calls were
used in the test, and UI/autosave integration remains unfinished. There is no new
cache format, directory, queue, replacement transaction or publication registry.

## Validation

242 unique focused tests pass without warnings:

- Initial 13 geometry cases + 36 existing recovery cases: 49 passed in 10.09 s.
- Expanded 15 geometry cases + 58 worker + 37 worker-lifecycle cases:
  110 passed in 22.63 s.
- Final 16 geometry cases + 24 recovery-transport + 34 permit + 37 immutable
  geometry-host cases: 111 passed in 10.27 s. Geometry cases overlap the runs.

All seven native extrusion families recover exact file bytes, publish once and
independently replay with poisoned recovery. A real subprocess cycle covers:
file recovery → extrusion edit → save → undo/save → stale-save refusal →
redo/save → close → second cold recovery. Recovered bytes equal the last saved
revision. The file lease is real, including refusal when identical bytes have
been atomically replaced under a different lease.

Other cases exercise old-profile refusal, gate refusal at admission/during worker/
commit, metadata-scope substitution, version/scope mixing and nonreproducible
saved geometry. Existing transport/lifecycle/permit tests cover cleanup,
cancellation and one-shot observations without altering their expectations.
All file fixtures are small, pytest-owned typed records; no user design or bulk
development artifact was created. No molecular builder or constant changed.

Changed-file Ruff and diff whitespace checks pass. `test-smart --dry-run` selects
FULL from accumulated changes and reports FAST fallback; zero broad tests ran.
Literal selector notice (the dry run did not execute FAST):

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

## Remaining exit and containment

Storage, worker edits, publication/history and explicit recovery now share the
same existing ownership infrastructure. Next connect host-selected creation/
recovery and editor HTTP to that lifecycle, including persistence acknowledgement
and cancellation. Keep the complete standard-tool/preserved-state expansion and
measured desktop/resource acceptance in FH-28/FH-29/FH-27. No extra transaction
host or alternate saved-model authority is needed. The repeated prerequisites
remain visible as four checkpoints, not four completed milestones.

NOT VERIFIED IN APP. This small-file cycle is not near-limit latency/RSS,
durability-under-crash or integrated UI qualification. Ordinary mutable editing
still has U44's GC capture risk. Public gates stay off; assemblies, machine-
specific VR and parked assets retain their agreed priorities.

Memory lint remains at its baseline six errors and 59 warnings; project head is
200 lines. Cleanup removed 543 completed pytest entries, including 70 owned
`.partcache` fixtures totaling 669,119 bytes, after no readable same-user process
references were found. PIDs 435/436 remain uninspectable. Pytest scratch and
shared memory are empty; user designs and existing caches were preserved.
