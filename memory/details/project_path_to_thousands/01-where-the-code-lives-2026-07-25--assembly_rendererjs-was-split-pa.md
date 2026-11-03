# WHERE THE CODE LIVES (2026-07-25 — assembly_renderer.js was split; paths below are current) — supporting detail

[Topic head](../../project_path_to_thousands.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

## WHERE THE CODE LIVES (2026-07-25 — assembly_renderer.js was split; paths below are current)
`scene/assembly_renderer.js` used to hold BOTH renderers (6,261 lines). It was split — behavior
unchanged, no logic edits, both paths verified in-app A/B on `gears_test.nass` + a 500-instance
polymer. Current homes:

| what | file |
|---|---|
| **shared-instancing renderer** (`_createSharedInstancingRenderer`, the DEFAULT path, stub table, bp-texture consts, LOD ladder) | `scene/assembly_renderer_shared.js` |
| legacy per-instance renderer (`initAssemblyRenderer`) + the `createAssemblyRenderer({useShared})` factory + the interface docblock | `scene/assembly_renderer.js` |
| far-LOD hull solids (`_hullGeoForSource`, `_bboxSolidFromNucs`, `HULL_*`) | `scene/assembly_hull_geometry.js` |
| cross-part linker helices + connector arcs (`_rebuildLinkerHelices`) | `scene/assembly_linker_render.js` |
| overhang-name sprites (`_overhangLabelAnchorsLocal`, `_makeOverhangNameTexture`) | `scene/assembly_overhang_labels.js` |
| mate connectors incl. bend centers (`computeInstanceBluntEnds`, `bendCenterRecordToWorld`) | `scene/blunt_end_connectors.js` |
| cluster membership (`clusterMemberFilter`) — was THREE byte-identical copies, now one | `scene/cluster_entries.js` |
| repr → `setDetailLevel` map, was `_CG_LOD` | exported as `CG_LOD` from `scene/helix_renderer.js` |

The **stub-list audit rule below still applies** — `_SHARED_RENDERER_STUB_DEFAULTS` now lives in
`assembly_renderer_shared.js`, so grep there when checking what is stubbed vs implemented.

## Shared-renderer visual parity audit (2026-08-28)

The shared assembly path must consume the same authoritative geometry as the individual
design path. The former selectable `measured_positioning` preference described by this audit
has been removed: both geometry APIs now require canonical native Full placement, with a
single `measured=1` display-cache identity. Their negotiated NDGB transport preserves those
placements exactly. Historically, mismatched modes had equal primitive counts but different
bead/slab transforms; matching counts alone is still insufficient.

Full shared sources also build the part renderer's crossover-specific geometry before applying the
shared-instancing patch: extra beads, slabs, backbone connectors, slab connectors, and scaffold /
staple / periodic-seam arc layers. Arc placement follows each assembly instance transform; periodic
seams remain independently toggleable. Coloring-mode updates must repaint both arc vertex buffers
and the extra-base GPU color textures. Cluster ownership follows the part rule: A/from endpoint,
then B/to endpoint, then natural strand color; Overhang-only dims non-overhang crossovers.

`frontend/e2e/bigo_assembly_geometry_parity.spec.js` is the source-level contract. For the one-unit
BigO assembly it compares unordered transform multisets (compact assembly transport order differs
from strand order) for backbone spheres/cubes, cones, slabs, and slab connectors to five decimal
places. It also checks total crossover vertices and Cluster/Overhang-only RGB histograms against
the individual part. Photomode shadow coverage additionally asserts that, with Studio Ambient off,
there is exactly one visible shadow-casting light and it is the key.

## `getAssembly()` returns the RAW v2 wire shape — NEVER read `.instances` off it (2026-05-27)
`api.getAssembly()` (and every `_syncFromAssemblyResponse`-backed call) RETURNS the raw backend
JSON. The backend's `_assembly_response` ([assembly.py](../../../backend/api/assembly.py) ~L186)
does `full.pop("instances", None)` and emits `format_version:2` + `instances_v2` + `sources`. So
`(await api.getAssembly()).assembly.instances` is **undefined**. The v1-shaped object (with
`.instances` populated) is what `_syncFromAssemblyResponse` writes into the STORE via
`_expandV2Assembly` — so callers must read `store.getState().currentAssembly`, NOT `result.assembly`.
**Bug this caused:** `_refreshAssemblyPartInstance` (main.js) did
`const assembly = result?.assembly ?? store.getState().currentAssembly` then `rebuild(assembly)`.
`result.assembly` was truthy but had no `.instances`, so `rebuild()` hit its `instances.length===0`
branch → `dispose()` → **every source wiped → assembly invisible after a part edit until a
rep-change forced a fresh rebuild from the store.** The store subscriber's build (using the
expanded `currentAssembly`) succeeded first, then this line immediately blanked it. Fixed by
`await api.getAssembly(); const assembly = store.getState().currentAssembly`. Other callers
(`_recoverAfterRestart`, `forceResync`) already read the store correctly; the `nadocDebug._backend()`
helper still logs `a.instances?.length` off the raw response (cosmetic, shows undefined — left as-is).
Diagnosis path: auto-probe showed `source groups in scene: []`; instrumenting `rebuild()` with a
caller stack trace named `_refreshAssemblyPartInstance` firing with `instances=0`.

## Curved-cylinder LOD for DEFORMED sources (2026-05-26)
The shared renderer instances only `InstancedMesh` objects (`_patchSharedMeshes` bails on
anything else). A bent (bend/twist-deformed) source's cylinders live in NON-instanced
`TubeGeometry` meshes (`_curvedCylGroup` in helix_renderer), and the per-domain `sharedLodMid`
is built from the STRAIGHT `iHelixCylinders` which is EMPTY for curved helices — so bent parts
rendered NO cylinders in the shared assembly path (verified black viewport; hull rep worked).
**Fix:** mirror the hull's bake-and-instance — `_curvedCylGeoForSource(helixCtrl)` bakes the
source's bent tubes (+caps) into ONE source-local geometry with per-vertex strand colours;
`_buildCurvedCylLodMesh` instances it via the per-instance xform texture (like `_buildHullLodMesh`
but lit + `vertexColors`); `srcEntry.curvedCylLod` rides the MID bucket in `_updateLodForSource`
(`count = nMid`, `offset = nClose`). Returns null for straight parts → zero impact on the straight
path (verified: 20-hinge `sharedLodMid` count 240, no curvedCylLod, no errors). Verified bent:
3-instance teeth → 3 bent colored combs, count 3. **~~Known v1 limitation~~ FIXED 2026-06-11:**
curved-cyl LOD now recolours live. `_applyColorsToSource` re-bakes the curved geometry's `color`
attribute from the freshly-recoloured temp helixCtrl (`_curvedCylGeoForSource(tmpHelixCtrl)` →
copy into `srcEntry.curvedCylLod.mesh.geometry` colour attr, guarded on vertex count). Verified
in-app on `Robot Arm/Elbow_pulley.nass`: the bent Arm_pulley now greys out in overhang-only and
recolours in cluster/strand like the straight Shaft. (Cost: re-bakes the merged tube geometry per
coloringMode change for curved sources only — fine for the few-curved-parts regime.)
**Same session: `sharedLodMid` now splits at STAPLE colour boundaries** (was: one cylinder per
dsDNA region, colour = AVERAGE of its domains → a helix with red end-caps + orange middle collapsed
to muddy uniform orange). `_buildMidLodMesh` now buckets staple vs scaffold domains, excludes the
spanning scaffold from the split, and breaks a run whenever the build-time strand colour changes
(8-bit-quantised key) — so every strand colour shows as its own cylinder; the per-interval re-average
in `_applyColorsToSource` is unchanged (intervals are now colour-homogeneous in strand mode, so the
average IS the exact colour). Scaffold-only helices fall back to a single scaffold interval.

---
