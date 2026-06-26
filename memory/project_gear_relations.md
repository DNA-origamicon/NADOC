---
name: project-gear-relations
description: "Assembly gear relations + continuous-spin kinematics — couple two revolute joints by a ratio/invert, and integrate live RPM spin in a per-frame ticker. Display-layer only; never mutates Design topology. Shipped 2026-05-29."
metadata: 
  node_type: memory
  type: project
  originSessionId: 2a7e54f9-6dda-49f5-aef7-e1af5e04bb08
---

# Assembly Gear Relations + Kinematics (continuous spin)

**Shipped 2026-05-29.** Built on top of [[project-assembly-groups]] (the group-transform path is one of the three rotation paths gears must follow).

## What it does

Two related capabilities on the assembly layer:

1. **Gear relations** — couple two revolute joints so rotating one drives the other through a fixed ratio:

   ```
   sign = -1 if invert else +1
   θ_b = joint_b_anchor + sign · (θ_a − joint_a_anchor) · ratio
   ```

   `ratio = 1` → synchronized; `ratio = 2` → joint_a spins twice as fast as joint_b. Anchors snapshot each joint's `current_value` at creation time, so the relation is satisfied from the current pose without an immediate jump. Coupling is **bidirectional** — grabbing either side drives the other (inverse edge uses `1/ratio`).

2. **Continuous spin** — each revolute joint carries an `angular_velocity_rpm`; a per-frame ticker integrates `current_value += ω·dt` and rotates the joint's child rigid-body group live. Gear relations then propagate to driven joints each tick.

## Three-Layer Law

Both only mutate `AssemblyJoint.current_value` (via silent PATCH) and the derived `PartInstance.transform` (via the renderer's `setLiveTransform`). **They never write to any field of an embedded Design** — spinning gears never touch scaffolds, strands, helices, crossovers, or design-internal cluster joints. This is asserted in the `kinematics_ticker.js` header and is the core invariant to preserve.

## The three rotation paths (all must drive the gear)

A gear relation has to fire no matter how the user rotates the driver. `tests/test_gear_relations.py` is organized around exactly these three paths so a failure points at which one broke:

1. `PATCH /assembly/joints/{id}` — ring-drag / slider path.
2. `PATCH /assembly/instances/{id}` — instance gizmo path.
3. `POST /assembly/groups/{id}/transform` — group gizmo path.

Backend: paths 2 and 3 run `_sync_revolute_values_for_instances` to recover each affected joint's angle from the new transform, then `_propagate_gear_relations_from` walks both forward and inverse edges (first-wins on conflicts, clamps to joint limits, back-propagates a clamped value to the driver). Path 1 calls the propagator directly. If path 1 passes but 2/3 fail → the sync helper isn't running; if 1 fails too → the propagator is broken.

## Files

- **Model:** `GearRelation` + `Assembly.gear_relations: List[GearRelation]` + `AssemblyGearRelationConfigState` (config-snapshot state) in `backend/core/models.py`. Fields: `joint_a_id`/`joint_b_id`, optional `endpoint_{a,b}_instance_id` + `endpoint_{a,b}_side` (resolve which side of the revolute is the moving body — needed when the revolute was authored "backward", e.g. wheel=parent/axle=child), `ratio` (finite, nonzero), `invert`, `joint_{a,b}_anchor`. Joint config-state gained `angular_velocity_rpm` + `spin_paused`. New `SnapshotOpKind` literals `assembly-create-gear` / `assembly-delete-gear`.
- **Backend routes** (`backend/api/assembly.py`): `POST /assembly/gear-relations`, `PATCH /assembly/gear-relations/{id}`, `DELETE /assembly/gear-relations/{id}`, `POST /assembly/gear-relations/{id}/resolve` (force-drive joint_b to the implied value now). Helpers `_propagate_gear_relations_from`, `_sync_revolute_values_for_instances`.
- **Ticker (NEW):** `frontend/src/scene/kinematics_ticker.js` — `initKinematicsTicker({store, api, getAssemblyRenderer, getAssemblyJointRenderer})` returns `{tick, suspendJoints, resumeJoints, flushNow, dispose, debugState}`. Constants: `FLUSH_INTERVAL_SEC = 0.2` (~5 Hz persistence), `MAX_DT_SEC = 1/15` (caps a single step on background-tab return), `TWO_PI_OVER_60 = π/30` (rpm→rad/s). Snapshot model: captures each revolute joint's rigid-body group base transforms on assembly-ref change; between rebuilds applies `R(axis, current − vSnapshot)` to the base transforms (derive-from-snapshot, never accumulate). Cycle detection breaks gear-graph loops with a one-time console warn; first relation in `gear_relations` order wins when two target the same driven joint. `suspend/resumeJoints` freeze spin during animation playback without zeroing RPM.
- **Persistence:** ticker flushes `current_value` (and RPM/`spin_paused`) to the backend at ~5 Hz via silent PATCH so reloads and configuration snapshots stay within a tick of live state. Non-fatal on network error — spin continues client-side.
- **UI — create:** the **"Create Mate"** define-mode dialog (in `frontend/src/scene/assembly_joint_renderer.js`) has a `gear` mate type. Pick two movable revolute-mated parts (→ joint_a/joint_b + endpoints), set ratio + invert, **Create Mate** → `api.createGearRelation`.
- **UI — list/edit:** gear relations render as rows in the same scrollable **Mates** list in `frontend/src/ui/assembly_panel.js` (each side labeled by the moving body's group name or instance name); inline edit form (name, ratio, invert, manual anchor overrides) + delete. RPM input + "Pause spin" checkbox live in the joint edit form.
- **API client:** `frontend/src/api/client.js` — `createGearRelation`, `patchGearRelation`, `deleteGearRelation`, `resolveGearRelation`.
- **Live-drag gear coupling (main.js):** `_applyGearLiveForRevoluteDrag` / `_applyGearLiveJointValue` / `_gearEndpointSide` apply gear coupling visually during an in-progress ring/gizmo drag (before the commit PATCH). Console diagnostic: `window.nadocGearDebug()` prints the current gear-relation state + the ticker's gear graph.
- **Tests:** `tests/test_gear_relations.py` — 14 tests across 7 classes covering the three paths, bidirectional coupling, ratio/invert, limit clamp + back-push, three-joint chain propagation from the middle, endpoint-aware "backward" revolute topology, and a stale-`base_transform` safety case (gizmo path bails instead of writing NaN). `tests/test_assembly_api.py` added a `clear_limits`/clamp-on-PATCH joint test.

## Gotchas

- **Endpoint sides matter.** When a revolute is authored with the *fixed* body as the child (e.g. axle fixed, big wheel = parent), the gear must target the moving endpoint, not the joint's nominal `instance_b`. That's what `endpoint_{a,b}_side` / `endpoint_{a,b}_instance_id` are for — see the `TestGearParentMovedTopology` regression (Big_wheel_base.nass).
- **Driven joints ignore their own RPM.** A joint that is the driven side of a gear gets its value from the relation, not from its own `angular_velocity_rpm` — the integration step is skipped for it. Letting a driven joint's RPM stack on top of the gear value is a deferred follow-up.
- **Don't accumulate.** The ticker always recomputes transforms from the snapshot base, never by multiplying incremental rotations, to avoid float drift over long spins.

## Why

Continuous-spin gears turn the assembly editor from a static poser into a mechanism demonstrator — the user can build a gear train of DNA-origami parts and watch the ratio play out. It composes with grouping (a spinning sub-mechanism can be grouped and moved as one) and configurations (RPM + gear state snapshot into a pose).

Related: [[project-assembly-groups]] (group-transform is path 3), [[project-assembly-configurations]] (RPM + gear state in config snapshots), [[project-path-to-thousands]] (shared renderer the ticker drives via `setLiveTransform`).
