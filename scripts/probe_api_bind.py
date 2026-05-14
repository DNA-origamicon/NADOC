"""Use the real API endpoint to bind B1 (with current code) and verify
the resulting locked_angle and crossover state."""
from __future__ import annotations
from fastapi.testclient import TestClient
from backend.api import state as design_state
from backend.api.main import app
from backend.core.models import Design

client = TestClient(app)

with open('workspace/Hinge.nadoc') as f:
    d = Design.model_validate_json(f.read())
design_state.set_design(d)

# Unbind first
binding = d.overhang_bindings[0]
bid = binding.id
if binding.bound:
    r = client.patch(f'/api/design/overhang-bindings/{bid}', json={'bound': False})
    print(f'unbind status: {r.status_code}')

# Check joint state pre-bind
d = design_state.get_or_404()
joint = next(j for j in d.cluster_joints if j.id == binding.target_joint_id)
print(f'\npre-bind joint: min={joint.min_angle_deg} max={joint.max_angle_deg}')
binding = d.overhang_bindings[0]
print(f'pre-bind binding: bound={binding.bound} locked={binding.locked_angle_deg} prior_min={binding.prior_min_angle_deg} prior_max={binding.prior_max_angle_deg}')

# Now bind via API
r = client.patch(f'/api/design/overhang-bindings/{bid}', json={'bound': True})
print(f'\nbind status: {r.status_code}')
if r.status_code != 200:
    print(r.text)

# Check post-bind state
d = design_state.get_or_404()
binding = d.overhang_bindings[0]
joint = next(j for j in d.cluster_joints if j.id == binding.target_joint_id)
print(f'\npost-bind joint: min={joint.min_angle_deg} max={joint.max_angle_deg}')
print(f'post-bind binding: bound={binding.bound} locked={binding.locked_angle_deg}')
xo = next(xo for xo in d.crossovers if xo.id.startswith('37218a20'))
print(f'post-bind crossover: half_a={xo.half_a} half_b={xo.half_b}')

# Check feature log for bind-relax entry
log = d.feature_log
print(f'\nLog tail (last 5 entries):')
for e in log[-5:]:
    src = getattr(e, 'source', None)
    print(f'  {getattr(e, "feature_type", "?")} source={src!r}')
