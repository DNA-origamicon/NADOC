---
name: Assembly part-context panels — status and deferred work
description: Part-context support for camera/feature-log/animation panels when a part is selected in assembly mode; two bugs also fixed; animations+feature-log need backend verification
type: project
originSessionId: e02ef695-62a3-4cfa-b257-f610fa3635fb
---
# Assembly Part-Context Panels

**Branch:** `assembly-overhaul`  
**Date:** 2026-04-23

## What was built

When a part instance is selected in assembly mode, the existing left-sidebar panels (camera poses, feature log, animation) now switch to show that part instance's **design-level** data instead of the active design's data. All operations route through a `patchFn` read-modify-write that calls `api.patchInstanceDesign(id, content)`.

### Architecture (3-layer)

`assembly_panel.js` owns the fetch/cache cycle:
- `_onPartInstanceChanged(instanceId)` — fetches design via `api.getInstanceDesign(id)`, caches it, builds `_makePatchFn(instanceId)`
- `_makePatchFn(instanceId)` — returns an async function that: (1) calls `beforePatchDesign(instanceId)` to invalidate geometry cache, (2) deep-clones design + applies modifier, (3) optimistic `onPartContextChange`, (4) PATCH, (5) re-fetch + notify again
- `onPartContextChange(instanceId, design, patchFn)` callback (wired in `main.js`) → dispatches to `_partCameraPanel`, `_partAnimPanel`, `_partFeatureLogPanel`

### Each panel has `setPartContext(instanceId, design, patchFn)` / `clearPartContext()`

**`camera_panel.js`** — complete:
- Capture, rename, update-camera, delete, reorder all route through `_modifyPartDesign(patchFn)` when `_partInstanceId` is set
- Store subscription guarded with `if (_partInstanceId) return`

**`feature_log_panel.js`** — complete (needs backend verification):
- `_seek(position)` calls `_partPatchFn(d => d.feature_log_cursor = position)` in part mode
- Delete button calls `_partPatchFn(d => d.feature_log.splice(i, 1))` in part mode
- **DEFERRED:** Needs to verify that `PATCH /assembly/instances/{id}/design` with an updated `feature_log_cursor` actually triggers full geometry recalculation on the backend. If not, may need a dedicated endpoint like `POST /assembly/instances/{id}/seek`.

**`animation_panel.js`** — complete (needs backend verification):
- All CRUD (create/delete/rename animation, fps/loop, add/delete/reorder/update keyframe) routes through `_partPatchFn` read-modify-write
- `_makeKfRow` reads `poses` and `featureLog` from `_partDesign` in part mode
- **DEFERRED:** Playback uses the existing `player.play(anim)` — this player drives design-level API calls (seekFeatures, updateKeyframe) which don't apply to part instances. Part-mode animation playback needs a separate playback path that patches instance joint_states and feature_log_cursor per keyframe.

### Two assembly bugs also fixed (same session)

**Bug 1 — Gold connector spheres persist after mate creation:**
- `assembly_joint_renderer.js`: `enterMateDefineMode()` sets `_connectorGroup.visible = true`; `exitMateDefineMode()` sets it to `false`; `setVisible(on)` now gates on `on && _mateMode`

**Bug 2 — Orange joint indicator doesn't track part during gizmo drag:**
- Added `setLiveJointTransform(instanceId, newMatrix4, assembly)` to `assembly_joint_renderer.js`
- Computes delta = newMatrix4 × committedMat⁻¹, applies to all joints where `joint.instance_a_id === instanceId`
- Called from all live-drag paths in `main.js`: gizmo callback, `_applyFKLive` (child + rigid group members), free drag

## What to do next session

1. **Verify feature-log seek on part instances** — check whether `PATCH /assembly/instances/{id}/design` with `feature_log_cursor` causes the backend to recompute deformations for that instance's geometry. Look at `assembly.py:836` (`patchInstanceDesign`) to see what happens on save. If it doesn't recompute, add a `POST /assembly/instances/{id}/seek` route that calls `seekFeatures` internally then saves.

2. **Part-mode animation playback** — the existing player drives design-level API calls. Part-mode needs a different playback path: for each keyframe, call `api.patchInstance(instanceId, { feature_log_cursor, joint_states })` and wait. This can be a new `playOpts.partMode` branch in the player, similar to the existing `_assemblyMode` branch that uses `onJointUpdate`.

3. **Test the full part-context UI** — load an assembly with a part that has camera poses, feature log entries, and/or animations; click the part instance; verify the sidebar panels switch content.
