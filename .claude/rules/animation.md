---
name: animation
description: Animation framework — camera poses, keyframe playback, assembly configurations, pre-baked frames, text/spin/trajectory keyframes, overhang bind-unbind.
paths:
  - "frontend/src/ui/animation*.js"
  - "frontend/src/ui/camera_panel.js"
  - "frontend/src/ui/keyframe_text_popup.js"
  - "frontend/src/ui/strand_anim_panel.js"
  - "frontend/src/scene/animation_player.js"
  - "frontend/src/scene/animation_text_overlay.js"
  - "frontend/src/scene/assembly_config_animator.js"
  - "frontend/src/scene/export_video.js"
  - "frontend/src/scene/overhang_unzip_overlay.js"
  - "frontend/src/scene/overhang_strand_anim.js"
  - "frontend/src/api/animation_endpoints.js"
  - "backend/api/routes_animations.py"
  - "backend/api/routes_camera_poses.py"
  - "backend/api/routes_assembly_animations.py"
  - "backend/api/routes_assembly_configs.py"
  - "backend/api/routes_feature_log.py"
---

# animation

Audited against live code **2026-07-30**. Everything below was verified by grep; the
"Removed API" block at the bottom lists names that are **gone** — do not resurrect them.

> **Scope note.** `.claude/rules/strand-anim.md` covers the *standalone sandbox*
> (`/strand-anim.html`, no Design, no backend). This rule covers the **design/assembly editor's**
> animation system, including the two places the sandbox's modules got reused
> (`overhang_unzip_overlay.js`, `overhang_strand_anim.js`).

## The one thing that is most wrong in older docs

**There are no design-scoped configurations.** `DesignConfiguration`, `ClusterConfigEntry`,
`config_panel.js`, `/design/configurations` — none of these ever shipped. Configurations exist
**assembly-scoped only**: `AssemblyConfigurationSnapshot` + `/assembly/configurations`, in heavy
production use (10+ `.nass` workspace files carry `configurations`). `AnimationKeyframe` names the
field `configuration_id` (not `config_id`). Topic file: `memory/project_assembly_configurations.md`.

## File map

| File | LOC | Role |
|---|---|---|
| [scene/animation_player.js](../../frontend/src/scene/animation_player.js) | 1205 | The player. `initAnimationPlayer({…20 deps})` at `:52`, init site [main.js:1581](../../frontend/src/main.js#L1581) |
| [scene/trajectory_keyframes.js](../../frontend/src/scene/trajectory_keyframes.js) | 197 | Trajectory keyframes → the jobs panels' display controllers. **Unit-tested** (26 `it`) |
| [ui/traj_prebuild_plan.js](../../frontend/src/ui/traj_prebuild_plan.js) | 62 | Free-RAM read + prebuild memory plan, shared by the MD panel and the animation path. **Unit-tested** (8 `it`) |
| [ui/animation_panel.js](../../frontend/src/ui/animation_panel.js) | 1624 | Authoring UI. `initAnimationPanel(store, {player, captureCurrentCamera, api, exportVideo, renderer, scene, camera, pinToFeature, getWorkspacePath})` at `:100`, init [main.js:6714](../../frontend/src/main.js#L6714) |
| [ui/camera_panel.js](../../frontend/src/ui/camera_panel.js) | 363 | `initCameraPanel(store, {captureCurrentCamera, animateCameraTo, api})` `:15`, init [main.js:6357](../../frontend/src/main.js#L6357) |
| [ui/keyframe_text_popup.js](../../frontend/src/ui/keyframe_text_popup.js) | 319 | `openKeyframeTextPopup` — text-keyframe editor, imported `animation_panel.js:22` |
| [ui/strand_anim_panel.js](../../frontend/src/ui/strand_anim_panel.js) | 292 | Per-overhang strand-anim setup UI, init [main.js:4604](../../frontend/src/main.js#L4604) |
| [scene/animation_text_overlay.js](../../frontend/src/scene/animation_text_overlay.js) | 65 | `applyAnimationTextOverlay(el, state)` — DOM overlay, driven by the player's `onTextOverlayUpdate` [main.js:1619](../../frontend/src/main.js#L1619) |
| [scene/assembly_config_animator.js](../../frontend/src/scene/assembly_config_animator.js) | 120 | Pure interpolation core for assembly configs, init [main.js:6348](../../frontend/src/main.js#L6348). **Unit-tested** (13 `it`) |
| [scene/export_video.js](../../frontend/src/scene/export_video.js) | 384 | WebM (`MediaRecorder`+`captureStream`) + GIF (`await import('gifenc')`). **TWO exporters:** `exportVideo` (raw editor canvas, Animations tab) and `exportPhotoVideo` (photo-mode pipeline via `photoMode.beginFrameSession`, **Photo** tab — see `memory/project_photo_mode.md`). **Unit-tested** (11 `it`) |
| [scene/overhang_unzip_overlay.js](../../frontend/src/scene/overhang_unzip_overlay.js) | 175 | `initOverhangUnzipOverlay({getHelixCtrl, getDesign})` `:36`; `update(items, geometry)` `:112`, `clear()` `:159` |
| [scene/overhang_strand_anim.js](../../frontend/src/scene/overhang_strand_anim.js) | 711 | `initOverhangStrandAnim({…})` `:44` → `{bind, setPhi, getFrame, isBound, clear, dispose}` `:658` |
| [api/animation_endpoints.js](../../frontend/src/api/animation_endpoints.js) | 107 | 18 exported client fns (design + assembly) |
| [backend/api/routes_animations.py](../../backend/api/routes_animations.py) | — | design animations + keyframes |
| [backend/api/routes_camera_poses.py](../../backend/api/routes_camera_poses.py) | — | design camera poses |
| [backend/api/routes_assembly_animations.py](../../backend/api/routes_assembly_animations.py) | — | assembly mirror of both |
| [backend/api/routes_assembly_configs.py](../../backend/api/routes_assembly_configs.py) | — | assembly configurations + assembly camera poses |
| [backend/api/routes_feature_log.py](../../backend/api/routes_feature_log.py) | — | seek + the three **pre-bake batch** routes |

`main.js` is 8059 LOC and the four init sites are spread across ~5000 lines — they are **not** a
contiguous block, and `initClusterGizmo` ([main.js:4614](../../frontend/src/main.js#L4614)) is not
adjacent to any of them.

## Player

`initAnimationPlayer` takes **20 deps**, nearly all lazy getters:

```
camera, controls, getCameraPoses, getDesign, getClusterTransforms, getHelixCtrl,
getBluntEnds, getUnfoldView, getDesignRenderer, getOverhangLinkArcs,
getOverhangUnzipOverlay, getMultiOverhangStrandAnim, getDesignGeometry,
onFetchGeometryBatch, trajectoryKeyframes, onFetchAtomisticBatch,
getAtomisticRenderer, onFetchSurfaceBatch, getSurfaceRenderer, onEvent, onTextOverlayUpdate
```

`trajectoryKeyframes` replaced the four `onFetchTrajectory*` / `onRestoreDesignAtomistic`
callbacks — see "Trajectory keyframes" below.

Public API (`:1217`): `play, pause, resume, stop, seekTo, cancelBake, setBounce, getBounce,
setLoopMode, getLoopMode, setDisablePoses, getDisablePoses, setLockFov, getLockFov, isPlaying,
getDirection, getCurrentTime, getTotalDuration, getActiveTextOverlay`.

**`setLockFov` vs `setDisablePoses` — they are not interchangeable.** `setDisablePoses` skips the
*whole* camera-pose lerp (so the user can orbit during playback). `setLockFov` keeps
position/target/up and suppresses only the two `camera.fov =` writes (spin branch + lerp branch).
It exists for the photo-mode video export: photo mode owns FOV as a setting and `setFOV` **dollies**
to preserve framing, so an unguarded pose would snap a 15° publication lens back to the 55° it was
captured at — and take the framing with it.

Internals worth knowing:

| Symbol | Line | Note |
|---|---|---|
| `_captureAllBases()` | `:583` | loops clusters calling `captureClusterBase(..., !first, {forceAxes:true})`; called from `play()` `:1159` |
| `_applyAt(t)` | `:829` | the per-frame lerp — camera pose, joints, binding φ, strand-anim φ, spin, text |
| `_driveBindingHinge(driver, phi)` | `:740` | display-only cluster rotation via `applyClusterTransform`; call site `:1044` |
| `_restoreBaseClusters()` | `:688` | **lives on the player, not the renderer**; only caller is `stop()` `:1196`. Applies an *identity* quaternion with `dummy === center` — there is no slerp here |
| `seekTo(seconds)` | `:1267` | `_applyAt` + a `tick` event. **Makes no backend call, by design** (display-only, Three-Layer-safe) |
| `cancelBake()` | `:355` | aborts the pre-bake fetch loop |
| `setDisablePoses(true)` | `:1260` | skips camera-pose lerp so the user can orbit during playback |
| bounce / loop | `:1244-1253`, boundary logic `:1082-1101` | |

**Pre-bake, not live-fetch.** Before playback the player batches geometry for every keyframe's
feature-log index: `POST /design/features/geometry-batch` (`routes_feature_log.py:112`), plus
`atomistic-batch` (`:138`) and `surface-batch` (`:168`). `POST /design/features/seek` is `:72`.
This is why `seekTo` needs no backend round-trip.

## Trajectory keyframes — ONE pipeline, and it is the jobs panel's (2026-08-02)

**The player fetches no trajectory data.** `scene/trajectory_keyframes.js`
(`initTrajectoryKeyframes({getController, planPrebuild})` — **unit-tested, 26 `it`**) drives the
SAME display controllers the jobs panels drive: `oxdnaDisplay` for oxDNA/LAMMPS, `mdViz` for NAMD
(both `initOxdnaDisplay`, `main.js` ~1948 / ~2020). Consequences worth knowing:

- The trajectory, its heavy frames, its memory budget and its job topology are fetched **once** and
  shared with the panel. Scrub a job in the Simulations tab, then play an animation over it, and the
  bake is a no-op (`activeJobId() === jobId` → no reload).
- Frame caps come from `prebuildMemoryPlan` + free RAM (`ui/traj_prebuild_plan.js`, a factory so
  each consumer caches its own MemAvailable reading), **not** a fixed number.
- `show()` calls `showFrame` only when the index CHANGES; `suspend()` hands the heavy rep back to
  the design between trajectory segments via `oxdnaDisplay.releaseHeavyToDesign()`.
- **Three methods on `oxdna_display.js` exist for this caller, and the distinction is the whole
  cross-play cache.** `stopAndRestore()` = done with the job, drops `_traj` + both bakes.
  `suspendToDesign()` = stop SHOWING it, restore the design, **keep** `_traj`/bakes/held topology;
  paired with `resumeTrajectory(jobId)`. `releaseHeavyToDesign()` = same but for the heavy rep only.
  `release()` on stop calls `suspendToDesign()` when the animation was the sole owner, or
  `showFrame(prevFrame)` when the panel was already scrubbing that job. **Using `stopAndRestore()`
  here re-downloads the trajectory on every Play** — on VoltronCoreScad that is 370 MB and >120 s,
  which is how the bug was caught (the e2e's second play timed out).
- **One job per controller at a time.** `prepare` loads the first job per controller; a second job
  on the SAME engine swaps in when its segment is reached (a reload each pass). Two jobs on
  different engines are free. No saved animation uses more than one job today.
- Bake progress for this phase has its own denominator, so it emits `baking_progress` with a
  `label` the panel prefers over its own "Rendering frame X of Y".

**The Animations tab now PRESERVES displays** (`ui/display_tab_policy.js`,
`DISPLAY_PRESERVING_TABS = ['photo', 'scene']`). Sharing the controller made an old,
previously-unreachable teardown live: arriving on `'scene'` fires `nadoc:left-tab-change` →
`oxdna_jobs_panel.js:2523` `_allDisplaysOff()` → `stopAndRestore()` on the controller the
animation is playing through. Symptom: **Animations → Photo → Animations reverted the model to
native positions** (Photo defers the leave, so the return trip is what tore it down). It was a
silent no-op before, because the player never made `oxdnaDisplay.isActive()` true.
`shouldStopLiveSession()` is the stricter sibling that keeps the OLD behaviour for streaming
sessions (oxDNA Live, "Display MD") — a stream writes the same beads every frame and must still
stop on `'scene'`. Both pinned in `display_tab_policy.test.js`.

**Deleted with the old pipeline — do not resurrect:** `_bakedTrajectories`, `_bakedTrajAtom`,
`_bakedTrajSurf`, `_TRAJ_ATOM_MAX`/`_TRAJ_SURF_MAX` (40/20), `_ensureDesignAtoms`,
`_mdAtomsActive`, `_lastMdAtomKey`, and the player's import of `framesToUpdates` from
`ui/oxdna_display.js`. The player no longer calls `applyFemPositions` for trajectories at all.

## Renderer hooks (in `scene/helix_renderer.js`, covered by `rendering.md`)

| Symbol | Line | Signature / note |
|---|---|---|
| `captureClusterBase` | `:4441` | `(helixIds, domainIds=null, append=false, {forceAxes=false}={})` — `append` is the **3rd positional**. Also on `domain_ends.js:758` with a **different arg order** `(transformKeys, append, domainIds)`, and on `joint_renderer.js:2639` / `overhang_locations.js:437` as `(helixIds)` only |
| `applyClusterTransform` | `:4544` | `(helixIds, centerVec, dummyPosVec, incrRotQuat, domainIds=null, {forceAxes=false}={})` |
| `setBeadOverrides` | `:3266` | surgical per-bead matrix write, safe per-frame (no console.log, no full-scene sweep). Consumers: `overhang_unzip_overlay.js:142,167`; `overhang_strand_anim.js:355,478,552,621,647` |
| `applyFemPositions` | `:3316` | the *other* bulk position path (oxDNA/mrDNA/CanDo/SNUPI) — **not** for animation |

## Models — `backend/core/models.py`

- **`CameraPose`** `:1241` — `{id, name, position, target, up, fov, orbit_mode}`.
- **`DesignAnimation`** `:1759` — `{id, name, fps, loop, keyframes: List[AnimationKeyframe]}`.
- **`AnimationKeyframe`** `:1696` — **27 fields**, five feature groups:
  - core: `id, name, camera_pose_id, configuration_id, feature_log_index, hold_duration_s, transition_duration_s, easing`
  - assembly: `joint_values` (joint id → value), `binding_states` (driver id → φ)
  - strand anim: `strand_anim_phi` (overhang id → φ)
  - trajectory: `is_trajectory, trajectory_job_id, trajectory_engine, trajectory_frame_start, trajectory_frame_end`
  - camera spin: `spin_axis, spin_rotations, spin_invert`
  - text: `text, text_font_family, text_font_size_px, text_color, text_bold, text_italic, text_align`
- **`AssemblyConfigurationSnapshot`** `:1291` + `AssemblyInstanceConfigState` `:1258`,
  `AssemblyJointConfigState` `:1268`, `AssemblyGearRelationConfigState` `:1278`.
- `Design` carries `camera_poses` `:2279` and `animations` `:2280` — **no `configurations` field**.

## Routes

| Path | Method | File:line |
|---|---|---|
| `/design/camera-poses` | POST | `routes_camera_poses.py:59` |
| `/design/camera-poses/{pose_id}` | PATCH / DELETE | `:81` / `:100` |
| `/design/camera-poses/reorder` | PUT | `:116` |
| `/design/animations` | POST | `routes_animations.py:108` |
| `/design/animations/{anim_id}` | PATCH / DELETE | `:123` / `:142` |
| `/design/animations/{anim_id}/keyframes` | POST | `:158` |
| `/design/animations/{anim_id}/keyframes/{kf_id}` | PATCH / DELETE | `:204` / `:232` |
| `/design/animations/{anim_id}/keyframes/reorder` | PUT | `:254` |
| `/assembly/configurations` | POST | `routes_assembly_configs.py:130` |
| `/assembly/configurations/{config_id}/restore` | POST | `:147` |
| `/assembly/configurations/{config_id}` | PATCH / DELETE | `:216` / `:244` |
| `/assembly/camera-poses[/{pose_id}][/reorder]` | POST/PATCH/DELETE/PUT | `:263 / :279 / :292 / :303` |
| `/assembly/animations…` (full mirror incl. keyframe reorder) | — | `routes_assembly_animations.py:103,115,130,142,184,204,221` |
| `/design/features/{seek,geometry-batch,atomistic-batch,surface-batch}` | POST | `routes_feature_log.py:72,112,138,168` |
| `/design/overhang-connections/{conn_id}/display-pose` | PATCH | **still in** `crud.py:7850` |
| `/design/overhang-bindings/{binding_id}/display-pose` | PATCH | **still in** `crud.py:8828` |
| `/design/overhangs/{overhang_id}/strand-anim-setup` | PATCH | **still in** `crud.py:8867` |

Registered in `backend/api/main.py`: `:216` camera_poses, `:221` animations, `:238`
assembly_animations, `:240` assembly_configs.

**Undo hygiene:** the assembly-config routes already use `assembly_state.set_assembly_silent`
(`routes_assembly_configs.py:212, 240, 288`) so config edits don't pollute the undo stack.

## The two overhang animation paths — they coexist

Both are **display-only** (no topology writes during playback) and operate on *disjoint beads*.

**1. `binding_states` — simple OH↔OH unzip** (shipped 2026-05-29). Per animated *driver* (an
`OverhangBinding` **or** a linker `OverhangConnection`, both carrying `target_joint_id` +
authored `unbound_angle_deg`/`bound_angle_deg` — `models.py:381-383` / `:611,623-624`):

- `_driveBindingHinge` (`animation_player.js:740`) rotates the driver's target-joint cluster to
  `lerp(unbound, bound, φ)` through `applyClusterTransform`. It **never clamps the live joint
  window**, so a bound/locked joint still plays; `stop()`'s `_restoreBaseClusters` undoes it.
- `overhang_unzip_overlay.js` splays the **real rendered nucleotides** (not a synthetic overlay)
  via `setBeadOverrides`. φ=1 = authored positions; φ→0 = a melt fork travels tip→root and freed
  nucleotides splay as a straight ssDNA arm pointing toward that strand's own root. Linkers move
  the two overhangs' beads only (bridge left as-is). Beads on the driven cluster get the live
  hinge `incrRot` so they stay attached to the moving arm.
  ⚠️ Its melt shape comes from the **sandbox**: `:33-34` imports `meltFraction` *and*
  `DEFAULTS as STRAND_DEFAULTS` from `strand-anim/`, and `:83-84` reads `rise`/`armPull`/`meltBp`
  from it. Editing `strand-anim/params.js` changes this overlay. See
  [strand-anim.md](strand-anim.md) → "Who imports this".
- Frame-loop call site: `animation_player.js:1037-1047` (`overlay.update(items, geometry)`);
  cleared at `:1202`. Overlay constructed at [main.js:1722](../../frontend/src/main.js#L1722),
  handed to the player at `main.js:1572`.
- Authoring: `animation_panel.js:638` `_ensureBindPoseSection` (open/closed angle inputs +
  grab-current), per-keyframe φ rows `:1183`, PATCH at `:428-431`. Linker joint is auto-detected
  server-side via `_overhang_owning_cluster_id` (`backend/core/linker_relax.py:56`, used
  `crud.py:7872`).
- v1 caveats (unchanged): splay/root geometry is computed from the *authored* frame; polarity
  (which end unzips, angle sign) uses defaults — verify in app.

**2. `strand_anim_phi` — the full parametric un/hybridization model.** `models.py:1726` →
`getMultiOverhangStrandAnim` (`animation_player.js:1054-1069`) → `overhang_strand_anim.js`, which
reuses the sandbox's `createStrandRenderer` (`strand-anim/strand_renderer.js:41`) plus
`melt.js`/`params.js`. Authored via `PATCH /design/overhangs/{id}/strand-anim-setup` and
`ui/strand_anim_panel.js`. Richer than path 1 and independently keyframed.

⚠️ The sandbox's `buildStrandGeometry` (`strand-anim/model.js:56`) is **not** used by the editor —
its only caller is the sandbox's own `strand-anim/app.js:42`. The editor path imports the
*renderer* only. Don't assume the pure geometry model is on the editor's frame path.

## Test coverage — state it honestly

| File | Count | Covers |
|---|---|---|
| `tests/test_animation.py` | 20 | pre-bake `geometry-batch` (10, incl. cursor invariance + surface vertex colors), `binding_states` roundtrip `:252,:278`, `strand_anim_phi` `:289,:312,:321`, trajectory keyframes `:339,:370`, `strand-anim-setup` `:393,:415`, model roundtrip `:422` |
| `tests/test_assembly_api.py` | 3 of 75 | `:231` config restore ignores newer parts, `:275` assembly camera-pose CRUD, `:294` keyframe accepts pose+configuration |
| `frontend/src/scene/assembly_config_animator.test.js` | 13 | pure interpolation core |
| `frontend/src/ui/animation_panel.normalize.test.js` | 5 | panel normalization helpers only |
| `frontend/src/scene/trajectory_keyframes.test.js` | 26 | job collection, no-reload-when-held, per-engine routing, budget hand-off, frame-change guard, suspend/release/cancel |
| `frontend/src/ui/traj_prebuild_plan.test.js` | 8 | RAM cache + which ceiling binds |

`frontend/src/scene/export_video.test.js` (12 `it`) covers `exportPhotoVideo` only: frame count +
seek times, the `play→pause→seek→stop` lifecycle, `followMotion`, the `setLockFov` bracket, abort,
and session disposal on throw. The encode branches themselves are browser machinery.

**Zero tests** for `animation_player.js` (1205 LOC), `exportVideo` (the raw-canvas twin),
`overhang_unzip_overlay.js`, `overhang_strand_anim.js`, `camera_panel.js`.
**Zero e2e specs** touch animation.
Names that sound relevant but are not: `tests/test_cluster_config.py` (Alpine HPC submission
profiles), `frontend/src/ui/export_menu.test.js` / `metric_export_modal.test.js` /
`oxdna_export_card.test.js` (unrelated export paths), `photo_renderer/figure_camera.test.js`
(photo mode, not camera poses).

## Removed API — do not resurrect

These names appear in older memory files, `docs/triage/05_animation.md`, and stale prose. They do
**not** exist in the codebase:

- `DesignConfiguration`, `ClusterConfigEntry` — no such models; `Design.configurations` is not a field.
- `frontend/src/ui/config_panel.js`, `initConfigPanel` — file never existed / was removed. The
  config dropdown is `animation_panel.js:711` and is **assembly-scoped by construction**
  (`_assemblyMode ? currentAssembly?.configurations : []`).
- `/design/configurations`, `/design/configurations/reorder`, `POST /design/configurations/{id}/go-to`,
  `api.goToConfiguration` — zero hits repo-wide.
- `update_configuration` (backend) — successor is `update_assembly_configuration`.
- `deformView`, `getConfigPanel` as player deps — gone; `designRenderer` is now `getDesignRenderer`.
- `MAP_ANIMATION.md` — deleted.
- `helix_renderer.buildHelixObjects()` clearing `_clusterBases` — `_clusterBases` does not exist.

## Diagnostics → [.claude/runbooks/RUNBOOK_ANIMATION.md](../runbooks/RUNBOOK_ANIMATION.md)

## Related
- `memory/project_assembly_configurations.md` — configurations, assembly camera poses/animations
- `memory/project_animation_fade.md` — per-bp-range fade during playback
- `memory/project_animation_all_reprs.md` — beads/atomistic/surface in the pre-bake + lerp pipeline
- `memory/project_strand_animations.md` + `.claude/rules/strand-anim.md` — the sandbox
- `.claude/rules/rendering.md` — `helix_renderer.js` hooks used above
