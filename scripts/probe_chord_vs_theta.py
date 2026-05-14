"""Plot chord(theta) for the OH→parent crossover over a wide range so we
can see the achievable minimum given the joint axis."""
from __future__ import annotations
import numpy as np
from backend.api import state as design_state
from backend.api.crud import (
    _geometry_for_design, _resolve_bond_anchor_from_endpoint,
    _cluster_id_for_helix, RelaxBondEndpoint,
)
from backend.core.linker_relax import _rot_axis_angle
from backend.core.models import Design, _local_to_world_joint
from backend.core.binding_relax import compute_bind_topology, apply_bind_topology, revert_bind_topology


with open('workspace/Hinge.nadoc') as f:
    d = Design.model_validate_json(f.read())
# Force unbound state
binding = d.overhang_bindings[0]
if binding.bound:
    d = revert_bind_topology(d, binding.prior_driven_topology)
    new_bindings = [b.model_copy(update={
        'bound': False, 'locked_angle_deg': None,
        'prior_driven_topology': None,
    }) for b in d.overhang_bindings]
    d = d.model_copy(update={'overhang_bindings': new_bindings})
design_state.set_design(d)

# Bind topology + apply
binding = d.overhang_bindings[0]
topology = compute_bind_topology(d, binding)
d = apply_bind_topology(d, topology)

# Find rewritten crossover
snap_ids = {x['id'] for x in topology.snapshot.get('crossovers', [])}
driven_helix = topology.snapshot['prior_ovhg_helix_id']
rewritten = None
for xo in d.crossovers:
    if xo.id in snap_ids and xo.half_a.helix_id != driven_helix and xo.half_b.helix_id != driven_helix:
        rewritten = xo
        break

# Anchors + joint axis
geom = _geometry_for_design(d)
ep_a = RelaxBondEndpoint(helix_id=rewritten.half_a.helix_id, bp_index=rewritten.half_a.index, direction=rewritten.half_a.strand.value)
ep_b = RelaxBondEndpoint(helix_id=rewritten.half_b.helix_id, bp_index=rewritten.half_b.index, direction=rewritten.half_b.strand.value)
anchor_a = _resolve_bond_anchor_from_endpoint(geom, ep_a)
anchor_b = _resolve_bond_anchor_from_endpoint(geom, ep_b)
cluster_a_id = _cluster_id_for_helix(d, rewritten.half_a.helix_id)
cluster_b_id = _cluster_id_for_helix(d, rewritten.half_b.helix_id)

# Joint
joint = next(j for j in d.cluster_joints if j.id == binding.target_joint_id)
ct = next(c for c in d.cluster_transforms if c.id == joint.cluster_id)
wo, wd = _local_to_world_joint(joint.local_axis_origin, joint.local_axis_direction, ct)
axis = np.asarray(wd, dtype=float)
axis = axis / np.linalg.norm(axis)
origin = np.asarray(wo, dtype=float)

# Which is moving anchor?
moving_is_a = (joint.cluster_id == cluster_a_id)
moving = anchor_a if moving_is_a else anchor_b
fixed  = anchor_b if moving_is_a else anchor_a

print(f'anchor_a (h={ep_a.helix_id} bp={ep_a.bp_index} {ep_a.direction}): {anchor_a}')
print(f'anchor_b (h={ep_b.helix_id} bp={ep_b.bp_index} {ep_b.direction}): {anchor_b}')
print(f'joint origin: {origin}')
print(f'joint axis:   {axis}')
print(f'cluster_a={cluster_a_id[:8]!r} cluster_b={cluster_b_id[:8]!r} joint.cluster={joint.cluster_id[:8]!r}')
print(f'moving_is_a={moving_is_a}')
print(f'|moving - origin| = {np.linalg.norm(moving - origin):.4f} nm')
print(f'|fixed  - origin| = {np.linalg.norm(fixed  - origin):.4f} nm')

# Project moving and fixed onto plane perpendicular to axis (through origin)
# This shows the rotational geometry
def perp_dist_to_axis(p, origin, axis):
    v = p - origin
    par = np.dot(v, axis) * axis
    perp = v - par
    return np.linalg.norm(perp), np.dot(v, axis)

rad_m, par_m = perp_dist_to_axis(moving, origin, axis)
rad_f, par_f = perp_dist_to_axis(fixed,  origin, axis)
print(f'moving: perp={rad_m:.4f} parallel={par_m:.4f} (radius from axis)')
print(f'fixed:  perp={rad_f:.4f} parallel={par_f:.4f} (radius from axis)')
print(f'min achievable chord: sqrt((rad_m - rad_f)^2 + (par_m - par_f)^2) = '
      f'{np.sqrt((rad_m - rad_f)**2 + (par_m - par_f)**2):.4f}')

# Sweep theta over a wide range to confirm
print()
print(f'{"theta_deg":>10}  {"chord_nm":>10}')
for theta_deg in range(-180, 181, 15):
    theta = theta_deg * np.pi / 180.0
    R = _rot_axis_angle(axis, theta)
    p_moving = R @ (moving - origin) + origin
    chord = float(np.linalg.norm(p_moving - fixed))
    print(f'{theta_deg:>10}  {chord:>10.4f}')

# Fine sweep around -60
print()
print('Fine sweep:')
print(f'{"theta_deg":>12}  {"chord_nm":>10}')
for theta_deg in np.linspace(-90, -30, 121):
    theta = theta_deg * np.pi / 180.0
    R = _rot_axis_angle(axis, theta)
    p_moving = R @ (moving - origin) + origin
    chord = float(np.linalg.norm(p_moving - fixed))
    print(f'{theta_deg:>12.2f}  {chord:>10.4f}')
