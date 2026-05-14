"""Backend undo path after relax_bond — does cluster_transform restore?"""
from __future__ import annotations
from fastapi.testclient import TestClient
from backend.api import state as design_state
from backend.api.main import app
from backend.core.models import Design

client = TestClient(app)

with open('workspace/Hinge.nadoc') as f:
    d = Design.model_validate_json(f.read())
design_state.set_design(d)
binding = d.overhang_bindings[0]
bid = binding.id

if binding.bound:
    client.patch(f'/api/design/overhang-bindings/{bid}', json={'bound': False})
client.patch(f'/api/design/overhang-bindings/{bid}', json={'bound': True})

d_pre = design_state.get_or_404()
binding = d_pre.overhang_bindings[0]
joint_id = binding.target_joint_id or next(
    j.id for j in d_pre.cluster_joints
    if j.cluster_id != next(c.id for c in d_pre.cluster_transforms if 'h_XY_3_3' in c.helix_ids)
)
# Find the joint's cluster
joint = next(j for j in d_pre.cluster_joints if j.id == joint_id)
ct_pre = next(c for c in d_pre.cluster_transforms if c.id == joint.cluster_id)

print(f'PRE-relax cluster {joint.cluster_id[:8]}: translation={ct_pre.translation} rotation={ct_pre.rotation}')

# Find OH→parent crossover from snapshot
snap_xover_ids = {x['id'] for x in binding.prior_driven_topology.get('crossovers', [])}
xo = next(x for x in d_pre.crossovers if x.id in snap_xover_ids)
print(f'\nOH→parent crossover {xo.id[:16]}:')
print(f'  half_a={xo.half_a.helix_id}:{xo.half_a.index}:{xo.half_a.strand}')
print(f'  half_b={xo.half_b.helix_id}:{xo.half_b.index}:{xo.half_b.strand}')

# Relax
r = client.post('/api/design/relax-bond', json={
    'bond_type': 'crossover', 'bond_id': xo.id, 'joint_ids': [joint.id],
})
print(f'\nrelax status: {r.status_code}')
print(f'relax info: {r.json().get("relax_info")}')

d_post = design_state.get_or_404()
ct_post = next(c for c in d_post.cluster_transforms if c.id == joint.cluster_id)
print(f'\nPOST-relax cluster: translation={ct_post.translation} rotation={ct_post.rotation}')

# Undo
r = client.post('/api/design/undo')
print(f'\nundo status: {r.status_code}')

d_undo = design_state.get_or_404()
ct_undo = next(c for c in d_undo.cluster_transforms if c.id == joint.cluster_id)
print(f'\nPOST-UNDO cluster: translation={ct_undo.translation} rotation={ct_undo.rotation}')

def vec_close(a, b, tol=1e-9):
    return all(abs(x - y) < tol for x, y in zip(a, b))

if vec_close(ct_pre.translation, ct_undo.translation) and vec_close(ct_pre.rotation, ct_undo.rotation):
    print('\n✓ Backend undo restored cluster transform EXACTLY.')
else:
    print('\n✗ Backend undo did NOT restore exactly.')
    print(f'  Δ rotation: {[u-p for p,u in zip(ct_pre.rotation, ct_undo.rotation)]}')

# Show response.cluster_diffs
print(f'\nresponse.cluster_diffs ({len(r.json().get("cluster_diffs", []))} entries):')
for d in r.json().get('cluster_diffs', []):
    print(f"  {d['cluster_id'][:8]}: old_rot={d['old_rotation']}")
    print(f"                                 new_rot={d['new_rotation']}")

# Print full response shape for undo
import json as _json
print('\nResponse diff_kind:', r.json().get('diff_kind'))
print('Response keys:', list(r.json().keys()))
# Also check relax response from earlier
print('\n--- Re-running relax to inspect its response ---')
client.post('/api/design/undo')   # back to PRE
r_relax = client.post('/api/design/relax-bond', json={
    'bond_type': 'crossover', 'bond_id': xo.id, 'joint_ids': [joint.id],
})
print('Relax response diff_kind:', r_relax.json().get('diff_kind'))
print('Relax response cluster_diffs:', _json.dumps(r_relax.json().get('cluster_diffs', []), indent=2))
