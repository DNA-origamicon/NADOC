"""Record a cluster Move/Rotate that separates pairing as a topology-bearing move."""
from uuid import uuid4
from backend.core.models import SnapshotLogEntry
from backend.core.sequences import domain_bp_range
from backend.core.unpair_reclassification import separated_staple_keys, relocate_segments


def separated_keys(before, posed, identities):
    from backend.core.deformation import _cluster_moving_segment_keys
    moving = set()
    for owner in posed.cluster_transforms:
        if owner.id in identities:
            moving.update(_cluster_moving_segment_keys(owner, posed))
    targets = [(d.helix_id, bp, d.direction.value, 0)
               for s in before.strands for i, d in enumerate(s.domains)
               if (s.id, i) in moving for bp in domain_bp_range(d)]
    return separated_staple_keys(before, posed, targets, allow_cluster_poses=True)


def reclassify(before, posed, params):
    keys = separated_keys(before, posed, {p['cluster_id'] for p in params['poses']})
    return relocate_segments(posed, keys, identity_seed=params['history_seed'])


def record_if_separated(source, posed, entry):
    if not separated_keys(source, posed, {entry.cluster_id}):
        return posed, entry
    from backend.api.state import encode_design_snapshot
    from backend.api.part_placement_pose_commands import build
    owner = next(c for c in posed.cluster_transforms if c.id == entry.cluster_id)
    params = {'_proof_version': 1, 'primary_cluster_id': owner.id,
        'selected_cluster_ids': [owner.id],
        'poses': [owner.model_dump(mode='json', include={'translation', 'rotation', 'pivot',
            'parent_cluster_id', 'overhang_duplex_driver_id'}) | {'cluster_id': owner.id}],
        'authoring': {'mode': 'free', 'joint_id': None, 'fixed_cluster_ids': [], 'pivot_id': 'centroid'},
        'primary_authored_fields': entry.authored_fields, 'legacy_source': entry.source,
        'reclassify_unpaired': True, 'history_seed': str(uuid4())}
    result = build(source, params)
    pre, pre_size = encode_design_snapshot(source)
    post, post_size = encode_design_snapshot(result)
    return result, SnapshotLogEntry(id=entry.id, op_kind='placement-poses', label='Move/Rotate', params=params,
        design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
        post_state_gz_b64=post, post_state_size_bytes=post_size)
