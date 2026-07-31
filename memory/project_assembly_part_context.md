---
name: Assembly part-context panels — status and deferred work
description: "Camera + animation panels re-target to the selected part instance via a patchFn; feature-log took a different route and its part-context code is unreachable. P2 — part-mode animation PLAYBACK is still unbuilt."
type: project
originSessionId: e02ef695-62a3-4cfa-b257-f610fa3635fb
---
# Assembly Part-Context Panels

**Rank:** P2 — authoring shipped without playback; one of the two deferred items landed under a
different name, the other needs a backend field that doesn't exist yet. Real but niche.

**Status (audited 2026-07-30 against live code).** Built 2026-04-23 on branch `assembly-overhaul`.
When a part instance is selected in assembly mode, the **camera** and **animation** panels
re-target to that instance's design-level data. Both are live and in daily use. The **feature-log**
panel was later solved a different way and its part-context code can no longer execute (below).

Sibling doc: **[[project_assembly_configurations]]** — the *assembly*-context tier (poses +
configurations on the `Assembly` itself), the third of the three panel contexts
(part > assembly > design). Read it alongside this one.
Not related: `project_path_to_thousands` is the render/scale refactor — no overlap.

## The mechanism (camera + animation)

`ui/assembly_panel.js` owns the fetch/cache cycle. It is push-based — **no panel subscribes to
`store.assembly.activeInstanceId` itself**; `assembly_panel.js:1705` is the only reader, and it
fans out through the `onPartContextChange` opt.

| Piece | Where | Notes |
|---|---|---|
| `_onPartInstanceChanged(instanceId, {force})` | `ui/assembly_panel.js:127` | one caller — `_rebuild` at `:1701-1706`, on `activeInstanceId` change |
| `_makePatchFn(instanceId)` | `ui/assembly_panel.js:106` | invalidate → deep-clone → optimistic notify → PATCH → refetch → notify. Called at `:147` |
| `beforePatchDesign` opt | `assembly_panel.js:41`, called `:109` | supplied `main.js:5322` → `assemblyRenderer.invalidateInstance(id)` |
| `onPartContextChange` opt | `assembly_panel.js:41`, fired `:114/121/132/137/148/150` | handler `main.js:5347-5358` |
| `setPartContext` / `clearPartContext` | camera `:348/:355` · animation `:1592/:1600` · feature-log `:1890/:1898` | **only 6 call sites, all in `main.js:5349-5356`** |
| Panel handles | `_partCameraPanel` `main.js:6357` · `_partFeatureLogPanel` `:6360` · `_partAnimPanel` `:6714` | |
| API client | `getInstanceDesign` `api/client.js:3560` · `patchInstanceDesign` `:3230` (now takes `{docId}`) · `patchInstance` `:3195` | |

**Camera** (`ui/camera_panel.js`): `_modifyPartDesign(patchFn)` at `:34`, called from capture/rename/
update-camera/delete/reorder (`:52/:170/:248/:300/:332`); store subscription guarded by
`if (_partInstanceId) return` (`:74`, `:81`). Complete.

**Animation** (`ui/animation_panel.js`): `_partMode/_partDesign/_partPatchFn` at `:136-138`, ~22
`_partPatchFn(...)` sites (`:211`…`:1252`) covering all keyframe/animation CRUD. `_makeKfRow` at
`:704` reads `_partDesign?.camera_poses` / `?.feature_log`. Authoring complete; **playback is not**
(open item 1).

**A fourth consumer was added since**: `clusterPanel.syncInstanceDesign(instanceId, design)`
(`main.js:5352`).

## Feature-log: the part-context path is DEAD CODE (found 2026-07-30)

`main.js:5351/5356` gate the feature-log calls on `!store.getState().assemblyActive` — but
`_onPartInstanceChanged` can only fire from `assembly_panel._rebuild`, which returns early unless
the panel is displayed (`assembly_panel.js:1719`), and the panel is only shown in assembly mode
(`main.js:5782`). The gate is therefore a contradiction. Belt-and-braces:
`feature_log_panel.js:1848-1851` nulls `_partInstanceId`/`_partPatchFn` whenever `assemblyActive`
goes true. So `feature_log_panel.js:474-475` (`_partPatchFn(d => d.feature_log_cursor = position)`),
`:907-908` (delete splice) and `:1085` are **unreachable**.

What replaced it, in-panel: an `assemblyTargetSelect` dropdown (`:361-385`) offering
`__assembly__` / `__configs__` / one entry per instance. Picking one calls
`_selectAssemblyPart(instanceId)` (`:397`), which sets `_assemblyPartInstanceId`; mode predicate
`_isAssemblyPartMode()` at `:187-190`. Seek goes to the real backend route (`:468-469`), delete to
`api.patchInstanceDesign(_assemblyPartInstanceId, …)` (`:897-900`). Strictly newer and better than
the `_partPatchFn` path it shadows.

## Backend

`PATCH /assembly/instances/{id}/design` → `backend/api/assembly.py:1265` (**not** `:836` — stale
anchor). It **stores content only**: `_replace_instance_design` (`:1240`) writes the workspace file,
snapshots, `set_assembly_silent`, `clear_geo_cache`. It does **not** replay `feature_log_cursor`
(`_part_geometry_signature` `:1614` hashes `cluster_transforms` + `deformations` + `loop_skips`
only, so a cursor-only patch also skips the auto-`resolve_assembly()` added later).

**Deferred item "verify feature-log seek on part instances" — SHIPPED**, under a different path
than proposed: `POST /assembly/instances/{id}/features/seek` →
`backend/api/assembly.py:1639`. It calls `crud_api._seek_feature_log` (`:1667`) →
`_replace_instance_design` (`:1669`) → conditional `resolve_assembly()` (`:1676-1679`) → computes
`nucleotides_compact` + `helix_axes` and warms `_GEO_CACHE` (`:1688-1697`). Client wrapper
`seekInstanceFeatures` (`api/client.js:3265`), consumed at `feature_log_panel.js:468-469`, wrapped
by `main.js:5167 _seekInstanceFeaturesFast`. Test: `tests/test_assembly_api.py:1183`.

## The two bug fixes from that session

**Bug 1 (gold connector spheres persist after mate) — fix superseded by a different mechanism.**
The doc's description is stale: `exitMateDefineMode` (`scene/assembly_joint_renderer.js:1890`) now
*keeps* `_connectorGroup.visible = true` (`:1916-1919`) and re-gates children per instance via
`_applyActiveVisibility()` (`:2567-2581`). In `setVisible` (`:2589`) the `on && _mateMode` gate is
on **`_bluntConnGroup`**, not `_connectorGroup`. Replaced during a later LOD/perf rework.

**Bug 2 (orange joint indicator during drag) — intact and expanded.**
`setLiveJointTransform(instanceId, newMatrix4, assembly)` at `assembly_joint_renderer.js:2512`
(delta math `:2516-2523`), now **9 callers**, all moved out of `main.js`:
`scene/assembly_transform.js:59/109/118/168/180`, `scene/group_gizmo.js:128/381`,
`scene/assembly_pointer.js:89`, `scene/kinematics_ticker.js:262/337`,
`scene/assembly_config_animator.js:109`. `_applyFKLive` → `applyFKLive`
(`scene/assembly_transform.js:96`); `main.js:4806` keeps an alias.

## Open items (live as of 2026-07-30)

1. **Part-mode animation playback is still unbuilt** — the panel authors part-mode animations
   fully, but `player.play(anim, playOpts)` has **two** branches only (`animation_panel.js:1322-1335`:
   `_assemblyMode` → joint patches, else design-level). `_partMode` is never consulted, so playing a
   part animation does not drive that instance's feature log. The 2026-04 proposal
   (`api.patchInstance(id, {feature_log_cursor, joint_states})`) **is not expressible today**:
   `PatchInstanceRequest` (`backend/api/assembly.py:392-401`) has `joint_states` but no
   `feature_log_cursor`. Likely shape now: a `partMode` branch that calls the shipped
   `seekInstanceFeatures` per keyframe.
2. **Delete the unreachable feature-log part-context code** — `setPartContext`/`clearPartContext`
   (`feature_log_panel.js:1890/1898`), `_partInstanceId`/`_partPatchFn` (`:63-64`) and the three
   branches at `:474-475`, `:907-908`, `:1085`, plus the two dead gates at `main.js:5351/5356`.
   Keep `_assemblyPartInstanceId` — that is the live path.
3. **Zero tests, front or back.** No hit for `setPartContext` / `clearPartContext` / `partContext`
   / `_partMode` in any `*.test.js` or `frontend/e2e/`. The `getInstanceDesign`/`patchInstanceDesign`
   tests that exist cover other subsystems (`assembly_refresh.test.js`, `assembly_instance_designs.test.js`,
   `file_io.test.js`). A pin on `_makePatchFn`'s read-modify-write order would be the cheapest one.
4. **Never manually exercised end-to-end** — the 2026-04 "test the full part-context UI" item was
   never checked off. Load an assembly whose part has camera poses + a feature log + an animation,
   select the instance, confirm all three panels re-target.
5. Consider moving part-context onto the newer `initInstanceDesignCache`
   (`ui/assembly_instance_designs.js:61`, used by both overhang panels via `main.js:5363-5373`) —
   that is the modern "panel needs the selected instance's design" pattern. It has no `patchFn`
   equivalent, so this is a design question, not a mechanical swap.
