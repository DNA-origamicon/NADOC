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

**Why:** publication-grade rendering for figures and animations. Activate/deactivate must restore the live scene exactly (lights, materials, scene.environment, scene.background) — the live editor still has to work after exit. **How to apply:** never mutate scene state from photo-mode code outside the saved-state pattern (`_savedMaterials`, `_savedSceneEnv`, `_savedSceneBackground`, `_savedLightState`). Adding a new visual feature means adding a save slot and a restore step in `deactivate()`.

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
checkbox can't lie.

**Export card** — tiled PNG at any resolution. TILING IS NOT OPTIONAL: a render
target above `MAX_TEXTURE_SIZE` silently clamps and yields a black image, and 300
DPI (4200×2970) already exceeds the 4096 limit common on WSL/integrated GPUs.
The offscreen renderer is a SEPARATE GL CONTEXT, so it needs its own composer,
its own FigurePass params, its own cue range per tile, and its own
`shadowMap.enabled` — none of the live renderer's GPU state carries over. That is
the rule that keeps preview and export in sync. Export representation is NOT
wired (it needs the assembly rep-upgrade machinery + an `api` dep).

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
4. Editor overlay geometry (~100 µm) silently sets the frustum and puts the whole
   design inside one texel. `shadow_bounds.js` rejects contributors >8× the
   median extent and names them in a console warning.

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
