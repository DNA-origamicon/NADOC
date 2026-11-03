# Camera-pinned key shadow — 2026-07-28 — supporting detail

[Topic head](../../project_photo_mode.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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
because the caller survived.** [scene/export_video.js:91](../../../frontend/src/scene/export_video.js#L91)
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

**Progress reporting was rebuilt 2026-08-02 — see `.claude/rules/animation.md` →
"Export progress".** The Export Video button no longer calls `showOpProgress` itself;
it opens a `beginExportSession` from `scene/export_progress.js` with a weighted phase
plan and passes `onPhase` into `exportPhotoVideo`. Two photo-specific gains: the
`beginFrameSession` build (max-texture probe → offscreen renderer → shadow map →
RenderPass/FigurePass/SMAA/Output) is announced as its own `session` phase before it
runs rather than being silent seconds, and the GIF `finish()`+Blob+download tail is the
`encode`/`save` phases instead of dead time after "100%". It also closed a live bug:
because `_exportInFlight` lived in `animation_panel.js`, a **Photo**-tab export left it
false, so the bake opened a second `op_progress` that retitled this popup to "Rendering
Animation" and replaced its Cancel handler with the bake's.

**`beginFrameSession` gained `renderFrameToCanvas()` (2026-08-03).** `renderFrame()`
returned a PNG **Blob** that the video caller immediately undid — `createImageBitmap` +
blit + `getImageData` — to recover the bytes already sitting in the session's own
`finalCanvas`. That is a full deflate-encode plus decode per frame (~0.2–0.5 s at 1080p).
`renderFrameToCanvas()` returns the stitch canvas directly; `renderFrame()` is now a thin
`toBlob` wrapper over it and still serves the still-PNG export. The canvas is
session-owned and reused, so consume it before the next frame. It also fixed a latent bug:
the tiles are composited with `drawImage`, and `finalCanvas` was never cleared between
frames — on a **transparent** background each frame showed through the next. It now clears
first. Pinned in `export_video.test.js` (`describe('efficiency')`), both paths.

**Known limits, all pre-existing and shared with the raw-canvas Animations-tab
export** (logged in `issues_ledger.md`, none photo-specific): a trajectory frame
can capture stale atoms (`oxdna_display._applyHeavy` is `async` and unawaited);
assembly joints animate in NO exported video (`export_video` calls `play()` with
no opts, so `onJointUpdate` is null); `configuration_id` is inert on the player.
