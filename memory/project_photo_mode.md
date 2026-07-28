---
name: photo-mode
description: "Photo-mode rendering pipeline — PBR + HDRI + SSS + emissive fluorophores + tiled high-res export. Architecture, gotchas, and known caveats from the 2026-05-14 session."
metadata: 
  node_type: memory
  type: project
  originSessionId: caf07b9d-c547-4a4a-b679-8f8f745bc1f2
---

Photo mode lives at [frontend/src/scene/photo_renderer.js](frontend/src/scene/photo_renderer.js) with sub-modules under `photo_renderer/` (material_presets, lighting_presets, post_processing) and the UI in [frontend/src/ui/photo_panel.js](frontend/src/ui/photo_panel.js) (left-panel tab, HTML in `index.html` under `#tab-content-photo`).

**Why:** publication-grade rendering for figures and animations. Activate/deactivate must restore the live scene exactly (lights, materials, scene.environment, scene.background) — the live editor still has to work after exit. **How to apply:** never mutate scene state from photo-mode code outside the saved-state pattern (`_savedMaterials`, `_savedSceneEnv`, `_savedSceneBackground`, `_savedLightState`). Adding a new visual feature means adding a save slot and a restore step in `deactivate()`.

## Exp. Photomode tab — camera-pinned key shadow (AO removed) — 2026-07-28

A SECOND, deliberately minimal photo tab (`data-tab="photo-exp"`) as a testbed for
render features before they earn a place in the Photo tab. Modules:
[photo_exp_mode.js](frontend/src/scene/photo_exp_mode.js) (renderer + tab orchestration),
[ui/photo_exp_panel.js](frontend/src/ui/photo_exp_panel.js),
[photo_renderer/shadow_bounds.js](frontend/src/scene/photo_renderer/shadow_bounds.js).
`main.js` gains only an import + factory init + a `TABS` entry.

**What it does:** flat figure materials, a CAMERA-PINNED light rig (ChimeraX
`move_lights_with_camera` — the rig's quaternion tracks the camera, so the shadow
sweeps as you reorient), and a real key-light shadow map **not gated on a floor**
(the shipping mode gates its rig behind `floor !== 'off'`, which makes
helix-on-helix shadow impossible there).

**`full` preset is tuned AWAY from ChimeraX's numbers on purpose.** ChimeraX
`lighting full` is key 0.7 / fill 0.3 / ambient 0.8, but a cast shadow only
subtracts the KEY light, so fill+ambient are a floor: the deepest possible shadow
removes just 39% of the light and reads as a grey smudge. `full` here is one key
at 2.0, no fill, ambient 0.15 → ~93%. That is what made it legible.

**THE parameter is shadow-map resolution, in nm/texel.** ChimeraX's map-size
defaults are sized for a ~5 nm protein. On a 150 nm origami a 1024 map at 64
directions gives 2.34 nm/texel — wider than a 2.0 nm duplex, so a thin arm cannot
cast a readable shadow at all. The panel prints live nm/texel vs a duplex and
warns when it is too coarse. Key shadow map size is selectable 1024–8192.

**Multishadow ambient occlusion: built, evaluated, REMOVED (same day).** A faithful
64-direction port of ChimeraX's ambient shadows (tiled depth atlas, cosine-weighted
accumulation, cached view-independent transforms, material-side consumption on the
indirect term). Cut because of the resolution arithmetic above — it never produced
long-range shadowing at origami scale, only a wash. Findings kept in
`photo_mode_ao_and_lowpoly_spec.md`; do not re-attempt without solving nm/texel first.

**Three bugs found here that no headless test could reach** — all cost real time:
1. `renderer.shadowMap.enabled` is a PROGRAM parameter (`WebGLPrograms.js`) and
   `setProgram` never re-checks it. Any internal scene render that flips it off
   compiles every material without `USE_SHADOWMAP`, permanently. Use
   `shadowMap.autoUpdate = false` to skip shadow rendering instead.
2. Shadow bias must scale with the shadow-map TEXEL, not the scene radius. A
   radius-proportional bias reaches 2–8 bead diameters on a real design and
   ERASES the shadow rather than de-acneing it.
3. Editor overlay geometry (~100 µm) silently sets the frustum and puts the whole
   design inside one texel. `shadow_bounds.js` rejects contributors >8× the median
   extent and names them in a console warning; they are also barred from casting.

`window.__photoExpMode.getDiagnostics()` reports the whole chain (renderer flag,
light pose, map rendered, fitted frustum, bounds contributors, cast/receive counts).

## Render-speed: idle gate + interactive preview + backend frame cache — 2026-07-14

Testing "oxDNA display → Photo → switch to surface/atomistic" was painfully slow. Two
independent causes, both now mitigated (the cheap tier of a larger plan; impostors for
atomistic and a topology-once/coords-per-frame backend rebuild remain as the big
structural wins if needed):

**Frontend — the photo render loop re-rasterised the whole (heavy) scene 4-6× every
animation frame** (SSAO+GTAO+outline+inscatter+bloom), unconditionally, even parked.
[photo_renderer.js](frontend/src/scene/photo_renderer.js) `_installComposerRenderFn` now:
- **idle gate** — a `_dirty` flag + camera-matrix compare skips the composite when nothing
  changed (last frame persists on the canvas). A `_IDLE_KEEPALIVE_FRAMES` (20 ≈ 3 Hz)
  keepalive still redraws so an *untracked* scene change (a live-sim frame applied while
  the camera is parked) appears within ~0.3 s. Public `invalidate()` forces an immediate
  redraw for callers that mutate the scene silently.
- **interactive preview** — while the camera moves, draw ONE plain `renderer.render` (no
  post chain), snapping back to the full composite `_PREVIEW_SETTLE_FRAMES` (3) still
  frames after motion stops. Keeps orbiting responsive on atomistic/surface geometry.
  **NOW GATED by the `orbitFullQuality` setting (2026-07-15, default ON).** With it ON,
  camera motion only marks the frame dirty — the FULL composite (GTAO/outline/bloom/mist)
  renders every orbit frame, so ambient-occlusion shadows stay live instead of popping in
  ~3 frames after motion stops (user saw the AO "second set of shadows" redraw on settle —
  that was this preview dropping the post chain). OFF → the old cheap preview (for very heavy
  structures that stutter). Setting + `setOrbitFullQuality` in photo_renderer.js (render loop
  reads it live in `_installComposerRenderFn`); checkbox `#photo-orbit-fullquality` in the
  Figure section, wired in `photo_figure_panel.js`; persisted via getSettings. Throttle tests
  updated + extended (`photo_renderer.test.js` P-T tier).
- Every public `set*` is auto-wrapped to call `_invalidate()` after it runs (loop over the
  api object), so a setting change always redraws even while idle — no per-setter
  annotation, no future setter silently missing the redraw. The old scattered
  `if (_ptEnabled) { _ptRenderer?.reset(); _ptSamples = 0 }` became `_invalidate()`.
- Path-tracing path is unchanged (it has its own progressive render fn; the gate is
  raster-only). Tests: `photo_renderer.test.js` "P-T — render throttle" (4 cases).

**Deeper backend rebuild ("topology once, stream coords") — INVESTIGATED AND REJECTED
(2026-07-14).** Profiling the slow designs (U6hb: 240 xovers + 72 skips) showed the all-atom
STAMP is <1 s of a ~9 s build; **86% is the L-BFGS-B backbone-bridge minimiser**
(`atomistic_minimisers._minimize_backbone_bridge`, one solve per crossover + per skip). That
solver is frame-dependent (no cross-frame cache) and ULP-chaotic — a batched-matmul stamp
that changed floats only at ~1e-16 moved backbone geometry up to **0.8 Å** at junctions by
tipping the near-degenerate minima. Reverted; kept the byte-identical per-atom stamp. The
right backend lever is the per-frame OUTPUT cache below (each frame builds once); the win for
huge designs is frontend impostors. Locked by `tests/test_atomistic_geometry_lock.py`. See
LESSONS **H15**.

**Backend — each atomistic/surface frame was a full all-atom rebuild (~23 atoms/nt, pure
Python), regenerated even for a frame you'd already visited.** Alignment was cached; the
*output* was not. Added a per-frame output LRU in
[oxdna_health.py](backend/core/oxdna_health.py) (`_display_out_get/_put`,
`display_out_cache_clear`, element-count bounded, 6M-elem budget): keys `("cta", aligned_key,
idx)` / `("cts", …, sparams)` in `composite_trajectory_atomistic/_surface`, and
`("dispA"/"dispS", conf_sig, align[, sparams])` at the relaxed-display routes
([routes_oxdna.py](backend/api/routes_oxdna.py)). Re-scrubbing a frame or flipping the rep
atomistic→surface→atomistic on the same frame is now free. `Atom` is now
`@dataclass(slots=True)` (atomistic.py) — cheaper per-atom alloc during the rebuild.

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

- **Zoomed far out, the outline swallows small features.** The contour is a pixel-space
  effect; when a bead is 2–3 px across, the crease term fires over the whole sphere and the
  strand renders as black line-art with no fill. At normal framing and at export resolution
  it is correct. The Thickness / Creases sliders are the mitigation.
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

## Export-only high-detail GEOMETRY swap — 2026-05-22

Distinct from the rep upgrade below (which changes *which* representation is built):
this upgrades the sphere/cylinder **tessellation** for export only.  The interactive
atom/bead/bond geometry is deliberately low-poly — atoms `SphereGeometry(1,10,8)`
([geometry_builder.js:28](frontend/src/scene/atomistic_renderer/geometry_builder.js#L28)),
bonds `CylinderGeometry(1,1,1,6,1)`, CG beads `SphereGeometry(BEAD_RADIUS,10,8)`
([helix_renderer.js:67](frontend/src/scene/helix_renderer.js#L67)) — so atomistic/full
figures came out visibly faceted ("non-full-sphere"; user-reported 2026-05-22).
Photo mode previously only swapped *materials*, never the tessellation.

`_withHighDetailGeometry(fn)` in [main.js](frontend/src/scene/../main.js) (composed into
`_withExportRepresentation`, so BOTH PNG + video export get it on every export path):
traverses the scene, swaps each matching InstancedMesh's `geometry` for a cached
high-segment version (`32×24` spheres / `24`-radial cylinders, built once in
`_highDetailGeometries`), runs the export, and restores in `finally`.  Match rules:
atoms/bonds by **shared-geometry reference** (`geometry === SPHERE_GEO` / `=== CYLINDER_GEO`,
imported into main.js as `ATOM_SPHERE_GEO`/`BOND_CYL_GEO`); beads/fluorophores by mesh
**name** (`backboneSpheres`/`extensionFluorophores`) AND `geometry.type === 'SphereGeometry'`
(so the opt-in impostor quads are skipped).  Swapping `mesh.geometry` leaves
instanceMatrix/instanceColor intact, so positions+colors hold.  Bead/fluoro HD radii must
match the source (BEAD_RADIUS / 0.25) since those instances translate (don't scale); atoms/
bonds are unit-sized and scaled per-instance.  Interactive view keeps the fast low-poly meshes.

Verified (temp e2e, deleted): real export button → swap upgrades atom 99→825 / bond 40→148 /
bead 99→825 verts DURING export, restores after, no errors.  Export PNG renders the live scene
through an offscreen RASTER pass (no path-tracer during export → no BVH rebuild needed).
**Caveats:** (a) headless = software-GL, so the actual smooth *look* is the user's manual check;
(b) detail level (`_highDetailGeometries`, 32×24) is the single tunable spot — very large
atomistic structures (100k+ atoms) may export slowly at this tessellation, dial down if needed;
(c) does NOT cover the impostor→real-sphere case (impostors flag on) — that's still the TODO
"Photo-mode revert path" in [[sphere-impostors]].  Cones (5′ markers) + slabs (base pairs) left
low-poly (not user-flagged).

## Final render representation (export-only LOD upgrade) — 2026-05-22

Lets the user edit/preview a large assembly at a fast LOD (e.g. cylinders) but export the
PNG/video at high detail. A **per-assembly** `Assembly.export_representation`
(`backend/core/models.py`, Literal incl. `'working'`, default `'full'`; serialized for free via
`model_dump`→`to_dict_v2`, round-trips in `.nass`) is set by `POST /assembly/export-representation`
(`backend/api/assembly.py`, validated against `_VALID_EXPORT_REPRESENTATIONS = ('working',)+_VALID_REPRESENTATIONS`,
`set_assembly_silent` — no undo entry). Client: `api.setAssemblyExportRepresentation(rep)`
(`client.js`); the field rides through `_expandV2Assembly`'s `...rest` into `store.currentAssembly`.

UI: an **"Export detail" dropdown next to the Export PNG button** (`index.html` `#photo-export-rep`:
Working / Full / Beads / Cylinders / VDW / Ball&Stick / Surface — any value in backend
`_VALID_EXPORT_REPRESENTATIONS` = `('working',)+_VALID_REPRESENTATIONS`, so adding an option is
just an `<option>`; the panel + `_withExportRepresentation` are rep-agnostic. Surface added
2026-05-22 — its async per-instance surface-geometry build is awaited by the rebuild chain
(`_buildSource` awaits `_buildSurfaceBatch` before `_fireRebuildComplete`, which
`_applyRepAndAwaitRebuild` waits on), so the export won't render before surfaces finish; slow
but export-only). `photo_panel.js` syncs it from `store.currentAssembly.export_representation`
in `syncToState`, persists on `change` via `setExportRepresentation` (NOT a photo-profile setting).

Mechanism (`main.js`, export-only, preview untouched): `_withExportRepresentation(fn)` wraps both
export handlers (PNG `renderToBlob`, video `exportPhotoVideo`). It snapshots every instance's rep →
`_applyRepAndAwaitRebuild(all→exportRep)` (batch-patch + await via a one-shot `onRebuildComplete`,
120 s timeout) → **`photoRenderer.resyncMaterials()`** → runs `fn` → in `finally` restores the
snapshot + `resyncMaterials()`. No-op when not assembly mode / no instances / `'working'` / already
matching. **`resyncMaterials()`** (new public method) re-runs `_swapMaterials()` on the freshly-
rebuilt meshes (the rebuild creates NEW meshes with default materials; `_swapMaterials` re-keys by
name + re-applies `_reapplyShared` instancing patch) and re-spawns fluorophore lights — required
because a mid-photo-mode rebuild replaces every assembly mesh.

Persistence safety: `_exportRepActive` flag blocks the two manual assembly-save handlers (toast) and
skips the session-close autosave, so the temporary upgrade never hits disk; restore-in-`finally` +
the load-time auto-downgrade (`_AUTO_DOWNGRADE_FULL_REP_THRESHOLD=6`) are the net. Verified by
`frontend/e2e/export_representation.spec.js` (preview stays cylinders; `.nass` round-trip; PNG export
upgrades to full mid-render then restores; blob produced) + backend tests
`test_export_representation_default_and_roundtrip` / `test_set_export_representation_route`.
Headless = software-GL, so the high-detail *look* of the export is the user's manual check.
See [[path_to_thousands]].

## Profiles (persisted across reloads)

Top of the photo tab has a Profile dropdown + New / Rename / Delete buttons. Storage lives in `localStorage`:
- `nadoc.photoProfiles.v1` — `{ name: settings, ... }` (settings is whatever `photoRenderer.getSettings()` returns)
- `nadoc.photoActiveProfile.v1` — name of the currently-selected profile

**Auto-save:** event delegation on `#tab-content-photo` listens for `input` + `change` events (capture phase) and debounces a 250 ms save of the active profile. Programmatic `.value` writes from `syncToState` / `_applyProfile` do NOT fire input/change events, so loading a profile doesn't recursively save itself.

**`_applyProfile(s)`** pushes each setting through the renderer's individual setters then calls `syncToState()` to refresh the UI. Two settings are quirky:
- `environment === 'file'` → downgraded to `'off'` on apply (HDR file blob can't be persisted in localStorage; user re-uploads if needed).
- Path tracing toggle is preserved in profile but PT is also rebuilt from active scene meshes, so re-entering with PT-on may take a moment.

**Lifecycle:** `initPhotoPanel` populates the dropdown and ensures a `Default` profile exists (snapshotted from `photoRenderer.getSettings()` on first run). The actual application happens in `applyActiveProfile()` which `main.js _photoModeEnter` calls *after* `photoRenderer.activate({})` — applying before activate would print "queued — activate photo mode first" toasts from `setMaterialPreset`.

## Reload behaviour

Photo mode active state is in-memory only (the `photoRenderer` is freshly constructed each load with `_active=false`), so a reload while photo mode is open never auto-re-enters photo mode. To prevent the left sidebar from leaving the user parked on an empty Photo tab after reload, [main.js](frontend/src/main.js) now treats a persisted `activeTab === 'photo'` as falling back to `'feature-log'` (other tabs preserve their saved state). The sidebar's `collapsed` preference is preserved independently.

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

## Core architecture

- `createPhotoRenderer(sceneCtx)` returns a controller; activate/deactivate swap state. The render override goes through `sceneCtx.setRenderFn` / `resetRenderFn` — photo mode does **not** own the rAF loop.
- Material swap detects representation by mesh name (`MESH_NAME_TO_REPR`) with fallback inference (`_inferRepr`: `DoubleSide`→surface, `MeshStandardMaterial`→atomistic). Meshes created *after* activate are adopted on the fly by `setMaterialPreset` (see "post-activate adoption" in the function).
- EffectComposer pipeline: RenderPass → SSAO → SMAA → optional Bloom → OutputPass. SSAO is tuned for nm-scale DNA (`kernelRadius=0.3`).

## Default environment = 'room' (so metals look metallic) — 2026-05-22

The photo-mode default environment is **'room'** (synthetic RoomEnvironment), NOT 'off'
([photo_renderer.js](frontend/src/scene/photo_renderer.js) `_settings.environment` +
`_envSourceType`).  **Why:** a `metalness=1.0` PBR surface is pure specular — with no
environment to reflect it renders dark/flat, so "CPK Metallic" (and the glossy presets)
looked broken (user-reported 2026-05-22; the material swap itself was fine — the missing
env was the cause).  'room' gives reflections WITHOUT changing the background (background
still follows `bgType`; only matters if `environmentBackground` is on).  Users can still
pick Off / File.  **Migration:** existing saved profiles pinned to the old 'off' default
would override the new default, so `_migrateEnvDefaultToRoom()` in
[photo_panel.js](frontend/src/ui/photo_panel.js) bumps any profile's `environment: 'off'`
→ 'room' exactly once (gated by `localStorage['nadoc.photoEnvRoomDefault.v1']`), before
any deliberate later 'off' choice — so a purposeful Off sticks.  Verified: seeding an 'off'
Default profile → enter photo mode → profile migrated to 'room', `getSettings().environment
=== 'room'`, `scene.environment` is a baked PMREM texture.  Visual metallic look is the
user's manual check (headless = software-GL).

**Related latent bug found (NOT fixed — atomistic still works):** `_inferRepr`
([photo_renderer.js:57](frontend/src/scene/photo_renderer.js#L57)) returns 'atomistic' for
any `MeshStandardMaterial`.  `MeshPhysicalMaterial` *extends* `MeshStandardMaterial`, so
AFTER activate swaps every material to MeshPhysicalMaterial, all UNNAMED meshes infer as
'atomistic' (probe on a 2-part ballstick assembly: `setMaterialPreset(atomistic)` updated
**203** meshes, `full`/`cylinders` only their ~5/3 NAMED meshes).  Atomistic atoms/bonds are
unnamed MeshStandardMaterial → correctly included, so the atomistic dropdown works; but the
full/cylinders dropdowns under-apply to unnamed CG meshes.  Fix would be a positive
atomistic tag (set `userData.repr='atomistic'` on atom/bond meshes in atomistic_renderer)
instead of the `instanceof` sniff.

## HDRI environment

`setEnvironment(mode, fileBlob?)`:
- `'off'` — direct lights only.
- `'room'` — Three.js synthetic `RoomEnvironment` (no asset shipped).
- `'file'` — user-uploaded equirectangular `.hdr` via `RGBELoader`.

PMREM-baked texture stored in `_envTexture`; source data (DataTexture for file mode, or just the type tag for `room`) kept in `_envSourceHDR` + `_envSourceType` so the env can be **re-baked per renderer**. This matters for high-res export: the offscreen renderer has a different GL context and can't see the main renderer's PMREM texture — `renderToBlob()` re-bakes via `_bakeEnvFor(offRenderer)`, swaps `scene.environment` for the duration of the export, then disposes the offscreen-context texture and restores the main-context one.

**Why:** sharing PMREM textures across GL contexts gives a black env. **How to apply:** any new feature that builds GPU resources (textures, render targets) needs the same per-renderer re-bake pattern in `renderToBlob`, or export will look different from preview.

`setEnvironmentBackground(enabled)` priority: HDRI background overrides the regular bg color radio when enabled. Modifying `_applyBackground` checks `_settings.environmentBackground && _envTexture` first.

## Subsurface scattering / translucency

Two layers:
1. **Surface preset upgrades** in `material_presets.js`: `gummy`, `wax`, `skin` use `transmission` + `thickness` + `attenuationColor` + `attenuationDistance` (KHR_materials_volume). Real volume absorption, so back-side picks up tinted shift.
2. **Global Translucency slider** (`setTranslucency(amount)`) — applies transmission override to Full + Cylinders reps only. Surface is left alone (it has its own preset for that). Routed through `_applyTranslucencyOverride(mat, repr)` which is called both at swap time (in `_swapMaterials`) and at preset-change time (in `setMaterialPreset`) so the override survives material changes.

Path tracer respects all of these; raster gives the planar refraction approximation that `MeshPhysicalMaterial.transmission` does.

## Fluorophores as light sources

`setFluorophoreEmissive(enabled, intensity)` does **two** things:
1. Swaps the fluorophore mesh material to `makeFluorophoreEmissive(...)` — `MeshPhysicalMaterial` with strong `emissiveIntensity`. Raster shader patch via `onBeforeCompile` makes `totalEmissiveRadiance = vColor * emissive.r` so each fluorophore's emission is its **instance color** (per-fluorophore emission color is correct in raster).
2. Spawns one `THREE.PointLight` per fluorophore at its world position, color from `instanceColor`. Lives in `_fluoroLightGroup` which is NOT a child of `_photoGroup` — so lighting yaw/pitch rotation does not move fluorophore lights (they stay on the structure).

**Per-frame sync:** the render override calls `_syncFluoroLights()` which reads `instanceMatrix` → world position → updates each `PointLight.position`. Handles cluster moves, animation playback, etc. Triggers a respawn if instance count changed.

**Gain constant:** `_FLUORO_LIGHT_GAIN = 12.0` — multiplier between slider intensity and `PointLight.intensity`. With `decay=2` (physical inverse-square), at intensity slider = 5, lights are I=60 — visible reflections in chrome at ~5 units. Slider range bumped to 0-100 per user request.

**Path-tracer limitation:** `three-gpu-pathtracer` reads `material.emissive * emissiveIntensity` per-mesh, **not** per-instance — so in PT mode all fluorophores emit uniform white at the chosen intensity, not their individual emission colors. Raster preview shows true per-fluorophore color via the shader patch. To get per-instance colored emission in PT, would need to split the InstancedMesh into N separate emitters with baked materials. Not currently implemented.

## Environmental effects (mist — volumetric inscatter)

Dropdown "Environmental Effects" in the photo tab. `setEnvironmentalEffect('none' | 'mist')` enables/disables a volumetric inscatter post-process pass.

**Why this approach (history):** initial v1 used `scene.fog = FogExp2` + additive halo sprites. `FogExp2` is a screen-space distance fade designed for landscapes — at any density above ~0.005 over an nm-scale structure it bleached the entire scene to fog colour because the geometry sat well past the fog half-distance. Replaced 2026-05-15 with proper volumetric inscatter (Cycles/Unreal style) — geometry is unaffected; only the air around lights brightens.

### Pipeline

`createComposer` uses Three.js's **default** EffectComposer setup — no custom render target. Composer order: RenderPass → **VolumetricInscatterPass** (toggled) → SSAO → SMAA → [Bloom] → Output. Inscatter is placed before Bloom so scattered halos can bloom — gives the "glowing fog" look. The pass starts `enabled=false`; orchestrator flips it via `_applyEnvEffect`.

**Depth handling:** the inscatter pass owns its own depth-only render target and runs its own depth pre-pass each frame (scene rendered through `MeshDepthMaterial` override). Same pattern as Three.js's `SSAOPass`. This is load-bearing — see the gotcha below.

**Depth-on-main-composer-target gotcha (do NOT revert):** an early attempt attached a `DepthTexture` to the composer's main render target so all passes could share scene depth. Two failure modes hit:
1. With `DepthFormat` + `UnsignedIntType` the surface `MeshPhysicalMaterial` fragment shader failed to compile when transmission was active (`THREE.WebGLProgram: Shader Error 1282 — VALIDATE_STATUS false … Material Type: MeshPhysicalMaterial … Fragment shader is not compiled`).
2. Switching to `DepthStencilFormat` + `UnsignedInt248Type` (the SSAOPass-compatible combination) silenced the compile error, but the inscatter pass still produced a black buffer when enabled — the swap-buffer color reads through the custom HDR target weren't surviving. Reverted both attempts.

The fix is the SSAOPass-style separate depth pre-pass: cost is one extra full-scene render per mist-on frame (cheap; same as SSAO already pays). The composer's main render target stays untouched.

### The pass

[frontend/src/scene/photo_renderer/volumetric_inscatter_pass.js](frontend/src/scene/photo_renderer/volumetric_inscatter_pass.js). Per-frame `render()`:
1. **Depth pre-pass:** override `scene.overrideMaterial = MeshDepthMaterial`, render into the pass-owned `_depthRT` (color + DepthStencilFormat depth texture), restore.
2. **Inscatter shader:** sample `tDiffuse = readBuffer.texture` (scene from RenderPass) + `tDepth = _depthRT.depthTexture`. For each pixel: reconstruct world position from `(uv, depth)` via `invProj × invView`, march from camera to that point in `STEPS=24` jittered steps (jitter via `hash12(vUv)` reduces banding), at each step sum `ambient + Σ(pointColor / max(r², minR2))`, then `inscatter *= stepSize × density × scatter × fogColor` and **add** to scene colour (no transmittance, so geometry isn't bleached). Where there's no geometry (`depth ≈ 1`), march to a fixed `uMaxDist` (default 200 nm) so halos render against empty space.

`MAX_LIGHTS = 64` — larger fluoro counts truncate with a console warning. Uniform arrays are pre-allocated; `setLights({points, ambient})` updates them in place.

### Debug helper

`window.__photoRenderer.setMistDebug(mode)` swaps the inscatter shader's output:
- `0` — passthrough (just the diffuse, looks identical to mist-off)
- `1` — solid magenta (proves the pass is rendering)
- `2` — depth as greyscale (proves the depth pre-pass is producing depth)
- `3` — ambient inscatter only (no point-light contribution)
- anything else (e.g. `99`) — full inscatter math (default)

Use when mist looks wrong: passthrough should always show the scene; if it's still black, the problem is in the composer plumbing, not the inscatter math.

### Light gathering (orchestrator)

`_gatherLightsForInscatter()` walks `_photoGroup` (rig — Ambient + Hemisphere accumulate as ambient term; Directional adds at half weight as anisotropy approximation) and `_fluoroLights` (PointLights — pushed as `{position, colorScaled = color × intensity}` since the shader expects pre-multiplied colour). Stored in module-level scratch arrays, then `_pushLightsTo(pass)` writes to uniforms. Called every frame from the render override only when mist is active.

### Per-frame cost

Per pixel: 24 marches × (1 ambient + ≤N fluoros × 1/r²). Cheap unless `MAX_LIGHTS` is approached. No BVH, no shadows, no scattering anisotropy.

### Export path (`renderToBlob`)

Each tile creates its own composer (because offscreen renderer has its own GL context) → its own inscatter pass instance → must be re-enabled and re-uniform'd per tile. Done inside the tile loop via `_pushInscatterParamsTo(exportComposer.inscatterPass)` + `_pushLightsTo(...)`. Same per-renderer-rebake pattern as HDRI environment.

### Settings ↔ uniforms

| Setting               | UI                      | Uniform     |
|-----------------------|-------------------------|-------------|
| `envEffect`           | dropdown                | `pass.enabled` |
| `mistDensity`         | slider 0.005..0.30      | `uDensity` (scattering coeff per nm) |
| `mistColor`           | color picker (#cad3e0)  | `uFogColor` (multiplicative tint on inscatter) |
| `mistHaloIntensity`   | slider 0..3 ("Scatter") | `uScatter` (overall multiplier) |
| `mistNoiseContrast`   | slider 0..2 ("Wispiness") | `uNoiseContrast` (0 = uniform; gates the noise branch in shader) |
| `mistNoiseScale`      | slider 0.005..0.30 ("Wisp size") | `uNoiseScale` (frequency in 1/nm) |
| `mistNoiseSpeed`      | slider 0..1 ("Drift")   | `uNoiseSpeed` (drifts noise along z) |

### Non-uniform mist (3D noise)

Per-step density is modulated by `densityMod = max(0, 1 + (fbm2(p × scale + z·t·speed) − 0.5) × 2 × contrast)`. `fbm2` is a 2-octave value-noise FBM built from a compact 3D hash (Hugo Elias / Hoskins variant) — no textures needed. Sampled in **world space** so noise is anchored to the scene, not the camera. When `contrast == 0` the noise branch is skipped (zero cost) — feature is opt-in. Time uniform is updated each render via `performance.now()`.

### Limitations

- **PT mode ignores inscatter** — three-gpu-pathtracer has its own render path that bypasses the EffectComposer. UI advisory says so.
- **Fog colour is multiplied** with inscatter, so heavily chromatic mist colours (saturated red/blue) will partly suppress complementary-coloured fluorophores. Default is desaturated cool grey; users can shift slightly.
- **Directional lights are approximated** as a constant-per-step ambient term at half weight — no anisotropic scattering / no Henyey-Greenstein phase function. For a more faithful look on dramatic rigs, would need to evaluate `cos(rayDir, lightDir)` per step and weight by HG.

## High-res export (tiled)

`renderToBlob(width, height)` probes `renderer.capabilities.maxTextureSize`, caps tiles at `min(maxTex, 4096)` for headroom. Splits image into a `tilesX × tilesY` grid via `camera.setViewOffset(W, H, x, y, w, h)` — modifies the projection matrix so a small viewport renders a sub-rectangle of the full image. Stitches via `CanvasRenderingContext2D.drawImage` (no GL limit on CPU canvas).

300 DPI = 4200×2970 → typically 2×1 tiles. 600 DPI = 8400×5940 → 3×2 or similar.

**Why tiled:** without tiling, 300/600 DPI exports produced empty images. WebGL render targets exceeding `MAX_TEXTURE_SIZE` (often 4096 on WSL/integrated GPUs) silently clamp and produce black output. **How to apply:** any future "render at custom resolution" feature has to go through `setViewOffset` tiling, not a single oversized render target.

**Bloom caveat:** bloom samples blur across tile boundaries → faint seams visible at tile joins when bloom + huge resolution + Bloom strength is high. SSAO + SMAA stitch cleanly. If seams become a problem, fix is overlap-tiles-and-crop-inner.

## Lighting

`applyLighting(presetName, _photoGroup)` rebuilds the rig in `_photoGroup`. Group's `rotation` set by `setLightingDirection(yawDeg, pitchDeg)` (Euler YXZ) — rotates the whole rig as one rigid body. Stays preserved across preset changes since `applyLighting` doesn't touch group transform.

## Path tracing (three-gpu-pathtracer)

Lives behind the Quality toggle. Builds a `DynamicPathTracingSceneGenerator` BVH from visible meshes. Live sample counter via `onSamplesUpdate` callback. Most setting changes (`setLighting`, `setMaterialPreset`, `setLightingDirection`, fluoro intensity, env, translucency) call `_ptRenderer?.reset()` to restart sampling — but **do not rebuild the BVH**. New PointLights added after PT start won't be visible until PT is toggled off-and-on. Documented limitation.

## Debugging entry points

Console-exposed objects (in `photo_panel.js`):
- `window.__photoRenderer` — the renderer controller
- `window.__photoPanelEls` — `{ matFull, matSurface, matCylinders, matAtomistic }` DOM refs

`setMaterialPreset` logs a `[photo] setMaterialPreset(repr, preset)` groupCollapsed with: updated mesh count, post-activate-adopted count, otherRepr count, ignored count, preset params, mesh names. Diagnostic toast also fires.

## Files touched (this session)

- [frontend/src/scene/photo_renderer.js](frontend/src/scene/photo_renderer.js)
- [frontend/src/scene/photo_renderer/material_presets.js](frontend/src/scene/photo_renderer/material_presets.js)
- [frontend/src/scene/photo_renderer/lighting_presets.js](frontend/src/scene/photo_renderer/lighting_presets.js)
- [frontend/src/scene/photo_renderer/post_processing.js](frontend/src/scene/photo_renderer/post_processing.js)
- [frontend/src/ui/photo_panel.js](frontend/src/ui/photo_panel.js)
- [frontend/index.html](frontend/index.html) — `#tab-content-photo` section (~line 3500+)

## Follow-up fix 2026-05-27 — surface culling + non-opaque-at-opacity-1

User report: in photo mode the surface rep "lost some surfaces" and the visible
ones stayed translucent even at opacity=1.

Root causes (both in `frontend/src/scene/photo_renderer/material_presets.js::makeMaterial`):
1. New `MeshPhysicalMaterial` defaulted to `side: FrontSide`; the surface mesh's
   non-manifold junction edges + occasional inward-winding triangles disappear
   under single-sided culling. Normal-mode `MeshPhongMaterial` uses `DoubleSide`
   for exactly this reason.
2. The `gummy` (default) / wax / skin / glass surface presets hard-code
   `transmission > 0`, which makes `MeshPhysicalMaterial` look glassy regardless
   of `opacity`. The opacity slider only flipped `transparent` + set `opacity`.

Fix (minimal):
- `makeMaterial`: force `side: DoubleSide` for `repr === 'surface'`. Stash
  `params.transmission ?? 0` into `mat.userData.presetTransmission`. When
  `opacity >= 1.0` zero `transmission` + `transparent` so the slider is
  authoritative. (For non-surface reps no preset has transmission, so this is a
  no-op for them.)
- `surface_renderer.js::setOpacity`: on a `MeshPhysicalMaterial`, drive
  `transmission` alongside `opacity` — `0` at `val>=1`, restore
  `userData.presetTransmission` at `val<1`. Lets the slider sweep through 1.0
  in photo mode correctly.

**Semantic change**: previously, gummy/wax/skin/glass at slider=1.0 still had
their SSS look. Now opacity=1.0 is authoritative opaque for all surface presets.
To get the SSS look, slide opacity below 1.0 (e.g. 0.95). Matches normal-mode
contract where opacity=1 ⇔ fully opaque. **NOT VERIFIED IN APP** (visual fix;
needs a hard-refresh and a re-enter of photo mode).

## Base slabs leaked normal-mode 0.90 opacity into photo mode — 2026-05-31

User report: in the full bead-and-slab rep, photo-mode slabs were permanently
slightly transparent and ignored the Translucency slider, while beads behaved
correctly.

Root cause: base slabs are built in normal mode with
`MeshPhongMaterial({ transparent: true, opacity: 0.90 })`
([helix_renderer.js:911](frontend/src/scene/helix_renderer.js#L911)) so beads
read through them. `_swapMaterials` (and both `setMaterialPreset` branches) read
`op = obj.material.opacity` from the source mesh and pass it to `makeMaterial`,
so the slab's 0.90 leaked in → photo slab material came out `transparent`,
`opacity 0.90`. The Translucency slider's `_applyTranslucencyOverride` only
drives `transmission` (never resets `opacity`), and at t≤0 it sets
`transparent = opacity < 1` → slabs stayed semi-transparent and the slider
couldn't push them opaque. Beads arrived at `op=1.0` so they were fine.

Fix (centralized in [material_presets.js](frontend/src/scene/photo_renderer/material_presets.js)
`makeMaterial`): only the `surface` rep honors the incoming opacity (it has its
own opacity slider); `full`/`cylinders`/`atomistic` are forced opaque
(`effectiveOpacity = repr === 'surface' ? opacity : 1.0`). The Translucency
slider is the sole transparency control for full/cylinders, so each slab now
matches its corresponding bead and the slider is authoritative. Covers all four
call sites (`_swapMaterials`, both `setMaterialPreset` branches, the
fluorophore-revert path) for free. Same principle as the 2026-05-27 surface fix
below (opacity=1 ⇔ fully opaque). All 6 box faces share one
MeshPhysicalMaterial, so "all sides match the bead" holds by construction.
**NOT VERIFIED IN APP** (photo-mode transmission look isn't faithful headless).

## Floor (resting surface) — 2026-05-27

New photo-tab section "Floor (resting surface)" — a configurable ground plane
that sits at any of the six bbox-aligned sides (±X, ±Y, ±Z) for CAD-style
"part on a surface" framing. Module: [frontend/src/scene/photo_renderer/floor.js](frontend/src/scene/photo_renderer/floor.js).
Auto-positions at the scene bounding-box face (computed by walking
Mesh/InstancedMesh, excluding the photo helper groups + additive sprites +
line materials); user adjusts via Offset (nm).

**Effectively-infinite plane + grid density (2026-05-30):** the old per-floor
"Size" slider was removed. The plane is now `planeSize = max(INFINITE_FACTOR=80
× bbox-diameter, ABSOLUTE_MIN_REACH=4000 nm)` (floor.js) — sized to reach the
**camera far-clip horizon**. KEY GOTCHA: part-mode camera far clip is hard-pinned
to **2000 nm every frame** by the frame callback in [main.js](frontend/src/main.js#L483)
(`if (!assemblyActive) camera.far = 2000`), so the floor can never extend past
2000 nm from the camera regardless of plane size — the far clip crops it into a
distant horizon (which reads as infinite). That clip is why the old `2×diameter`
plane looked "near." The freed control is a **Grid density** slider
(`floorGridDensity`, cells per bbox diameter, default 10, range 2–40) inside the
grid-style sub-row (only visible when Grid overlay is on). Cell size =
diameter/density; subdivisions = `planeSize/cellSize` capped at
`MAX_GRID_DIVISIONS = 4000` (whole slider stays exact for tens-of-nm structures).
`floorSize` + `setFloorSize` kept as deprecated no-ops for old profiles. **The
floor module is constructed once** in `createPhotoRenderer`, so floor.js edits
need a FULL PAGE RELOAD (HMR won't update the captured closure).

**Far-clip must reach the floor (the actual "still looks small" fix):** a big
plane alone is not enough — the per-frame camera near/far callback in
[main.js](frontend/src/main.js#L481) crops it. Part mode pins far=2000; **assembly
mode brackets far tightly around the assembly bounding sphere**, so the floor was
cropped right at the content edge (this is why it "persisted" for assemblies).
Fix: `floor.js` exposes `getReach()` → `{center, reach=planeSize/2}`,
`photo_renderer.js` re-exposes it as `getFloorReach()` (null unless active +
floor on), and the main.js frame callback extends far to enclose the floor in
BOTH branches (part: `far=max(2000, d+reach+1)`; assembly: expand the effective
radius to `max(contentRadius, dist(center,floorCenter)+reach)`). `near` still
tracks the CONTENT radius (floored at `far/1e5`) so depth precision around the
parts is unchanged. No edits to the locked phase constants or topology.

Materials: `matte` / `glossy` / `metallic` (MeshPhysicalMaterial PBR), `mirror`
(three Reflector from `addons/objects/Reflector.js` — real per-frame reflection
render), `shadow-catcher` (THREE.ShadowMaterial — transparent except where rig
shadows fall; ideal for compositing). Color picker is ignored by shadow-catcher.

**Shadow rig** (when floor on AND `floorShadows` checked):
`_applyShadowRig(true)` in photo_renderer.js flips `renderer.shadowMap.enabled`
(saved/restored), sets `THREE.PCFSoftShadowMap`, walks `_photoGroup` and on
every DirectionalLight sets `castShadow=true` + fits the ortho shadow camera
to the scene bbox (`radius = bbox.size.length() * 0.6`, `mapSize=2048²`,
`bias=-0.0005`, `normalBias=0.02`) + adds `light.target` to scene root and
aims it at bbox center. Scene meshes get `castShadow=true` saved/restored
through `_savedCastShadow` Map. **Skips** (no shadow casting): shared-renderer
LOD impostors (`userData.sharedLodImpostor`), sphere impostors
(`material.userData.impostorRadius != null`), additive sprites, line
materials, and the floor itself (`userData.photoFloor`). Same skip-list
informs the bbox computation in floor.js.

**Re-apply hooks**: `setLighting()` rebuilds the rig with new directional
lights at `castShadow=false`, so it calls `_enableRigShadows()` again when
`_shadowRigApplied`. `resyncMaterials()` (called when assembly meshes are
rebuilt mid-photo-mode) re-invokes `_rebuildFloor()` so the bbox + shadow
cameras refit and the new meshes are flagged. The rig restore happens in
`deactivate()` BEFORE `_photoGroup` is removed (the walk needs the lights).

**Floor mesh skip-list** for material-walking functions: `_swapMaterials`,
`setMaterialPreset`, `setTranslucency` all check `obj.userData.photoFloor`
and skip — otherwise the rep-driven swap would stomp the floor's PBR/Reflector/
Shadow material (a DoubleSide MeshPhysicalMaterial gets misinferred as
'surface' by `_inferRepr` and re-skinned with the gummy preset).

**Export path**: `renderToBlob`/`beginFrameSession` set
`offRenderer.shadowMap.enabled = _shadowRigApplied` so PNG/video exports
include the shadow (previously hard-coded `false`).

**Caveats:** (a) PT mode ignores Reflector (mirror floor renders as the base
color in path-traced output); (b) mirror floor does NOT receive shadows (the
Reflector replaces the material; shadow-catcher is the choice if you want
shadows); (c) Reflector texture size locked at construction — window resize
keeps the original reflection texture resolution; (d) grid overlay is a
GridHelper re-oriented from XZ-plane to the chosen axis via Quaternion
`setFromUnitVectors`, lifted by `diameter * 0.0008` along the normal to
avoid z-fighting.

Settings in `getSettings()`: `floor`, `floorMaterial`, `floorColor`,
`floorOpacity`, `floorGridDensity`, `floorOffset`, `floorShadows`, `floorGrid`
(+ deprecated unused `floorSize`) — all persisted in profiles. Setters:
`setFloor`, `setFloorMaterial`, `setFloorColor`, `setFloorOpacity`,
`setFloorGridDensity`, `setFloorOffset`, `setFloorShadows`, `setFloorGrid` —
each triggers a full `_rebuildFloor()`
(cheap: dispose old + rebuild plane geometry).

## Neon-grid camera-distance fade — 2026-05-31

User report (with screenshot): the neon floor grid's distant lines piled up into
a bright magenta band at the horizon that overwhelmed the scene. Cause: the grid
([floor.js](frontend/src/scene/photo_renderer/floor.js) `GridHelper`,
`toneMapped=false` HDR neon colours) spans an effectively-infinite plane with NO
distance falloff, so the thousands of lines converging at the horizon draw at
full brightness and Bloom amplifies the stack. Worse for assemblies (spread-out
parts stretch the plane over huge distances).

Fix = **Option B, camera-distance fade** (chosen over center-anchored radial
fade because in an assembly the camera can sit next to a distant part while the
grid center is far away — a center fade would dim the grid under the camera).
`_grid.material.onBeforeCompile` patches the LineBasicMaterial ('basic' shader):
vertex passes `vGridCamDist = length(mvPosition.xyz)`, fragment scales final
`gl_FragColor.rgb` + `.a` by `1.0 - smoothstep(fadeStart, fadeEnd, vGridCamDist)`.
**Final anchor: per-fragment EYE DEPTH (`-mvPosition.z`), fade window scaled to
the CAMERA'S HEIGHT ABOVE THE FLOOR PLANE H** — `fadeStart = 2·H`, `fadeEnd =
6·H`, `H = |(cameraPosition − floorPoint)·floorNormal|` computed live in the
vertex shader from the built-in `cameraPosition` uniform (so it tracks orbit/
dolly every frame, no per-frame JS; `floorPoint`/`floorNormal` ride in as
uniforms). `createFloor` takes only `{scene}` again. Constants
`GRID_FADE_START_HEIGHTS=2` / `GRID_FADE_END_HEIGHTS=6`.

Took FOUR wrong attempts; all dead ends confirmed with a real-WebGL2 Playwright
repro (built `frontend/grid_shader_test.html`, since deleted — rebuild it the
same way to retune):
1. **bbox `diameter` anchor** → `_computeSceneBBox()` excludes sphere impostors /
   sprites / lines, diameter floored to ~1 nm → window a few nm → whole grid gone.
2. **`planeReach`/`camToFloor×2` anchor** → visible grid spans from the structure
   to the far clip; a window keyed to the camera→floor-CENTRE distance (122 nm)
   faded out everything (repro showed on-screen grid eye-depths of 1500–2000 nm,
   not the ~150 I assumed).
3. **`far×[0.15,0.45]`** → killed the band at `far=2000`, but the user's `far` is
   INFLATED by the floor-reach extension (main.js pushes far out to enclose the
   huge floor plane, ~3640 nm), so the window landed past the band → band survived.
   ALSO: the band can't be removed by gentle dimming — semi-transparent lines, ~10
   overlapping at 0.4 alpha still composite to opaque, so the far lines must reach
   ~zero before they pack.
4. **angle/grazing fade** (`smoothstep` on `|dot(viewDir,normal)|`) → killed the
   band but faded as an ugly curved dome.
Key insight that ended it: where a ground plane visually packs toward the horizon
is set by the camera's HEIGHT above it, nothing else — so the band sits at a fixed
multiple of H regardless of scene scale, far clip, or grazing angle. Verified the
`[2H,6H]` window gives an identical clean fade at camera heights 25/90/200.
Eye depth means near content always stays bright → grid can't black out.

**"Fade reach" slider (2026-05-31):** `floorGridFade` setting (default **1.5**)
scales the whole window — `sm = 2×fade`, `em = 6×fade` — keeping the start:end
ratio, so higher = grid extends farther before dissolving. Default 1.5 = 1.5× the
original `[2H,6H]`. Wired like the other floor-grid controls: `_settings.floorGridFade`
+ `setFloorGridFade` (photo_renderer.js), `#photo-floor-grid-fade` range 0.3–6
(index.html, under the grid Density row), el/listener/applyProfile/syncToState in
photo_panel.js (persisted in profiles via `getSettings`).
`-mvPosition.z`
recomputes per frame from the modelView matrix, so it tracks camera moves with
no rebuild and works identically on the offscreen export renderer (anchors
verified against three r172: `#include <project_vertex>` in basic vtx,
`#include <dithering_fragment>` last in basic frag; chunks use `gl_FragColor`).
Single shared `floor.js` grid path → applies to BOTH part and assembly photo
mode automatically. **NOT VERIFIED IN APP** (needs a hard reload + re-enter
photo mode; watch console for shader-compile errors).

## Export-path parity audit — 2026-05-28

Verified every new photo-mode feature shipped this week renders through both
PNG (`renderToBlob`) and video (`beginFrameSession`) exports:

| Feature | Captured in export? |
|---|---|
| Floor mesh + matte/glossy/metallic/shadow-catcher materials | scene-level, no extra work |
| Mirror (`Reflector`) floor | per-renderer GL allocation via Three.js `properties` cache — works in offRenderer |
| Sun light (`_sunGroup` at scene root) | scene-level, no extra work |
| Shadow rig (rig + sun + floor receiveShadow) | `offRenderer.shadowMap.enabled = _shadowRigApplied` + `PCFSoftShadowMap` |
| Neon grid (HDR vertex colors, `toneMapped=false`) | survives the offscreen composer chain |
| Surface vertex colors through topology rebuilds | baked into surface-batch payload (see earlier entry) |

**Fix added 2026-05-28:** the live render loop's `renderer.resetState?.()`
call (which mitigates the bloom+HDRI+metallic darkness bug from WebGLState
texture-unit cache desync) was missing from both export paths. Added
`offRenderer.resetState?.()` before each `composer.render()` call in
`renderToBlob`'s tile loop and `beginFrameSession.renderFrame`'s tile loop.
Without this, a high-res PNG of a metallic scene under HDRI + Bloom could
come out fully black while the live preview rendered correctly.

Verified by stacking every new effect at once (HDRI Room + Bloom + Mist +
Fluoro Emissive + Floor -Y + Shadows + Neon Grid + Sun + full=metallic),
calling `renderToBlob(800, 600)`, and inspecting the PNG: non-trivial
size, opaqueFraction=1.0, zero console errors.

## Surface strand colouring through animation playback/export — 2026-05-28

Surface mesh (`'dna-surface'`) lost its per-vertex strand colours during
animation preview/video export inside photo mode whenever a keyframe pair had
different marching-cubes topology. `surface_renderer.js::_rebuildTopology()`
was unconditionally setting `material.vertexColors = false` and painting a
uniform grey, because the batch endpoint shipped only `{vertices, faces}` —
no colour data the new topology could use.

**Fix:**

- Backend [crud.py](backend/api/crud.py) `surface_batch`: when
  `body.color_mode == "strand"`, calls `surface_to_json` (same per-vertex
  strand-colour computation the live `/design/surface` endpoint uses) and
  pulls `vertex_colors` into the per-position payload. Rounded to 4 decimals
  for compact bake-payload size.
- Frontend [surface_renderer.js](frontend/src/scene/surface_renderer.js)
  `_rebuildTopology`: when the new geometry data carries `vertex_colors`
  AND `_colorMode === 'strand'`, attaches them as the `color` attribute and
  keeps `material.vertexColors = true`. Photo-mode `MeshPhysicalMaterial`
  honours the same flag and per-vertex `color` attribute as normal-mode
  `MeshPhongMaterial`, so the fix is identical for both render modes.
- Two new tests in `tests/test_animation.py`:
  `test_surface_batch_includes_vertex_colors_in_strand_mode` and
  `..._omits_vertex_colors_in_uniform_mode`.

Same-topology lerps were always fine — the geometry's existing `color`
attribute survives in-place position updates. Only the topology-rebuild
branch needed the fix.

## Sun = sole light source (preset rig hidden when sun on) — 2026-05-31

User request: toggling the Sun on in photo mode should leave exactly one light
source. Previously the Sun only took over *shadow casting* (one-key-light rule
below); the preset studio rig kept providing fill/rim/ambient illumination.

Fix ([photo_renderer.js](frontend/src/scene/photo_renderer.js)): new
`_applyRigVisibility()` sets `_photoGroup.visible = !_settings.sun`, called at
the top of `_applySun()` so it fires on entry (`activate` → `_applySun`) and
every sun setter. Sun on → the whole preset rig (ambient + hemisphere +
directionals) is hidden; sun off → restored. Mist gather (`_gatherLightsForInscatter`)
now gates the rig traverse on `_photoGroup?.visible` (traverse ignores
`.visible`) so inscatter matches what's rendered. PT picks it up on its next
BVH build (scene generator respects `.visible`; `setSun` resets sampling — the
documented "lights update on PT off/on" limitation still applies). **Image-based
lighting from the Environment dropdown is independent** and still contributes;
turn the environment off too for a pure single-light look. **NOT VERIFIED IN APP.**

## One-key-light shadow rule — 2026-05-27

To avoid double shadows from the preset rig + Sun, **exactly one directional
light casts a shadow at any time** (or zero if the floor's shadow rig is off):

- **Sun on** → Sun is the sole shadow caster. Every preset DirectionalLight has
  `castShadow=false` (they still illuminate as fill).
- **Sun off** → the *first* DirectionalLight encountered in `_photoGroup` is
  the key (castShadow=true, fitted ortho frustum); the rest are fill.
- **Floor off / shadow rig off** → no directional casts shadow.

Enforced in `_enableRigShadows()` (one-pass traverse with a `keyAssigned` flag
+ `sunOwnsShadow` gate) and re-called from `_applySun()` on every sun toggle/
parameter change so the demote-preset-key / restore-preset-key transition is
deterministic. Verified by counting `castShadow` directionals after each
toggle: always 1 with floor on, 0 with floor off.

## Steerable Sun light — 2026-05-27

User complaint: yaw/pitch sliders rotate the *whole preset rig*, so positioning
a shadow "directly behind" a part required juggling two coupled angles. Added
a dedicated **Sun** in the Lighting section — an independent DirectionalLight
steered by polar coordinates relative to the chosen floor's normal:

- `sun` (toggle), `sunAzimuth` (deg around floor normal), `sunElevation`
  (0..90, above floor), `sunStrength`, `sunColor`. Settings persisted in
  profiles. Setters: `setSun`, `setSunAzimuth`, `setSunElevation`,
  `setSunStrength`, `setSunColor`.
- Lives in its own `_sunGroup` at scene root (NOT under `_photoGroup`), so
  yaw/pitch (which rotate `_photoGroup`) do not move the sun.
- `_sunUpAxis()` returns the visible-face normal of the active floor
  (`{-y:+Y, +y:-Y, -x:+X, +x:-X, -z:+Z, +z:-Z}`) or world +Y if no floor.
  `_sunDirFromPolar(up, az, el)` builds a tangent frame on the floor (ref =
  world +X, falls back to +Z if up ≈ +X), rotates around `up` by azimuth, tilts
  toward `up` by elevation. Sun position = bbox center + dir × (radius × 2).
- `_applySun()` is called from `activate()`, `_rebuildFloor()` (floor change
  invalidates both up-axis and bbox), and each sun setter. Shadow camera is
  fit via the same `_fitDirLightShadow()` when `_shadowRigApplied`.
- `_gatherLightsForInscatter` now walks both `_photoGroup` and `_sunGroup` so
  mist accumulates the sun's contribution.

**Why three controls instead of one click-on-floor gizmo:** sliders are
predictable, scrub-able with drag_scrub, and fit the existing photo-panel
idiom. A click-on-floor placement was offered but not chosen.

## Bloom + HDRI + metallic = black scene fix — 2026-05-28

User report on `Ultimate Polymer Hinge2.nadoc` (a large polymer design where
every mesh uses `full=metallic`): bloom on + HDRI on + metallic = complete
darkness; turning off any one of those three fixed it.

Root cause: WebGLState's texture-unit binding cache desyncs vs. actual GL
state during UnrealBloomPass's heavy per-frame texture churn (5-level mip
chain + high-pass input + composite tints). The next frame's
MeshPhysicalMaterial with `metalness=1` + `scene.environment` samples a
texture unit that bloom last left bound elsewhere → uniformly black scene.

The triplet is the worst case because:
- Metallic (metalness=1, low roughness) has NO diffuse path — pure spec
  lookup against PMREM. No fallback if the env sample fails.
- HDRI provides the PMREM texture that the spec lookup needs.
- Bloom is the texture-unit churn that knocks the env's binding out of
  cache sync.

Disabling any single one breaks the triplet — bloom is removed (no churn),
HDRI is removed (no env to lose), or metallic is removed (a non-zero diffuse
path masks the missing env reflection).

**Fix** ([photo_renderer.js](frontend/src/scene/photo_renderer.js) in
`_installComposerRenderFn`): call `renderer.resetState?.()` once before
`composer.render()` each frame. Flushes the WebGLState cache so bindings
are re-validated. Standard Three.js mitigation when post-process + PBR +
env-reflective materials interact.

## Bloom + HDRI — corrected fix (no composer rebuild after activate) — 2026-05-28

Original gotcha: PMREMGenerator (`fromScene`/`fromEquirectangular`) mutates
renderer state as a side effect. A composer (UnrealBloomPass) constructed
AFTER any PMREM bake on that renderer inherits the lingering state and the
bloom additive blend paints garbage (angle-dependent colour tint).

The activate-time pattern works because PMREM has never run on the renderer
yet — composer construction is clean, bake comes after.

First attempt (2026-05-27, since reverted) tried "dispose + rebuild composer +
re-bake env" inside `setBloom`/`setSSAO`. **This did NOT work.** Within that
helper, composer construction still happens AFTER the activate-time bake's
state mutation — the re-bake at the end doesn't undo what the prior bake did
to the renderer. So the rebuild path itself re-triggered the original bug.

**Correct fix (2026-05-28):**
- Bloom + SSAO passes are **always constructed** in `createComposer`. The
  pass's `enabled` flag is what toggles them — EffectComposer skips disabled
  passes entirely (no swap, no work).
- `setSSAO(enabled)` / `setBloom(enabled, …)` just flip `pass.enabled` (and
  push new uniforms for bloom strength/radius/threshold). **No composer
  reconstruction at any point post-activate.**
- The composer is built exactly once at activate time, after which any number
  of HDRI / bloom / SSAO toggles are safe.
- `renderToBlob` / `beginFrameSession` keep composer-first / bake-second
  because their offscreen renderer has never seen PMREM. `renderToBlob` also
  reuses one composer across all tiles (was previously rebuilt per tile,
  which would have hit the same bug repeatedly).

Cost: one idle bloom mip-chain + SSAO RT allocation when those features are
off. Negligible.

The mist-on-fixes-it correlation was a state-coincidence at render time; it
no longer matters with the construction-time bug eliminated.

## World-origin axes + bloom = black square on ANGLE/D3D11 — 2026-06-21

User report: with **Bloom on** in photo mode, a large black square covered the
design over a *range of orbit angles* (it tracked the **world origin**, not the
design). Windows + RTX-2080, Chrome's **ANGLE/D3D11** backend. Setting-independent
(background / material / floor / SSAO / environment / path-tracing all no effect);
only **bloom off** OR **hiding the origin axes** removed it; **export PNG was always
clean**. Never reproduced on the headless e2e backend (desktop GL) — ANGLE-specific.

Root cause: photo mode hid the design's helix-axis arrows
(`designRenderer.setAxisArrowsVisible(false)`) but NOT the **world-origin triad**
(`originAxes = new THREE.AxesHelper(4)`, [main.js](../../../NADOC/frontend/src/main.js)
~L242, toggled by View ▸ Toggle Origin Axes). The AxesHelper's `toneMapped:false`
`LineBasicMaterial` interacts with `UnrealBloomPass` on ANGLE/D3D11 to paint a black
square at the origin's screen position. (Earlier mis-diagnoses this session, all
wrong: floor occlusion → transparent-bg-through-bloom → composer resize mismatch.
The decisive clue was the user noticing it tracks the ORIGIN + the axes-toggle.)

Fix: `photo_mode.js` now hides `originAxes` on enter (saving prior visibility) and
restores it on exit, alongside the other editor gizmos it already hides;
`originAxes` is passed in as an `initPhotoMode` dep from `main.js`. Correct on its
own merits (origin triad doesn't belong in a publication figure) and dodges the
ANGLE bloom artifact. Verified: triad visible→hidden→restored, smoke green.

**Generalize:** any `toneMapped:false` line/gizmo left visible in photo mode (the
View grid `GridHelper`, debug overlays, etc.) is a candidate for the same ANGLE +
bloom black-square artifact — hide editor gizmos in photo mode. **Separate latent
bug found + deferred:** the live EffectComposer doesn't resize with the canvas
(`handleResize` is never wired via `setResizeCallback`); harmless on desktop GL
(it stretches the stale buffer) but a real size mismatch that could bite on ANGLE.

## Locked constants

- `_FLUORO_LIGHT_GAIN = 12.0` ([photo_renderer.js](frontend/src/scene/photo_renderer.js)) — tuning constant for slider→PointLight.intensity. Not load-bearing; change freely if reflections are too weak/strong.
- Tile max = `min(gl.MAX_TEXTURE_SIZE, 4096)` in `renderToBlob`. Lower if browser clamps; raise carefully.
