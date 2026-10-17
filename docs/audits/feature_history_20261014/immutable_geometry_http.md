# Immutable geometry HTTP lifecycle — U49

Progress: **21/38 complete; 17 remaining (8 core, 9 parked)**. U49 is engineering
checkpoint 49 since B1 and FH-28 checkpoint 5, still task-growth flagged.
Completed/total delta: **+0/+0**. FH-28's original exit remains unchanged.

## Delivered boundary

The existing strict dispatcher now exposes four gated adapters under
`/api/design/geometry-history`: recovery jobs, indexed feature edit, undo/redo,
and explicit save. Recovery uses the existing job inspect/cancel/commit routes.
The geometry gate remains false. Ordinary desktop routes are unchanged.

Before reading a request body, the dispatcher captures the exact session,
immutable source, revision and policy generation. The handler checks them again;
edit/history admission also checks the original source and session identity.
Recovery carries an explicit expected empty-session identity, including absence.
Closing and reopening a document with the same ID/revision cannot redirect an
old request to the new document. JSON cannot supply those private authority
handles, a verified flag or candidate geometry.

Edits use the existing thread-draining helper and disconnect monitor. Cancellation
reaches the native worker owner; the handler drains work before returning. No
additional worker queue, publication registry, cache format or model authority
was introduced. Undo/redo retains exact immutable handles. Native regeneration
and file writes remain outside the document lock.

Save captures a specific owned revision and writes through the existing typed
persistence owner. Its response separately reports requested revision, written
revision and whether that revision is still current. A successful older write
therefore cannot claim a newer live revision is saved. This is explicit save,
not completed UI autosave integration or crash-durability qualification.

## Evidence and limitations

**212 unique focused tests pass**, without warnings:

- Geometry HTTP (19), strict dispatcher (61), geometry host (37) and geometry
  recovery (16): **133 passed in 13.44 s**.
- Existing recovery (36) and file transport (43): **79 passed in 7.92 s**.

Seven extrusion families exercise HTTP recovery/edit/save/undo/redo with real
small typed files and independent native replay. One complete HTTP recovery/edit/
save case uses real subprocess workers. Other cases check refusal before body
reads, session replacement during acquisition and admission, forbidden authority
fields, write failure, revision advancement during save and disconnect cleanup.
An initial disconnect test used a blocking receive incompatible with Starlette's
nonblocking polling; correcting that fixture made the cancellation assertion pass.
No production cancellation behavior was weakened.

Changed-file Ruff and diff checks pass. Memory lint retains its existing six
errors/59 warnings; the project head remains 200 lines. `main.js` remains 7350
lines, delta zero. No molecular builder, phase constant or golden changed.

The selector dry-run chose FULL from accumulated changes, then FAST fallback;
**zero broad tests ran**. Its literal notice (the dry-run did not execute FAST):

```
DEFERRED: this change would have needed the FULL suite, but no test-dedicated
session is open, so only the fast suite ran. Parked in .nadoc-slow-pending.
This is broad-suite debt, not a block on development. Run relevant slow tests with `just test-focused TARGET` without a session.
Only request `just test-session` when a broad/full sweep is actually needed.
```

**NOT VERIFIED IN APP.** No browser workflow was exercised; public gates remain
off. These small-file tests do not establish near-limit latency, memory tails,
full editor compatibility or crash recovery. Ordinary capture's U44 GC risk is
still open. Assemblies/VR and parked asset priorities are unchanged.

## Containment and next exit

Five checkpoints on FH-28 is a visible overrun signal, not five delivered
milestones. Storage, worker, publication, recovery and HTTP are now connected for
the admitted extrusion scope. Do not create another parallel transaction host.
Remaining work is fresh creation, complete standard-tool/preserved-state coverage,
editor integration and measured lifecycle/resource acceptance. Catalog/public
release remains FH-29; desktop acceptance remains FH-27. Do not enable the gate
or count FH-28 complete on the strength of these focused tests.

Cleanup removed 595 completed pytest entries including 78 owned
`.partcache` files (781,647 bytes). No readable same-user process referenced
them; PIDs 435/436 remained uninspectable. Pytest scratch and shared memory
are empty. User designs and existing caches were preserved.
