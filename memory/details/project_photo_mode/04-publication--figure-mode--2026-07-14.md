# Publication / figure mode — 2026-07-14 — supporting detail

[Topic head](../../project_photo_mode.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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

- **[figure_pass.js](../../../frontend/src/scene/photo_renderer/figure_pass.js)** — the big lever.
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
- **[style_presets.js] (recorded path: `../frontend/src/scene/photo_renderer/style_presets.js`)** — pure.
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
- **[figure_camera.js](../../../frontend/src/scene/photo_renderer/figure_camera.js)** — pure dolly
  maths for the near-parallel projection.
- **[ui/photo_figure_panel.js] (recorded path: `../frontend/src/ui/photo_figure_panel.js`)** — the section's
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
