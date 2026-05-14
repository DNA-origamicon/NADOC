"""Audit: does the optimizer converge to the actual chord minimum?

Procedure:
  1. Set up bound state via API (with current code: bind = topology
     relocation only, no auto-relax).
  2. Snapshot the cluster transform.
  3. Manually rotate by a fine delta sweep, computing chord via
     _resolve_bond_anchor_from_endpoint (rendered backbone bead position).
  4. Find the empirical min.
  5. Call the optimizer (core_relax_bond) on the same anchors and
     compare its result to the empirical min.
"""
from __future__ import annotations
import numpy as np
from fastapi.testclient import TestClient
from backend.api import state as design_state
from backend.api.main import app
from backend.api.crud import (
    _geometry_for_design, _resolve_bond_anchor_from_endpoint,
    _cluster_id_for_helix, RelaxBondEndpoint,
)
from backend.core.bond_relax import relax_bond as core_relax_bond
from backend.core.linker_relax import _composed_transform
from backend.core.models import Design, _local_to_world_joint

client = TestClient(app)

with open('workspace/Hinge.nadoc') as f:
    d = Design.model_validate_json(f.read())
design_state.set_design(d)

binding = d.overhang_bindings[0]
bid = binding.id

# Ensure clean bound state (current code: topology only)
if binding.bound:
    client.patch(f'/api/design/overhang-bindings/{bid}', json={'bound': False})
client.patch(f'/api/design/overhang-bindings/{bid}', json={'bound': True})

d = design_state.get_or_404()
binding = d.overhang_bindings[0]
joint = next(j for j in d.cluster_joints if j.id == binding.target_joint_id)
print(f'Post-bind: locked={binding.locked_angle_deg} '
      f'joint min/max={joint.min_angle_deg}/{joint.max_angle_deg}')

# Anchors + joint axis
ep_a = RelaxBondEndpoint(helix_id='h_XY_3_3', bp_index=199, direction='FORWARD')
ep_b = RelaxBondEndpoint(helix_id='h_XY_5_3', bp_index=199, direction='REVERSE')
geom0 = _geometry_for_design(d)
pa0 = _resolve_bond_anchor_from_endpoint(geom0, ep_a)
pb0 = _resolve_bond_anchor_from_endpoint(geom0, ep_b)
print(f'Chord at bind pose (no auto-relax): {float(np.linalg.norm(pa0 - pb0)):.4f} nm')

# Manual sweep — rotate cluster 2 (the joint's cluster) and measure
# real rendered chord at each step.
ct_joint = next(c for c in d.cluster_transforms if c.id == joint.cluster_id)
wo, wd = _local_to_world_joint(joint.local_axis_origin, joint.local_axis_direction, ct_joint)
axis = np.asarray(wd, dtype=float); axis = axis / np.linalg.norm(axis)
origin = np.asarray(wo, dtype=float)

def chord_at(delta_rad: float) -> float:
    q_new, t_new = _composed_transform(ct_joint, origin, axis, delta_rad)
    new_clusters = [
        c.model_copy(update={'rotation': list(q_new), 'translation': list(t_new)})
        if c.id == joint.cluster_id else c
        for c in d.cluster_transforms
    ]
    d2 = d.model_copy(update={'cluster_transforms': new_clusters})
    geom = _geometry_for_design(d2)
    pa = _resolve_bond_anchor_from_endpoint(geom, ep_a)
    pb = _resolve_bond_anchor_from_endpoint(geom, ep_b)
    return float(np.linalg.norm(pa - pb))

# Coarse sweep
print('\nCoarse sweep (delta_deg, chord_nm):')
deltas = np.linspace(-90, 90, 181)  # 1° steps
chords = [chord_at(d_deg * np.pi / 180.0) for d_deg in deltas]
min_idx = int(np.argmin(chords))
print(f'  empirical minimum: delta={deltas[min_idx]:.2f}°  chord={chords[min_idx]:.4f} nm')

# Fine sweep around empirical min
center = deltas[min_idx]
print(f'\nFine sweep around delta={center:.2f}°:')
fine_deltas = np.linspace(center - 2, center + 2, 401)  # 0.01° steps
fine_chords = [chord_at(d_deg * np.pi / 180.0) for d_deg in fine_deltas]
fine_min_idx = int(np.argmin(fine_chords))
print(f'  fine minimum: delta={fine_deltas[fine_min_idx]:.4f}°  chord={fine_chords[fine_min_idx]:.6f} nm')

# Now call the optimizer on the same anchors
cluster_a_id = _cluster_id_for_helix(d, 'h_XY_3_3')
cluster_b_id = _cluster_id_for_helix(d, 'h_XY_5_3')
d_relax, info = core_relax_bond(
    d, anchor_a=pa0, anchor_b=pb0,
    cluster_a_id=cluster_a_id, cluster_b_id=cluster_b_id,
    target_nm=0.13,
    joint_ids=[joint.id], source_tag='audit',
)
geom_relax = _geometry_for_design(d_relax)
pa_relax = _resolve_bond_anchor_from_endpoint(geom_relax, ep_a)
pb_relax = _resolve_bond_anchor_from_endpoint(geom_relax, ep_b)
chord_relax = float(np.linalg.norm(pa_relax - pb_relax))
print(f'\nOptimizer result: theta_deg={info["theta_deg"]:.4f}  chord={chord_relax:.6f} nm')

# Compare
if abs(chord_relax - fine_chords[fine_min_idx]) < 0.001:
    print('\n✓ Optimizer matches empirical minimum (within 0.001 nm).')
else:
    print(f'\n✗ Optimizer is OFF by {chord_relax - fine_chords[fine_min_idx]:.4f} nm.')
    print(f'  Optimizer chord: {chord_relax:.6f}')
    print(f'  Empirical min:   {fine_chords[fine_min_idx]:.6f}')
