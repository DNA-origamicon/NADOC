# Durable geometry empty creation — U50

**21/38 milestones complete; 17 remaining (8 core, 9 parked).** U50 is engineering
checkpoint 50 since B1; FH-28 remains open after six checkpoints, task-growth
flagged. Delta +0 completed/+0 estimated total. No exit criteria changed.

The existing durable creation transaction now has a host-selected geometry
entry point. It creates only an empty native recipe, seals it for geometry
storage, reserves an absent file, writes complete bytes and then publishes one
revision through the existing permit/retention transaction. Preparation and file
writes remain outside the document lock. The registered-batch creation path
retains its original scope and behavior; there is no second creation engine,
new cache format, queue or saved geometry authority.

`POST /api/design/geometry-history/empty` accepts only bounded name and lattice
options. The strict dispatcher binds the empty session (including absence) before
body acquisition. Admission rejects replacement of that session even if its
revision and document ID match. Saved JSON/request bodies cannot choose the
scope or supply geometry. The geometry gate is checked at admission, preparation,
pre-write, publication and the final post-retention liveness check.

A completed file survives publication failure for explicit recovery. The file
owner can retain its write binding; that is not live publication authority and
does not make an empty/closed session appear saved. Existing pending records
refuse new creation without overwrite. Successful creation has revision 1 and
no undo entry; recovery uses the existing geometry worker and job lifecycle.

## Validation

**166 unique focused tests pass:**

- Creation/permits/strict HTTP: 147 passed, 1 slow test deselected, in 8.15 s.
- That relevant slow durable creation/batch/save/restart/edit test separately
  passed via `just test-focused tests/test_part_immutable_creation.py -m slow`
  in 7.13 s. This checks the unchanged shared creation transaction's older path.
- Final geometry creation (17) plus geometry recovery (16): 33 passed in 8.26 s;
  15 creation cases overlap the first run.

New tests cover both lattices, exact bytes through create/save/close/recover,
real-worker recovery, gate revocation at four boundaries, write/publication/close
failures, reopened sessions during body acquisition and admission, refused
client-supplied content and disabled-gate refusal before reading the body.
Initial failure assertions incorrectly demanded deletion of the existing file
binding after a completed write. They now check the required behavior: no live
publication or saved-live-revision claim, and preserved recoverable bytes.
No persistence semantics were changed to accommodate those tests.

Changed-file Ruff and whitespace checks pass. Memory lint remains at baseline
six errors/59 warnings; the project head remains 200 lines. `main.js` remains
7350 lines, delta zero. No native molecular builder, phase constant or golden
changed. No frontend suite was needed for this backend-only change.

`test-smart --dry-run` selected FULL from accumulated changes, with FAST fallback;
zero broad tests ran. Literal notice (the dry run itself did not execute FAST):

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

## Remaining integration, not a completed milestone

**NOT VERIFIED IN APP.** Public gates remain false. Empty creation is not complete
new-part authoring: adding the first extrusion and subsequent core tools through
this sealed host remains open, as do full preserved-state coverage, editor
integration, cancellation/resource acceptance and desktop responsiveness. This
checkpoint does not resolve ordinary capture's GC risk or the outstanding
movement/connection molecular cases. Assemblies, machine-specific VR and parked
assets remain deferred as agreed.

Next connect native feature append to the existing evaluator/publication host,
using the original command inputs and independent regeneration. Reuse the
existing command contracts and avoid a second recipe format or another
transaction engine. Keep FH-28's six-checkpoint growth signal visible; do not
count separate implementation layers as completed delivery milestones.

Cleanup removed 463 completed pytest entries: 67 owned small files,
540,600 bytes. No readable same-user process referenced them; PIDs 435/436
remained uninspectable. Pytest scratch and shared memory are empty. Existing
user designs, caches and managed jobs were preserved.
