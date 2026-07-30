---
name: rendering
description: The CG design render pipeline — design_renderer (store-aware) → helix_renderer (pure builder) → 16 instanced meshes. Store keys, LOD/representation, color merge, display-position overlays, glow layers, deform ghost.
paths:
  - "frontend/src/scene/design_renderer.js"
  - "frontend/src/scene/helix_renderer.js"
  - "frontend/src/scene/helix_renderer/**"
  - "frontend/src/scene/glow_layer.js"
  - "frontend/src/scene/domain_ends.js"
  - "frontend/src/scene/crossover_connections.js"
  - "frontend/src/scene/representation_overrides.js"
  - "frontend/src/scene/impostor_material.js"
  - "frontend/src/ui/representation_switcher.js"
---

# rendering

**Scope.** The coarse-grained *design* render pipeline: how a `Design` + geometry array becomes
Three.js objects. ~10.4k LOC across 9 files, **20 unit tests** (see Coverage — it is worse than
it sounds).

**Not this rule:** the assembly render stack (`assembly_renderer_shared.js` 3,940 +
`joint_renderer.js` 3,224 + `assembly_joint_renderer.js` 2,839 ≈ 10k LOC — **no rule covers it**,
and it calls `buildHelixObjects` too) · selection/glow *policy* (`selection.md`) · the deform
tool (`deformation.md`) · unfold (`unfold.md`) · the K-key 2D view (`cadnano-2d.md`) ·
atomistic/surface reps (`scene/atomistic_renderer/`, `scene/atom_surface_display.js` — also
uncovered).

*Rewritten 2026-07-30 against live code. Line anchors are dated, not permanent — re-grep before
citing one.*

## File map

| File | LOC | Entry | Tests |
|---|---|---|---|
| `scene/design_renderer.js` | 1,529 | `initDesignRenderer(scene, storeRef)` — **the only export**; called `main.js:286`, first factory in `main()` | **0** |
| `scene/helix_renderer.js` | 5,232 | `buildHelixObjects(...)` :344 + ~6 named exports | 4 |
| `scene/helix_renderer/palette.js` | 253 | `STAPLE_PALETTE` :28, `buildStapleColorMap`, `nucColor` | 4 |
| `scene/glow_layer.js` | 188 | `createGlowLayer` :120, `createMultiColorGlowLayer` :70 | 0 |
| `scene/domain_ends.js` | 873 | `initDomainEnds(...)` :350 — called `main.js:2988` | 4 |
| `scene/crossover_connections.js` | 543 | 15 pure exports, no factory | 8 |
| `scene/representation_overrides.js` | 264 | `resolveRepOverrides` etc. | (via `design_queries.test.js`) |
| `scene/impostor_material.js` | 183 | `impostorsEnabled()` :30, `makeImpostorPhongMaterial` | 0 |
| `ui/representation_switcher.js` | 302 | the F1–F7 representation menu | yes |

## The two-layer split (the load-bearing law)

```
store ──subscribe──> design_renderer  (the ONLY store-aware layer)
                        │
                        └─> buildHelixObjects(geometry, design, scene,
                                              customColors, loopStrandIds, helixAxes, lod)
                                    │
                                    └─> helix controller  (69 methods)
```

- **`helix_renderer.js` reads the store ZERO times.** It is a pure builder: everything arrives as
  one of those 7 arguments. Do not import the store into it — that is the whole reason the
  assembly renderer can reuse it.
- `buildHelixObjects` has **7 callers**, only one of which is this rule's subject:
  `design_renderer.js:477`, `assembly_renderer.js:608,:1180`,
  `assembly_renderer_shared.js:1217,:3179,:3590`, `assembly_linker_render.js:132`.
  **A change to its signature or return shape breaks the assembly render path**, which has no
  rule and few tests. Check all 7.
- `design_renderer` subscribes **once** (`:629`, plain `storeRef.subscribe`, no `subscribeSlice`)
  plus one eager build from `getState()` (`:780`).

### Counting the API instead of sampling it

`initDesignRenderer` returns **92 methods**; the helix controller returns **69**. Don't trust any
prose list (including this one) to be complete — regenerate:

```bash
rg -n '^    [a-zA-Z_][a-zA-Z0-9_]*[(:]' frontend/src/scene/design_renderer.js | sed -n '/789/,$p'
rg -n 'return \{' -A200 frontend/src/scene/helix_renderer.js | sed -n '/2552/,/5231/p'
```

Coarse families on `designRenderer`: mode/entries · **7 glow layers** · arcs · color ·
external-geometry render · position overlays · LOD+cylinders (18 methods) · crossovers ·
misc (axis arrows, opacity, deform preview, dispose).

## Store keys `design_renderer` actually reads (15)

`currentGeometry` · `currentHelixAxes` · `currentDesign` · `loopStrandIds` · `strandColors` ·
`strandGroups` · `staplesHidden` · `isolatedStrandId` · `coloringMode` · `showReferenceGeometry` ·
`deformToolActive` · `domainDesigner.modalActive` · `lastPartialChangedHelixIds` ·
`cadnanoActive` · `unfoldActive`.

Three of those drive behaviour that is easy to break and was undocumented until this rewrite:

- **`domainDesigner.modalActive`** (`:625-654`) — while the Domain Designer modal is open the
  rebuild is *deferred*; colors still repaint.
- **`lastPartialChangedHelixIds`** (`:727-748`) — the in-place patch fast path
  (`_tryPatchInPlace`, `:583`). If set, only those helices are touched instead of a full rebuild.
- **`cadnanoActive` / `unfoldActive`** — position-ownership guards (see Invariants).

`cgRelaxPositions`, `deformVisuActive`, `straightGeometry`, `straightHelixAxes`, `showSequences`,
`atomisticMode`, `surfaceMode` are **real store keys but are not read here** — they belong to
`deform_view.js`, `unfold_view.js`, `sequence_overlay`, `atomistic_renderer`, `surface` display.
(The pre-2026-07-30 version of this rule attributed all of them to this file.)

## Instanced meshes — there are 16, not 4

All in `helix_renderer.js`. One mesh per row = one draw call.

| Line | Var | What |
|---|---|---|
| 842 | `iSpheres` | **all** backbone beads, both directions, one mesh |
| 848 | `iCubes` | 5′ end markers — a **separate** mesh from the cones |
| 890 | `iFluoros` | fluorophore beads (`FLUORO_EMISSION_COLORS` :138) |
| 926 | `iCones` | direction cones |
| 981 | `iSlabs` | base-pair slabs |
| 1093 | `iHelixCylinders` | LOD-2 domain cylinders |
| 1106 | `iCurvedHelixCylinders` | |
| 1128 / 1142 | `iOverhangCylinders` / `iOverhangFullCylinders` | overhang half/full |
| 1163 / 1169 / 1175 | `iHelixCylGlow` / `iOverhangCylGlow` / `iOverhangFullCylGlow` | additive selection outline |
| 1228 / 1239 | `iCurvedOverhangCylinders` / `iCurvedOverhangFullCylinders` | |
| 1260 | `iLinkerBindingCylinders` | |
| 1274 | `iLinkerBridgeCylinders` | ds-linker bridge (2 public accessors) |

Plus two non-instanced `THREE.Group`s of per-domain tube meshes for the **deformed** case —
`_curvedCylGroup` (:1121) and `_curvedOvhgGroup` (:1251) — and the axis-arrow meshes (:428-812).

**Impostors** (`:836-848`): when `impostorsEnabled()` is true, `iSpheres` and `iFluoros` swap
`GEO_SPHERE` → `IMPOSTOR_QUAD` + `makeImpostorPhongMaterial` + `installSphereImpostorRaycast`.
This changes the raycast path, not just the look.

## Representation / LOD

Two different scales, often confused:

1. **`setDetailLevel(level)`** — helix_renderer `:3503`, wrapper `design_renderer:1155`, driven
   from `main.js:7395`. Levels are **integers** from `CG_LOD` (`helix_renderer.js:64`):
   `{ full: 0, beads: 1, cylinders: 2 }`. It **returns `{ needsRebuild: boolean }`** and the
   assembly renderer depends on that return value — don't drop it.
2. **The user-facing representation menu is 7 reps, F1–F7** (`ui/representation_switcher.js:36-44`):
   `hull-prism, cylinders, beads, full, surface, vdw, ballstick`. Only 3 of them map to
   `setDetailLevel`; `surface`/`vdw`/`ballstick` are separate renderers and `hull-prism` is a
   separate mesh path.

**Per-column/strand overrides** (mixed representation): `resolveRepOverrides`
(`scene/representation_overrides.js`, used `design_renderer.js:396` inside
`_applyRepresentationOverrides` :387) → `_applyRepOverrides` (`helix_renderer.js:2493`, public as
`applyRepOverrides` :2588) → per-instance alpha via `_installInstanceAlpha` (:238).

> **Known gap — do not assume overrides cover everything.** `_applyRepOverrides` (:2493-2549)
> touches none of `_curvedCylGroup`, `_curvedOvhgGroup`, `iCurvedHelixCylinders`,
> `iCurvedOverhangCylinders`, `iCurvedOverhangFullCylinders`, `iLinkerBindingCylinders` —
> `_reapplyDetailVisibility` (:2484) does. And `_installInstanceAlpha` **skips `iSpheres`/
> `iFluoros` when `_useImpostors`** (:2420-2424, :2471-2479), so impostor beads get no
> per-instance alpha at all. Net: mixed representation and reference-ghosting silently no-op on
> deformed/curved cylinders and on impostor beads. This is the P1 item in
> `memory/project_mixed_representation.md`.

## Color merge

- `_effectiveColors(strandColors, strandGroups)` — `design_renderer.js:151`. Takes **two maps and
  returns a whole `{strandId: hex}` object**; it is not a per-strand lookup. Group color
  **overwrites** the per-strand override (`:153-157`).
- Palette fallback is *not* in that function — applied downstream (`:695-696` `?? palette.get(sid)`,
  and inside `palette.js::nucColor` :230).
- `STAPLE_PALETTE` here is the canonical copy, `scene/helix_renderer/palette.js:28`
  (imported `helix_renderer.js:33`). Three other divergent copies exist repo-wide — see
  `project_tech_debt`. `design_renderer.js` imports only `buildStapleColorMap`.
- `setEntryColor(entry, hex)` — `design_renderer:808` → `_setInstColor` (`helix_renderer:192`).
  Main callers are `selection_manager.js` (12 sites), `ui/view_tool_buttons.js`,
  `scene/slice_highlighter.js`.

**Group/color changes never rebuild** — verified. `design_renderer.js:688-704` diffs old vs new
effective colors and repaints in place, and it runs *before* the structural early-return at `:706`
(`if (!geoChanged && !designChanged && !loopChanged) return`). A group edit sets none of those
three flags. Keep that ordering.

## Display-position overlays — one channel, eight consumers

`applyFemPositions(updates, amp = 1.0)` (`design_renderer:1019` → `helix_renderer:3316`) is **the**
channel for moving beads to externally-computed positions. `updates = null` reverts.

It is **not** mrDNA-specific and **not** historical-FEM-only: `ui/mrdna_display.js` ·
`ui/oxdna_display.js` · **`ui/cando_display.js` (a real FEM solver)** · `ui/snupi_display.js` ·
`ui/lammps_display.js` · `ui/blade_display.js` · `ui/md_panel.js` · `scene/animation_player.js`.
**`main.js` is not a caller.** Three-Layer Law: this is Physical/display state — it never writes
back to topology.

Real arities (all previously under-documented):

| Method | Signature | Callers |
|---|---|---|
| `applyDeformLerp` | `(straightPosMap, straightAxesMap, straightBnMap, t)` — **4 args**; `straightBnMap` is the base-normal map that fixes a 30° slab error at t=0 (`helix_renderer:3564`) | `deform_view.js:152` (one of 6 sibling subsystems, `:152-157`) |
| `applyUnfoldOffsets` | `(helixOffsets, t, straightPosMap, straightAxesMap)` — **4 args** | `unfold_view.js:883,941,997,1277` |
| `applyUnfoldOffsetsExtensions` | `(extArcMap, t, straightPosMap)` | `unfold_view.js:885,943,998,1278` |
| `applyPositionLerp` | 460 LOC, the largest function in the file (`helix_renderer:3850`) | cluster/animation paths |

**Scalar recolor** (per-base heat maps): `applyScalarColors(colorByKey)` / `clearScalarColors()`
(`design_renderer:1065/:1149` → `helix_renderer:3443/:3481`). Captures and restores prior colors,
no rebuild. Fans out to `_scalarArcUpdater` → `unfold_view.applyFemArcColors` (wired
`main.js:1539`) so crossover arcs match; sibling `_femArcUpdater` wired `main.js:1537`.
**Key format is `"helix:bp:dir:copy"`** (`helix_renderer:3458-3459`); `oxdna_display.js` writes the
3-part `"helix:bp:dir"` form only when `copy === 0`. Drivers: oxDNA RMSF **and** CanDo RMSF; oxDNA
additionally routes to `atomistic_renderer.applyScalarColors` for the atomistic path.

## Deform-tool preview ghost (current solid + result ghost, 2026-05-27)

The one section that survived this audit intact. During a bend/twist preview both the current
design and a ghost of the result are shown, for the CG reps.

- `designRenderer.beginDeformPreview(ghostOpacity)` (`:1503`) — called **once per session** from
  `deformation_editor.previewDeformation` (`:380`, guarded by `if (!_previewOriginalAxes)`),
  before the first preview op, on both the new-op and edit-in-place paths. Sets
  `_captureNextAsFrozen`; the next `_rebuild` keeps the OLD committed root in the scene at full
  opacity (`_frozenRoot` = "where the design is now") and every later deformed rebuild renders at
  `_ghostOpacity`.
- `designRenderer.endDeformPreview()` (`:1514`) — from `deformation_editor._cancelPreview` (`:489`),
  the universal teardown (confirm/cancel/escape/exit). Disposes `_frozenRoot`, restores solid, or
  the 0.15 tool dim if the tool is still active.
- `PREVIEW_GHOST_OPACITY = 0.38` lives in **`scene/deformation_editor.js:33`**, not in
  design_renderer — it arrives as the `ghostOpacity` argument.
- Opacity is **flipped** vs the old "before-ghost": reference solid, result ghosted.
  `setToolOpacity` (`:1491`) and `_tryPatchInPlace` (`:583`) both early-out while
  `_ghostOpacity !== null`. While merely placing planes the scene dims to 0.15 (`:529-532`).
- Hull-prism auto-switches to `full` on deform activation at **`main.js:4327`**, inside the
  `deformToolActive` subscriber (`:4318-4344`) that also blanks all 10 `selectableTypes`. A
  *second*, separate `deformToolActive` subscriber at `main.js:4285-4297` hides the slice plane.
- `deform_view`'s straight↔deformed LERP is a separate system (lerps the same beads, no second
  copy) and is untouched by the ghost.

## Glow layers

`glow_layer.js` exports two factories, not one, and neither is an `init*`:
`createGlowLayer(scene, color = 0x3fb950, scale = GLOW_SCALE, name = '')` (InstancedMesh spheres,
additive) and `createMultiColorGlowLayer(scene)` (sprites, per-entry `emissionColor`). Each returns
**5 methods**: `setEntries`, `refresh`, `clear`, `count`, `dispose`.

**12 live instantiations.** Seven inside `design_renderer.js` (`:60,62,65,68,71,75,106` — selection,
undefined-base, anchor, clash, capture, preview-hover, fluorophore), plus `unfold_view.js:102`
(arc glow), `zoom_scope.js:52` (hover), `main.js:5113` (cluster), and two in
`ui/overhang_connections_panel.js:134-135` (the factory is injected at `main.js:4119`).

**Selection does not drive glow through a store subscriber.** It is imperative, inside the click
handlers: `selection_manager.js` `_highlightStrand:2338` / `_highlightDomain:2351` /
`_highlightBead:2360` / `_highlightCluster:1749` → `_setSelectionGlow:2626` →
`designRenderer.setGlowEntries` (:2641) **and** `designRenderer.glowCylinderDomains` (:2642) — at
cylinder LOD the glow is an additive *cylinder* outline, not spheres. `store.setState({selectedObject})`
happens in the same handlers but nothing keys off it for glow.

## `domain_ends.js` (formerly `blunt_ends.js`)

Rings/labels at domain ends. `initDomainEnds(scene, camera, canvas, { onDomainEndClick,
onDomainEndRightClick, isDisabled, getUnfoldView })` :350, called `main.js:2988` — where **the
local variable is still named `bluntEnds`**. 13-method API (`:634+`): `clear`, `setVisible`,
`isRingHit`, `getEndScreenInfo`, `applyDeformLerp`, `applyUnfoldOffsets`, `applyCadnanoPositions`,
`revertPhysics`, `captureClusterBase`, `applyClusterTransform`, `getEndTable`, `getHelixLabelTable`,
`dispose`.

Its store subscriber owns a position-reapply branch that is easy to break (`:589-593`):

```js
_rebuild(newState.currentDesign, newState.currentHelixAxes)
if (store.getState().cadnanoActive && _lastCadnanoParams) {
  _applyCadnanoPositions(_lastCadnanoParams.rowMap, _lastCadnanoParams.spacing, _lastCadnanoParams.midX)
}
if (!store.getState().cadnanoActive) getUnfoldView?.()?.reapplyIfActive()
```

The two branches are mutually exclusive on `cadnanoActive` — rebuild recreates rings at 3D
positions, so *something* must re-project them. `_lastCadnanoParams` is cached at `:625`.
A cluster-transform-patch skip guard returns before the rebuild at `:576-588`.
(`reapplyIfActive` itself is **`unfold_view.js:1272`**, not here.)

## `crossover_connections.js` — the extra-base render path

543 LOC the previous rule globbed and never mentioned. Pure module, 15 exports, **imports only
`three`** and reads **zero store keys** — everything arrives as arguments.

- It draws **only crossovers that have extra bases**: `buildCrossoverConnections` (:179) skips any
  crossover with `extra_bases.length === 0` (:196). Plain crossovers are drawn as arcs by
  `unfold_view.js`.
- Emits a `THREE.Group` named `crossoverConnections` (:246) with 3 InstancedMeshes — beads, slabs,
  and arrow-cone backbone connectors threading `prev_real → eb0 … → next_real`. Positions from a
  quadratic Bezier (`BOW_FRAC_3D = 0.3`, :20); slab Z-offset uses the cadnano `_stapH/_stapL` phase
  sets (`HC_PLUS_Z`/`HC_MINUS_Z` :32-33, `SQ_*` :35-36).
- `design.forced_ligations` are wrapped into a crossover-shaped object (:215-241) so one loop
  serves both.
- Consumers: `design_renderer.js` (imports 8 symbols; builds :491, live-updates :312-313, :365,
  :377, :1027, :1395, :1409-1410), `assembly_renderer.js:65`, `overhang_link_arcs.js:25-28`,
  `unfold_view.js:26`, `force_crossover_tool.js:29`.
- **File-header invariant (:10-13), quoted because it is the DNA-topology law in miniature:**
  *"no geometry or topology reasoning here. The crossover record is the single source of truth.
  Look up nucleotide positions by key, draw the line. Any attempt to infer connection targets from
  strand topology will produce wrong results."*
- `updateExtraBaseInstances` deliberately does **not** set `needsUpdate` (:398-399) — the caller
  batches and flushes once (`flushExtraBaseMeshes`). Its scratch vectors (:390-395) are separate
  from the build-time ones to avoid aliasing when called from `unfold_view`.

## Invariants

1. **`helix_renderer` never reads the store.** Everything is an argument. This is what lets the
   assembly renderer reuse it.
2. **Design + geometry should arrive in one `setState`.** `_syncFromDesignResponse`
   (`api/client.js:360`) does that only on the embedded-geometry path (`:461` → single setState
   `:536`); the fallback path writes the store *then* awaits `getGeometry()` (`:547`) — two writes,
   two rebuilds. Prefer `_design_response_with_geometry` (`backend/api/crud.py:339`) on mutating
   routes.
3. **Position ownership: cadnano > unfold > 3D.** Anything that calls `revertToGeometry()` must
   first check `cadnanoActive`/`unfoldActive`, or beads snap to 3D for a frame. Subscribers fire in
   registration order, so a *late* subscriber wins.
4. **Group/strand color changes must not rebuild** — repaint in place, before the structural
   early-return (`design_renderer:688-706`).
5. **`setDetailLevel` returns `{needsRebuild}`** and callers act on it. Don't make it void.
6. **Extra-base crossover geometry is looked up, never inferred** (`crossover_connections.js:10-13`).

## Traps — statements that contradict the code

Fix the doc, not the code, unless you have re-derived the intent.

- **`deform_view.reapplyLerp()` has ZERO callers** (`deform_view.js:378`, exported `:409`). The old
  rule and runbook both said "after any `revertToGeometry()`, call `deformView.reapplyLerp()`" —
  nothing does. The wired analogue is `getUnfoldView?.()?.reapplyIfActive()` (`deform_view.js:308`,
  `domain_ends.js:593`). Before "fixing" a missing re-apply, check whether a deformation is even
  active — `oxdna_display.test.js:424` explicitly pins that `applyFemPositions(null)` is the *last*
  call with no re-apply after it.
- **`design_renderer.clearFemOverlay()` has ZERO callers** (`:1241`). The off path now goes through
  `applyFemPositions(null)`. Its body still carries the 2026-04-01 cadnano/unfold guard — that
  guard is dead code, and the subscriber it was written against no longer exists.
- **`refreshAllGlow()` refreshes 6 of the 7 layers** (`:955-962`) — `_captureGlowLayer` is omitted.
  Likely a bug, not a rule error; capture glow will lag during unfold animation.
- **The variable is `bluntEnds`, the module is `domain_ends.js`.** Also stale `blunt_ends` comments
  at `loop_skip_highlight.js:254`, `unfold_view.js:1170`, `cadnano_view.js:91`, and
  `.claude/rules/unfold.md` still lists `blunt_ends.js` as a file to read.
- **`scene/arc_tube_geometry.test.js` tests a file that does not exist** — a 2026-06-07 throwaway
  diagnostic still in the suite.

## Coverage — honest

| File | LOC | Tests |
|---|---|---|
| `design_renderer.js` | 1,529 | **0** — none of its 92 methods |
| `helix_renderer.js` | 5,232 | **4**, both pure helpers (`orderStrandNucleotides`, `directConnectedOverhangIds`). `buildHelixObjects` (~2,200 LOC) and all 69 controller methods: untested |
| `glow_layer.js` | 188 | **0** |
| `domain_ends.js` | 873 | 4 |
| `crossover_connections.js` | 543 | 8 |
| `helix_renderer/palette.js` | 253 | 4 (all on `buildStapleColorMap`) |

**20 tests for ~8.6k LOC.** Several sibling tests (`ui/cando_display.test.js`,
`ui/lammps_display.test.js`, `ui/md_panel.test.js`, `scene/slice_highlighter.test.js`) *mock*
`designRenderer` rather than exercise it — a green suite proves nothing about this pipeline.
Rendering changes need an app exercise; see `CLAUDE.md` → Verification expectations.

## Undocumented subsystems inside `helix_renderer.js`

Grep targets when something visual breaks and this rule doesn't mention it:

| Lines | Area |
|---|---|
| 428-812 | helix **axis arrows** — per-domain segmentation, shaft modes, per-segment lerp |
| 1017-1327 | domain-cylinder LOD-2 subsystem (11 meshes, phantom-instance guard :1077, per-domain glow) |
| 1327-1610 | curved-tube builder `_buildDomainTubeGeo` — the deformed-helix tube geometry |
| 1621-1809 | validation overlay + 9 debug modes `modeNormal`/`modeV11-V14`/`modeV21-V24` |
| 2401-2550 | reference-geometry alpha + mixed-representation overrides |
| 2714-2956 | coloring subsystem (`patchNucleotides`, `setStrandColor`, `applyColoring`) |
| 3571-4310 | position-lerp engine (`applyDeformLerp` + the 460-LOC `applyPositionLerp`) |
| 4441-4841 | cluster rigid-transform (`captureClusterBase`, `applyClusterTransform`, `commitClusterPositions`) |
| 4841-5069 | linker-bridge + bulk position updates |

## Removed API — do not resurrect

`iFwd` · `iRev` (never existed; the meshes are `iSpheres`/`iCubes`) · the `"Sticks"` LOD level
(levels are `full`/`beads`/`cylinders`) · `hd.bead` · `_withHighDetailGeometry` · the XPBD/oxDNA
physics-overlay store key · the FEM RMSF heatmap (replaced by `applyScalarColors`) ·
`MAP_RENDERING.md` (never existed) · a `designRenderer`/`opts` parameter on `buildHelixObjects`.

## Diagnostics → [.claude/runbooks/RUNBOOK_RENDERING.md](../runbooks/RUNBOOK_RENDERING.md)

## Related

- `memory/project_mixed_representation.md` — the P1 curved-cylinder/impostor override gap above
- `memory/project_sphere_impostors.md` · `memory/project_hull_prism.md`
- `.claude/rules/deformation.md` · `unfold.md` · `cadnano-2d.md` · `selection.md`
