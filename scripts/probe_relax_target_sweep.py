"""Sweep target_nm, this time properly restoring the joint window from
the first-claimant snapshot before each bind (matching the actual user
flow of unbind + rebind)."""
from __future__ import annotations
import numpy as np
from backend.api import state as design_state
from backend.api.crud import (
    _geometry_for_design, _resolve_bond_anchor_from_endpoint,
    _cluster_id_for_helix, RelaxBondEndpoint,
)
from backend.core.bond_relax import relax_bond as core_relax_bond
from backend.core.binding_relax import (
    compute_bind_topology, apply_bind_topology, revert_bind_topology,
)
from backend.core.models import Design


def load_unbound():
    with open('workspace/Hinge.nadoc') as f:
        d = Design.model_validate_json(f.read())
    binding = d.overhang_bindings[0]
    if not binding.bound:
        return d
    # Revert topology
    d = revert_bind_topology(d, binding.prior_driven_topology)
    # Restore joint window from prior_min/max
    new_joints = []
    for j in d.cluster_joints:
        if j.id == binding.target_joint_id and binding.prior_min_angle_deg is not None:
            new_joints.append(j.model_copy(update={
                'min_angle_deg': binding.prior_min_angle_deg,
                'max_angle_deg': binding.prior_max_angle_deg,
            }))
        else:
            new_joints.append(j)
    # Clear binding state
    new_bindings = [b.model_copy(update={
        'bound': False,
        'locked_angle_deg': None,
        'prior_driven_topology': None,
        'prior_min_angle_deg': None,
        'prior_max_angle_deg': None,
    }) for b in d.overhang_bindings]
    d = d.model_copy(update={
        'overhang_bindings': new_bindings,
        'cluster_joints': new_joints,
    })
    return d


def chord_for(geom, xo):
    pa = _resolve_bond_anchor_from_endpoint(
        geom, RelaxBondEndpoint(
            helix_id=xo.half_a.helix_id, bp_index=xo.half_a.index,
            direction=xo.half_a.strand.value))
    pb = _resolve_bond_anchor_from_endpoint(
        geom, RelaxBondEndpoint(
            helix_id=xo.half_b.helix_id, bp_index=xo.half_b.index,
            direction=xo.half_b.strand.value))
    return float(np.linalg.norm(pa - pb))


def measure(target_nm: float):
    d = load_unbound()
    # Joint range pre-bind
    binding = d.overhang_bindings[0]
    j = next(j for j in d.cluster_joints if j.id == binding.target_joint_id)
    pre_joint_range = (j.min_angle_deg, j.max_angle_deg)

    # Bind topology + apply
    topology = compute_bind_topology(d, binding)
    d = apply_bind_topology(d, topology)
    design_state.set_design(d)

    snap_ids = {x['id'] for x in topology.snapshot.get('crossovers', [])}
    driven_helix = topology.snapshot['prior_ovhg_helix_id']
    rewritten = next(
        (xo for xo in d.crossovers if xo.id in snap_ids
         and xo.half_a.helix_id != driven_helix
         and xo.half_b.helix_id != driven_helix),
        None,
    )
    geom = _geometry_for_design(d)
    pre_chord = chord_for(geom, rewritten)
    ep_a = RelaxBondEndpoint(helix_id=rewritten.half_a.helix_id, bp_index=rewritten.half_a.index, direction=rewritten.half_a.strand.value)
    ep_b = RelaxBondEndpoint(helix_id=rewritten.half_b.helix_id, bp_index=rewritten.half_b.index, direction=rewritten.half_b.strand.value)
    anchor_a = _resolve_bond_anchor_from_endpoint(geom, ep_a)
    anchor_b = _resolve_bond_anchor_from_endpoint(geom, ep_b)
    cluster_a = _cluster_id_for_helix(d, rewritten.half_a.helix_id)
    cluster_b = _cluster_id_for_helix(d, rewritten.half_b.helix_id)
    d2, info = core_relax_bond(
        d,
        anchor_a=anchor_a, anchor_b=anchor_b,
        cluster_a_id=cluster_a, cluster_b_id=cluster_b,
        target_nm=target_nm,
        joint_ids=[binding.target_joint_id],
        source_tag='probe',
    )
    post_geom = _geometry_for_design(d2)
    post_chord = chord_for(post_geom, rewritten)
    return target_nm, pre_chord, post_chord, info.get('theta_deg'), pre_joint_range


print(f'{"target":>10}  {"pre_chord":>12}  {"post_chord":>12}  {"theta_deg":>12}  {"joint_pre":>16}')
for t in [0.0, 0.13, 0.34, 0.56, 0.67, 1.0, 2.0]:
    target, pre, post, theta, jrange = measure(t)
    print(f'{target:>10.3f}  {pre:>12.6f}  {post:>12.6f}  {theta:>12.6f}  {jrange[0]:>7.2f}/{jrange[1]:<7.2f}')
