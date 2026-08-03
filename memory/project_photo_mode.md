---
name: photo-mode
description: "Photo mode — flat figure materials, camera-pinned key shadow, ChimeraX depth-outline silhouette, tiled export. v1 (PBR/HDRI/bloom/PT/floor) was archived 2026-07-29."
metadata: 
  node_type: memory
  type: project
  originSessionId: caf07b9d-c547-4a4a-b679-8f8f745bc1f2
---

> **REPLACED 2026-07-29.** What shipped as "Exp. Photomode" IS photo mode now.
> The old one (`photo_renderer.js` + `photo_mode.js` + `photo_panel.js` +
> `photo_figure_panel.js` + floor/post_processing/style_presets/inscatter) moved
> **verbatim** to `frontend/archive/photo_mode_v1/` — read its README before
> reviving anything. There is ONE photo tab. The v1 history — HDRI, bloom, path
> tracer, floor, mist, style presets, profiles, the export-rep upgrade — moved to
> [project_photo_mode_archive.md](project_photo_mode_archive.md); mine it only for
> a specific past decision.

Photo mode lives at [frontend/src/scene/photo_mode.js](frontend/src/scene/photo_mode.js),
UI in [frontend/src/ui/photo_panel.js](frontend/src/ui/photo_panel.js)
(`data-tab="photo"`, HTML under `#tab-content-photo`), with the shared sub-modules
that SURVIVED v1 under `photo_renderer/`: `figure_pass`, `figure_camera`,
`material_presets`, `lighting_presets`, `shadow_bounds`, `mesh_repr`.
`main.js` carries only an import + factory init + the `TABS` entry (LOC 8074 → 8059
on the merge — the archive removed more wiring than the rename added).

**Why:** publication-grade rendering for figures and animations. Activate/deactivate must restore the live scene exactly (lights, materials, scene.environment, scene.background, **renderer tone mapping**) — the live editor still has to work after exit. **How to apply:** never mutate scene state from photo-mode code outside the saved-state pattern (`_savedMaterials`, `_savedSceneEnv`, `_savedSceneBackground`, `_savedLightState`, `_savedToneMapping`/`_savedExposure`). Adding a new visual feature means adding a save slot and a restore step in `deactivate()`.

## Inherited from v1 — tone mapping is load-bearing, don't drop it

v2 was written from the ground up, but one v1 fix was re-derived into it and must
stay: [photo_mode.js:513](frontend/src/scene/photo_mode.js#L513) sets
`THREE.ACESFilmicToneMapping` in `activate()` (exposure hardcoded `1.0`, no
slider), restores both at [:621](frontend/src/scene/photo_mode.js#L621), and the
offscreen export renderer sets the same at
[:772](frontend/src/scene/photo_mode.js#L772). **Why it is not cosmetic:** with
`NoToneMapping` (the Three.js default), HDR values hard-clip at 1.0 — that clipping
is what produced v1's screen-filling **yellow/purple wash** (2026-06-18 audit).
Pinned by `photo_mode.test.js` (ACES on activate, `NoToneMapping` on deactivate).
Export parity depends on the offscreen renderer matching the preview.

The rest of v1's lighting stack is gone by design — no IBL (`scene.environment =
null` unconditionally, "ambient occlusion IS the ambient light here"), no bloom, no
Sun/preset-rig duality, no fluorophore point-lights, and no *visible* ground plane
(there is now a shadow CATCHER — see below — which is a different thing). So v1's other four
remediations (Sun-sole, PMREM re-bake isolation, Reflector state isolation, the
emissive clamp) have **no live subject matter**; they are recorded in
[project_photo_mode_archive.md](project_photo_mode_archive.md) for anyone reviving
`frontend/archive/photo_mode_v1/`.

**One live orphan.** `FLUORO_EMISSIVE_MAX = 25` +`makeFluorophoreEmissive()` in the
surviving [material_presets.js:163](frontend/src/scene/photo_renderer/material_presets.js#L163)
have **no caller in `src/`** (only the archived v1 renderer) and no test. Its
comment block is the only in-code record of the pre-tone-map bloom mechanism, and
it points at `photo_renderer.js`, which no longer exists live. Don't delete it
without moving that explanation; don't trust its file pointer.

## Camera-pinned key shadow — 2026-07-28

Flat figure materials, a CAMERA-PINNED rig (ChimeraX `move_lights_with_camera`),
and a key-light shadow map **not gated on a floor** (v1 gated its rig behind
`floor !== 'off'`, which made helix-on-helix shadow impossible there).
No preset selector — the Key/Fill/Ambient sliders ARE the preset.

**The key light is steered in the SCREEN frame, not the Sun's floor-normal
frame.** `keyLightDirection(azimuth, elevation)` (pure, exported): azimuth sweeps
around the screen (0 = from the right, 90 = above, 180 = left), elevation tilts
toward the viewer (0 = grazing/longest shadow, 90 = down the camera barrel where
the shadow hides behind the object, negative = rim light from behind). The angle
off the camera axis is exactly `90 - elevation`. Defaults (135°, 35.264°)
reproduce ChimeraX's own key direction `(-0.577, 0.577, 0.577)` exactly. Only the
KEY light is steered; the fill keeps the preset's direction. This replaces the
shipping mode's Sun, whose polar frame is the floor normal — there is no floor
here and the rig is pinned to the camera, so the screen is the natural frame.

**The rig ships at MAX CONTRAST, not ChimeraX's numbers.** ChimeraX `full` is key
0.7 / fill 0.3 / ambient 0.8, but a cast shadow only subtracts the KEY light, so
fill+ambient are a floor: the deepest shadow removes just 39% of the light. Key
2.0 / fill 0 / ambient 0.15 → ~93%. `DEFAULT_EXP_SETTINGS` key/fill/ambient MUST
equal `LIGHTING_PRESETS.full` — `_rebuildRig` applies the settings OVER the
preset, so a mismatch silently overrides it. Pinned by a test.

**THE parameter is shadow-map resolution in nm/texel.** ChimeraX's map defaults
are sized for a ~5 nm protein; on a 150 nm origami a 1024 map at 64 directions is
2.34 nm/texel, wider than a duplex, so a thin arm cannot cast a readable shadow.
The panel prints live nm/texel vs a duplex and warns when it is too coarse.

**Panel cards use the `.ox-card` component** (`src/styles/components.css`), the
same one the Simulations tab uses — NOT a bare `.panel-section`, which has no
card look at all. That was the first attempt and it rendered flat. The pop-out
comes from a double background on a transparent border: a faint fill on
padding-box plus a top→bottom `#3f464f → #20252b` gradient on border-box, which
keeps rounded corners that `border-image` would square off. Markup:

    <div class="ox-card" id="X-panel">
      <div id="X-heading" class="ox-card__header" style="color:#c9d1d9">
        <span id="X-arrow" class="ox-card__chevron icon icon--xs icon--rotates"
              data-icon="chevron-down"></span><span class="ox-card__title">Title</span>
      </div>
      <div id="X-body" class="ox-card__body"> … </div>
    </div>

Chevron sits LEFT of the title. Collapse persists via
`getSectionCollapsed/setSectionCollapsed('photo', …)`. Verified by comparing
computed styles against a live `#simulate-jobs` card — copy that shape for any
new card here rather than inventing one.

## Video export — an animation rendered through photo mode, 2026-08-02

**The redo dropped the ONE API the video path needed, and it went unnoticed
because the caller survived.** [scene/export_video.js:91](../frontend/src/scene/export_video.js#L91)
`exportPhotoVideo()` was written for v1 and is still there, complete — frame loop,
WebM + GIF, text-overlay compositing, abort, progress, download. It was dead code:
nothing imported it, and its first act is to throw unless
`photoRenderer.beginFrameSession()` exists, which only v1 had
(`archive/photo_mode_v1/photo_renderer.js:1640`). v2 shipped `renderToBlob` alone.
So "photo mode has no video export" was really "photo mode is missing a ~90-line
function its own exporter asks for by name".

`renderToBlob` is now a **one-shot wrapper** over
`beginFrameSession(width, height, {followMotion})` → `{renderFrame, dispose, tiles}`.
Everything previously rebuilt per call — the max-texture probe, tiling maths,
stitch canvas, offscreen renderer, composer, FigurePass — is hoisted to the
session; only `setViewOffset` + params + `composer.render()` stay per tile.
**This is not an optimisation.** Browsers block new WebGL contexts after ~30, so a
`renderToBlob`-per-frame loop dies around frame 30 with *"Web page caused context
loss and was blocked"*. `photo_frame_session.test.js` pins both halves: 40 frames
from one session = **2** renderer constructions, and the same 40 frames the old way
= **80**. That second case is the *discriminator* — it is what proves the first
test would have failed before the split (the adapted-code pin rule in `CLAUDE.md`).

**Two things the live preview gets for free that an offline export must do
itself.** `_perFrameSync` only runs inside the `setRenderFn` render-loop override,
and a frame-stepped export never ticks it. `_syncForOfflineFrame()`, called at the
top of `renderFrame`, replaces it:

- **`sceneSignature` changed → `resync()`.** Meshes are REPLACED mid-timeline —
  trajectory keyframes swap the heavy atomistic/surface rep in and out
  (`trajectory_keyframes.js` `show`/`suspend`), pre-baked geometry frames rebuild
  beads — and every fresh mesh arrives with the EDITOR's materials and shadow
  flags. Without this an export starts correct and silently degrades partway.
- **`followMotion` → `_rebuildRig()` every frame.** Cluster rotations and binding
  hinges move the bounding box while the mesh set is IDENTICAL, so the fingerprint
  cannot see it and the shadow frustum stays fitted to where the structure *used
  to be*. Only the video caller pays this; stills leave it off (`false`).
- `_syncRigToCamera()` — the rig is camera-pinned and a camera-pose keyframe moves
  the camera every frame.

**The photo lens wins over the animation's camera poses.** `animation_player.js`
gained `setLockFov()` (mirrors `setDisablePoses` in shape and API slot) guarding
its two `camera.fov =` writes at the spin and lerp branches; `exportPhotoVideo`
brackets the frame loop with it. Deliberately **not** `setDisablePoses`, which
suppresses the whole pose lerp — the camera *move* is exactly what we keep.
Without the lock a 15° publication lens snaps to the 55° the pose was captured at
on the first posed keyframe, and since `setFOV` had already dollied for 15°, the
framing goes with it.

`_figureParams()` and `_pushCueRangeTo(pass)` were extracted **first**: the 11-key
param block and the cue-range fit each existed in two copies (preview + still
export) and a third was about to be added. Same "export parity is not automatic"
rule as the Export card above — duplicate copies are how preview and export drift.

**The UI is in the Photo tab, not the Animations tab, and that is forced.**
`main.js setActiveTab` exits photo mode for any `tabId !== 'photo'`, so the
Animations panel can never be open while the mode is active. The Export card
gained an animation picker (read straight off
`currentAssembly?.animations ?? currentDesign?.animations`, same source and
precedence as `animation_panel.js`), **video-only** size presets 720p–2160p (the
*print* presets tile 4–6× per frame — wrong for 300 frames), format, fps and a
live note. `animationDuration()` re-derives clip length as `Σ(transition + hold)`
exactly as the player's `_buildSchedule` does, so pricing the export never calls
`play()` — which would bake geometry just to populate a dropdown.

**Known limits, all pre-existing and shared with the raw-canvas Animations-tab
export** (logged in `issues_ledger.md`, none photo-specific): a trajectory frame
can capture stale atoms (`oxdna_display._applyHeavy` is `async` and unawaited);
assembly joints animate in NO exported video (`export_video` calls `play()` with
no opts, so `onJointUpdate` is null); `configuration_id` is inert on the player.

## Shadow-catching floor — 2026-08-01

**It started as a BUG the user liked.** In photo mode, selecting a cluster from the
movable-clusters sidebar made a translucent infinite ground plane appear that caught
the key shadow. Nobody built it. `TransformControls` ships a 100000×100000
`TransformControlsPlane` (its mouse→3D drag plane) whose material is `visible:false`;
`cluster_gizmo.attach()` adds the helper root to the scene and flips it visible.
`swapToFlatMaterials` then replaced that material with a fresh photo material —
carrying `side`, `depthWrite`, opacity and colour across, but **not `visible`**, which
defaults to true. The new material also carried `depthWrite:true`, so `isShadowExcluded`
(which tests the CURRENT material) stopped recognising it as an overlay and
`_applyMeshShadowFlags` gave it `receiveShadow = true`. Casting was blocked only by the
separate `_rejected` outlier guard — the same object caught one layer down.

**Fix:** `swapToFlatMaterials` now skips `src.visible === false` outright — the same
class of contract as the `depthWrite` rule in bug 3 below. Pinned in `photo_mode.test.js`
(proven by re-running the new case with the guard line removed: fails without it).

**Feature:** [photo_renderer/shadow_catcher.js](../frontend/src/scene/photo_renderer/shadow_catcher.js)
— a real, owned version. `THREE.ShadowMaterial`, so it is transparent everywhere the
shadow map says "lit": the structure keeps floating on the flat background and only the
contact shadow appears. **It gates nothing** — that is the whole difference from v1's
floor, which hid helix-on-helix shadowing behind `floor !== 'off'`.

- `userData.photoFloor` was already read in three skip-lists and never written; now it is.
  `swapToFlatMaterials` and `isShadowExcluded` needed no change. Two DID:
  `_applyMeshShadowFlags` needs an explicit `photoFloor` skip (falling through sets
  `receiveShadow = !isShadowExcluded(obj)` = **false** on the one mesh whose job is to
  receive), and `FigurePass._hideNonSurfaces` needs one too, or the silhouette draws a
  contour along the horizon.
- Placement is pure + tested (`shadowCatcherPlacement`): flush with the chosen FACE of the
  bounding box, centred on the other two axes, half-extent `1.25 × diagonal`. The **box, not
  the sphere** — a 400×4×400 platform's sphere would park the plane 280 nm below a 4 nm-thick
  object.
- **The user picks the side: `floorAxis` ∈ `±x/±y/±z`** (`FLOOR_AXES`, default `-y`). `-y` is
  the floor, `+y` a ceiling, `±x`/`±z` back walls. **World axes, not screen axes** — the key
  light is camera-pinned, so a screen-pinned plane would give the shadow nothing fixed to sweep
  across, which is the whole effect. Three consequences that are easy to get wrong:
  `offset` means OUTWARD from the face (so positive never buries the plane inside the design,
  whichever side is picked); the normal points **inward**, because `LightShadow.normalBias`
  offsets along it and an outward normal biases the wrong way; and the material is
  `DoubleSide`, or a ceiling seen from below is culled away entirely. The `+y` case is the
  antiparallel input to `Quaternion.setFromUnitVectors` — three handles it, but it is pinned by
  a NaN test because getting it wrong makes the plane silently vanish.
  An unrecognised axis falls back to `-y` rather than dropping the plane.
- Fitted at the tail of `_applyKeyShadow`, which is both the end of every `_rebuildRig`
  (fresh bounds) and the direct entry point for every shadow setting.
- Settings `floor` (default **on**), `floorAxis` `-y`, `floorOpacity` 0.35, `floorOffset` 0 nm;
  four controls in the Lighting card under the key-shadow group.
- **`main.js`'s `_floorReach` stub is LIVE again** (it was `() => null`, logged as debt).
  The catcher extends past the content, so the adaptive far clip has to reach its far
  CORNER (`halfExtent × √2`) or the plane gets cropped in assembly mode. Wired through a
  forward-declared `let _photoFloorReach` declared OUTSIDE the clipping block — `_photoMode`
  is a closure const ~6100 lines below the frame callback, and a TDZ read inside a frame
  callback kills `setAnimationLoop` permanently.

Verified in-app on the isolated smoke stack (18hb, off-axis camera, grazing key): the
bundle's per-bead shadow pattern is projected onto the plane with the floor on and gone with
it off; all six sides drive off the real `<select>` and land on the right face with an inward
normal. Note when eyeballing this — **only the faces the shadow is actually thrown at show
anything**. A key light from screen-above throws the shadow DOWN, so `+y` looks empty until
you invert the light (azimuth −90); that is correct, not a broken ceiling.
Zero console errors; `just smoke` green.

**Figure card** — silhouette outline + depth cue, reusing `FigurePass` directly
(no fork). Both share ONE depth+normal pre-pass and the pass is `enabled` only
when an effect is on, so both-off costs nothing.

*Silhouette: two algorithms, one uniform.* `uSilhouette` selects between the
original Roberts cross (0 — still what the shipping Photo tab uses, unchanged)
and a **ChimeraX mimic** (1 — the exp tab's default, `silhouette: 'chimerax'`).
Ported from `graphics/opengl.py` `Silhouette` + `fragmentShader.txt`
`USE_DEPTH_OUTLINE`. Four things the mimic does differently, all deliberate:
1. **Depth only — no normals.** ChimeraX has no crease term at all. That single
   fact is the fix for the "zoomed out → black line-art" caveat below.
2. **Circular disc min-filter**, radius = thickness px (`i²+j² ≤ r²`), vs a 4-tap
   Roberts cross. Thickness becomes a true pixel radius with round caps.
   `MAX_DISC_R = 4` (GLSL ES 1.00 needs constant loop bounds; slider caps at 4).
3. **The contour lands on the FARTHER pixel**, so it sits *outside* the near
   object instead of eroding it — including on empty background, which is why
   the mode does NOT early-return on background pixels and why it raises alpha
   (`alpha = max(alpha, edge)`) so an alpha export keeps the line it drew.
4. **Threshold is a constant world-space gap.** ChimeraX's
   `nf*(d0-ds) < jump*(1-nf1*ds)*(1-nf1*d0) → discard` reduces exactly to
   `Δz_eye ≥ depth_jump × (far − near)` — algebra pinned in `figure_pass.test.js`.
   ChimeraX gets a tight `(far − near)` free by refitting clip planes to the bbox
   each frame; we don't, so the orchestrator pushes the **bbox diagonal** via
   `setSceneDepth()` and the shader uses that as the span. Consequence: **the
   depth-jump slider only affects INTERNAL contours** — the outer silhouette runs
   against background depth clamped to the far plane and clears any threshold.
Panel: the old Silhouette/Creases pair was replaced by one **Depth jump** slider
(0.005–0.15, ChimeraX default 0.03). `outlineDepthSensitivity`/`…CreaseSensitivity`
survive in the settings for the Roberts path only.

The depth-cue window is
`[nearest bbox corner along the view axis, that + bbox DIAGONAL]` — the diagonal
is a CONSTANT for the design, not the current view's depth extent; scaling to the
view normalises every angle to a full 0→1 fade and washes out a thin helix seen
side-on. `computeShadowBounds` now also returns `box`/`corners`/`diagonal` so the
cue gets the same outlier rejection as the shadow frustum.

**Camera card** — FOV + parallel projection. "Parallel" is an 8° LONG LENS +
dolly, not an `OrthographicCamera`: a real ortho swap means touching every
consumer of the shared perspective camera (the `PERSPECTIVE_CAMERA` shader
defines baked into the post passes at construction, OrbitControls' distance-based
zoom, main.js's per-frame near/far rewrite). `setFOV` dollies via
`dollyDistanceForFov` so framing is preserved, and `deactivate` restores the
editor's lens WITH a dolly. A FOV at or below 8° sets the `parallel` flag, so the
checkbox can't lie. `#photo-fov-reset` (the `↺` next to the slider) calls
`photoMode.resetFOV()` → `setFOV(PERSPECTIVE_FOV)`, so the default lives in the
mode, not the panel — same rule as `resetKeyDirection`.

**The FOV slider used to break panning** (2026-08-02). `setFOV` dollies, so a long
lens parks the camera ~7× further out — and TrackballControls (i.e. Multiscale,
the default nav mode) pans by `|camera − target| × panSpeed` with **no lens term**,
as does `nav_controller`'s WASD. Result: pan flew at 8° and crawled at 90°.
[scene/fov_pan.js](../frontend/src/scene/fov_pan.js) `fovPanScale()` =
tan(fov/2)/tan(55°/2) now multiplies both — pixels-per-drag ∝ panSpeed/tan(fov/2),
so the lens cancels. **Do not apply it to OrbitControls**: its own `panLeft/panUp`
already folds `tan(fov/2)` in, so it would double-correct.

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
   slabs + their crossover extra-base twins, driven by the new sidebar slab-opacity
   slider) inherited `depthWrite:false` and was then dropped from the shadow pass by
   `isShadowExcluded` — `castShadow` *and* `receiveShadow` both went false, silently,
   only below the default opacity. Such meshes now set
   `material.userData.photoForceDepthWrite = true`, which `swapToFlatMaterials`
   honours. Pinned by two `photo_mode.test.js` cases (overlay stays false, flagged
   structure forces true). Verified in-app by A/B: toggling `baseSlabs.castShadow`
   changes the rendered figure at both 0.90 and 0.45 slab opacity.
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

**Fix: [frontend/src/ui/display_tab_policy.js](frontend/src/ui/display_tab_policy.js)** — one
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

## Publication / figure mode — 2026-07-14

**The diagnosis first, because it governs every choice below.** Photo mode was a
*product-visualization* renderer (gummy/glass/metallic PBR, HDRI, bloom, volumetric mist,
neon floor grid, mirror floor, path tracing). The user's renders "looked amateurish" next
to a cryo-EM/ChimeraX figure — and the reason is that the ChimeraX house style is a
deliberate **rejection** of exactly those knobs, not a tuning of them. A journal figure has
no specular highlight, no reflections, no bloom, no floor, no shadow. Shape is carried by
**ambient occlusion + a silhouette outline**, under a **near-parallel** camera, with **flat
matte** materials. Photorealism is what reads as amateur 3D in a paper. So the feature is
not "more sliders" — it is a second, opposed aesthetic that had to be added alongside.

**Everything is an ordinary independent setting; the "Publication" style preset is only a
named bundle that switches the right ones on.** One code path turns a settings object into
renderer state (`_applyProfile`), and a style is applied through it like a profile.

New modules (all under `photo_renderer/`):

- **[figure_pass.js](../frontend/src/scene/photo_renderer/figure_pass.js)** — the big lever.
  Silhouette **outline** (Roberts cross on linearized depth *and* view-space normals: the
  depth term gives silhouettes, the normal term gives creases) + **depth cue**. Both share
  ONE depth+normal pre-pass (`scene.overrideMaterial = MeshNormalMaterial` into a
  pass-owned RT with a `DepthStencilFormat`/`UnsignedInt248Type` DepthTexture — the same
  driver-safe combination the inscatter pass uses; do NOT attach depth to the composer's
  main target, see the gotcha below). They stay independently toggleable; `pass.enabled =
  hasEffect()` so both-off costs nothing.
  **Pre-pass exclusions** (same skip-list as the material swap): additive-blending sprites,
  line materials, and `userData.sharedLodImpostor` — the impostors compose instance
  transforms in a custom vertex shader MeshNormalMaterial doesn't have, so under the
  override they collapse to the source origin and stamp a bogus edge there.
  Background pixels (`depth >= 0.9999`) are left untouched, so the contour is drawn just
  *inside* the object and a transparent-background export stays transparent.
- **[style_presets.js](../frontend/src/scene/photo_renderer/style_presets.js)** — pure.
  `publication` / `publication2` / `studio` bundles + `resolveStyle` / `detectStyle`. The Style
  dropdown is a *view* of the settings, not a stored setting: `detectStyle` re-derives it, so it
  falls back to "Custom" the moment the user deviates. A test asserts every key a preset sets is a
  real key of `DEFAULT_PHOTO_SETTINGS` (a typo would otherwise silently no-op). **`publication2`
  (2026-07-15)** mimics a ChimeraX "soft lighting + strong ambient occlusion on black" render: same
  flat/matte materials as `publication` but with a soft directional key (`lighting:'scientific'`)
  for rounded form, strong GTAO (`ao:true, aoRadius 2.5, aoIntensity 1.5, ssao:false`) as the
  PRIMARY depth cue, **outline + depthCue OFF** (occlusion shadow separates strands, not contours —
  works because the per-strand split surface has real crevices to occlude), moderate perspective
  (`parallel:false, fov 30`), `bgType:'black'`. The dropdown is a STATIC `<select>` in index.html
  (line ~5417) — a new preset needs BOTH the STYLE_PRESETS entry AND an `<option>`. Values inferred
  from the reference image; AO strength / lighting / fov are the tuning knobs if the user wants it closer.
- **[figure_camera.js](../frontend/src/scene/photo_renderer/figure_camera.js)** — pure dolly
  maths for the near-parallel projection.
- **[ui/photo_figure_panel.js](../frontend/src/ui/photo_figure_panel.js)** — the section's
  controls; `photo_panel` constructs it and delegates `applySettings` / `syncToState`.

Plus: `flat`/`cpk-flat` **material presets** (`specularIntensity: 0` is what actually kills
the highlight — roughness alone only widens it; `matte` still catches an HDRI sheen), an
`ambient` **lighting preset** (no key light; three weak wide-spread fills), and **GTAO**
in the composer (`post_processing.js`) as real occlusion shading — the `ssao` pass stays as
the photoreal garnish and is a separate control.

### Decisions that cost time — don't re-litigate

- **"Parallel projection" is an 8° long lens + dolly, NOT an OrthographicCamera.** A real
  ortho swap means touching every consumer of the shared PerspectiveCamera: the
  `PERSPECTIVE_CAMERA` shader defines baked into SSAO/GTAO at construction, the inscatter
  pass's perspective ray march, the path tracer's camera, OrbitControls' distance-based
  zoom, and main.js's per-frame near/far rewrite — and **the composer cannot be rebuilt
  post-activate** (PMREM state → bloom paints garbage). At 8° the residual convergence over
  a 60 nm object is sub-pixel at print resolution. `setFOV` now **dollies** to preserve
  framing (`dollyDistanceForFov`), and `deactivate()` restores the editor's lens *with* a
  dolly so the user keeps whatever framing they orbited to.
- **The depth-cue window is `[nearest bbox corner, that + bbox DIAGONAL]`.** Two wrong
  versions preceded it: (1) a bounding *sphere* is orientation-blind, so a long bundle seen
  side-on reports its *length* as the depth extent — an order of magnitude too wide — and
  the fade started at the camera and washed the whole structure out; (2) normalizing to the
  *current view's* depth extent forces a full 0→1 fade in every view, so a thin helix seen
  side-on gets the same total wash as a deep bundle seen end-on. Against a **fixed** length
  (the design's diagonal, a constant), depth cue does what it should: near-nothing on a
  shallow view, strong only when you are genuinely looking down the depth of a structure.
  Anchoring to the structure (not to a fraction of camera distance) is also what makes it
  survive the parallel projection, where camera distance balloons ~7×.
- **The Style dropdown's refresh listener must be on the BUBBLE phase.** The autosave
  listeners use capture, which runs *before* the control's own handler has pushed the change
  into the renderer — a capture-phase read leaves the dropdown showing a preset the user just
  deviated from. Deferring to a microtask does **not** fix it (the microtask queue drains
  *between* listener callbacks, not after the dispatch). And the Style select is excluded
  from its own refresh: a `<select>` fires `input` **before** `change`, so refreshing on that
  `input` rewrote `styleSel.value` back to the old match and the `change` handler then applied
  the *wrong style*.
- **Export parity is not automatic.** `renderToBlob` / `beginFrameSession` build their own
  composers in a separate GL context, so the figure + GTAO passes need
  `_pushFigureParamsTo` / `_pushAOParamsTo` per export composer, and the cue range re-pushed
  per tile — same per-renderer rule as the HDRI bake.

### Known caveats

- **Zoomed far out, the outline swallows small features — Roberts mode only.** The contour is
  a pixel-space effect; when a bead is 2–3 px across, the crease term fires over the whole
  sphere and the strand renders as black line-art with no fill. At normal framing and at export
  resolution it is correct. The Thickness / Creases sliders are the mitigation. **The exp tab's
  ChimeraX mode is immune** — it reads no normals, so there is no crease term to fire; this was
  the specific reason for porting it.
- Path-traced mode bypasses the EffectComposer, so **outline + depth cue do not apply in PT**
  (same limitation as mist). The panel says so.
- GTAO + the figure pre-pass add two full-scene renders per frame; on software GL (headless)
  frames get slow enough that Playwright's element-screenshot stability wait times out — use
  `page.screenshot` there, not `locator.screenshot`.

Verified in-app on the isolated smoke stack (never the user's :8000 — see
[[feedback_no_live_server_mutation_for_verify]]): Publication applies through to every
control, each control toggles independently, the pass disables when both effects are off,
`renderToBlob` produces a real PNG with the outline, exit restores the lens, zero console
errors (i.e. no shader-compile failures). Screenshots confirmed the flat/outlined look.

## Exit on file close/open/new (in-session) — 2026-05-29

Photo mode is in-memory only, so a *page reload* is already safe (renderer
reconstructed with `_active=false`, see "Reload behaviour"). But an **in-session**
close → new/open left photo mode running: `_photoModeExit()` was only wired to the
Photo tab button (photo mode is entered/exited **only** via the left-sidebar Photo
tab — there is NO keyboard shortcut; the old `p` binding was removed and `P` is now
Physics), so nothing dropped it when the design/assembly was torn down. Symptom: in
photo mode → Close Session → New Part came up "in photo mode" (the render override
stayed installed).

Fix ([main.js](frontend/src/main.js)):
- `_photoModeExit()` is now **idempotent** — early-returns if `!photoRenderer.isActive()`,
  so it's safe to call from any teardown path.
- Called at the **top of `_resetForNewDesign()`** (the choke point for new/open/import/
  load/close of a part — runs first so `deactivate()` restores live materials while
  meshes still exist) and at the **top of `_enterAssemblyMode()`** (open/new assembly).
- Together these cover: Close Session, New/Open Part, New/Open Assembly, import
  cadnano/scadnano/PDB. **Not** wired to the SSE external-edit in-place reload of the
  *same* open file — that's not a context switch and the renderer adopts rebuilt
  meshes on the fly.

### No design ⇒ no open sidebar (Close Session) — 2026-08-02

**The bug was CSS specificity, and it is not photo-specific.**
[sidebar_resize.js:45](../frontend/src/ui/sidebar_resize.js#L45) persists a dragged
sidebar width as an **inline** `style.width`, which outranks
`#left-panel.hidden { width: 0 }` from the stylesheet. So for any user who had ever
resized the sidebar, `.hidden` stopped collapsing it — and Close Session fires
`nadoc:workspace-path-change` with a null path, whose handler RE-APPLIES the saved
global width, inline, onto the panel it just hid. Symptom: close the session and the
sidebar is still there, showing an empty pane. A fresh browser profile never
reproduces it (no saved width) — that is why the first repro of this looked clean.

Three parts, all in the "shut" direction:
1. `#left-panel.hidden { width: 0 !important; min-width: 0 }` — an author
   `!important` beats a non-important inline style. Load-bearing; don't drop it
   while `sidebar_resize` writes inline widths.
2. `_render()` derives `shut = collapsed || locked` and drives the tab highlight and
   the toggle arrow off it, not off `collapsed` alone — a lit tab and a "Hide
   sidebar" arrow over a shut panel were most of what read as "still open".
3. `_showWelcome()` calls `__leftSidebar.collapseForTeardown()` (via `window.`, NOT
   the closure const — `_showWelcome` runs at boot, thousands of lines before that
   `let` initialises → TDZ). It drops a RENDER_OVERRIDE tab (`_photoMode.exit()`,
   activeTab → feature-log) so the override is off and the pane can't flash back.
   It does **not** touch `collapsed` and persists nothing: that is the user's
   preference, replayed by `_setLeftPanelEnabled(true)` on the next design open.

Also: `_setLeftPanelEnabled(false)` now disables the Photo tab button with the rest.
Its exemption ("works on any scene, even empty") had been dead for a long time —
`setActiveTab`/`toggleCollapsed` both early-return while `locked-hidden` is set, so
the button was clickable and inert.

Verified with a saved global width, closing from Photo AND from Feature Log:
`{inlineWidth: '420px', width: 1, enabledTabs: []}` — inline width back, panel shut
anyway — and re-opening a design restores both the 420 px width and Feature Log.

## Exit on sidebar-tab switch + feature-log default on load — 2026-06-20

Two related sidebar behaviours:
- **Switching to any non-Photo left-sidebar tab now exits photo mode.** The tab
  strip's `setActiveTab(tabId)` (main.js sidebar controller) calls
  `_photoMode.exit({ skipTabRestore: true })` whenever `tabId !== 'photo'`.
  `_photoModeExit` ([photo_mode.js](frontend/src/scene/photo_mode.js)) gained a
  `{ skipTabRestore }` option so the exit doesn't yank the user back to
  feature-log — the strip switch lands them on the tab they clicked. (Entering
  via the Photo tab is unchanged; clicking Photo while active still just
  collapses.) Supersedes the old "exit is ONLY wired to the Photo tab button"
  claim in the in-session-exit note below.
- **A freshly loaded part defaults to the Feature Log tab.** `_hideWelcome()`
  (the universal funnel for every open/new/import path) calls a new
  `__leftSidebar.selectTab('feature-log')` — a non-toggling tab setter
  (preserves the user's collapsed/expanded pref; unlike `setActiveTab`, it never
  collapses when re-selecting the active tab) that overrides whatever tab was
  persisted in `localStorage`.

Verified in-app (temp Playwright spec, since deleted): persisted `plates` →
load part → active tab is `feature-log`; enter photo → switch Dynamics/Plates →
`__photoRenderer.isActive()` false + clicked tab active, no console errors.
