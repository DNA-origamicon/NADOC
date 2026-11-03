# Cylinders → full upgrade is now fast (shipped 2026-05-15) — supporting detail

[Topic head](../../project_polymerize_origami.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Cylinders → full upgrade is now fast (shipped 2026-05-15)

After Phases 1–3, the user reported that loading 20 cylinders-mode instances was fine, but switching them back to `'full'` took ~1.5 min. Three compounding costs were responsible:

1. **Per-bp `setMatrixAt` loops** in [helix_renderer.js:525–683](../../../frontend/src/scene/helix_renderer.js#L525-L683). For a 61k-bp design at full LOD that's ~120k iterations × 4 mesh types per instance. Inherent cost — unaddressed in this PR; would need a worker / typed-array refactor.
2. **Phase-1's `invalidateInstance + recursive rebuild`** at cheap → full transitions tore down the WHOLE instance group (arcs, crossover bead meshes, labels, overhang names) and re-fetched geometry over the network, even though only the helix LOD changed.
3. **20 parallel PATCHes**: `Promise.all(instances.map(api.patchInstance(...)))` returned 20 separate assembly responses; each fired the assembly subscription and triggered a full 20-instance rebuild walk.

Fixes:

**In-place helix LOD swap** in [frontend/src/scene/assembly_renderer.js](../../../frontend/src/scene/assembly_renderer.js) (`_inPlaceHelixLodRebuild`). When `setDetailLevel` reports `needsRebuild`, the renderer now:
- Detaches `arcGroup` + `xoverResult.group` from the old `helixCtrl.root` so they survive the swap.
- Disposes only the old helix meshes (skipping `userData.shared` template singletons from Phase 1).
- Re-runs `buildHelixObjects` with the entry's cached `nucleotides` + new LOD — **no network round-trip, no rebuild of labels / overhang names / hull groups / crossovers**.
- Re-parents the stashed arc + xover groups under the new `helixCtrl.root`.

**Batch representation patch**: `PATCH /assembly/instances/batch` ([backend/api/assembly.py](../../../backend/api/assembly.py)) extended to accept `representation` + `visible` per item, mirroring the per-instance route's session-state bookkeeping (`remember_instance_display`). The frontend "Apply to all" handler in [frontend/src/main.js:10245ish](../../../frontend/src/main.js#L10245) now uses `api.batchPatchInstances` — one round-trip, one renderer rebuild walk, in-place LOD upgrade per entry.

Expected impact: the user's 20-instance cylinders → full switch should drop from ~1.5 min to ~10–20 s (still bottlenecked by item 1 above — the per-bp loops in `buildHelixObjects` itself).

Tests added in [tests/test_assembly_api.py](../../../tests/test_assembly_api.py): `test_batch_patch_applies_representation_atomically` + `test_batch_patch_rejects_invalid_representation`. Suite: 1336 passed (+2 net), no regressions.
