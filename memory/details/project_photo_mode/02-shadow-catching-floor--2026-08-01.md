# Shadow-catching floor — 2026-08-01 — supporting detail

[Topic head](../../project_photo_mode.md). Open only the section relevant to the task.
Original dates and qualification limits are retained; this is not a new validation run.

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

**Feature:** [photo_renderer/shadow_catcher.js](../../../frontend/src/scene/photo_renderer/shadow_catcher.js)
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
[scene/fov_pan.js](../../../frontend/src/scene/fov_pan.js) `fovPanScale()` =
tan(fov/2)/tan(55°/2) now multiplies both — pixels-per-drag ∝ panSpeed/tan(fov/2),
so the lens cancels. **Do not apply it to OrbitControls**: its own `panLeft/panUp`
already folds `tan(fov/2)` in, so it would double-correct.
