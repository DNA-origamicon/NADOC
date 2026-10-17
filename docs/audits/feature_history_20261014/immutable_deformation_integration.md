# Typed Bend/Twist integration and request cleanup — U53

**21/38 milestones complete; 17 remaining (8 core, 9 parked).** U53 is engineering
checkpoint 53 since B1. FH-28 remains open after nine checkpoints, task-growth
flagged. Delta +0 completed/+0 total; original exits are unchanged.

## Delivered behavior

The shared geometry catalog now admits typed `DeformationLogEntry` creation and
editing. A closed input adapter reuses Bend/Twist parameter schemas, native
creation selection and prefix-aware overlay editing. The host owns operation
and feature identities; clients cannot submit affected-helix or target-range
receipts. Whole-part, numerical cluster and explicit domain selections resolve
on the independently proved prefix. Changed groups use the existing native
reference/error handling; empty or missing selections do not broaden to all DNA.

Creation appends one typed entry, retaining the native resolved operation; it
never converts Bend/Twist into snapshot geometry. Append source/candidate proof,
editing through the suffix, exact-handle history, file persistence and recovery
reuse the existing host. The storage scope checks typed entries, proof version,
operation identity and Bend/Twist family. Snapshot-shaped deformation impostors
are refused. The private storage label remains byte-compatible as documented in
U52; no migration or second model format is introduced.

The shared executor applies the existing deformation frame-span admission before
native evaluation, including source replay and geometry cold recovery. This
prevents a very distant plane edit from allocating native frame arrays before
its work bound is checked. The existing limits and molecular algorithms remain
unchanged. Named-group/organized sources still need their full storage/lineage
integration; this is an outstanding original requirement, not a product exclusion.

## Request cleanup bug found and corrected

Two scoped runs stalled at the same real-worker HTTP case, while that case passed
alone. Live process inspection showed no active child and an idle thread-pool
worker; a faulthandler dump placed the main thread waiting for the HTTP response.
The two owned test processes were explicitly terminated only after confirming
that state; terminal results were observed before rerunning. Neither run is
reported as a pass.

Inspection found cleanup relied solely on `task.cancel()` to stop a disconnect
poll. Starlette's receive poll uses its own cancellation scope; AnyIO distinguishes
scope cancellation from asyncio task cancellation. See the
[Starlette source](https://github.com/Kludex/starlette/blob/main/starlette/requests.py)
and [AnyIO cancellation explanation](https://anyio.readthedocs.io/en/stable/why.html).
These sources support the cancellation mechanism; the attribution of the local
stall is based on process evidence, the regression below and the corrected rerun.

The monitor now requires a separate explicit stop event, set before cancelling
and draining it. Both geometry HTTP and saved-recipe file transport use it. No
unbounded cancellation-only fallback remains. A deterministic regression models
a receive scope that consumes external cancellation and proves monitor shutdown
without falsely cancelling completed native work. The full previously stalled
run passes after the correction. Work cancellation/disconnect signaling remains
separate from normal monitor shutdown.

## Validation

**366 unique focused cases have passing results:**

- Initial Bend/Twist + Sweep: 31 passed in 13.09 s.
- Expanded typed inputs + scope/worker/host: 103 passed/1 fixture failure in
  20.00 s. The malformed snapshot test was corrected to inject the invalid kind
  after schema construction, so it actually reaches storage admission.
- Final typed Bend/Twist (23), geometry recovery (16), recovery worker (58),
  existing deformation preview (81), file transport (44): **222 passed in 16.66 s**.
- Geometry HTTP (19), evaluator (14), fast append (17), Sweep (11), geometry host
  (37): **98 passed/1 deselected in 15.90 s**, three pre-existing ORJSONResponse
  deprecation warnings from evaluator setup.
- The previously classified slow full lifecycle: **1 passed/17 deselected in
  7.90 s**, call 5.05 s, via `just test-focused ... -m slow`.
- The 22 storage-scope and 23 geometry-worker cases passed in the earlier run
  and are distinct from the final two batches. Overlapping results count once.

New cases exercise both deformation families across whole/cluster/domain scope,
creation/edit through later extrusion, typed identity preservation, exact save/
undo/redo/recovery, real child construction and upstream editing, invalid family/
identity/derived inputs, coercible types, oversized spans and missing groups.
No scientific output or golden was changed. Existing limits were not raised.

Changed-file Ruff and diff checks pass. Memory lint retains its six-error/
59-warning baseline, and the project head is 200 lines. `main.js` stays 7350 lines,
delta zero. No frontend behavior changed in this checkpoint.

`test-smart --dry-run` selects FULL from accumulated changes and FAST fallback;
zero broad tests ran. Literal notice (the dry run did not execute FAST):

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

**NOT VERIFIED IN APP.** Public gates remain off. Named-group organization,
Move/Rotate, Fine Routing, complete preserved state, preview/editor integration,
latency/memory and desktop qualification remain open. The existing movement/
connection scientific cases and ordinary capture GC risk are unchanged.
Assemblies, machine-specific VR and parked assets remain deferred as agreed.

Cleanup removed 677 completed pytest entries: 97 owned `.partcache`
files and two dead-process pytest lock files, 914,196 bytes total. Both lock
PIDs were absent. No readable same-user process referenced the scratch; PIDs
435/436 remained uninspectable. Pytest scratch/shared memory are empty. User
designs, existing caches and managed jobs were preserved.
