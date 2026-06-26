---
name: Assembly configurations + assembly-scoped camera poses & animations
description: Configuration snapshots, assembly-level camera poses, configuration_id on keyframes, part_joints and cluster_transform_overrides — what was added, where it lives, what's deferred
type: project
originSessionId: 770e357f-ae2f-4cd2-b87f-af6de5746cac
---
# Assembly Configurations, Camera Poses, and Animation Keyframes

**Branch:** `kinematics-cleanup` (built on top of `assembly-overhaul` work).
**Date:** 2026-04-29.

This memory complements `project_assembly_part_context.md`. That earlier work
added *part-context* panels (when an instance is selected in assembly mode the
panels show the part's design-level data). This work added *assembly-context*
panels: camera poses and configurations live on the **assembly itself**, parallel
to design-level data.

## Why: Three parallel contexts now

Camera panel / feature-log panel / animation panel each route to one of:

1. **Part context** — instance selected, panel shows that PartInstance's design
   (`_partInstanceId` truthy). Stored in the source design via `patchInstanceDesign`.
2. **Assembly context** — assembly active, no part selected. Camera poses and
   configurations live on `Assembly.camera_poses` / `Assembly.configurations`.
3. **Design context** — no assembly. Standard design-level poses/animations.

Order of priority (in panel subscriptions): part > assembly > design. Camera
panel's `_rebuild` start: `assemblyActive ? currentAssembly.camera_poses : currentDesign.camera_poses`.

## Backend additions (`backend/core/models.py`, `backend/api/assembly.py`)

### New models
- `AssemblyConfigurationSnapshot` — `id`, `name`, `instance_states[]`, `joint_states[]`.
- `AssemblyInstanceConfigState` — `instance_id`, `name`, `transform`, `base_transform`,
  `joint_states`, `cluster_transform_overrides`.
- `AssemblyJointConfigState` — `joint_id`, `current_value`, `axis_origin`, `axis_direction`.
- `Assembly.configurations: List[AssemblyConfigurationSnapshot]` (default empty).
- `Assembly.configuration_cursor: Optional[str]` — id of last captured/restored config.
- `AnimationKeyframe.configuration_id: Optional[str]` — assembly snapshot to apply at this keyframe.
- `PartInstance.cluster_transform_overrides: List[ClusterRigidTransform]` — assembly-scoped
  overrides for part-internal cluster transforms (does **not** modify the source design).
- `PartInstance.allow_part_joints: bool` — toggles interactive in-assembly part-joint rotation;
  when true the joint indicator renders larger/highlighted.
- `InterfacePoint.cluster_id: Optional[str]` — connector → cluster mapping; `add_joint` now
  infers `cluster_id_a/cluster_id_b` from connector labels via `_infer_cluster_ids_for_connector_label`.
- `Crossover.process_id: Optional[str]` — operation that placed the crossover (e.g. "manual", "auto_crossover").

### Endpoints (all under `/assembly/`)

| Verb   | Path                                          | Purpose |
|--------|-----------------------------------------------|---------|
| POST   | `/configurations`                             | Capture current state as named snapshot. Cursor → new id. |
| POST   | `/configurations/{id}/restore`                | Restore matching instances+joints. Adds-after-capture left as-is. Cursor → id. |
| PATCH  | `/configurations/{id}`                        | Rename, or `overwrite_current=true` to replace with current state. |
| DELETE | `/configurations/{id}`                        | Remove; cursor falls back to last remaining. |
| POST   | `/camera-poses`                               | Create assembly-level camera pose. |
| PATCH  | `/camera-poses/{id}`                          | Update fields (silent — no undo entry). |
| DELETE | `/camera-poses/{id}`                          | Remove. |
| PUT    | `/camera-poses/reorder`                       | Reorder by `ordered_ids`. |
| PATCH  | `/instances/{id}/cluster-transform`           | Store a per-instance cluster transform override (no design mutation). Body may include a `delta_transform` to propagate to mated child parts. |

`set_assembly_silent` is used for non-undoable intermediate steps; explicit
undo points use `snapshot()`. Configuration restore is silent (so it can be
animated) — it does NOT push to the undo stack.

### Geometry cache
`_GEO_CACHE` (LRU 16) in `backend/api/assembly.py`. Key = file path + mtime
(or inline design id) + sha256(cluster_transform_overrides). Used by both
`/instances/{id}/geometry` and `/assembly/geometry` to skip re-running
`_geometry_for_design` on undo/redo, tab switches, etc.

### `update_assembly_*` patch semantics changed
`update_assembly_animation` and `update_assembly_keyframe` switched from
`model_dump(exclude_none=True)` to `model_dump(include=body.model_fields_set)`.

**Why:** Old behavior dropped any explicit `null` value, so clients couldn't
clear `configuration_id`/`feature_log_index`/`camera_pose_id`. Now sending
`{configuration_id: null}` actually clears the field.

**How to apply:** When adding new optional patch fields to assembly endpoints,
prefer `include=body.model_fields_set` so explicit nulls round-trip. Setting
a field to `None` *not in the request body* still leaves it untouched.

## Frontend (`frontend/src/`)

### `api/client.js`
- `createAssemblyCameraPose / updateAssemblyCameraPose / deleteAssemblyCameraPose / reorderAssemblyCameraPoses`
- `createAssemblyConfiguration / restoreAssemblyConfiguration / updateAssemblyConfiguration / deleteAssemblyConfiguration`
- `patchInstanceClusterTransform(id, body)` — for in-assembly cluster manipulation.

### `ui/camera_panel.js`
Panel checks `assemblyActive && currentAssembly` and routes to the assembly camera pose API.
Subscribes to both `design` and `assembly` slices. Initial render and
`clearPartContext` both prefer assembly poses when active.

### `ui/feature_log_panel.js`
**Becomes the "Configuration Snapshot" panel in assembly mode.**
- `_isAssemblyConfigMode()` returns true when not in part mode and assembly is active.
- `_refreshTitle` swaps heading text to "Configuration Snapshot" and shows a
  "+ Capture Configuration" toolbar button; rail (notch timeline) is hidden.
- `_rebuildAssembly` lists each configuration with action buttons:
  - ▶ (`_goStyle`) → Animate (lerp transforms 650ms, then restore — see below).
  - ⟳ (`_updateStyle`) → Overwrite with current state.
  - ✎ → Rename.
  - × → Delete.
  - Click row body → instant restore (`_seekAssemblyConfig`).
- Cursor is tracked by `assembly.configuration_cursor` (not numeric like
  feature log).
- `initFeatureLogPanel(store, { api, onEditFeature, onAnimateConfiguration })`
  — new `onAnimateConfiguration` callback wired in `main.js`.

### `ui/animation_panel.js`
Keyframe state selector toggles content based on `_assemblyMode`:
- **Design mode:** populated from `feature_log` (F0/F1.../All features).
- **Assembly mode:** populated from `currentAssembly.configurations`.
- The dropdown's value writes either `feature_log_index` (design) or
  `configuration_id` (assembly).
- New keyframes seed both fields to `null`.

### `main.js`
- `_animateAssemblyConfiguration(cfg)` (around line 7883):
  1. Builds per-instance from→to matrix pairs (start = live transform from
     `assemblyRenderer.getLiveTransform(id)` fallback to instance transform;
     end = `cfg.instance_states[i].transform`).
  2. RAF loop with cubic ease (650 ms) calls
     `assemblyRenderer.setLiveTransform(id, mat)` and
     `assemblyJointRenderer.setLiveJointTransform(id, mat, assembly)`.
  3. After RAF completes, calls `api.restoreAssemblyConfiguration(cfg.id)` to
     persist the final state to the store.
- Wired to feature_log_panel via `onAnimateConfiguration` option.
- `_assemblyPendingPartJoints` map and `_commitAssemblyPending` flush both
  pending part-joint cluster transforms (`patchInstanceClusterTransform`) and
  pending FK transforms (`propagateFk`).

## Animation player — what's NOT wired (deferred)

`scene/animation_player.js` currently consumes only `kf.feature_log_index`,
`kf.camera_pose_id`, `kf.joint_values`. **It does NOT yet apply
`kf.configuration_id` during playback.** Storing configuration_id on a keyframe
shows correctly in the panel and round-trips through the API, but pressing
Play won't trigger configuration restoration.

For an assembly-mode animation, the player would need to:
- Pre-resolve each keyframe's `configuration_id` to its
  `AssemblyConfigurationSnapshot` (poses live on the assembly, not the design).
- During the transition window, lerp instance `transform` per
  `instance_states` (and joint `current_value`) — same shape as the manual
  `_animateAssemblyConfiguration` in `main.js`.
- Apply final state via `restoreAssemblyConfiguration(id)` at hold-start.

The standalone `_animateAssemblyConfiguration` exists as a working reference;
a future player path can borrow its structure.

## Other changes shipped in the same diff

- `assembly_renderer.js` exports many new helpers used by the cluster gizmo:
  `getLiveTransform`, `getInstanceDesign`, `captureInstanceClusterBase`,
  `applyInstanceClusterTransform`, `pickInstanceCluster`, `pickPartJoint`,
  `getConnectorClusterIds`, `getInstanceBackboneEntries`, `getLabelTable`.
- Helix label sprites are now built **in the assembly renderer**
  (`_buildInstanceLabelGroup`), per instance group, gated by
  `store.showHelixLabels`. Default flipped to `false` in `state/store.js`.
- `assembly_constraint_graph.js` adds `computeFixedDepths(assembly)` (BFS over
  rigid joints from each `inst.fixed === true` anchor; returns
  `Map<instId, depth>`) and `isGroupAnchored(assembly, instanceId)`.
- Crossover arc lines now carry `userData.arcConnections` so live cluster
  drags can update arc geometry in-place (`_updateInstanceCrossoverArcs`).
  Extra-base instance crossovers similarly: `_updateInstanceExtraBaseCrossovers`
  re-runs `arcControlPoint` + `updateExtraBaseInstances` with live nuc positions.
- `_sourceKey` includes `cluster_transform_overrides` so the renderer cache
  invalidates correctly when overrides change.
- Batch geometry path now uses per-instance fetch when fewer than 3
  instances need geometry (cheaper than `/assembly/geometry`).
