---
name: hull-prism-representation-extrusion-hull-overhang-markers
description: "Design-view Hull Prism rep — coarse distance-readable solid built from feature-log extrusions or a cross-section scan, dsDNA-only, with color-coded overhang face markers. All in joint_renderer.js."
metadata: 
  node_type: memory
  type: project
  originSessionId: bbfbdeb4-f435-46e2-ae4a-d7094b347162
---

# Hull Prism representation (2026-05-20)

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

The **Hull Prism** representation (`View → Representation → Hull Prism`, rep id
`'hull-prism'`) is a coarse, distance-readable solid. In the DESIGN view all
logic lives in `frontend/src/scene/joint_renderer.js`; it's driven by
`jointRenderer.setHullRepr(true)` → `_rebuildHullRepr(design, helixAxes)`.
(`main.js` `_setRepresentation('hull-prism')` calls it.)

**Assemblies (shared renderer) — ALSO supported as of 2026-05-21.** Previously
hull-prism only worked in the design view; on the shared instancing renderer
(default since 2026-05-20) `_repToLodCap('hull-prism')` fell into the catch-all
`return 2`, so parts were silently demoted to a far billboard. Now `assembly_renderer.js`:
- `_hullGeoForSource(design, nucleotides, helixAxes)` (module-level) mirrors
  `_rebuildHullRepr`'s FULL decision tree — extrusion boxes → cross-section scan
  → **per-cluster cross-section SCAN** — and merges all SOLID meshes
  (transforms baked, attrs normalised to position+normal/non-indexed) into ONE
  source-local geometry. Reuses 4 builders newly exported from joint_renderer.js
  (`buildExtrusionBoxes`, `scanExtrusionGroup`, `dsTrimmedAxes`, `dsBpByHelix`).
  **FIX 2026-05-22:** the per-cluster branch (#3, clustered parts w/o extrusion
  ops — e.g. hinges) previously called `_buildHullGroupsForDesign` → convex
  prisms over EVERY cluster (incl. the whole-part "Scaffold Cluster"), which did
  NOT match the design view. It now mirrors `_rebuildHullRepr` exactly: drop
  whole-part clusters (`is_default` OR ≥90% of helices) + clusters under
  `HULL_MIN_SIZE_FRACTION`(0.10) of dsDNA bp, then `scanExtrusionGroup` per
  remaining cluster. Verified parity: design-view hull and assembly hull are
  byte-identical (36 tris, same bbox) for `Ultimate Polymer Hinge`.
  **Overhang face markers ADDED 2026-05-22** (was solid-only): `_hullGeoForSource`
  now also calls `buildOverhangMarkers` (exported from joint_renderer.js) onto the
  SOURCE-LOCAL hull meshes and returns `{ solid, markers }`; `_buildMarkerLodMesh`
  instances the vertex-coloured quad geometry with the SAME per-instance xform
  shader as `_buildHullLodMesh` (`srcEntry.hullMarkerLod`, mesh `sharedLodHullMarkers`,
  MeshBasic + vertexColors + polygonOffset). It rides the hull LOD bucket —
  `_updateLodForSource` sets its count + `u_instanceOffset` identical to `hullLod`.
  Verified parity: design-view markers and assembly markers byte-identical
  (234 tris) for `Ultimate Polymer Hinge`. **Only edge wireframes remain
  design-view-only** (instanced lines not worth it for the coarse LOD).
  `_buildHullGroupsForDesign` (convex prisms) remains, used ONLY by the legacy
  per-instance renderer (`?shared=0`, line ~1214).
- `_buildHullLodMesh` instances that geometry across all hull-prism instances
  (single-index `gl_InstanceID + u_instanceOffset`, `world = instTransform × pos`,
  grey MeshLambert). One draw call per source.
- LOD bucket 3 = hull (4 = hidden) in `_repToLodCap` + `_updateLodForSource`;
  distance-independent (hull draws at all zooms). `frustumCulled=false` +
  `sharedLodImpostor=true` (photo-mode skip) are mandatory.

**Hull is now also the universal FAR rep (2026-05-22).** The billboard tier
(bucket 2) was retired — far-away close/mid instances of ANY rep collapse to the
hull solid (a static sprite misrepresents structure under a moving camera). So
every source must have a hull even with no extrusion/scan/cluster geometry:
`_hullGeoForSource` no longer returns null in that case — it falls back to
`_bboxSolidFromNucs` (an AABB over the part's nucleotides) so distant hull-less
parts don't vanish. Photo export suppresses the far→hull demotion via
`setSuppressLodDemotion(true)`. See [[path_to_thousands]] for the full ladder.
- NB clustered parts (hinges) have no extrusion ops in their feature_log, so they
  hit the per-cluster SCAN branch (#3 above) — the SAME per-cluster cross-section
  scan + cluster filtering the design view uses (NOT convex prisms; that earlier
  note was wrong and is fixed — see the 2026-05-22 fix above).
NOTE: the OLD per-instance renderer (`?shared=0`) had its own hull path
(`_buildHullGroupsForDesign` via `_applyRepresentation`) and is untouched.

<a id="curved-hull-prism-deformed-designs--design-view-shipped-2026-05-26"></a>
- [Curved hull prism (deformed designs) — DESIGN VIEW SHIPPED 2026-05-26](details/project_hull_prism/01-curved-hull-prism-deformed-designs--design-view-shipped-2026-05-2.md#curved-hull-prism-deformed-designs--design-view-shipped-2026-05-26)

<a id="native-feature-log-hull-follows-cluster-transforms--design-view-shipped-2026-05-31"></a>
- [Native feature-log hull follows cluster transforms — DESIGN VIEW SHIPPED 2026-05-31](details/project_hull_prism/01-curved-hull-prism-deformed-designs--design-view-shipped-2026-05-2.md#native-feature-log-hull-follows-cluster-transforms--design-view-shipped-2026-05-31)

<a id="sub-helix-partial-coverage--assembly-bake--shipped-2026-05-31"></a>
- [Sub-helix partial coverage + assembly bake — SHIPPED 2026-05-31](details/project_hull_prism/01-curved-hull-prism-deformed-designs--design-view-shipped-2026-05-2.md#sub-helix-partial-coverage--assembly-bake--shipped-2026-05-31)

<a id="box-axial-extent-now-from-real-dsdna-span-not-stale-feature-log--2026-05-31"></a>
- [Box axial extent now from real dsDNA span (not stale feature-log) — 2026-05-31](details/project_hull_prism/01-curved-hull-prism-deformed-designs--design-view-shipped-2026-05-2.md#box-axial-extent-now-from-real-dsdna-span-not-stale-feature-log--2026-05-31)

## Geometry modes (`_hullMode`, default `'extrusions'`)
- **`extrusions`** (default): one rectangular box per extrusion.
  - NADOC-built parts → `_buildExtrusionBoxes(design)`: reads `design.feature_log`
    (`bundle-create`/`extrude-*` entries) — each carries `cells` (lattice [row,col]),
    `length_bp`, build `plane`, `offset_nm`. Box = bounding rect of cells × axial run.
    Alternating cross-sections (e.g. teeth.nadoc 16/8/16/8/16) reproduce teeth directly.
  - Imported parts (no feature log) → fallback `_scanExtrusionGroup(...)`: scans the
    bundle axis; helix ends rounded to the lattice **major tick** (margin) so ragged
    per-helix starts/ends don't spawn junk segments; each constant-cross-section run
    → one box.
- `'boxes'`: per-helix occupancy boxes merged per cluster (older approach).
- `'prism'`: legacy convex per-cluster bundle prism (`_buildHullForCluster` → `_bundleGeometry`).

<a id="key-passes-extrusions"></a>
- [Key passes (extrusions)](details/project_hull_prism/02-key-passes-extrusions.md#key-passes-extrusions)

<a id="overhang-markers-color-coded-quads"></a>
- [Overhang markers (color-coded quads)](details/project_hull_prism/02-key-passes-extrusions.md#overhang-markers-color-coded-quads)

## Debug + tuning
- `window.nadocHull`: `.mode('extrusions'|'boxes'|'prism', boxFill?)`, `.scanTick(bp)`,
  `.minSize(frac)`, `.debug(on)`.
- `Help → Debug → Show Hull Cluster Debug` — colors clusters distinctly + labels
  bp %, shows excluded clusters faint.
- X-section margin slider lives in the Representation options (`repr-hull-margin-row`).

<a id="related"></a>
- [Related](details/project_hull_prism/03-related.md#related)
