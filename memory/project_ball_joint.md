---
name: ball-joint
description: "Phase 2 of bond-relax extension — adds spherical/ball cluster joints so a forced scaffold ligation between two geometry clusters can be relaxed with 3 rotational DOF anchored on the non-moving side's bead. Scoped only; no code yet (2026-05-14)."
metadata: 
  node_type: memory
  type: project
  originSessionId: 852ab7cb-bc56-400c-abb9-990a338d2ad7
---

Companion to [[bond-relax-framework]]. Phase 1 (dual-cluster pair picker — same-cluster guard no longer hides Relax bond items for forced scaffold ligations) shipped 2026-05-14. Phase 2 is the auto-suggest-joint UX the user asked for in the same session, deferred for design.

## Goal

When the Relax bond submenu opens on a forced scaffold ligation (or other 0-DOF bond between two geometry clusters), let the user one-click create a **ball joint** that anchors at the bond's non-moving-side backbone bead. After creation, bond-relax re-evaluates: it now sees a spherical joint on either GC1 or GC3 (the user picked) and runs a 3-DOF rotation optimisation instead of the rigid translate.

This subsumes the geometric question "what axis should the joint use?" by removing the question — a ball joint has no preferred axis.

## User-facing flow (target)

Right-click the stretched arc → crossover menu:
```
Add extra bases…
─────────────
Relax bond — move Geometry Cluster 1
Relax bond — move Geometry Cluster 3
Add ball joint on Geometry Cluster 1   ← new
Add ball joint on Geometry Cluster 3   ← new
```

Picking "Add ball joint on GC1" creates a `ClusterJoint(joint_type='spherical', cluster_id='GC1', …)` with origin at GC3's anchor bead position (expressed in GC1's local frame). Picking "GC3" mirrors. Either way, the joint sits AT the non-moving side's bead so the rotating cluster pivots around the fixed anchor.

Then the relax items refresh and `jointsBetween.length === 1` → "Relax bond (3 DOF)" appears.

## Required changes

### 1. Model ([backend/core/models.py](backend/core/models.py))

`ClusterJoint.joint_type` is currently `Literal['revolute']` (line 705). Widen to:

```python
joint_type: Literal['revolute', 'spherical'] = 'revolute'
```

`local_axis_direction` becomes meaningless for spherical joints. Two options:
- **(A)** Keep the field; spherical joints ignore it. Validator just sets it to `[0, 1, 0]` for spherical. Simple but slightly ugly.
- **(B)** Make `local_axis_direction` Optional, document the meaning per `joint_type`. Cleaner schema but pydantic validator + downstream call sites need defensive None-handling.

**Recommend (A).** The field stays a 3-vector; spherical relax ignores it. Matches existing surface_detail / min_angle_deg / max_angle_deg pattern (revolute-only fields that spherical simply doesn't consult).

`min_angle_deg` / `max_angle_deg` are revolute-only. For spherical, add (optional) per-axis caps later if needed; defer until a real use case emerges.

### 2. Joint creation endpoint ([crud.py:11678](backend/api/crud.py#L11678))

`AddJointBody` needs a `joint_type` discriminator (default `'revolute'` for backwards compat). When `joint_type='spherical'`:
- Skip the world→local axis-direction conversion (still convert axis_origin).
- Store `local_axis_direction=[0,1,0]` (sentinel; not read).
- `surface_detail` still useful for the sphere mesh resolution.

Add a sibling endpoint OR extend the existing one. **Recommend** extending the existing endpoint — joints are conceptually a single resource with a `joint_type` discriminator. The frontend can pass `joint_type: 'spherical'` and skip the axis-direction probe.

### 3. Bond-relax solver ([backend/core/bond_relax.py](backend/core/bond_relax.py))

Current dispatch:
- **0-DOF**: no joints between clusters → rigid translate.
- **1-DOF**: exactly one joint → `_optimize_angle` brent search on θ.
- **N-DOF**: multiple joints → Powell over [θ_1, …, θ_n] + θ² regulariser.

Spherical joints contribute **3 DOF** each. New cases:
- 1 spherical joint, no others: 3-DOF Powell on (rx, ry, rz). Axis-angle parameterisation; magnitude ≤ π. θ² regulariser → `‖r‖²`.
- 1 spherical + N revolute: (3 + N)-DOF Powell.
- 2+ spherical joints: rare but possible; sum the DOF.

Add a per-joint DOF helper:
```python
def _joint_dof(joint: ClusterJoint) -> int:
    return 3 if joint.joint_type == 'spherical' else 1
```

Refactor `_relax_n_joints` so the parameter vector is the concatenation of `_joint_dof(j)` slots per joint, and per-joint rotation builder picks `axis_angle_to_rotvec` for spherical vs `_rot_axis_angle(θ, axis)` for revolute.

The 1-DOF fast path (`_relax_one_joint` → `_optimize_angle`) doesn't apply to spherical. Route the single-spherical case into the N-DOF Powell path directly.

The relax info dict needs new fields for the spherical case: report final `[rx, ry, rz]` magnitudes (or the equivalent quaternion).

### 4. Local→world joint math ([models.py: _local_to_world_joint](backend/core/models.py))

`_local_to_world_joint` returns `(world_origin, world_direction)`. For spherical, world_direction is undefined / unused — callers should branch on `joint_type` before consuming `world_direction`. Audit call sites:

```bash
grep -rn "_local_to_world_joint\|local_to_world_joint" --include="*.py"
```

Likely call sites in joint rendering, joint editor panel, bond-relax. Each needs a `if joint.joint_type == 'spherical': skip-direction` branch.

### 5. Frontend rendering

The prism-mesh joint visual is built from `local_axis_origin` + `local_axis_direction` + `surface_detail`. For spherical:
- Replace with a sphere mesh (or a translucent ball) at `local_axis_origin`.
- Suggested radius: ~0.5 nm (≈ a backbone bead). Configurable via `surface_detail`-like field later.
- Suggested color: same as revolute joints (consistent palette) with maybe a different shape cue (sphere vs prism is already distinct).

Search for joint rendering:
```bash
grep -rln "joint.*mesh\|jointMesh\|JointRenderer\|drawJoint" frontend/src
```

### 6. Joint editor panel

Currently shows axis-origin XYZ, axis-direction XYZ, surface-detail slider, min/max angle. For spherical:
- Hide axis-direction row.
- Hide min/max angle rows (or repurpose as per-axis caps later).
- Keep axis-origin XYZ.

The panel lives in `frontend/src/panels/` somewhere — find the joint panel and gate fields on `joint.joint_type`.

### 7. Frontend menu (the actual auto-suggest UX)

In `selection_manager.js`'s `_showCrossoverMenu` ([line 1247+](frontend/src/scene/selection_manager.js#L1247)), append two new menu items after the relax items (only when 0-DOF case applies, i.e. `jointsBetween.length === 0`):

```js
const beadA_world = /* fetch anchor_a world position via geometry */;
const beadB_world = /* fetch anchor_b world position via geometry */;
menu.appendChild(_menuItem(`Add ball joint on ${clusterA.name}`, async () => {
  // joint sits at the NON-moving side's bead, i.e. anchor_b in world space
  await api.createJoint(clusterA.id, {
    joint_type: 'spherical',
    axis_origin: beadB_world,
    axis_direction: [0, 1, 0],  // sentinel; not used
    name: `Ball joint @ ${bondLabel}`,
  });
}));
menu.appendChild(_menuItem(`Add ball joint on ${clusterB.name}`, async () => {
  await api.createJoint(clusterB.id, {
    joint_type: 'spherical',
    axis_origin: beadA_world,
    axis_direction: [0, 1, 0],
    name: `Ball joint @ ${bondLabel}`,
  });
}));
```

Anchor world positions are available in the geometry response — currently the menu doesn't fetch them but `unfold_view.getArcEntries()` exposes `fromNuc` / `toNuc` and the arc has `getMidWorld()`. The world position of each anchor bead is the cone/backbone entry for that nucleotide — accessible via `designRenderer.getBackboneEntries()`. Wire that up at menu-open time.

### 8. Tests

- `tests/test_joints.py`: spherical joint round-trip (create → read → update → delete).
- `tests/test_relax_bond.py`: new cases:
  - `test_relax_bond_1_spherical_joint_3dof_closes_chord` — 1 spherical joint on side A, chord closes via 3-DOF Powell.
  - `test_relax_bond_spherical_plus_revolute_mixed` — (3 + 1)-DOF case.
  - `test_relax_bond_spherical_joint_invariant_under_repeat` — running twice gives the same final pose.
- `tests/test_atomistic.py` or wherever local↔world joint math has coverage: spherical joint world-direction is None / skipped.

### 9. Migration

Existing `.nadoc` files have `joint_type='revolute'` either explicitly or via the default. Widening the Literal is backwards-compatible (pydantic accepts the existing value). No file migration needed — `model_copy` / load paths just keep emitting `revolute` for old joints.

Forward-compat: a newer NADOC writing `'spherical'` can't be opened in an older NADOC. Accept this; the .nadoc format doesn't have a forward-compat version mechanism today.

## Out of scope for Phase 2

- **Joint-axis limits for spherical joints** — `min/max_angle_deg` are revolute-only. Per-axis caps for spherical (e.g. cone-constrained ball joint) could come later.
- **Multi-helix joints / joint that owns two clusters** — current model has 1 cluster_id per joint. Don't change that here.
- **Animation player integration** — keyframe slerp currently uses `min/max_angle_deg` for revolute. Spherical needs its own keyframe representation. Defer.

## Open design questions to confirm with user before coding

1. **Should "Add ball joint" be available even when `jointsBetween > 0`?** I.e. let the user stack joints. Probably yes — a stacked joint adds to the DOF pool. But could also surface a warning ("already has a joint, will be over-determined").
2. **Joint radius/visual** — what default sphere radius? Should match backbone-bead scale (currently ~0.4–0.5 nm) so it visually sits at the bead.
3. **Naming convention** — auto-name as `Ball joint @ <bond>` is OK; user can rename via the panel.
4. **Should the joint_type be a different model entirely?** Current proposal extends `ClusterJoint`. Alternative: `class ClusterBallJoint(BaseModel)` and a `cluster_ball_joints: List[ClusterBallJoint]` field on Design. Cleaner separation but doubles the call-site count. Sticking with the discriminator union is recommended.

## Estimated effort

- Model + endpoint extension: ~2-3 hrs.
- Solver extension + tests: ~4-6 hrs (this is the gnarly part — axis-angle parameterisation, mixed DOF vector, regression for the existing revolute paths).
- Rendering: ~1-2 hrs.
- Panel update: ~1 hr.
- Frontend menu items + anchor-world wiring: ~1-2 hrs.
- Verification in app on the hinge ligation `f07a513b`: ~1 hr.

Total: ~10-15 hrs across 1-2 sessions.

## Resume guide

When picking this up:
1. Re-read [[bond-relax-framework]] for the existing solver structure.
2. Re-read this file's "Required changes" section in order — 1 → 9.
3. Start with §1 (model) + §2 (endpoint) + a minimal `test_joints.py` round-trip — get a `joint_type='spherical'` joint to persist before touching the solver.
4. Then §3 (solver) is the meat. Write the new test cases first (TDD-style) — the existing relax tests give you the structural template.
5. Rendering / panel / menu come last; the backend solver should be green before any UI work.
