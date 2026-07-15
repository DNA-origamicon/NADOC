---
name: animation
description: Animation framework — camera poses, keyframe playback, configurations, pre-baked frames.
paths:
  - "frontend/src/ui/animation*.js"
  - "frontend/src/scene/animation_player.js"
  - "backend/api/animation*.py"
---

# animation

> **Strand-anim integration (SHIPPED 2026-05-29):** the display-only strand module
> (`strand-anim/model.js` `buildStrandGeometry` + `strand-anim/strand_renderer.js`
> `createStrandRenderer`) is now wired into the design-editor player as a **bind/unbind φ**
> animation. Seam chosen = **keyframe field** (`AnimationKeyframe.binding_states`: driverId → φ),
> lerped in `_applyAt` alongside `joint_values`. Each frame, per animated *driver* (an
> `OverhangBinding` OR a linker `OverhangConnection`, both carrying `target_joint_id` +
> authored `unbound_angle_deg`/`bound_angle_deg`): (1) `_driveBindingHinge` rotates the driver's
> target-joint cluster to `lerp(unbound, bound, φ)` via the existing `applyClusterTransform`
> path (display-only, restored by `_restoreBaseClusters` on stop — never clamps the live joint
> window so a bound/locked joint still plays); (2) `overhang_unzip_overlay.js` splays the
> **REAL overhang beads** (NOT a synthetic overlay): it moves the actual rendered nucleotides via
> `helixCtrl.setBeadOverrides(updates)` — a new quiet, surgical per-bead updater added to
> `helix_renderer.js` (next to `applyFemPositions`, but no console.log / no full-scene sweep, so
> it's safe per-frame). φ=1 = authored positions; φ→0 = a melt fork travels tip→root and freed
> nucleotides splay as a straight ssDNA arm pointing TOWARD that strand's own root (perp-to-duplex-
> axis component of root−center → ~90° for overhang-to-overhang). Linkers animate the two overhangs'
> beads only (bridge left as-is). Beads on the hinge's driven cluster are rotated by the live hinge
> incrRot so they stay attached to the moving arm. On stop the overlay restores moved beads to
> authored (also redundantly covered by `_restoreBaseClusters`). Authoring UI in
> `animation_panel.js`: "Bind/Unbind poses" section (open/closed angle inputs + grab-current
> buttons; linker joint auto-detected server-side) + per-keyframe driver φ rows. Linker driver =
> `PATCH /design/overhang-connections/{id}/display-pose` (auto-detects spanning joint via
> `_overhang_owning_cluster_id`); binding driver = `PATCH /design/overhang-bindings/{id}/display-pose`.
> Three-layer-safe (no topology writes during playback). v1 caveats: splay/root geometry computed
> from authored frame; polarity (which end unzips, angle sign) uses defaults — verify in app.

## Architecture

## Entry Points
- **Player**: `frontend/src/scene/animation_player.js` — `initAnimationPlayer({camera, controls, designRenderer, deformView, getConfigPanel})`
- **Animation panel**: `frontend/src/ui/animation_panel.js` — `initAnimationPanel(store, {player, api})`
- **Config panel**: `frontend/src/ui/config_panel.js` — `initConfigPanel(store, {getHelixCtrl, api})`
- **Camera panel**: `frontend/src/ui/camera_panel.js` — `initCameraPanel(store, {captureCurrentCamera, animateCameraTo, api})`
- All panels initialized at main.js ~lines 3507–3530, after clusterGizmo

## Phase Status
- **Phase 1 (Camera Poses)**: ✅ stable — `CameraPose` CRUD, `V` hotkey to capture
- **Phase 2 (Keyframe Playback + WebM/GIF export)**: ✅ stable — frame loop, bounce/seek, MediaRecorder export
- **Phase 3 (Configurations)**: 🔴 needs debugging — implemented but untested end-to-end

## API Endpoints
| Group | Method | Path |
|-------|--------|------|
| Camera poses | `POST/PATCH/DELETE` | `/design/camera-poses` |
| Camera poses | `PUT` | `/design/camera-poses/reorder` |
| Animations | `POST/PATCH/DELETE` | `/design/animations/{id}` |
| Keyframes | `POST/PATCH/DELETE` | `/design/animations/{id}/keyframes/{kf_id}` |
| Configurations | `POST/PATCH/DELETE` | `/design/configurations` |
| Configurations | `PUT` | `/design/configurations/reorder` |

## Models
- `CameraPose`: `{id, name, position, target, up, fov, orbit_mode}`
- `AnimationKeyframe`: `{id, config_id?, camera_pose_id?, ...}`
- `DesignConfiguration`: `{id, name, entries: ClusterConfigEntry[]}`
- `ClusterConfigEntry`: cluster transform snapshot (translation, rotation quaternion)

## Cluster Config Animation Flow
```
captureClusterBase(append=True) → snapshot current cluster transforms as base positions
per keyframe: slerp rotation + lerp translation per cluster
stop() → restoreBaseClusters()
```

## Known Phase 3 Bug Suspects
1. `captureClusterBase` append mode interaction with renderer rebuild (rebuild clears base)
2. `_restoreBaseClusters` identity quaternion math (incorrect slerp from identity)
3. Config dropdown not populating if configs loaded after panel init (timing race)
4. Backend `set_design_silent` missing on `update_configuration` (undo stack pollution)
5. Export timing: `seekTo()` doesn't trigger backend persist → export may use stale geometry

## Export
- `frontend/src/scene/export_video.js` — WebM (MediaRecorder + `captureStream`) + GIF (`gifenc`, lazy import)
- Triggered from animation panel export button

## Key Files
- `backend/core/models.py` — ClusterConfigEntry, DesignConfiguration, AnimationKeyframe
- `backend/api/crud.py` — configuration + animation CRUD endpoints
- `frontend/src/scene/helix_renderer.js` — `captureClusterBase(append)`, `applyClusterTransform()`, `_restoreBaseClusters()`

## Diagnostics → [.claude/runbooks/RUNBOOK_ANIMATION.md](../runbooks/RUNBOOK_ANIMATION.md)

## Files to Read
- `frontend/src/scene/animation_player.js` — `captureClusterBase`, `_restoreBaseClusters`, slerp logic
- `frontend/src/ui/config_panel.js` — dropdown population, store subscription
- `frontend/src/ui/animation_panel.js` — config dropdown, keyframe config_id handling
- `backend/api/crud.py` — configurations CRUD endpoints

## Related
- `MAP_ANIMATION.md` — animation architecture and Phase status

