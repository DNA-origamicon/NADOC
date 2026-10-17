# Private immutable extrusion storage prerequisite

U45, October 17, 2026. FH-28 checkpoint 1. No milestone closed, no public gate
opened, and no capture latency improvement claimed. The ordinary editor still
uses mutable capture. This checkpoint supplies its missing storage prerequisite.

## Finding and implementation

The U44 ownership audit correctly identified sealed-source worker projection,
but understated its scope restriction: preparation itself admits only early
helix/strand, gold and placement recipes. Native extrusion cannot enter it.
Changing only the worker operation allowlist would therefore be insufficient.

`prepare_geometry_revision` now reuses exact canonical full-document preparation,
independent mutable materialization, immutable handle ownership, projection
digests, preserved-document checks and existing work/node/byte/history/recovery
limits. Its distinct `native_extrusion_v1` scope admits the seven native extrusion
families plus reviewed placement rows. Materialized fields include native frames,
dimensions, helices, strands, overhangs and crossovers. It does not invent new
geometry or change the molecular builders. Shared envelope checks were extracted
from batch admission instead of copied into a second validator.

The old `prepare_revision` factory remains batch-only. Equal document bytes under
different scopes are not interchangeable. Existing evaluation admission, worker
reservation and batch publication refuse the geometry scope explicitly. Geometry
storage does not prove regeneration: a deliberately inconsistent recipe can be
stored, but its independent replay is still rejected. No saved validity label,
recovery payload or privately prepared handle grants publication authority.

This is an intermediate private scope. Organized groups, other core geometry
families, nondefault presentation/physical state, imports and asset families
remain outside this factory until their complete preservation contracts are
implemented. They remain required by the existing delivery map, not exclusions
from the final overhaul. Existing public batch and durable recovery profiles
retain their original scope.

## Research basis and next boundary

Onshape documents regeneration as execution of the Part Studio build function,
with features calling versioned feature functions: [FeatureScript introduction](https://cad.onshape.com/FsDoc/intro.html).
Its [standard library context documentation](https://cad.onshape.com/FsDoc/library.html)
describes context-held version behavior during regeneration. This supports
preserving explicit command semantics while changing storage/transport. It does
not prescribe NADOC's Python storage scopes; that separation is our engineering
choice to prevent compatibility expansion from granting publication authority.

Next implement a geometry-specific owned worker operation and exact source-bound
edit permit using this storage scope, with normalization/selection performed in
the child. Prove source reproduction, downstream rebuild, stale/cancel/policy
refusal and one immutable undo before connecting ordinary editor HTTP. Then
qualify durable creation/recovery, expand complete standard-tool preservation and
measure actual app latency. Do not seal mutable live documents inside the lock,
relax capture limits, automatically migrate files or reuse the batch permit.

## Validation

239 unique focused backend tests pass: 22 new geometry-scope tests plus existing
revision (49), evaluation (27), state (31), worker (30), permit (34), batch-scope
(14) and preservation (32) regressions. The two final invocations passed 92 tests
in 5.82 s and 163 in 10.28 s, with 16 overlapping tests. No final warnings.
Seven native extrusion recipes round-trip exactly and independently replay with
poisoned recovery retained only as bytes. Tests cover mutable alias isolation,
cross-scope identity, matching-digest permit refusal, unsupported rows/versions,
generated attribution, history bounds and preserved-state/asset refusal.

Initial run found the native overhang fixture's crossover output omitted from
the proposed field envelope; crossovers are now explicitly classified. A limit
test was corrected to expect CaptureLimit, not a command error. One mistyped
test filename collected zero tests before the corrected run. No molecular
validation or resource limit was weakened.

Changed-file Ruff and diff whitespace checks pass. `test-smart --dry-run` selects
FULL from the accumulated baseline, reports FAST fallback and broad-suite debt;
zero broad tests ran. An initial dry-run attempt was refused while the focused
suite was live; it was rerun after that suite completed, without bypassing guards.
The selector's literal notice (its wording is not evidence of execution):

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

NOT VERIFIED IN APP. No frontend changes or desktop/VR runs. The complete
FH-28 lifecycle and FH-27 responsiveness exits remain open.
Memory lint retains the baseline six errors and 59 warnings; project head stays
at 200 lines. Cleanup removed 327 completed pytest directory/symlink entries,
zero regular-file bytes, after no readable same-user process references were
found. PIDs 435/436 remain uninspectable. Pytest scratch and shared memory are
empty; user designs and existing caches were preserved.
