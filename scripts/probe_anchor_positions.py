"""Verify ANCHOR POSITIONS match the rendered backbone beads.

Approach:
  1. Load Hinge.nadoc + force a clean bound state via the API.
  2. Compute the chord between (h_XY_3_3, 199, FORWARD) and
     (h_XY_5_3, 199, REVERSE) using _resolve_bond_anchor_from_endpoint.
  3. Sweep the joint angle by manually applying cluster transforms (the
     same way the user would via the gizmo) and re-measure the chord
     each time. If the user is right that the chord can drop below
     my "floor", we'll see it here.
"""
from __future__ import annotations
import numpy as np
from fastapi.testclient import TestClient
from backend.api import state as design_state
from backend.api.main import app
from backend.api.crud import (
    _geometry_for_design, _resolve_bond_anchor_from_endpoint,
    RelaxBondEndpoint,
)
from backend.core.models import Design, _local_to_world_joint
from backend.core.linker_relax import _rot_axis_angle, _composed_transform

client = TestClient(app)


with open('workspace/Hinge.nadoc') as f:
    d = Design.model_validate_json(f.read())
design_state.set_design(d)
binding = d.overhang_bindings[0]
bid = binding.id
# Ensure bound state via the API
if not binding.bound:
    client.patch(f'/api/design/overhang-bindings/{bid}', json={'bound': True})
else:
    # rebind to get current code's result
    client.patch(f'/api/design/overhang-bindings/{bid}', json={'bound': False})
    client.patch(f'/api/design/overhang-bindings/{bid}', json={'bound': True})

d = design_state.get_or_404()
binding = d.overhang_bindings[0]
joint = next(j for j in d.cluster_joints if j.id == binding.target_joint_id)
print(f'After API bind: locked={binding.locked_angle_deg:.4f}, joint min/max={joint.min_angle_deg:.4f}/{joint.max_angle_deg:.4f}')

# Chord NOW
geom = _geometry_for_design(d)
ep_a = RelaxBondEndpoint(helix_id='h_XY_3_3', bp_index=199, direction='FORWARD')
ep_b = RelaxBondEndpoint(helix_id='h_XY_5_3', bp_index=199, direction='REVERSE')
pa = _resolve_bond_anchor_from_endpoint(geom, ep_a)
pb = _resolve_bond_anchor_from_endpoint(geom, ep_b)
print(f'\nAt bind angle:')
print(f'  anchor h_XY_3_3:199:FORWARD = {pa}')
print(f'  anchor h_XY_5_3:199:REVERSE = {pb}')
print(f'  chord = {float(np.linalg.norm(pa - pb)):.6f} nm')

# Now manually rotate cluster 2 by various delta angles around the joint
# and measure chord — simulating the user's gizmo manipulation.
ct_moving = next(c for c in d.cluster_transforms if c.id == joint.cluster_id)
wo, wd = _local_to_world_joint(joint.local_axis_origin, joint.local_axis_direction, ct_moving)
print(f'\njoint world origin = {np.asarray(wo)}')
print(f'joint world axis   = {np.asarray(wd)}')

# To probe, we must temporarily unlock the joint then rotate cluster
# manually. The cluster's transform encodes the absolute rotation; we
# compose an additional delta theta.
def measure_at_delta(delta_deg: float) -> float:
    delta_rad = delta_deg * np.pi / 180.0
    # Compose: new_quat = q_axis(delta) ⊗ old_quat
    axis = np.asarray(wd, dtype=float)
    axis = axis / np.linalg.norm(axis)
    origin = np.asarray(wo, dtype=float)
    q_new, t_new = _composed_transform(ct_moving, origin, axis, float(delta_rad))
    new_ct = ct_moving.model_copy(update={
        'rotation': list(q_new),
        'translation': list(t_new),
    })
    new_clusters = [new_ct if c.id == ct_moving.id else c for c in d.cluster_transforms]
    d2 = d.model_copy(update={'cluster_transforms': new_clusters})
    # Also unlock the joint so the simulated rotation is reflected in geom
    new_joints = [j.model_copy(update={'min_angle_deg': -180, 'max_angle_deg': 180})
                  if j.id == joint.id else j for j in d2.cluster_joints]
    d2 = d2.model_copy(update={'cluster_joints': new_joints})
    geom2 = _geometry_for_design(d2)
    pa = _resolve_bond_anchor_from_endpoint(geom2, ep_a)
    pb = _resolve_bond_anchor_from_endpoint(geom2, ep_b)
    return float(np.linalg.norm(pa - pb))

print('\nManually rotate cluster (joint delta from current bind pose):')
print(f'{"delta_deg":>10}  {"chord_nm":>10}')
for delta in [-30, -20, -10, -5, -1, 0, 1, 5, 10, 20, 30]:
    c = measure_at_delta(delta)
    print(f'{delta:>10}  {c:>10.4f}')

print('\nFine sweep around the bind pose:')
print(f'{"delta_deg":>12}  {"chord_nm":>10}')
for delta in np.linspace(-2, 2, 81):
    c = measure_at_delta(float(delta))
    print(f'{delta:>12.3f}  {c:>10.4f}')
