# Shadow-catching floor — 2026-08-01 — supporting detail

[Topic head](../../project_photo_mode.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

Measured on 18hb, identical restored pose, one 120 px right-drag (throwaway e2e
stack, spec deleted after the run): 55° → 54 px of structure travel, 20° → 78 px,
8° → 86 px, 90° → 21 px, with `panSpeed` = 0.800 / 0.271 / 0.108 / 1.537 exactly
tracking tan(fov/2). Pre-fix the same drags would have been ~639 px at 8° and
~11 px at 90° — a 59× spread, now 4×. **The residual 4× is NOT the lens**: it is
Multiscale re-parking the pivot on the NEAREST helix axis at every pointerdown,
so pan is scaled by (camera−surface) while what you watch move is the structure
CENTRE — a gap that closes as the long lens dollies out. Flattening that means
changing the near-surface pivot rule (`multiscale_controls._repivot`), which is a
whole-app nav-feel change, not a photo-mode one.

**Export card** — tiled PNG at any resolution. TILING IS NOT OPTIONAL: a render
target above `MAX_TEXTURE_SIZE` silently clamps and yields a black image, and 300
DPI (4200×2970) already exceeds the 4096 limit common on WSL/integrated GPUs.
The offscreen renderer is a SEPARATE GL CONTEXT, so it needs its own composer,
its own FigurePass params, its own cue range per tile, and its own
`shadowMap.enabled` — none of the live renderer's GPU state carries over. That is
the rule that keeps preview and export in sync. Export representation is NOT
wired (it needs the assembly rep-upgrade machinery + an `api` dep).
The card also carries the **video export** — see its own section below.

**Materials card** — one preset per representation (full / cylinders / surface /
atomistic), dropdowns built from `PRESET_LABELS`, so adding a preset in
`material_presets.js` appears with no markup change. Defaults are the FIGURE
materials (`flat` / `cpk-flat`, `specularIntensity: 0`).

**`photo_renderer/mesh_repr.js`** — `MESH_NAME_TO_REPR` + `inferRepr` + `reprOf`,
lifted verbatim out of photo_renderer.js so both photo modes share one name table.
The exp mode reads the repr from the mesh's ORIGINAL material, before the swap:
`MeshPhysicalMaterial` extends `MeshStandardMaterial`, so inferring after a swap
makes every unnamed mesh look 'atomistic' — the latent bug photo_renderer's own
`setMaterialPreset` still has.

**`resetKeyDirection()` lives on the MODE, not the panel.** The panel importing
the default constants would close an import cycle (the mode already imports the
panel), so the defaults have exactly one home.

**Ambient occlusion: built, evaluated, retired** — `archive/multishadow_ao/` has
the code and rationale. Occlusion modulates the AMBIENT term, so at ambient 0.15
it can touch only 7% of the light and toggling it changes nothing on screen.

**A merge of these features INTO photo_renderer.js was attempted and reverted
(2026-07-28)** — too many overlapping options; the plan is to rebuild from the
ground up. The shipping photo mode keeps its own floor-gated shadow rig,
`floorShadows` and `shadow-catcher` untouched.

**Four bugs found here that no headless test could reach:**
1. `renderer.shadowMap.enabled` is a PROGRAM parameter (`WebGLPrograms.js`) and
   `setProgram` never re-checks it. Any internal scene render that flips it off
   compiles every material without `USE_SHADOWMAP`, permanently. Use
   `shadowMap.autoUpdate = false` to skip shadow rendering instead.
2. Shadow bias must scale with the shadow-map TEXEL, not the scene radius. A
   radius-proportional bias reaches 2–8 bead diameters on a real design and
   ERASES the shadow rather than de-acneing it.
3. `swapToFlatMaterials` must preserve `depthWrite`. A fresh material defaults to
   TRUE, so overlays drawn `depthWrite:false` became opaque occluders AND shadow
   casters, and defeated the depthWrite exclusion in `shadow_bounds.js`.
   **Corollary, 2026-08-01:** that inheritance is only right for *overlays*. A
   STRUCTURAL mesh whose `depthWrite` tracks a user opacity control (the base-pair
   slabs + their crossover extra-base twins, then driven by the sidebar slab-opacity
   slider) inherited `depthWrite:false` and was then dropped from the shadow pass by
   `isShadowExcluded` — `castShadow` *and* `receiveShadow` both went false, silently,
   only below the default opacity. Such meshes now set
   `material.userData.photoForceDepthWrite = true`, which `swapToFlatMaterials`
   honours. Pinned by two `photo_mode.test.js` cases (overlay stays false, flagged
   structure forces true). Verified in-app by A/B: toggling `baseSlabs.castShadow`
   changes the rendered figure at both 0.90 and 0.45 slab opacity.
   **Update 2026-08-02:** the slab-opacity slider is gone and both slab materials are
   built OPAQUE, so nothing drives their `depthWrite` down any more. The flag STAYS —
   per-cluster/reference fades still turn those materials transparent through
   `instanceAlpha`, which is the same hazard by a different route.
4. Editor overlay geometry (~100 µm) silently sets the frustum and puts the whole
   design inside one texel. `shadow_bounds.js` rejects contributors >8× the
   median extent and names them in a console warning.
5. **`swapToFlatMaterials` must also carry `onBeforeCompile` — 2026-08-01.** The
   same class of bug as 3, one level deeper. `makeMaterial` builds a *brand-new*
   material, so any behaviour living in a shader patch on the source material is
   silently gone. The live case is `instanceAlpha`, the per-instance alpha channel
   behind reference-geometry ghosting, mixed-representation region visibility and
   (new) per-cluster opacity: the geometry attribute survives the swap untouched
   (geometry is never replaced here), but with no `onBeforeCompile` the fragment
   never multiplies by it, so **everything faded rendered fully OPAQUE in photo
   mode and in the tiled export** — which reuses the same swapped materials.
   FIX: the patch moved out to `scene/instance_alpha.js` as a module-level named
   function + `applyInstanceAlphaMaterial(mat)`, which marks
   `userData.instanceAlphaPatch`; the swap re-installs it on that marker, exactly
   how `photoForceDepthWrite` works. Two subtleties worth not rediscovering:
   `transparent` must be set explicitly (the swap's opacity carry-over is gated on
   `src.opacity < 1`, and it is 1 — the fade is in the attribute), and the function
   must stay module-level, because three derives its program cache key from
   `onBeforeCompile.toString()`; a per-material closure would compile one shader
   per mesh. `depthWrite` stays TRUE — one InstancedMesh holds both faded and
   opaque instances, and `isShadowExcluded` would drop the whole mesh from the key
   shadow. **No new save slot is needed:** the patched photo material is one of the
   `saved` map's swapped materials, so `restore()` already disposes it and puts the
   original (which kept its own patch) back. Pinned by 4 `photo_mode.test.js` cases
   + `instance_alpha.test.js`.

**After ANY edit to a tab pane in index.html**, check whole-file `<div>`/`</div>`
balance and that the pane's nesting depth matches its siblings. A stray `</div>`
here once pushed `#viewport-container` out of `#main-area`, collapsed it to zero
height and clipped the welcome screen away — no JS error, green suite (95096cf).

## Simulation displays survive the Photo tab — 2026-07-14

**The bug was never in photo mode.** The photo renderer reuses the live `THREE.Scene`
in place (material/light/env swap; no clone, no rebuild from topology), so it renders
whatever is on screen — including simulated positions. But every engine panel writes its
result into the *shared* bead overlay via `designRenderer.applyFemPositions()` (there is no
separate sim scene graph), and each panel used to revert that overlay on **any**
`nadoc:left-tab-change` away from `dynamics`. Clicking Photo fires that event → oxDNA /
NAMD-MD / live-oxDNA displays called `stopAndRestore()` → `revertToGeometry()` **before**
`photoRenderer.activate()` drew a frame. The user photographed the un-simulated design.

**Fix: [frontend/src/ui/display_tab_policy.js](../../../frontend/src/ui/display_tab_policy.js)** — one
shared predicate (`shouldTearDownDisplays(activeTab)` / `shouldResumeDisplays` /
`displayTabIds`) declaring `dynamics` the display home tab and `photo` a *view-only,
display-preserving* tab. Consumers: `oxdna_jobs_panel` (`_allDisplaysOff`),
`oxdna_live_controller` (`stop()`), `md_jobs_panel` (both the `left-tab-change` listener AND
the per-button click handler, whose `_isDynamicsTabVisible()` DOM check became
`_isDisplayTabVisible()`). Polling still pauses off-Dynamics; only the *teardown* is exempted.
**All the panels must agree** — one that still tears down un-simulates the shot for everyone.

Also: `main.js setActiveTab` used to call `_leaveAnimationsTab()` (a backend re-seek →
`design_renderer._rebuild()` from topology) on Animations→Photo, which dropped *every*
overlay. Now deferred via `_animLeaveDeferred` and paid off when Photo is exited to a
non-Animations tab.

**Known latent bug, deliberately NOT fixed:** `mrdna_jobs_panel.js:548`,
`cando_jobs_panel.js:698`, `snupi_jobs_panel.js:620` guard on `e.detail?.from`, a field the
event never carries (`detail` is `{activeTab, collapsed}`), so those overlays are torn down
on *no* tab change at all — they already survive Photo, but they also survive Design/Assembly,
which the code clearly did not intend. Making the guard live is a behaviour change beyond the
Photo fix; ask before doing it.
