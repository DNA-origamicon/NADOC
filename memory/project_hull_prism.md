---
name: hull-prism-representation-extrusion-hull-overhang-markers
description: "Design-view Hull Prism rep — coarse distance-readable solid built from feature-log extrusions or a cross-section scan, dsDNA-only, with color-coded overhang face markers. All in joint_renderer.js."
metadata: 
  node_type: memory
  type: project
  originSessionId: bbfbdeb4-f435-46e2-ae4a-d7094b347162
---

# Hull Prism representation (2026-05-20)

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

## Curved hull prism (deformed designs) — DESIGN VIEW SHIPPED 2026-05-26
The extrusions hull now follows bend/twist in the **design view**. Per extrusion
box, `_buildExtrusionBoxes(design, helixAxes, curveTolNm)` (joint_renderer.js)
sweeps the box's wCol×wRow rectangle along its helices' DEFORMED spine instead of
emitting a straight `BoxGeometry` — so the bent comb is preserved per-extrusion.
- New module helpers: `_boxSweptSections(design, helixAxes, boxHelixIds, bpLo, bpHi,
  wCol, wRow)` (maps cells→helix via grid_pos, box bp-range→sample indices via
  `_AXIS_SAMPLE_STEP=7`, centroid spine + **rotation-minimizing (parallel-transport)**
  cross-section frame, fixed rectangle corners) → reuses the existing flat-shaded,
  capped `_buildSweptHullGeometry`.
- **Frame singularity fix (2026-05-27):** the original `U = cross(tangent, worldY)`
  (Z fallback) frame is SINGULAR when the spine tangent nears the vertical axis. A
  bend that drives the bundle toward world-up — teeth.nadoc's 90° bend at direction
  270° gives final tangent ≈ −Y (verified: `|t·Y|` 0.023→1.000 along the spine) —
  collapsed the U axis and flipped it: a sudden spurious twist, wrong degree + direction.
  Replaced with a rotation-minimizing (parallel-transport) frame: rotate U forward by the
  minimal rotation between consecutive tangents (no world-up ref → no pole → no flip).
  Verified on the real teeth spine: section-to-section U jump 21.2° (old) → 0.07° (new).
  **TWO-PART fix — the seed matters too:** `_boxSweptSections` is called PER extrusion
  box, and each box independently re-seeded its frame from `tangent×worldY` at ITS OWN
  first section. The LAST box sits entirely in the bent region, so its seed landed on the
  −Y pole → the whole final block stayed mis-rolled even after per-box smoothing. FIX:
  build centers over the FULL range `[0, idxHi]` (not `[idxLo, idxHi]`) and propagate the
  PT frame from idx 0 (bundle start, tangent ≈ +Z, well-conditioned), EMITTING sections
  only for `idxLo..idxHi`. Every box now shares ONE globally-consistent frame → continuous
  across box boundaries. Verified: last box first-U vs the lower boxes' settle direction
  31.8° (per-box seed) → 8.9° (anchored, = the true accumulated rotation, continuous).
  NOTE: the swept box is a smooth envelope, it does NOT roll by the bundle's material
  twist — `samples` carry only spine centers, no per-bp orientation; the visible coil
  comes from the spine path. Fixing `_boxSweptSections` fixes BOTH views (assembly
  `_hullGeoForSource` imports `buildExtrusionBoxes`).
- **Deform edit drops Hull Prism (2026-05-27):** editing a bend/twist feature while
  Hull Prism is active left the coarse prism solid persisting UNDER the full-rep deform
  preview (both visible). The `deformToolActive` activation branch (main.js) now calls
  `_setRepresentation('full')` when `_currentRepr === 'hull-prism'` so only the deforming
  geometry shows. No auto-restore (full is the clearest result view; user re-picks Hull
  Prism after). `_currentRepr` is tracked in `_setRepresentation`.
- **Curvature-adaptive faceting**: `_decimateSections(sections, tolNm)` = Douglas–
  Peucker on the spine centers. Straight runs collapse to 1 facet; bends keep more.
  Knob = max facet deviation in nm (`_hullCurveTolNm`, default 1.0).
- **Slider**: `repr-hull-curve-row` ("Curve detail (nm)", 0.25–5) → `setHullCurveDetail`
  → rebuild. Lives next to the X-section margin slider in Representation Options.
- Flat-shaded (per-face normals in `_buildSweptHullGeometry`) + caps both ends =
  the chosen low-poly/CAD look. Verified on teeth: faceted grey arc, comb preserved,
  ~80 tris @1nm → 112 @0.25nm, no console errors.
- `mergeGeometries` attr-uniformity: straight boxes now `deleteAttribute('uv')` so
  they merge with the swept (position+normal-only) geos. Merged-edge threshold
  15° when deformed (facet boundaries only), 1° straight.
- NB the per-CLUSTER curved path (`_buildHullForCluster` → `_computeSpineSections` +
  `_buildSweptHullGeometry`) already existed and is unchanged; this added curvature
  to the DEFAULT extrusions path that NADOC-built parts (teeth) hit.

**Assembly shared renderer — PORTED 2026-05-26.** `_hullGeoForSource`
(assembly_renderer.js) now calls `buildExtrusionBoxes(design, helixAxes, HULL_CURVE_TOL_NM)`
— the source's `helix_axes` already carry `.samples` (built via `_axesArrayToMap`), so a
bent part's boxes sweep along its spine here too. `HULL_CURVE_TOL_NM = 1.0` (module const,
matches the design-view default; the design-view slider does NOT reach the assembly path —
separate renderer). The swept geo bakes fine through the existing clone→applyMatrix4→
toNonIndexed→strip-to-position+normal→merge path (position+normal only, like the boxes after
their `deleteAttribute('uv')`). Verified with a throwaway 1-instance teeth `.nass` fixture:
assembly shows the faceted bent comb in Hull Prism, 96 tris, no console errors. Non-deformed
sources (hinges etc.) still build straight boxes — no regression.

## Native feature-log hull follows cluster transforms — DESIGN VIEW SHIPPED 2026-05-31
Before this, the NADOC-native (feature-log) path merged ALL extrusion boxes into
ONE group keyed `'__extrusions__'`, built in build-space — so a moved finer cluster
(e.g. a hinge arm with a `ClusterRigidTransform`) did NOT follow its transform: the
block stayed at the build origin on rebuild AND the single merged group lacked the
per-cluster key that `captureClusterBase`/`applyClusterTransform` look up, so the
live gizmo drag couldn't move it either. (Cadnano imports were already correct —
their per-cluster `_scanExtrusionGroup` groups are keyed by `cluster.id` and scan
the already-cluster-transformed helix axes.)
**Fix:** `_buildExtrusionBoxes(design, helixAxes, curveTolNm, opts)` gained an
optional `opts.renderClusters`. When supplied it returns a
`Map<clusterId|'__extrusions__', THREE.Group>` instead of one Group: each box is
assigned to the render cluster owning the MAJORITY of its helices (cell→helix via
`grid_pos`; `_cellComponents` already splits a hinge's two arms into separate
lattice-connected boxes, so the vote is clean — verified on Hinge.nadoc: the
extrude-continuation splits 18 cells Cluster-1 / 18 cells Cluster-2). That cluster's
rigid transform `p' = R·(p−pivot)+pivot+T` (`_clusterMatrix`) is BAKED into the
straight box geometry; the group is keyed by `cluster.id` so live drag + rebuild
both move it. **Swept/deformed boxes are NOT re-baked** — the backend already
cluster-transforms the spine `samples` ([deformation.py](../../NADOC/backend/core/deformation.py) `deformed_helix_axes`
applies `_apply_cluster_transforms_to_point`), so baking would double-apply.
`_rebuildHullRepr` only splits out FINER clusters ≥ `_hullMinSizeFraction` of dsDNA
bp; the whole-part/`is_default` cluster + small clusters keep their boxes in
`'__extrusions__'` untransformed (nothing vanishes). The legacy single-Group return
(no `opts`) is unchanged, so the **assembly renderer is untouched** (still calls
`buildExtrusionBoxes` 3-arg). Verified in-app on `workspace/Hinge.nadoc` (Cluster 2:
T≈[0,17.6,−12.3] + ~49° X-rot): hull renders as a bent two-block hinge; Cluster-2
group bbox centre Y≈31 vs un-moved blocks Y≈2.
### Sub-helix partial coverage + assembly bake — SHIPPED 2026-05-31
Two follow-ups from the v1 above are now done, both in `_buildExtrusionBoxes`:
- **Per-(helix,bp) decomposition (replaces majority vote).** `opts` is now
  `{ clusters, keyByCluster }`. A `_buildBpClusterResolver(design, clusters)` →
  `(helixId, bp) → subset-index | -1` reuses the canonical `buildClusterLookup`
  (imported from `helix_renderer/palette.js`) at DOMAIN granularity. Each straight
  box is walked base-by-base per cell into owner runs, then split into axial
  segments at every owner boundary and, within each segment, one sub-box per
  distinct owning cluster (bounding rect of that cluster's cells). This handles
  helix-level clusters, full-coverage domain clusters, AND sub-helix PARTIAL
  coverage — a "bridge" helix (some domains move, some don't) or a box straddling
  a cluster boundary axially/across its cross-section now splits cleanly. Each
  sub-box bakes its owning cluster's `_clusterMatrix`. Swept/deformed boxes are
  NOT decomposed or re-baked (samples already cluster-transformed) — attributed
  whole by majority for keying only. Verified: synthetic bridge design (distal
  domains of both helices moved +20Y) splits the [0,100) box → proximal
  '__extrusions__' @Y0, distal cluster group @Y20, axially distinct.
- **Assembly integration.** `assembly_renderer.js::_hullGeoForSource` now passes
  `{ clusters: allClusters }` (NO `keyByCluster` → ONE merged Group with transforms
  baked) to `buildExtrusionBoxes`, but ONLY when some cluster is non-identity
  (`clusterMoved` gate) — so the common no-moved-cluster assembly is byte-identical
  to before. A native part with a rigidly-moved arm (straight boxes, no bend) now
  bakes the transform into its source hull (previously it ignored it; swept/bent
  parts already followed via samples). No per-cluster keying needed (the part is a
  single instance). Verified on real Hinge.nadoc: assembly merged-bake hull
  reaches maxY 56.1 (the rotated arm) vs legacy 16.9 (build origin).
### Box axial extent now from real dsDNA span (not stale feature-log) — 2026-05-31
The cluster-aware box path reconstructed each box's axial run from the feature-log
op's `length_bp`/`offset_nm`. That goes STALE once scaffold routing / continuations
extend the helices past the original `bundle-create` — the box ends up the wrong
length AND can't show the per-helix stagger. Symptom (mini_hinge.nadoc): the moving
arm's hull "extended too far back" (box started at bp 0 but the arm's dsDNA starts
at bp 24) and the stationary arm "had no back porch" (its row-0 helices reach bp 0
while row-1 starts at bp 24 — a real dsDNA stagger the uniform box flattened).
**Fix:** `_dsBpRangeByHelix(geometry)` → `Map<hid,[minBp,maxBp]>` over genuinely
double-stranded positions, passed as `opts.dsBpRange`. The decomposition now walks
each cell over its OWN dsDNA bp range (axial coord = bp·rise) instead of the op's
`[bpLo,bpHi)`; cells absent from an axial segment are skipped, so staggered/extended
ends and the back-porch step appear. Passed by BOTH callers — `_rebuildHullRepr`
(`_dsBpRangeByHelix(currentGeometry)`) and assembly `_hullGeoForSource`
(`dsBpRangeByHelix(nucleotides)`, exported as `dsBpRangeByHelix`). Falls back to the
op range when `dsBpRange` is absent (legacy / non-cluster path unchanged — teeth
etc. still use feature-log dims). NB this is dsDNA-only by design: a short ssDNA
scaffold tail (mini_hinge bp [−5,0)) is intentionally NOT in the hull even though
the per-DOMAIN cylinder rep draws it — the hull matches the dsDNA body, not ssDNA
tails. Verified on mini_hinge: stationary arm reaches the bp-0 porch (z≈0) + forward
to ~bp 88 (z≈29, was capped 84→28), moving arm no longer over-extends; Hinge.nadoc
bent-hinge regression intact.

- **Remaining caveat:** assembly *live* intra-part cluster drag still isn't a thing
  on the shared instancing path (parts are instanced; you'd edit the part in
  part-edit/design view, which IS covered). Design-view live drag + both rebuild
  paths are covered.

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

## Key passes (extrusions)
- **Per-cluster** (imports): each detected cluster gets its OWN bundle frame
  (`_bundleFrame`) + axial scan. **Whole-part clusters skipped** — `is_default`
  OR ≥90% of helices (drops the autodetect "Scaffold Cluster" that overlaps the
  geometry clusters); falls back to all clusters when no finer ones exist.
- **Size exclusion**: clusters < `_hullMinSizeFraction` (default 0.10) of total
  dsDNA bp are dropped (`window.nadocHull.minSize`).
- **dsDNA-only**: `_dsTrimmedAxes` trims each helix's axis to its base-paired
  extent (projects dsDNA nucleotides onto the axis — `length_bp` is NOT physical
  extent, LESSONS F1), excluding ssDNA: unpaired scaffold, overhang/staple-only tails.
- **5% block filter**: `_filterSmallBlocks` drops boxes < 5% of total volume
  (declutters stub segments); empty-guard keeps the largest if all are below.
- **Margin** (`_hullScanTickBp`, null → per-lattice default): user-chosen
  **7 bp square / 8 bp honeycomb** (set in `_setRepresentation`; X-section margin
  slider overrides). NB: this is the OPPOSITE of the crossover period — a
  deliberate visual default, do not "correct" it.
- **Material**: solid opaque CAD-grey `0x9a9a9a` (`_extrusionMeshMat`), not the
  translucent green `_hullMeshPhong`.

## Overhang markers (color-coded quads)
`_buildOverhangMarkers` — one flat quad per overhang, **raycast onto the BUILT
hull mesh** (built first, then markers) so it lands flush on the actual rendered
face with the hit normal. Position from **current (transformed) overhang
nucleotide positions** (grouped by `overhang_id`), NOT the stored
`OverhangSpec.pivot` (base-frame, goes stale under cluster transforms). Color =
overhang strand color (vertex colors, one merged mesh). EPS 0.08 nm proud.
Why raycast: the rendered hull varies per axial segment (trim/filter/per-segment),
so a computed face plane can't match it.

## Debug + tuning
- `window.nadocHull`: `.mode('extrusions'|'boxes'|'prism', boxFill?)`, `.scanTick(bp)`,
  `.minSize(frac)`, `.debug(on)`.
- `Help → Debug → Show Hull Cluster Debug` — colors clusters distinctly + labels
  bp %, shows excluded clusters faint.
- X-section margin slider lives in the Representation options (`repr-hull-margin-row`).

## Related
- Overhang detection that feeds this: [[overhang_subdomains]] + LESSONS F4 (per-bp
  scaffold coverage; `autodetect_all_overhangs` now runs on `.nadoc` load/import).
- Assembly far-LOD + shared-renderer LOD ladder: [[path_to_thousands]]. Hull-prism
  is now a 4th LOD bucket on that shared path (see above).
