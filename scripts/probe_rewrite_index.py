"""Confirm exactly what the current bind code produces for the OH→parent
crossover's index after rewrite."""
from __future__ import annotations
from backend.api import state as design_state
from backend.core.binding_relax import (
    compute_bind_topology, apply_bind_topology, revert_bind_topology,
)
from backend.core.models import Design

with open('workspace/Hinge.nadoc') as f:
    d = Design.model_validate_json(f.read())
binding = d.overhang_bindings[0]
print(f'Live state: B1 bound={binding.bound} locked={binding.locked_angle_deg}')
# Find the rewritten crossover in live state
xo_live = next(xo for xo in d.crossovers if xo.id.startswith('37218a20'))
print(f'Live crossover 37218a20: half_a={xo_live.half_a} half_b={xo_live.half_b}')

# Revert + clear bind state
if binding.bound:
    d = revert_bind_topology(d, binding.prior_driven_topology)
    new_joints = []
    for j in d.cluster_joints:
        if j.id == binding.target_joint_id and binding.prior_min_angle_deg is not None:
            new_joints.append(j.model_copy(update={
                'min_angle_deg': binding.prior_min_angle_deg,
                'max_angle_deg': binding.prior_max_angle_deg,
            }))
        else:
            new_joints.append(j)
    new_bindings = [b.model_copy(update={
        'bound': False, 'locked_angle_deg': None,
        'prior_driven_topology': None,
        'prior_min_angle_deg': None,
        'prior_max_angle_deg': None,
    }) for b in d.overhang_bindings]
    d = d.model_copy(update={
        'overhang_bindings': new_bindings,
        'cluster_joints': new_joints,
    })

# Pre-bind crossover
xo_pre = next(xo for xo in d.crossovers if xo.id.startswith('37218a20'))
print(f'\nPre-bind 37218a20: half_a={xo_pre.half_a} half_b={xo_pre.half_b}')

# Compute topology and inspect target_start/end
binding = d.overhang_bindings[0]
topology = compute_bind_topology(d, binding)
print(f'\ntopology.target_start_bp={topology.target_start_bp}')
print(f'topology.target_end_bp={topology.target_end_bp}')
print(f'topology.target_direction={topology.target_direction}')
print(f'topology.snapshot["prior_domain"]={topology.snapshot["prior_domain"]}')

# Apply
d_post = apply_bind_topology(d, topology)
xo_post = next(xo for xo in d_post.crossovers if xo.id.startswith('37218a20'))
print(f'\nPost-bind 37218a20: half_a={xo_post.half_a} half_b={xo_post.half_b}')

# Driver OH1's domain
ohs = d.overhangs
oh1 = next(o for o in ohs if o.label == 'OH1')
oh1_strand = next(s for s in d.strands if s.id == oh1.strand_id)
oh1_dom = next(dom for dom in oh1_strand.domains if dom.overhang_id == oh1.id)
print(f'\nDriver OH1 domain: helix={oh1_dom.helix_id} bp=[{oh1_dom.start_bp},{oh1_dom.end_bp}] dir={oh1_dom.direction}')
