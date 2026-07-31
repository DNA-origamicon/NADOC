---
name: project-assembly-groups
description: "PowerPoint-style PartGroup feature in the assembly editor — bundle parts into a group that moves/copies/deletes as one entity, nestable, persists in .nass v2. Shipped 2026-05-28; small tail open (P2)."
metadata: 
  node_type: memory
  type: project
  originSessionId: d9349017-5603-48d1-9f50-5301e6122c18
---

# Assembly PartGroups (PowerPoint-style grouping)

**Status: SHIPPED and live-wired end-to-end** (2026-05-28). **Rank: P2** — the feature works; what
remains is a 3-item tail, one of which is a user-visible dead control (group representation).

**Audited against the codebase 2026-07-30.** The 2026-05 file list was stale in *every* row: the
backend routes were carved out of `assembly.py` into their own sub-router, and the 3D multi-select +
gizmo + group-walk logic was carved out of `main.js` into five `scene/` modules. Nothing was
superseded — this was **relocation, not replacement**. Table below is the probed truth.

## What it does

Multi-select PartInstances in an assembly, right-click → **Group**, then operate on the bundle as one
entity:

- Parts-list panel collapses members under one group row with a caret toggle.
- Group row carries: eye (visibility overlay), duplicate, move (translate), name, ungroup,
  cascade-delete, representation overlay *(stored but not rendered — see open item 1)*, expandable
  external-facing connector list.
- Groups **nest**; the partition invariant (a member belongs to at most one parent group) is enforced
  by the model validator.
- Duplicate clones every transitive member + internal joints + internal overhang bindings with fresh
  ids; *external* connections (members ↔ non-members) are dropped.
- Cascade-delete removes the group and all transitive members + cross-bindings.
- Move applies a rigid translation; **rigidly-mated external partners follow** via the joint/binding
  transitive closure (rigid joints + duplex bindings only — revolute/prismatic/spherical/toehold stay put).
- Persists in `.nass` v2 (`Assembly.groups`), survives save/load, round-trips through feature-log snapshots.

## Where the code is (probed 2026-07-30)

### Backend

| Thing | Location |
|---|---|
| `PartGroup` class | `backend/core/models.py:3060` (`representation` `:3081`, `expanded` `:3084`) |
| `Assembly.groups` | `models.py:3112` |
| Partition validator | `models.py:3259-3313` `_validate_groups` |
| 6 `SnapshotOpKind` literals | declared `models.py:1507-1512`; emitted `routes_assembly_groups.py:126,154,195,236,272,329` |
| **Routes (all 6)** | **`backend/api/routes_assembly_groups.py`** — registered `backend/api/main.py:40` + `:257` (`prefix="/api"`). *(There is no `backend/main.py`; the app is `backend/api/main.py`.)* |
| ↳ `POST /assembly/groups` | `:89` `create_group` |
| ↳ `DELETE /assembly/groups/{id}` | `:138` `ungroup` |
| ↳ `PATCH /assembly/groups/{id}` | `:172` `patch_group` |
| ↳ `POST /assembly/groups/{id}/duplicate` | `:207` `duplicate_group` |
| ↳ `DELETE /assembly/groups/{id}/cascade` | `:248` `cascade_delete_group` |
| ↳ `POST /assembly/groups/{id}/transform` | `:298` `transform_group` |
| Pure helpers | `backend/core/assembly_groups.py` — `collect_group_member_ids:43`, `collect_group_instance_ids:68`, `transitive_rigidly_attached:110`, `clone_group_subtree:146`, `apply_group_translation:236`, `apply_group_transform:269`, `filter_groups_after_instance_removal:295`, `filter_groups_after_group_removal:315` |
| `delete_instance` strips membership | `backend/api/assembly.py:2368` (def), strip at `:2376` via `filter_groups_after_instance_removal` |
| `transform_group` re-solves | `routes_assembly_groups.py:345` `resolve_assembly()` (guarded by `if mutated.joints:` `:344`) |
| Tests | `tests/test_assembly_groups.py` — 24 tests, **unmarked → fast suite** |

### Frontend

| Thing | Location |
|---|---|
| Store keys | `state/store.js:346` `multiSelectedInstanceIds`, `:354` `activeGroupId`, `:362` `groupDiveStack`; all three in the assembly-reset key set `:415` |
| API client (6, all called) | `api/client.js:3169` createGroup · `:3176` ungroup · `:3181` patchGroup · `:3192` duplicateGroup · `:3202` deleteGroupCascade · `:3209` transformGroup |
| Panel tree walker | `ui/assembly_panel.js` — `_buildGroupIndex:449`, `_externalConnectorsForGroup:464`, `_buildGroupRow:500`, `_renderGroupSubtree:733`. Ctrl-click row toggle `:309-315`; plain click clears `:319` |
| Context menu | `ui/assembly_context_menu.js:61-62` callbacks, items `:217-225`; **wired `main.js:5060`/`:5076`** (doc's old `~8082` is dead) |
| **Group-walk utils (was undocumented)** | **`scene/assembly_groups_util.js`** — `findOwningGroupId:7`, `collectGroupMemberInstanceIds:15`, `resolveGroupClickThrough:54`, `computeGroupHiddenInstanceIds:70`. The frontend mirror of `core/assembly_groups.py`. Imported by `main.js:39`, `assembly_transform.js:13`, `assembly_pointer.js:24`, `assembly_multi_box.js:24`, `group_gizmo.js:22` |
| **Lasso (extracted from main.js)** | **`scene/assembly_lasso.js`** — `instancesInRect:19`, `toggleInstanceSelection:52`, `initAssemblyLasso:69`; wired `main.js:6132`. Strict 8-corner containment intact (`:27`) |
| **Union box (extracted)** | **`scene/assembly_multi_box.js`** — `initAssemblyMultiBox:36`, `update():47`; wired `main.js:5781`, disposed `:5845` |
| **Gizmo (extracted)** | **`scene/group_gizmo.js`** — `attachGroupGizmo:240`, `_createGroupTransformContext:319`, `attachGroupGizmoForGroup:336`, `initGroupGizmo:74`, `revoluteCommitValue:43`; aliased `main.js:4896-4897`, called `main.js:5986,5993,6013,6029,6239` + `scene/translate_rotate_tool.js:92,177` |
| Motion-constraint analyzer | **`scene/assembly_transform.js:215`** `analyzeMotionConstraints` (exported `:325`, aliased `main.js:4819`) |
| `applyConstraint({mode,axis,showX/Y/Z})` | `scene/instance_gizmo.js:271` (exported `:310`); called from `group_gizmo.js:297,302,307,431,436,441` |
| Click-through pointer logic | `scene/assembly_pointer.js:439-463` (`resolveGroupClickThrough`) |
| Visibility overlay — per-instance | `scene/assembly_renderer.js:1020` `applyGroupVisibilityOverlay`, module Set `:392`, read `:1089,1096,1202` |
| Visibility overlay — **shared path** | `scene/assembly_renderer_shared.js:3810` (exported `:3870`) — **real implementation, not a stub**; explicitly excluded from `_SHARED_RENDERER_STUB_DEFAULTS` `:80`. Called `main.js:5767` (in `_runAssemblyRebuild:5753`) + `:5934` (store sub) |
| `setLiveTransform` | both renderers; callers `main.js:5119,5915,5963`, `kinematics_ticker.js:261,336`, `assembly_config_animator.js:108`, `assembly_transform.js:58,108` |
| Tests (all previously undocumented) | `assembly_groups_util.test.js` (18 `it()` — hidden-set recursion, parent-drives-child, dive-stack **push** state machine), `group_gizmo.test.js:268/:279` (free group POSTs rigid delta; revolute group patches the joint instead), plus `assembly_multi_box.test.js`, `assembly_lasso.test.js`, `assembly_pointer.test.js`, `assembly_transform.test.js` |

### Coupling the original doc missed

- **Gears/kinematics ride the group transform.** `transform_group` also runs
  `_sync_revolute_values_for_instances`, `_sync_revolute_values_for_parent_moves`, and
  `_propagate_gear_relations_from` (`routes_assembly_groups.py:352-370`), and
  `backend/core/assembly_kinematics.py:121` documents a dependency on `apply_group_transform`
  clearing `base_transform`. `tests/test_gear_relations.py` references `PartGroup`. Touching the
  group transform path can move gears — see [[project-gear-relations]].
- `main.js:5231` passes `attachGroupGizmo` into the translate/rotate tool.

## Key design decisions (unchanged, still true)

- **Persistence:** legacy v1 `.nass` loads with an empty groups list (no migration prompt); v2 serializer
  round-trips via `model_dump()`.
- **3D click semantics (PowerPoint click-through):** click a grouped part → selects the GROUP (purple
  union BoxHelper + gizmo at centroid); click again on a member of the *active* group → "enters" it
  (`groupDiveStack` pushed) and selects the individual part; click an ungrouped part or empty space →
  normal single-select.
- **Group gizmo:** TransformControls re-anchored to the union-AABB centroid. Live drag pushes a uniform
  world-space delta to every member via `setLiveTransform`; commit POSTs the row-major 16-float delta to
  `/assembly/groups/{id}/transform`, which extends the move via the server-side rigid-mate closure. The
  "↔" panel button remains as a numeric fallback.
- **Motion-constraint gizmo:** `analyzeMotionConstraints(target)` walks the joint graph from the moving
  body to the anchored network (`inst.fixed=true` + rigid closure) and exposes ONLY the available DOF —
  anchored → no gizmo + red chip; single revolute → 1-DOF ring on the joint axis; single prismatic →
  1-DOF arrow; spherical → 3-DOF rotation at the joint origin; over-constrained → no gizmo + amber chip.
  Both the single-instance and group paths dispatch through it. Backend safety net: `transform_group`
  re-runs `resolve_assembly()`, snapping off-axis drift back.
- **Visibility overlay:** group `visible=false` adds members to a renderer-side Set; per-instance
  `visible` is untouched, so toggling back restores prior visibility.
- **External connectors on the group row:** an InterfacePoint is "external-facing" if no joint between
  *two members* consumes it. Joints to outside parts and unused IPs both count as external.
- **Copy externals:** internal joints/bindings cloned with fresh ids; external ones dropped on the clone.

## Open items (live, probed 2026-07-30)

1. **Group representation overlay is a dead control — user-visible.** `PartGroup.representation`
   exists (`models.py:3081`), is patchable (`routes_assembly_groups.py:164-185`), and has UI
   (`assembly_panel.js:680-682`) — but **no renderer ever reads it.** Both renderers resolve
   representation from the instance only (`assembly_renderer.js:1072,1179,1224` `inst.representation ??
   'full'`; `assembly_renderer_shared.js:1191,1297`). Setting it does nothing. Either wire it (group
   overlay AND-ed with instance rep, mirroring how the *visibility* overlay already works) or remove
   the control. Related: per-assembly `export_representation` exists (`models.py:3133`, route
   `assembly.py:980-992`) but its photo-mode consumers now live in `frontend/archive/photo_mode_v1/`.
2. **Escape to pop `groupDiveStack` still not wired.** The only global Escape chain
   (`ui/keyboard_shortcuts.js:665-712`) never touches assembly-group state — it doesn't even read
   `assemblyActive`. The source still carries the admission: `scene/assembly_pointer.js:439`
   `// The dive stack lets Escape (future) pop one level back to the group.` Today the stack is
   **push-or-nuke only** — every writer either pushes (`assembly_groups_util.js:65`) or clears to `[]`
   (`assembly_groups_util.js:60`, `assembly_pointer.js:463`, `assembly_panel.js:528`, `main.js:5850`);
   nothing removes a single level. `assembly_groups_util.test.js:112-123` pins the push side; a pop
   would need a test and a new writer.
3. **Polymerize → auto-group.** `backend/api/routes_assembly_polymerize.py`
   (`polymerize_assembly:85`, `polymerize_periodic_assembly:206`) contains zero `group` references, and
   the replay hooks (`assembly.py:1914-1974`) never construct a `PartGroup`. Auto-grouping the
   generated chain is still a small win. See [[project-polymerize-origami]].
4. *(Cleanup)* `find_owning_group` (`core/assembly_groups.py:74`) has **zero callers anywhere** —
   the frontend `findOwningGroupId` does this job client-side. Dead on arrival.

**Closed since the plan was written:** shared-renderer group visibility (was listed as a stub needing
`?shared=0`). It is implemented — `srcEntry.visibility` is a real `Float32Array`
(`assembly_renderer_shared.js:1275,1291-1292,1319`), `_updateLodForSource` reads it (`:2372`, hidden
rows demoted to `+Infinity`), and the GLSL discards `v_visible < 0.5` (`:367,671,1751,2077`). Shared is
the **default** path; `?shared=0` / `localStorage.NADOC_SHARED_RENDERER` (`main.js:297-301`) remain as
opt-outs only.

## Why: anchor for the wider scale-up goal

NADOC's value proposition is scaling complex multi-part assemblies. Grouping gives the user a way to
manage a 20-part arm as one selectable/movable/copyable unit instead of fighting 20 rows.

Related: [[project-path-to-thousands]] (shared renderer + `.nass` v2 wire format — it *implemented*
this plan's visibility overlay rather than superseding it) · [[project-assembly-overhaul]] (parts-list
panel + context-menu lineage) · [[project-polymerize-origami]] (sibling scale-up feature, open item 3)
· [[project-gear-relations]] (the group-transform path is one of three rotation paths gears follow) ·
[[project-assembly-configurations]] (sibling tier — configs do **not** snapshot groups).
