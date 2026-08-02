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
Three.js objects. ~10.4k LOC across 9 files, **23 unit tests** (see Coverage — it is worse than
it sounds).

**Not this rule:** the assembly render stack (`assembly_renderer_shared.js` 3,940 +
`joint_renderer.js` 3,224 + `assembly_joint_renderer.js` 2,839 ≈ 10k LOC — **no rule covers it**,
and it calls `buildHelixObjects` too) · selection/glow *policy* (`selection.md`) · the deform
tool (`deformation.md`) · unfold (`unfold.md`) · the K-key 2D view (`cadnano-2d.md`) ·
atomistic/surface reps (`scene/atomistic_renderer/`, `scene/atom_surface_display.js` — also
uncovered, though as of 2026-08-01 they share this rule's per-cluster alpha contract; see the
instanceAlpha section).

*Rewritten 2026-07-30 against live code. Line anchors are dated, not permanent — re-grep before
citing one.*

## File map

| File | LOC | Entry | Tests |
|---|---|---|---|
| `scene/design_renderer.js` | 1,554 | `initDesignRenderer(scene, storeRef)` — **the only export**; called `main.js:286`, first factory in `main()` | **3** (structural only) |
| `scene/helix_renderer.js` | 5,232 | `buildHelixObjects(...)` :344 + ~6 named exports | 4 |
| `scene/helix_renderer/palette.js` | 253 | `STAPLE_PALETTE` :28, `buildStapleColorMap`, `nucColor` | 4 |
| `scene/glow_layer.js` | 188 | `createGlowLayer` :120, `createMultiColorGlowLayer` :70 | 0 |
| `scene/domain_ends.js` | 873 | `initDomainEnds(...)` :350 — called `main.js:3006` | 4 |
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

**Sidebar tuning sliders** (`ui/repr_option_sliders.js`, rows in `index.html` under
`#repr-options-section`): bead radius (full/beads) and **slab thickness + slab opacity (full only)**.
Slab thickness is **`slabParams.width`** — mind the historical naming, `width` (0.06) is the plate's
smallest dimension and `thickness` (0.70) is the long in-plane extent. It mutates the live
`slabParams` in `helix_renderer.js` — the ~25 inline slab composes on the deform/lerp/cluster/MD
paths read it, so they stay consistent — then restretches the existing instances' Y scale **in
place** (keeping whatever an active display overlay positioned/sized them at) rather than calling
the still-dead `applySlabParams()`, which would snap them back to design geometry. Both
settings are held in `design_renderer.js` (`_slabScale`/`_slabOpacity`) and re-applied in the
post-rebuild block, since a rebuild makes a fresh `iSlabs`. Opacity also drives the crossover
extra-base slabs and tracks `depthWrite` (LESSONS D8) — which is why both slab materials carry
**`userData.photoForceDepthWrite = true`**: `photo_mode.js::swapToFlatMaterials` copies `depthWrite`
onto the figure material and `shadow_bounds.js::isShadowExcluded` reads `depthWrite:false` as
"cannot occlude", so without the opt-in a user-faded slab silently stopped casting *and* receiving
shadows in photo mode. Pinned by `photo_mode.test.js`. Any future structural mesh whose depthWrite
tracks a user opacity control needs the same flag.

**Per-column/strand overrides** (mixed representation): `resolveRepOverrides`
(`scene/representation_overrides.js`, used inside `_applyRepresentationOverrides`) →
`_applyRepOverrides` (`helix_renderer.js`, public as `applyRepOverrides`) → per-instance alpha
via `_installInstanceAlpha`.

### The instanceAlpha channel has THREE factors and ONE writer (2026-08-01)

`instanceAlpha` is a per-instance buffer attribute multiplied into `diffuseColor.a` by an
`onBeforeCompile` patch. **Three independent features share it:**

| Factor | Set by | Source |
|---|---|---|
| reference-geometry ghosting | `setReferenceStrands` / `setReferenceHidden` | `_refAlphaFor(strandId)`, `REF_ALPHA = 0.4` |
| mixed-representation visibility | `applyRepOverrides` | `beadVis(nuc)` / `cylVis(dom)`, 0 or 1 |
| **per-cluster opacity** | `setClusterAlphas(Map)` | `scene/cluster_entries.js::clusterAlphaKeys`, nucKey → alpha |

They **multiply**. Until 2026-08-01 the first two were separate ABSOLUTE writers that clobbered
each other (`_applyRepOverrides` hand-multiplied `_refAlphaFor` back in), which does not scale —
so they were collapsed: `_applyAlphaChannel()` (formerly `_applyReferenceAlpha`) is the single
writer when no override is active, `_applyRepOverrides` when one is. **A fourth factor is a new
term in those two functions, never a fourth sweep.** `_ensureAlphaInstalled` (formerly
`_ensureRepAlpha`) is the single lazy installer, latched by `_repAlphaReady`; once latched every
writer keeps maintaining the buffers, which is how clearing a fade restores 1.0 instead of baking
in the last value.

**The shader patch lives in `scene/instance_alpha.js`, not here** — `instanceAlphaOnBeforeCompile`
(a module-level NAMED function, because three derives the program cache key from
`onBeforeCompile.toString()`: one shared function = one shared compiled program) and
`applyInstanceAlphaMaterial(mat)`, which also stamps `userData.instanceAlphaPatch`. That marker
exists because **`photo_mode.js::swapToFlatMaterials` replaces every mesh material and copies no
`onBeforeCompile`** — before the fix, everything faded rendered fully opaque in photo mode and in
the tiled export. The swap now re-installs the patch on the marker, and must set `transparent`
explicitly (the fade is in the attribute, so `src.opacity` is 1 and the swap's opacity carry-over
never fires). Pinned by `instance_alpha.test.js` + 4 tests in `photo_mode.test.js`.

Keep `depthWrite: true` on these materials. One InstancedMesh holds both faded and opaque
instances, so dropping it would break the opaque ones — and `shadow_bounds.js::isShadowExcluded`
reads `depthWrite:false` as "overlay, cannot occlude", silently removing the whole mesh from the
photo key shadow. The `< 0.02 discard` in the patch is what keeps a fully-faded instance from
being an invisible occluder (LESSONS D8); the patch touches only `diffuseColor.a`, redefining no
stock chunk variable (LESSONS D5).

> **Gap list — CLOSED 2026-08-01.** The alpha channel now drives every mesh family in this
> pipeline. What used to be missing, and why each was missing, because the shapes recur:
>
> | Was missing | Root cause |
> |---|---|
> | curved TUBE meshes (`_curvedCylGroup`, `_curvedOvhgGroup`) | the deform cross-fade owned `material.opacity` ABSOLUTELY at 4 sites, so any per-domain factor was clobbered on the next lerp frame |
> | curved PROXIES (`iCurvedHelixCylinders`, `iCurvedOverhang*`) | no alpha channel installed, and their data arrays had no `domainIndex`, so only helix-level keys could ever resolve |
> | `iLinkerBindingCylinders` | **no instance→domain array existed at all** — `bindIdx` was never recorded |
> | impostor beads (`iSpheres`/`iFluoros`) | `_installInstanceAlpha` was skipped outright under `_useImpostors` |
>
> The fixes, in the order you'd need to understand them:
>
> 1. **The cross-fade is now a compositor.** `_fadeCurvedTube(mesh, base)` stores the cross-fade
>    base on the mesh and applies `base × _curvedTubeFactor(userData)`; `_refreshCurvedAlpha()`
>    re-applies stored bases when a factor changes. **Never write `_fadeMat` on a curved mesh
>    directly again** — there is one legitimate raw write left and it is inside the compositor
>    (pinned by `helix_renderer.test.js`).
> 2. **`_fadeCurvedProxy` keeps `_fadeMat`'s depth contract** (`depthWrite` only when opaque —
>    an opacity-0 depth-writing mesh is an invisible occluder, LESSONS D8) but forces
>    `transparent` while any per-instance factor is live, or `instanceAlpha` would have nothing
>    to blend into. Material opacity × instanceAlpha compose for free in the shader, which is why
>    the proxies need no compositor of their own.
> 3. **`_effCol` / `_cylRepVis` / `_cylFactor` are hoisted to closure scope** and shared by the
>    instanced writers and the curved-tube compositor, so the two cannot disagree about which
>    columns resolve to `cylinders`. **This closes the mixed-representation P1 too** — region
>    overrides now reach deformed geometry, not just cluster opacity.
> 4. **Impostors compose rather than clobber.** `applyInstanceAlphaMaterial` *assigns*
>    `onBeforeCompile`; doing that to an impostor would wipe its billboard + `gl_FragDepth`
>    patch and leave flat quads. So `instance_alpha.js` exports the raw transform
>    (`patchShaderForInstanceAlpha`) and the geometry half (`installInstanceAlphaGeometry`)
>    separately, and `impostor_material.js` composes the transform inside its own
>    `onBeforeCompile`, opted in by `enableImpostorInstanceAlpha`. **Only opt in once the mesh
>    actually has the attribute** — GLSL reads a missing attribute as 0 and the patch discards
>    below 0.02, so a premature call makes every bead vanish.
>
> **Atomistic + surface too, 2026-08-01** (their renderers are `Not this rule` above, but the
> contract is here because it reuses this machinery).
>
> **Resolve cluster identity per NUCLEOTIDE, never per strand.** A strand can pass through several
> clusters and the scaffold passes through nearly all of them, so collapsing a strand onto one
> cluster paints the whole scaffold with whichever cluster owns its first domain. That shipped as a
> bug (VoltronCoreScad: 979 scaffold nucleotides genuinely in Cluster 3 came out Cluster 4's
> colour) and it is silent — the CG bead view was right the whole time, because it resolves per
> nucleotide via `domain_index`.
> - **Atomistic**: `setClusterDisplay(alphas, colors)`, both keyed `helix:bp:dir`. Atoms carry no
>   `domain_index` (`atom_table.js` `ATOM_FIELDS`) but they do carry helix + bp + direction, so
>   `color_util.js::buildNucClusterIndex` walks the design's domains once to recover which
>   (strand, domain) each nucleotide belongs to, then applies the same two-tier rule as the beads.
>   O(1) per atom; a per-atom range scan would be O(domains) against millions of atoms. The sweep
>   lives inside `_applyColors`, which `_rebuild` already calls, so it survives a rebuild for free.
>   Bonds take the LOWER of their two atoms' alphas. Impostor atom materials route through
>   `enableImpostorInstanceAlpha`, same as the beads. Note `<REVERSE>` domains store
>   `start_bp > end_bp` — min/max the range or half of them vanish.
> - **Surface** resolves per nucleotide too, as of 2026-08-01 — it needed a backend payload
>   change. `surface_to_json` now emits `vertex_nuc_index_table` / `vertex_nuc_index` beside the
>   strand pair, sourced from the same nearest-point KD-tree query that already assigned the
>   strand (`SurfaceMesh.vertex_nuc_ids`; `surface_atom_cloud` returns a 4th per-point array).
>   `applyClusterDisplay({nucColors, nucAlphas, strandColors, strandAlphas})` takes BOTH key
>   spaces and the renderer picks per payload, so anything without the block — the oxDNA
>   frame-surface overlay, a surface cached from before — still fades at strand granularity
>   instead of silently doing nothing.
>
>   **Synthetic helices need the bare-helix fallback.** 5′/3′ extension tails live on
>   `__ext_<id>` helices that appear in NO strand's domains, so the domain walk that builds
>   `buildNucClusterIndex` cannot reach them — extension vertices on the coarse surface took no
>   cluster colour or fade at all (reported 2026-08-01). Their per-bp keys are not enumerable
>   from the design either (a tail's length is a geometry property), so the index carries a BARE
>   `__ext_<id>` entry and every consumer resolves through `color_util.clusterOfNucKey`, which
>   falls back from `helix:bp:dir` to the bare helix. Real helix ids carry no colons, so the two
>   key shapes cannot collide. The bead view was never affected — `cluster_entries.clusterNucKeys`
>   emits its own `h:__ext_<id>` keys.
>
>   **Simulation surfaces too, 2026-08-02.** Every engine overlay that draws a surface —
>   oxDNA relaxed / RMSF / trajectory, and NAMD through the mdViz adapter — shares the ONE
>   `surfaceRenderer` from `main.js` and reaches it through `applyPositionLerp`, never
>   `update()`. That path did not record the payload, so `_cachedData` still described the
>   DESIGN surface while a sim frame was on screen and the cluster machinery either
>   early-returned or resolved against the wrong identity table. `applyPositionLerp` now
>   records the frame on ALL THREE of its branches (in-place lerp, snap, rebuild) — the
>   in-place branch is the easy one to miss, and it is taken whenever the vertex count
>   happens to match. Backend side, `frame_surface_json` and `md_frames_surface` emit the
>   tables via the shared `surface.vertex_index_tables(mesh)`; the identity was always on
>   the mesh, both were building their payload by hand and dropping it. `_SurfAtom` (NAMD)
>   had to grow the nucleotide triple — it carried only `strand_id`.
>
>   **Colour is suppressed for a `scalar` payload, opacity is not.** The flexibility map's
>   viridis ramp IS the information in RMSF mode, so a cluster tint would destroy it; the
>   fade still applies, matching "colour is mode-gated, opacity is not" everywhere else.
>
>   The oxDNA display cache (`_DISPLAY_OUT_CACHE`) is an in-process dict with no natural
>   invalidation, so `_SURF_PAYLOAD_V` participates in its key — **bump it whenever
>   `frame_surface_json`'s output changes shape**, or a long-running server keeps serving
>   pre-change payloads.
>
>   **The binary format has no version field, and deliberately so.** Each trailing block is
>   `u32 kind · u32 tableLen · UTF-8 JSON table · u32[nVerts] index`, optional and
>   self-describing, so an old decoder stops when it runs out of bytes. That is how the
>   nucleotide block was added without a magic bump. Two traps if you add a third: the
>   variable-length JSON table leaves the offset unaligned, so index blocks must be copied via
>   `buf.slice()` and never viewed in place; and `tests/test_surface_bin_transfer.py::_unpack`
>   asserts zero trailing bytes, which is the canary that catches an encoder/decoder mismatch.
> - **Surface**: `applyStrandAlphas(Map)`. One merged mesh, one material, so `material.opacity` is
>   global (the sidebar slider owns it) and the fade rides a per-VERTEX attribute — **reusing the
>   same `instanceAlpha` name and patch**, because `attribute float instanceAlpha` is per-vertex in
>   GLSL and only becomes per-instance when the buffer is an `InstancedBufferAttribute`. That reuse
>   is what makes photo mode's re-install work here for free. The two multiply in the shader.
>   **Trap:** `setOpacity`'s `transparent = val < 1.0` would switch blending off at slider 1.0 and
>   silently discard the fade — it is now `|| _strandAlphaMap.size > 0`.
>
> Both are driven by `atom_surface_display.js`, whose colour subscriber did **not** watch
> `currentDesign` — a swatch drag changes neither `coloringMode` nor `strandColors`, so it needed a
> `clusterDisplaySignature` guard to see cluster edits at all.
>
> **Nothing in this pipeline is left uncovered.**
>
> **Closed 2026-08-01: overhang link arcs + flexible arcs.** `scene/overhang_link_arcs.js` and
> `scene/flexible_arcs.js` each own their meshes and honoured no colouring mode at all. Both now
> resolve their cluster from the A-side anchor nucleotide, falling back to B, and fade to the
> LOWER of the two alphas — the same owner rule as crossover arcs and extra bases, so a connection
> never disagrees with the geometry it joins. Two things worth knowing:
> - **`flexible_arcs` had three module-level SHARED materials** (`_tubeMat`/`_beadMat`/`_slabMat`)
>   handed to every connection's meshes, so per-connection colour or fade was structurally
>   impossible — one write hit every arc. They are now per-connection, and `_clear()` disposes
>   them (the shared ones deliberately were not disposed; that asymmetry is a leak if you revert
>   half of this).
> - **`overhang_link_arcs` materials carry their own base opacity** (arcs 0.85, slabs 0.90), so the
>   cluster factor MULTIPLIES rather than replaces — captured once as `userData.baseOpacity` so
>   repeated refreshes don't compound. Both are pinned by real behavioural tests in their
>   `.test.js` files.
>
> Still true for both: they respond to `coloringMode` via their own subscribers, because the
> design-change subscriber that drives their rebuild never fires for a mode switch.
>
> **Closed 2026-08-01: crossover ARCS.** Plain crossovers (no extra bases) are drawn as arcs by
> `unfold_view.js`, and **they render in the plain 3D view too** (straight, bow = 0), so this was
> visible without ever entering unfold. They had no cluster colour (`_arcModeColor` handled only
> `overhang-only`; the file's comment said cluster "isn't wired to crossovers") and no per-arc
> alpha at all. Fixed by widening the merged colour attribute from RGB to **RGBA** — all arcs of a
> strand type share one `LineSegments` and one material, so three's `USE_COLOR_ALPHA` is the only
> per-arc channel there is. See `.claude/rules/unfold.md` for the stride contract; a `* 3` index
> left in that buffer silently smears one arc's blue into its neighbour's alpha.
>
> **Closed 2026-08-01: crossover extra bases and 5′/3′ extensions.** Both were reported in-app as
> "doesn't inherit the cluster's colour" and both had the same root shape — geometry that is not
> addressed the way the lookup assumed.
> - **Extra bases** live in `design_renderer`'s own `_xoverBeadsMesh`/`_xoverSlabsMesh`/
>   `_xoverConnMesh`, which `applyColoring` and `setClusterAlphas` cannot reach at all. They now
>   get `_applyXoverColoring('cluster', design)` for colour and `_applyXoverClusterAlpha()` for
>   fade (lazy install, so a design with nothing faded pays nothing). An extra base takes the
>   cluster of the crossover's A-side nuc, falling back to B — same owner for both, so they cannot
>   disagree.
> - **Extensions** render on synthetic `__ext_<id>` helices that appear in no cluster's
>   `helix_ids`, and their `domain_index` is an out-of-range sentinel (`-1` for 5′,
>   `len(domains)` for 3′ — `design_geometry.py`), so **neither** the domain tier nor the helix
>   tier could ever resolve them. Opacity always worked (`clusterNucKeys` emits `h:__ext_<id>`);
>   colour did not, until `buildClusterColorLookup` grew the matching registration pass. If you
>   add a third thing keyed by nucleotide, check it against an extension bead first.
>
> The curved groups look like a one-line `_fadeMat(mesh.material, a)` and are not: their
> `material.opacity` is already absolutely owned by the deform cross-fade at four sites, each
> writing an absolute value, so an alpha factor written there is clobbered on the next lerp frame.
> This is the P1 item in `memory/project_mixed_representation.md`; fixing it now buys two features.

## Color merge

- `_effectiveColors(strandColors, strandGroups)` — `design_renderer.js:151`. Takes **two maps and
  returns a whole `{strandId: hex}` object**; it is not a per-strand lookup. Group color
  **overwrites** the per-strand override (`:153-157`).
- Palette fallback is *not* in that function — applied downstream (`:695-696` `?? palette.get(sid)`,
  and inside `palette.js::nucColor` :230).
- `STAPLE_PALETTE` here is the canonical copy, `scene/helix_renderer/palette.js:28`
  (imported `helix_renderer.js:33`). **Four other copies exist repo-wide and all AGREE**
  (`constants.py`, `surface.py`, `cadnano-editor/pathview/palette.js`,
  `color_util.js`+`selection_manager.js`) — verified 2026-07-31; the list is kept in the
  `constants.py` comment. `design_renderer.js` imports only `buildStapleColorMap`.
- **`buildStapleColorMap` is the palette ASSIGNMENT, and it is shared state.** It pins a slot per
  `strand.id` in a module-level `_pinnedByDesign` map, so a mutation that reshuffles `design.strands`
  does not recolour untouched staples. **Any consumer that wants to agree with 3D must call it, not
  re-derive `index % 12`** — `ui/spreadsheet.js` did the latter until 2026-07-31 (TD-02) and its
  row swatches, colour sort key and exported .xlsx each used a different index.
- **Cluster colour precedence, highest first (2026-08-02):** `provenance` → tier → explicit
  colour → later array entry. **A cluster the USER built always outranks one the app made by
  itself**, because auto clusters routinely blanket every helix — an imported design gets a
  "Scaffold Cluster" AND a "Geometry Cluster" covering all of them, and either could silently
  win the colour on a nucleotide the user had deliberately clustered. Provenance is
  `ClusterRigidTransform.auto_created`, set at every auto creation site (the catch-all,
  all four `cluster_autodetect` passes, overhang-duplex children, the deformation synthetic,
  PDB import); only `POST /design/cluster` leaves it false. Designs saved before the field
  existed are backfilled once on load by a `model_validator(mode="before")`.
  **Name is NOT a usable proxy** — `cluster_autodetect` also emits a plain `"Cluster N"`,
  identical to the user-created default — so the legacy inference keys only on `is_default`,
  `overhang_duplex_driver_id`, and the two unambiguous `"Scaffold Cluster "` / `"Geometry
  Cluster "` prefixes. The single predicate is `cluster_entries.isAutoCluster`, used by
  `palette.buildClusterColorLookup` and both walks in `color_util`, so the bead, atomistic and
  surface views cannot disagree. **OPACITY deliberately ignores provenance** — overlapping
  fades take the minimum, so there is no winner to pick.
- **Cluster coloring goes through `buildClusterColorLookup`, not `buildClusterLookup`.** The latter
  returns a cluster *array index* and still has three consumers that want exactly that
  (`joint_renderer`, `assembly_renderer_shared` ×2). The former returns a packed colour and is what
  `applyColoring('cluster', …)` + `cylColorFor` use, because a cluster can now carry a user-set
  `color` that overrides its `STAPLE_PALETTE[i % 12]` slot. Overlap resolution: domain tier beats
  helix tier (unchanged), and **within a tier an explicit colour beats an unstyled cluster**, ties to
  the later array entry. That last rule exists because overlapping clusters are normal — a design
  with a scaffold cluster and a geometry cluster over the same 59 helices would otherwise make the
  swatch on one of them do nothing at all. With no colours set the output is identical to the old
  palette path (pinned in `palette.test.js`). `color_util.js` carries the atomistic/surface twin.
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
handlers: `selection_manager.js` `_highlightStrand` / `_highlightDomain` / `_highlightBead` /
`_highlightCluster` → `_setSelectionGlow` → `designRenderer.setGlowEntries` **and**
`designRenderer.glowCylinderDomains` — at cylinder LOD the glow is an additive *cylinder* outline,
not spheres. `store.setState({selectedObject})` happens in the same handlers but nothing keys off
it for glow.

**`setGlowEntries` has ONE writer: `_composeGlow()`** (`selection_manager.js`). Three independent
pools feed the same layer — the strand/bead selection (`_selectionGlowEntries`), the Alt-picked
measurement beads (`_ctrlBeads`), and the base-level pool (`_baseGlowEntries`) — and each used to
call `setGlowEntries` itself, so whichever wrote last clobbered the other two. `_setSelectionGlow`,
`_clearSelectionGlow` and `_refreshCtrlGlow` all route through the composer now. **Adding a fourth
pool means adding a term to `_composeGlow`, never a new `setGlowEntries` call** — the same
single-writer discipline the `instanceAlpha` channel has.

Base-level glow entries expose a **live `pos` getter** (read from `getMatrixAt` on access) rather
than a captured Vector3: `refreshAllGlow` fires every simulation frame and `glow_layer`'s
`_writeEntries` copies immediately, so one shared scratch vector is safe and the glow tracks a bead
moving under MD playback.

## `domain_ends.js` (formerly `blunt_ends.js`)

Rings/labels at domain ends. `initDomainEnds(scene, camera, canvas, { onDomainEndClick,
onDomainEndRightClick, isDisabled, getUnfoldView })` :350, called `main.js:3006` — where **the
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
- ~~**`refreshAllGlow()` refreshes 6 of the 7 layers**~~ — **FIXED 2026-08-01** (TD-05).
  `_captureGlowLayer` was omitted; it is now refreshed at `:980`. The lag was worse than the old
  note said: `refreshAllGlow` has **5 callers**, and one is inside `applyFemPositions`
  (`design_renderer.js:1068`), so it fires on **every simulation frame**, not just unfold. Capture
  strands are precisely the beads `applyFemPositions` moves (`:420-422`), so with "Highlight
  strands" on the white halos stayed at design positions while the strands went to the oxDNA frame.
  **Pinned by `design_renderer.test.js`** — a source-text test asserting the created-layer list and
  the refreshed-layer list agree. Add an 8th glow layer and that test tells you to refresh it.
- **The variable is `bluntEnds`, the module is `domain_ends.js`.** The three stale *comments*
  (`loop_skip_highlight.js:254`, `unfold_view.js:1170`, `cadnano_view.js:91`) were fixed
  2026-08-01. **The identifiers deliberately stay** — `getBluntEnds` is a named dep in **7 factory
  signatures** (`unfold_view:42`, `cadnano_view:42`, `deform_view:25`, `slice_plane:144`,
  `expanded_spacing`, `animation_player`, `debug_overlay`), a destructured `bluntEnds` opt in 4 more,
  and `toolFilters.bluntEnds` is a **persisted store key** (`store.js:137`, in the `ui` slice `:411`)
  — renaming it resets the toggle for every existing session without a migration. Not worth it.
  Unrelated and **correctly** named: `ui/blunt_end_menus.js`, `scene/blunt_end_connectors.js` and the
  backend's `blunt` usage are about real blunt-end duplex termini. Never blanket-rename `blunt`.
- **`scene/arc_tube_geometry.test.js` tests a file that does not exist** — a 2026-06-07 throwaway
  diagnostic still in the suite, and it has since **drifted**: it hardcodes tube radius `0.63` while
  the live constants are `PREVIEW_ARC_RADIUS = SELECTION_ARC_RADIUS = 0.147` (`:78-79`), so its exact
  bbox tuples describe geometry the app has not built since 2026-06-07. Deletion is parked as
  **DEC-04** in `memory/project_tech_debt.md` (test deletion is a user call).

## Coverage — honest

| File | LOC | Tests |
|---|---|---|
| `design_renderer.js` | 1,554 | **3**, all *structural* (source-text) — none of its 92 methods run |
| `helix_renderer.js` | 5,232 | **4**, both pure helpers (`orderStrandNucleotides`, `directConnectedOverhangIds`). `buildHelixObjects` (~2,200 LOC) and all 69 controller methods: untested |
| `glow_layer.js` | 188 | **0** |
| `domain_ends.js` | 873 | 4 |
| `crossover_connections.js` | 543 | 8 |
| `helix_renderer/palette.js` | 253 | 4 (all on `buildStapleColorMap`) |

**23 tests for ~8.6k LOC.** Several sibling tests (`ui/cando_display.test.js`,
`ui/lammps_display.test.js`, `ui/md_panel.test.js`, `scene/slice_highlighter.test.js`) *mock*
`designRenderer` rather than exercise it — verified 2026-08-01, all four build literal mock objects.
A green suite proves nothing about this pipeline. Rendering changes need an app exercise; see
`CLAUDE.md` → Verification expectations.

**This section is the OWNER of the render-coverage debt** (promoted here from `project_tech_debt.md`
TD-05, 2026-08-01 — it auto-loads on these files, which the ledger does not). Do not attempt a WebGL
harness. Two things actually work here, in value order:

1. **Pin the pure functions**, one per pass: `_effectiveColors` (`design_renderer.js:151`),
   `bezierAt` / `arcControlPoint` (`crossover_connections.js`), the `CG_LOD` ↔ representation
   mapping. Each is argument-in / value-out and needs no scene.
2. **Pin cross-list agreement with source-text tests** where two lists in one closure must match.
   `design_renderer.test.js` is the template: it caught nothing at runtime but would have caught the
   `_captureGlowLayer` omission the day it was written. Other candidates in this file: the 7
   representations vs `CG_LOD`; the 16 instanced meshes vs `_reapplyDetailVisibility`'s list; the
   `_applyRepOverrides` skip-list documented under "Known gap" above.

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
