# Phases 2 + 3 of the rendering-memory plan (shipped 2026-05-15) — supporting detail

[Topic head](../../project_polymerize_origami.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## Phases 2 + 3 of the rendering-memory plan (shipped 2026-05-15)

Combined into one change because they share the response-reshape surface. The user reported Chrome still OOMing on the polymerized load after Phase 1 (cheap-LOD skip-allocate) shipped — Phase 1 cut per-instance GL state but the wire payload was still ~9 × ~30 MB JSON per polymerized clone.

**Phase 2 — compact wire format** ([backend/api/assembly.py](../../../backend/api/assembly.py)):
- `GET /assembly/instances/{id}/geometry` now emits `nucleotides_compact` (parallel arrays per helix per direction) instead of the verbose per-nuc dict list. ~50% smaller wire payload, ~50% faster JS parse. The compact builder `_compact_geometry_from_nucleotides` already existed in `crud.py` for the main design path — reused here directly.

**Phase 3 — source-keyed dedup** (same file):
- `GET /assembly/geometry` (batch) is reshaped to `{ sources: {srcKey: entry}, instances: {instId: srcKey}, errors }`. Two N-clone instances of the same part share **one** source entry — wire size drops from O(N) to O(unique sources). The source key reuses `_geo_cache_key` so the dedup respects cluster-transform overrides (different overrides ⇒ different sources). Per-instance errors are surfaced separately so one bad instance doesn't poison the batch.

**Frontend** ([frontend/src/api/client.js](../../../frontend/src/api/client.js)):
- New module-local `_expandCompactNucleotides(compact)` helper mirrors the existing main-design decoder used by `_syncFromDesignResponse`.
- `getInstanceGeometry` decodes `nucleotides_compact` into the flat list the renderer expects (no renderer change needed).
- `getAssemblyGeometry` projects the new `{sources, instances}` shape back into the legacy `{instances: {id: {nucleotides, helix_axes, design}}}` map the renderer consumes — but the per-instance entries share the **same** decoded JS array reference across instances pointing to the same source, so V8 doesn't carry N copies of identical nucleotide lists.

**Combined impact** for the user's 9-instance polymerize case:
- Wire size: ~270 MB → ~15 MB (Phase 2's compact form × Phase 3's 9:1 dedup).
- JS parse heap: drops similarly.
- Phase 1 covered the per-instance GL/InstancedMesh waste; Phases 2+3 cover the per-instance JSON/parse waste.

Tests in [tests/test_assembly_api.py](../../../tests/test_assembly_api.py): `test_get_instance_geometry_inline` updated to assert the new `nucleotides_compact` shape; two new tests `test_assembly_geometry_dedups_identical_sources` + `test_assembly_geometry_distinct_sources_when_designs_differ` cover the batch dedup semantics. Suite: 1335 passed (+2 net), no regressions.

## Phase 1 of the rendering-memory plan (shipped 2026-05-15)

Background: the previous OOM mitigation (cheap-rep default for new clones + load-time auto-downgrade) hid the deeper problem. The systemic-investigation agent found three layers of waste; Phase 1 addresses the biggest (and only one that's frontend-only):

**Cheap LOD wasn't actually cheap.** `buildHelixObjects` in [frontend/src/scene/helix_renderer.js](../../../frontend/src/scene/helix_renderer.js) used to allocate the full set of bead / cone / slab / fluoro InstancedMesh buffers regardless of `representation`. `setDetailLevel('cylinders')` only flipped `.visible = false`. For 9 polymerized instances of a 61k-bp part that's ~250 MB of resident-but-hidden InstancedMatrix Float32Arrays.

Fix:
- Added a `lod` parameter to `buildHelixObjects(geometry, design, scene, customColors, loopStrandIds, helixAxes, lod = 'full')`. Skips allocating the heavy per-bp count for beads/cones/slabs/fluoros when the LOD doesn't need them — falls back to a dummy count=1 InstancedMesh (64-byte buffer) so downstream code keeps its references but the per-bp loops never run.
- `_builtFlags` records what was actually allocated. `setDetailLevel(level)` now returns `{ needsRebuild: boolean }`; when the caller asks to upgrade to a level whose meshes weren't built, the assembly renderer invalidates the instance and triggers a rebuild so the heavier meshes are re-allocated at full count.
- `assembly_renderer.js` passes each instance's `representation` field as the build-time LOD and reacts to `needsRebuild` from `setDetailLevel`.

**Latent dispose-of-shared-singletons fixed.** Module-level template geometries (`GEO_SPHERE`, `GEO_CUBE_5P`, `GEO_UNIT_BOX`, `GEO_UNIT_CONE`, `GEO_UNIT_CYL`, `GEO_HALF_CYL`, `GEO_FLUORO_SPHERE`) are now tagged with `userData.shared = true` at definition. Every `traverse(o => o.geometry?.dispose())` call site in `assembly_renderer.js` (5 of them — `_disposeGroup`, hull groups, part-joint indicators, orphan-group cleanups in `rebuild` + `dispose`, linker-group teardown) now skips disposal when the flag is set. Previous behavior would have invalidated the shared GPU buffer for every other instance using the same template — a real bug, latent until the user happened to dispose and rebuild in the right order.

Expected impact: the user's 2D-polymerize case (9 heavy instances at `'cylinders'`) drops from ~250 MB Chrome heap to ~30 MB on the build itself. Total assembly geometry payload over the wire is unchanged in this phase (that's Phase 2's job).

Phase 2 (compact wire format) and Phase 3 (source-keyed dedup) — see `/home/joshua/.claude/plans/resilient-growing-sparrow.md`.

## OOM-on-polymerize-then-can't-reopen (fixed 2026-05-15)

User repro: `workspace/Hinge Polys.nass` polymerized to 16 × `Ultimate Polymer Hinge` (61,598 bp / 75 helices / 208 strands each). Each PartInstance at `representation='full'` builds ~50 MB+ of GL state in the browser; 16 of them OOM'd the tab. The saved `.nass` faithfully recorded all 16 at `'full'`, so re-opening reproduced the OOM.

Three coordinated fixes:

1. **Polymerize clones default to `'cylinders'`** in [backend/api/assembly.py](../../../backend/api/assembly.py)`polymerize_assembly`. New primaries on both sides + pattern additionals all get `representation='cylinders'` at creation time. The user's seed instances are untouched; they can upgrade individual clones via the rep picker if they want detail on one of them. Tested by `test_polymerize_new_clones_default_to_cheap_representation` in [tests/test_polymerize.py](../../../tests/test_polymerize.py).

2. **Load-time auto-downgrade** for assemblies that already exceed the threshold. `_maybe_auto_downgrade_for_memory` in [backend/api/assembly.py](../../../backend/api/assembly.py): if more than `_AUTO_DOWNGRADE_FULL_REP_THRESHOLD = 6` instances are at `'full'`, every `'full'` instance is downgraded to `'cylinders'` before the active assembly is set. The `/assembly/load` and `/assembly/import` response gains an optional `notice` field describing what happened so the frontend can toast it. Tested by `test_load_auto_downgrades_when_too_many_full_instances` + `test_load_does_not_downgrade_when_under_threshold`. The user's saved file is now openable.

3. **Pre-polymerize confirm dialog** in [frontend/src/ui/polymerize_panel.js](../../../frontend/src/ui/polymerize_panel.js): if the projected new instance count (≈ `(count-2) × (1 + n_additionals)`) reaches 10+, a `window.confirm` warns and shows what's about to happen + that clones default to cheap rep.
