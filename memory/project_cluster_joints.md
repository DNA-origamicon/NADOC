---
name: Cluster Joint System — current state and known issues
description: ClusterJoint revolute axis feature: what's built, hull prism rendering fixed (2026-04-24), hull tracking rebake (2026-05-05), rotation tool bugs outstanding
type: project
originSessionId: 96a8235a-e27a-4ded-baaf-0d9bf2a43d2f
---

## Feature-log delete clears joint indicators (2026-05-14)

`delete_feature` in `backend/api/crud.py` now inverts joint deltas when a `routing-cluster` log entry is deleted: it decodes the entry's `pre_state_gz_b64` / `post_state_gz_b64`, computes joints created/deleted/updated by that cluster, and applies the inverse to `temp.cluster_joints` before `_seek_feature_log` runs. Without this, joint icons stayed in the 3D view because `_seek_feature_log` doesn't rebuild `cluster_joints` from log entries (joints mutate only via routing-cluster minor ops, and `_topology_substitute` deliberately does not include `cluster_joints`). Evicted routing-clusters (no pre/post payload) can't recover the delta and joints persist — manual joint-delete is the workaround. Tests: `test_delete_routing_cluster_removes_joints_it_placed`, `test_delete_routing_cluster_preserves_unrelated_joints` in `tests/test_joints.py`.

## Hull tracking after cluster commits (2026-05-05)

Previously: Plan B's commit/edit/undo paths kept `currentHelixAxes` stale, so `jointRenderer.rebuildHulls()` (when triggered) placed the hull at the pre-move position. Fixed via new helper `_rebakeHelixAxesForClusterDelta(helixIds, oldCt, newCt)` in `main.js` — applies the OLD→NEW cluster transform delta to `ax.start`, `ax.end`, `ax.samples`, `ax.segments[*]`, and `ax.ovhgAxes[*]` IN PLACE (preserves outer object reference so subscribers don't fire spuriously). Wired into:
- `_confirmTranslateRotateTool` standard commit (snapshots oldCt before commit)
- `_confirmTranslateRotateTool` cluster_op edit branch
- `_applyClusterUndoRedoDeltas` (undo / redo / seek)

Sub-cluster (`domain_ids`) moves skip the rebake because the helix isn't rigidly transformed — only some domains move. The live-drag callback in `clusterGizmo` already skips `jointRenderer.applyClusterTransform` for sub-cluster moves, so this is consistent.

**Don't break:** `_rebakeHelixAxesForClusterDelta` MUST mutate in place. The hull-rebuild subscriber gates on `n.currentHelixAxes !== p.currentHelixAxes`; the explicit `jointRenderer.rebuildHulls()` call in the same code paths is what triggers the rebuild. Replacing the mutation with clone-and-replace will cascade rebuilds across unrelated subscribers.

## Multi-cluster group move/rotate (2026-07-10)

Selecting >1 movable cluster (Ctrl/Shift-click → `store.multiSelectedClusterIds`) then
opening Move/Rotate (`t` / Tools menu — NOT a pre-targeted Rotate button) drives them all
as **one rigid body**. `_activateTranslateRotateTool` (translate_rotate_tool.js) detects
`multiSelectedClusterIds.length > 1` (and only when `targetClusterId` is null) and calls
the new `clusterGizmo.attachGroup(ids, …)` instead of `attach(one, …)`.

**Additive selection keeps the gizmo alive and re-centers it (2026-07-10 follow-up).**
Click cluster 1 → single gizmo; Ctrl+click / lasso cluster 2 → the gizmo STAYS and
re-centers on the combined centroid. Two pieces make this work:
- `_promoteSelectionToMulti` (selection_manager.js) now nulls `selectedObject` AND seeds
  `multiSelectedClusterIds` in ONE `setState`. Previously the null landed first (empty
  pool), and the tool bridge read it as a deselection and closed the gizmo.
- `decideSelectionAction` returns `none` (not `close`) on a bare deselection when
  `multiSelectedCount >= 1`, and a new `handleMultiClusterSelectionChange` subscriber
  (wired in main.js next to `handleSelectionChange`) follows `multiSelectedClusterIds`
  while the tool is active: >=2 → `_showClusterGroup`, exactly 1 → `_showClusterSingle`
  (only when leaving a group), 0 → left to the selectedObject bridge. `_showClusterGroup`/
  `_showClusterSingle` are shared by activation and the subscriber. In-progress moves
  survive re-attach because `attachGroup` reads `_withPendingTransform` for the baseline.

How it works (cluster_gizmo.js):
- One dummy at the **combined centroid** G = mean of each member's visual centroid
  (`pivot + translation`; rotation about the pivot leaves the centroid fixed). Dummy starts
  at identity rotation, so the panel's number boxes read the GROUP delta (0 at open).
- Live paint: the same `(startDummyPos, dummyPos, incrQuat)` rigid delta is fed to
  `onLiveTransform` once **per member** (each with its own `helix_ids`/`domain_ids`), so
  mixed full/sub-domain clusters both paint correctly. captureBase appends across members.
- Commit: `_recordGroupTransforms` composes the group delta onto each member's **attach-time
  baseline** and queues an absolute per-member transform. The standard confirm path already
  loops `commitPendingTransforms` → per-cluster `commitClusterPositions` + axis rebake, so no
  group-specific commit path was needed. `_pendingTransforms` was already a Map.
- Pure, unit-tested math: `combinedGroupCentroid(members)` and
  `composeGroupMemberTransform(baseline, G, dummyQuat, dummyPos)` → for baseline (P,T0,Q0):
  `R' = Rd·Q0`, `T' = Rd·(P + T0 − G) + dummyPos − P`, pivot kept at P (backend form
  `R·(p−P)+P+T`). Tests in cluster_gizmo.test.js verify every member reproduces the shared
  rigid delta, and identity delta is a no-op.
- Group mode is **free translate/rotate only**: joints / ssDNA constraints disabled
  (`getActiveJoint`/`isJointConstraintActive` return null/false when `_isGroup()`), pivot +
  cluster dropdowns disabled. Two main.js subscribers (activeClusterId panel-repopulate,
  strand-click retarget) early-out on `clusterGizmo.isGroupActive()` so they don't clobber
  the group panel or break the group by retargeting to one member.

NOT verified in the running app yet (frontend suite green: 2553 tests). Needs a real
multi-cluster design (e.g. `workspace/2x4_Hinge_autoscaff_test1.nadoc`, 2 clusters) to
confirm the live drag + commit visually.

## What's been built (2026-04-03)

Full ClusterJoint system across backend + frontend — revolute joint axes defined by clicking a face on a surface approximation of the cluster.

### Backend (complete, 18 tests passing)
- `ClusterJoint` model in `backend/core/models.py` — `id`, `cluster_id`, `name`, `joint_type`, `local_axis_origin`, `local_axis_direction`, `surface_detail`. **Storage refactor 2026-05-04:** axis is now stored once in the cluster's LOCAL frame; world-space is derived lazily on every API response by `crud._inject_joint_world_axes` (injects `axis_origin` / `axis_direction` for frontend compat). This is drift-free under repeated cluster transforms — there is no longer any "rebase" math at PATCH time. Legacy world-space joints loaded from `.nadoc` files are auto-migrated by `Design._migrate_world_space_joints` model_validator(mode='before') using `_world_to_local_joint`. Helpers: `_world_to_local_joint`, `_local_to_world_joint` in `backend/core/models.py`.
- `Design.cluster_joints: List[ClusterJoint]` with `to_dict` / `from_dict` round-trip
- POST/PATCH/DELETE routes in `backend/api/routes_cluster_joints.py` (extracted from crud.py in Refactor #29, 2026-06-16; the pure builders `_build_add_joint` / `_build_update_joint` / `_build_delete_joint` + the `AddJointBody`/`PatchJointBody` models moved with them) — undo-stack integrated AND logged in `feature_log` as MinorOpSubtypes `joint-place` / `joint-update` / `joint-delete` under a Fine Routing cluster. Endpoints route through `design_state.mutate_with_minor_log`; the replay dispatcher `_replay_minor_op` **stays in crud.py** and imports the three builders **function-locally** from `routes_cluster_joints` (top-level would be circular — that module imports `_design_response` back from crud.py). `joint_id` is generated at the endpoint and stored in params so mid-cluster slider seek replays produce a deterministic joint id. The endpoint converts the user's world-space click to the cluster's local frame BEFORE calling `mutate_with_minor_log` so the params dict is invariant under any intervening cluster transforms during seek replay.
- API client helpers in `frontend/src/api/client.js`

### Frontend scene files
- **`frontend/src/scene/joint_renderer.js`** — the main file for this feature:

  #### Surface geometry (define mode)
  - `_bundleGeometry()` — fits a prism to cluster helix axes; lattice-aware exterior panels when `latticeType` passed
  - `_computeExteriorPanels()` — UV inter-helix refAngle derivation, canonical bins, boundary-layer filtering, ±1.5nm panel half-width
  - `_convexHull2D` / `_expandHullCorners` — convex hull of helix UV positions for cap corners (avoids spike artefacts)
  - `_buildPanelSurface` — rectangular panel faces + convex-hull caps
  - `_buildPrismGeometry` — regular N-gon fallback prism
  - Three independent surface meshes shown in define mode:
    - `_surfaceMesh` — exterior lattice panels (blue `0x4488ff`), default **off**
    - `_surfaceMesh2` — regular polygon (orange `0xff8844`), default **off**
    - `_hullMesh` / `_hullWire` — convex hull prism (green `0x44ff88`), default **on**
  - `_hitMesh` removed; `_hullMesh` is always in scene as gap-fill fallback
  - `_surfaceGrid` — periodic bp grid rings (always built, always visible; matches hull shape)
  - `_surfaceHover` — per-bp hover rings (vertex-coloured, fading on pointermove)

  #### Raycast priority in define mode
  When hull surface on → only `_hullMesh` is hit-tested (exclusive).
  When hull off → exterior panels / polygon first, then `_hullMesh` as gap fallback.

  #### Joint indicators (persistent, always visible)
  - Ghost preview arrow + checkerboard sprite on hover
  - Placed joint: white shaft + cone + checkerboard sprite + white rotation ring
  - All arrow/ring parts: `renderOrder 9999`, `depthTest: false`, `transparent: true` — renders over everything
  - White rotation ring: 1 nm above surface along axis (`position.y = -PREV_HALF_LEN + 1`)
  - `pickJoint(e)` — shaft/cone pick; `pickJointRing(e)` — ring-only pick

  #### Repr mode
  - `_hullReprMeshes: Map<clusterId, THREE.Group>` — persistent hull repr (one group per cluster)
  - Each group: `MeshPhongMaterial` (shininess 60, specular #88ccff, polygonOffset) + `EdgesGeometry` black lines
  - `setHullRepr(on)` — builds/clears all cluster hull meshes; called by `main.js` repr system
  - `rebuild(design)` and `dispose()` both clean up `_hullReprMeshes`

  #### Cluster panel toggles (in define mode joint section)
  - Hull surface ✅ (default on, green accent)
  - Exterior panels ☐ (default off, blue accent)
  - Regular polygon ☐ (default off, orange accent)
  - Solid fill ✅
  - Debug overlay ☐ — live overlay showing source, normal, azimuth, matched panel data

  #### Public API
  `enterDefineMode`, `exitDefineMode`, `setExteriorPanels`, `setHullSurface`, `setRegularPolygon`,
  `setShowFill`, `setDebugOverlay`, `setHullRepr`, `rebuild`, `highlightJoint`, `clearHighlight`,
  `pickJoint`, `pickJointRing`, `captureClusterBase`, `applyClusterTransform`,
  `setVisible`, `isVisible`, `dispose`, `getPanels`

- **`frontend/src/scene/cluster_gizmo.js`** additions:
  - `setConstraint(type, joint)` — switches mode to rotate when joint selected
  - `_showLine` / `_hideLine` — axis-translation drag handle
  - `beginConstrainedRotation(joint, e)` — starts ring drag from pointerdown on indicator ring
  - Orange rotation ring: `renderOrder 9999`, `transparent: true`, 1 nm above surface
    (`_ringMesh.position.copy(_axisOrigin).addScaledVector(_axisDir, 1)`)

- **`frontend/src/ui/cluster_panel.js`** additions:
  - Pivot dropdown, `setPivotOptions`, `setSelectedPivot`
  - Joint section surface toggles (hull, exterior panels, regular polygon, solid fill, debug overlay)

### main.js wiring
- `_onToolPickPointerDown`: checks `pickJointRing` first; calls `beginConstrainedRotation` if hit
- `_onToolCanvasClick`: checks `pickJoint`; updates dropdown + constraint
- Hull Prism added to `_ALL_REPRS` as `repr: 'hull-prism'` / `id: 'menu-view-hull-prism'`
- `_setRepresentation('hull-prism')` → `_setCGVisible(false)` + `jointRenderer.setHullRepr(true)`
- All other reprs call `jointRenderer.setHullRepr(false)` on activation

### index.html
- `<button id="menu-view-hull-prism">Hull Prism</button>` added to Representation submenu

---

## Hull prism rendering fixes (2026-04-24, kinematics-cleanup branch)

Four bugs caused hulls to overlap / occlude geometry:

### Root cause: connector rows inflated the hull cross-section
`_computeExteriorPanels` used ALL `cluster.helix_ids`, including ssDNA connector helices (no dsDNA backbone) and overhang-only rows. For Nanosynth_Final, bottom/top rows had zero dsDNA positions, so their UV projections expanded the panel layout beyond the actual rigid body.

**Fix**: `_bundleGeometry` now tracks `dsHelixIds` — the set of helix IDs that contributed ≥1 dsDNA backbone point (both FORWARD and REVERSE strands present, no overhang). Only these are passed to `_computeExteriorPanels`:
```js
const panelHelixIds = dsHelixIds.size >= 3 ? [...dsHelixIds] : cluster.helix_ids
```
Result: Nanosynth_Final cluster 1 Y range changed from −1.12–7.88 to 0.75–6.00 (gap, not overlap, between clusters).

### Material: transparent depth occlusion
`_hullMeshPhong` used `side: THREE.FrontSide` with default `depthWrite: true`, causing translucent hulls to write to the depth buffer and occlude geometry behind them.

**Fix**: `side: THREE.DoubleSide, depthWrite: false` on `MeshPhongMaterial`. Edge line materials also set `depthWrite: false`.

### Short-helix axis-endpoint fallback
When backbone positions are unavailable, the fallback used all `cluster.helix_ids` axis endpoints — including very short connector helices (<2 nm) that skew the centroid.

**Fix**: Fallback filters helices with `lengthSq < 4.0` (i.e. <2 nm). Uses long axes if any exist; falls back to all axes only if none pass.

### currentGeometry not passed to _bundleGeometry
`_buildHullForCluster` was called with `null` for `backbonePositions`, so the backbone-point path was never used.

**Fix**: `_buildHullForCluster` now reads `store.getState().currentGeometry` and passes it.

---

## Known issues — MUST REVIEW NEXT SESSION

**Why:** rotation tools were left with bugs at session end. User confirmed "there are still many bugs."

### Priority items to investigate:
1. **Ring drag doesn't feel right** — `beginConstrainedRotation` bypasses the proximity check; may start drag even when click was far from the ring. Gizmo ring radius (bounding sphere) may differ from indicator ring radius visually.

2. **Default mode on joint select** — `setConstraint('joint', ...)` switches translate→rotate, but if already in rotate it stays. Selecting centroid does NOT reset the line handle.

3. **Line handle (axis translation)** — not yet tested in practice. The `_closestTOnAxis` formula may have bugs; `_linePerpTrans` accumulation from pivot may drift.

4. **`beginConstrainedRotation` when cluster not yet active** — if no pivot set, `_dummy = null` guard fires but cluster panel pivot dropdown won't be populated.

5. **Two overlapping rings** — indicator ring (small, ~1.18 nm) + gizmo ring (large, bounding sphere) both visible in rotate mode. May look cluttered.

6. **`exitDefineMode` cleanup in `_resetForNewDesign`** — confirm listener cleanup path is reached when File > New fires before tool deactivation.

7. **Hover ring fade performance** — `_updateHoverGrid` iterates all bp rings on every `pointermove`. Not yet profiled for long clusters.
