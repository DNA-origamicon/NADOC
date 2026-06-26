---
name: project-assembly-groups
description: "PowerPoint-style PartGroup feature in the assembly editor — bundle parts into a group that moves/copies/deletes as one entity, nestable, persists in .nass v2. Shipped 2026-05-28."
metadata: 
  node_type: memory
  type: project
  originSessionId: d9349017-5603-48d1-9f50-5301e6122c18
---

# Assembly PartGroups (PowerPoint-style grouping)

**Shipped 2026-05-28.** Plan: `~/.claude/plans/nadoc-must-specialize-in-fluttering-puddle.md`.

## What it does

Lets the user multi-select PartInstances in an assembly, right-click → **Group**, then operate on the bundle as a single entity:

- The parts-list panel collapses members under one group row with a caret toggle.
- Group row carries: eye (visibility overlay), duplicate, move (translate), name, ungroup, cascade-delete, representation overlay, expandable external-facing connector list.
- Groups may **nest** (a group can contain other groups). The partition invariant (a member belongs to at most one parent group) is enforced by the model validator.
- Duplicate clones every transitive member + internal joints + internal overhang bindings with fresh ids; *external* connections (members ↔ non-members) are dropped.
- Cascade-delete removes the group and all its transitive members + cross-bindings.
- Move applies a rigid translation; **rigidly-mated external partners follow** via the joint/binding transitive closure (rigid joints + duplex bindings only — revolute/prismatic/spherical/toehold stay put).
- Groups persist in `.nass` v2 (`Assembly.groups` field), survive save/load, and round-trip through the feature-log snapshots.

## Files

- **Model:** `PartGroup` class + `Assembly.groups: List[PartGroup]` + `@model_validator` in `backend/core/models.py:2201-2275`. Six new `SnapshotOpKind` literals (`assembly-create-group`, `-ungroup`, `-patch-group`, `-duplicate-group`, `-delete-group`, `-transform-group`).
- **Helpers (pure):** `backend/core/assembly_groups.py` — `transitive_rigidly_attached`, `clone_group_subtree`, `apply_group_translation`, `apply_group_transform`, `collect_group_member_ids`, `filter_groups_after_instance_removal`, `find_owning_group`.
- **Routes:** `backend/api/assembly.py` — 6 endpoints under `/assembly/groups[...]`. `delete_instance` also strips the deleted id from group membership so the validator doesn't trip on next load.
- **Tests:** `tests/test_assembly_groups.py` (24 tests covering invariants, all 6 routes, transitive closure, and `.nass` round-trip). All pass.
- **Frontend store:** `frontend/src/state/store.js` adds `multiSelectedInstanceIds`, `activeGroupId`, `groupDiveStack` to the `assembly` slice.
- **API client:** `frontend/src/api/client.js` — `createGroup`, `ungroup`, `patchGroup`, `duplicateGroup`, `deleteGroupCascade`, `transformGroup`.
- **Panel:** `frontend/src/ui/assembly_panel.js` — tree walker (`_renderGroupSubtree`, `_buildGroupRow`, `_buildGroupIndex`, `_externalConnectorsForGroup`); Ctrl-click on instance row toggles `multiSelectedInstanceIds`.
- **Context menu:** `frontend/src/ui/assembly_context_menu.js` — `onGroup` / `onUngroup` callbacks (wired in `main.js` ~8082).
- **3D multi-select (in `main.js`):** Ctrl/Meta-click on a part toggles it in `multiSelectedInstanceIds`; Ctrl/Meta-drag draws a dashed purple rectangle (`_createAssemblyLassoOverlay` / `_finalizeAssemblyLasso`) and on pointerup hit-tests every visible instance via `assemblyRenderer.getInstanceCenters()` projected to screen. **Strict containment**: all 8 corners of an instance's world-AABB must project inside the rect (and within [-1,1] z) to be selected — a part that's only partially inside is skipped. Shift-during-drag = additive (extends the current selection). When 2+ instances are selected, a purple `Box3Helper` is drawn around the union of their world-AABBs (`_updateAssemblyMultiBox`), updated on every multi-select or assembly change. Mode exit disposes the union box + cleans up any in-flight lasso + clears the multi-select.
- **Renderer overlay:** `frontend/src/scene/assembly_renderer.js` — `applyGroupVisibilityOverlay(hiddenInstanceIds)` + module-level `_groupHiddenInstanceIds` Set, AND-ed with each instance's own `visible` flag at both rebuild branches. `main.js:_runAssemblyRebuild` calls it after each rebuild (plus the transform-only fast path).

## Key design decisions

- **Persistence:** new `Assembly.groups` field; legacy v1 `.nass` files load with empty groups list (no migration prompt). v2 serializer round-trips via `model_dump()` — no extra special-casing.
- **3D click semantics (PowerPoint-style click-through, wired 2026-05-28):** click a grouped part → selects the GROUP (purple union BoxHelper + group gizmo at centroid); click again on a member of the active group → "enters" the group (`groupDiveStack` pushed) and selects the individual part. Click an ungrouped part or empty space → falls through to normal single-select.
- **Group gizmo:** the existing TransformControls is re-anchored to the union AABB centroid via `_attachGroupGizmoForGroup`. Live drag pushes a uniform world-space delta to every member via `assemblyRenderer.setLiveTransform`; commit POSTs the row-major 16-float delta matrix to `/assembly/groups/{id}/transform`, which extends the move via the rigid-mate transitive closure server-side. After commit, the store sub re-anchors the gizmo at the new centroid. The "↔" panel button is still there as a numeric-input fallback.
- **Motion-constraint gizmo (2026-05-28):** `_analyzeMotionConstraints(target)` walks the joint graph from the moving body to the "anchored network" (`inst.fixed=true` + rigid transitive closure) and returns the available DOF. The gizmo then exposes ONLY that motion: anchored → no gizmo + red "Anchored" chip; single revolute mate → 1-DOF rotation ring around the joint axis through its origin; single prismatic → 1-DOF translation arrow along the axis; spherical → 3-DOF rotation at the joint origin; over-constrained (2+ mates to anchored) → no gizmo + amber warning chip ("use joint sliders instead"). `instance_gizmo.applyConstraint({mode, axis, showX/Y/Z})` reuses the existing TransformControls — sets dummy quaternion via `setFromUnitVectors([0,0,1], jointAxis)` so the dragged ring/arrow lies on the joint axis. Both the single-instance path (`_attachGroupGizmo`) and group path (`_attachGroupGizmoForGroup`) dispatch through the analyzer; the resulting overlay chip at the top of the canvas tells the user what their selection's DOF is BEFORE they try to drag. Backend safety net: `transform_group` already runs `resolve_assembly()` after each move so any off-axis drift gets snapped back.
- **Visibility overlay:** group `visible=false` adds members to a renderer-side Set; per-instance `visible` is untouched. Toggling the overlay back restores each member to its prior visibility. **Shared-instancing path (default since 2026-05-20) doesn't implement the overlay yet** — opt into the per-instance path via `?shared=0` or `localStorage.NADOC_SHARED_RENDERER='false'` if you need group visibility to take visual effect.
- **External connectors on the group row:** computed from joints — an InterfacePoint is "external-facing" if no joint between *two members of the group* consumes it. Joints to outside parts (and unused IPs) all count as external.
- **Copy externals:** internal joints/bindings cloned with fresh ids; external joints/bindings dropped on the clone (predictable, matches typical CAD duplicate).

## Known gaps / follow-ups

- Escape key to pop `groupDiveStack` (back out of an "entered" group) is not yet wired — today, re-entering a group can be done by clicking empty space then clicking the part again.
- Shared-renderer group visibility: stub on the shared path; needs the per-source `visibility` Float32Array to mask group-hidden ids during `_updateLodForSource`.
- Group-level export representation overlay for photo mode (the per-assembly `export_representation` already exists; a per-group override would let users render some groups at hull-prism and others at full).
- Polymerize → auto-group: polymerize today creates independent instances; auto-grouping the resulting chain is a small win.

## Why: anchor for the wider scale-up goal

NADOC's value proposition is scaling complex multi-part assemblies. Grouping is the first piece — it gives the user a way to manage a 20-part arm as one selectable / movable / copyable unit instead of fighting 20 individual rows. Follow-ups in [[project-path-to-thousands]] (shared renderer LOD ladder) and the gizmo-on-group work above should compose with this to make hundreds-of-parts ergonomic.

Related: [[project-path-to-thousands]] (shared renderer + .nass v2 wire format), [[project-assembly-overhaul]] (parts-list panel + context menu lineage), [[project-polymerize-origami]] (auto-replication of mated chains — sibling feature for scale-up), [[project-gear-relations]] (gear/continuous-spin kinematics — the group-transform path is one of the three rotation paths gears follow).
