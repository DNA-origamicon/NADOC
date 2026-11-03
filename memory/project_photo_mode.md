---
name: photo-mode
description: "Photo mode — flat figure materials, camera-pinned key shadow, ChimeraX depth-outline silhouette, tiled export. v1 (PBR/HDRI/bloom/PT/floor) was archived 2026-07-29."
metadata: 
  node_type: memory
  type: project
  originSessionId: caf07b9d-c547-4a4a-b679-8f8f745bc1f2
---

# Photo mode

## Topic navigation and current boundaries

Reorganized October 17, 2026. Read the retained contracts here, then only the
matching detail below. Dated results and old handoffs are not new verification
or authorization; current user instructions and `CLAUDE.md` take precedence.

> **REPLACED 2026-07-29.** What shipped as "Exp. Photomode" IS photo mode now.
> The old one (`photo_renderer.js` + `photo_mode.js` + `photo_panel.js` +
> `photo_figure_panel.js` + floor/post_processing/style_presets/inscatter) moved
> **verbatim** to `frontend/archive/photo_mode_v1/` — read its README before
> reviving anything. There is ONE photo tab. The v1 history — HDRI, bloom, path
> tracer, floor, mist, style presets, profiles, the export-rep upgrade — moved to
> [project_photo_mode_archive.md](project_photo_mode_archive.md); mine it only for
> a specific past decision.

**2026-09-11 — sidebar stack revision:** Rail clicks append full-height,
independently resizable columns, including shared-state copies. Source controllers
and DOM listeners are shared; other views mirror changed nodes/properties and
retain their own scrolling. Appearance uses an explicit `photo-lighting-enabled`
switch, never panel visibility. Closing a copy or hiding all controls preserves
lighting and playback. Columns have close buttons and subtle type-colored headers;
capacity reserves the right sidebar and 320px of workspace. Layout v3 migrates old
preferences. See `docs/expandable_panels_implementation_plan.md` for the pending
user checkpoint. Detached controls are assessed only in
`docs/detached_controls_feasibility.md`.

Photo mode lives at [frontend/src/scene/photo_mode.js](../frontend/src/scene/photo_mode.js),
UI in [frontend/src/ui/photo_panel.js](../frontend/src/ui/photo_panel.js)
(`data-tab="photo"`, HTML under `#tab-content-photo`), with the shared sub-modules
that SURVIVED v1 under `photo_renderer/`: `figure_pass`, `figure_camera`,
`material_presets`, `lighting_presets`, `shadow_bounds`, `mesh_repr`.
`main.js` carries only an import + factory init + the `TABS` entry (LOC 8074 → 8059
on the merge — the archive removed more wiring than the rename added).

**Why:** publication-grade rendering for figures and animations. Activate/deactivate must restore the live scene exactly (lights, materials, scene.environment, scene.background, **renderer tone mapping**) — the live editor still has to work after exit. **How to apply:** never mutate scene state from photo-mode code outside the saved-state pattern (`_savedMaterials`, `_savedSceneEnv`, `_savedSceneBackground`, `_savedLightState`, `_savedToneMapping`/`_savedExposure`). Adding a new visual feature means adding a save slot and a restore step in `deactivate()`.

## Inherited from v1 — tone mapping is load-bearing, don't drop it

v2 was written from the ground up, but one v1 fix was re-derived into it and must
stay: [photo_mode.js:513](../frontend/src/scene/photo_mode.js#L513) sets
`THREE.ACESFilmicToneMapping` in `activate()` (exposure hardcoded `1.0`, no
slider), restores both at [:621](../frontend/src/scene/photo_mode.js#L621), and the
offscreen export renderer sets the same at
[:772](../frontend/src/scene/photo_mode.js#L772). **Why it is not cosmetic:** with
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
surviving [material_presets.js:163](../frontend/src/scene/photo_renderer/material_presets.js#L163)
have **no caller in `src/`** (only the archived v1 renderer) and no test. Its
comment block is the only in-code record of the pre-tone-map bloom mechanism, and
it points at `photo_renderer.js`, which no longer exists live. Don't delete it
without moving that explanation; don't trust its file pointer.

<a id="camera-pinned-key-shadow--2026-07-28"></a>
- [Camera-pinned key shadow — 2026-07-28](details/project_photo_mode/01-camera-pinned-key-shadow--2026-07-28.md#camera-pinned-key-shadow--2026-07-28)

<a id="video-export--an-animation-rendered-through-photo-mode-2026-08-02"></a>
- [Video export — an animation rendered through photo mode, 2026-08-02](details/project_photo_mode/01-camera-pinned-key-shadow--2026-07-28.md#video-export--an-animation-rendered-through-photo-mode-2026-08-02)

- [Video export — an animation rendered through photo mode, 2026-08-02 — continued detail](details/project_photo_mode/01-camera-pinned-key-shadow--2026-07-28.md)

<a id="shadow-catching-floor--2026-08-01"></a>
- [Shadow-catching floor — 2026-08-01](details/project_photo_mode/02-shadow-catching-floor--2026-08-01.md#shadow-catching-floor--2026-08-01)

- [Shadow-catching floor — 2026-08-01 — continued detail](details/project_photo_mode/02-shadow-catching-floor--2026-08-01.md)

- [Shadow-catching floor — 2026-08-01 — continued detail](details/project_photo_mode/03-shadow-catching-floor--2026-08-01.md)

<a id="simulation-displays-survive-the-photo-tab--2026-07-14"></a>
- [Simulation displays survive the Photo tab — 2026-07-14](details/project_photo_mode/03-shadow-catching-floor--2026-08-01.md#simulation-displays-survive-the-photo-tab--2026-07-14)

<a id="publication--figure-mode--2026-07-14"></a>
- [Publication / figure mode — 2026-07-14](details/project_photo_mode/04-publication--figure-mode--2026-07-14.md#publication--figure-mode--2026-07-14)

<a id="decisions-that-cost-time--dont-re-litigate"></a>
- [Decisions that cost time — don't re-litigate](details/project_photo_mode/04-publication--figure-mode--2026-07-14.md#decisions-that-cost-time--dont-re-litigate)

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

<a id="exit-on-file-closeopennew-in-session--2026-05-29"></a>
- [Exit on file close/open/new (in-session) — 2026-05-29](details/project_photo_mode/05-exit-on-file-closeopennew-in-session--2026-05-29.md#exit-on-file-closeopennew-in-session--2026-05-29)

<a id="no-design--no-open-sidebar-close-session--2026-08-02"></a>
- [No design ⇒ no open sidebar (Close Session) — 2026-08-02](details/project_photo_mode/05-exit-on-file-closeopennew-in-session--2026-05-29.md#no-design--no-open-sidebar-close-session--2026-08-02)

<a id="exit-on-sidebar-tab-switch--feature-log-default-on-load--2026-06-20"></a>
- [Exit on sidebar-tab switch + feature-log default on load — 2026-06-20](details/project_photo_mode/05-exit-on-file-closeopennew-in-session--2026-05-29.md#exit-on-sidebar-tab-switch--feature-log-default-on-load--2026-06-20)
