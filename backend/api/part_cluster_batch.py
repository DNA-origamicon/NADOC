"""Atomic ordinary-cluster moves through the existing replacement publisher."""
from uuid import uuid4

from fastapi import HTTPException

from backend.api import state
from backend.api.part_group_recording import _start, _publish
from backend.api.part_placement_pose_commands import build, parse_command
from backend.core.models import SnapshotLogEntry


def move_clusters(placements, expected_revision):
    if not 1 <= len(placements) <= 64 or any(
            set(item.fields) != {'translation', 'rotation', 'pivot'} for item in placements):
        raise HTTPException(422, detail='A move requires 1–64 complete cluster poses.')
    with state._lock:
        session, source, revision, identity = _start('group_edit')
        if revision != expected_revision:
            raise HTTPException(409, detail={'code': 'source_changed', 'message': 'Refresh before applying movement.'})
        owners = {c.id: c for c in source.cluster_transforms}
        poses = []
        for item in placements:
            owner = owners.get(item.cluster_id)
            if owner is None:
                raise HTTPException(422, detail={'code': 'missing_reference', 'message': 'A moved cluster is missing.'})
            poses.append({'cluster_id': owner.id, **item.fields,
                'parent_cluster_id': owner.parent_cluster_id,
                'overhang_duplex_driver_id': owner.overhang_duplex_driver_id})
        params = {'_proof_version': 1, 'primary_cluster_id': placements[0].cluster_id,
            'selected_cluster_ids': [item.cluster_id for item in placements], 'poses': poses,
            'authoring': {'mode': 'free', 'joint_id': None, 'fixed_cluster_ids': [], 'pivot_id': 'centroid'},
            'primary_authored_fields': {}, 'legacy_source': None}
        try:
            parse_command(params)
            candidate = build(source, params)
            from backend.api.part_cluster_unpair import separated_keys
            if separated_keys(source, candidate, set(params['selected_cluster_ids'])):
                params.update(reclassify_unpaired=True, history_seed=str(uuid4()))
                candidate = build(source, params)
            from backend.api.part_recovery_budget import RecoveryBudget
            from backend.core.part_recovery_storage import MAX_RECOVERY_BYTES, retained_recovery_bytes
            budget = RecoveryBudget(MAX_RECOVERY_BYTES - retained_recovery_bytes(source.feature_log, max_rows=1999))
            pre, pre_size = state.encode_design_snapshot(source)
            budget.charge(pre)
            post, post_size = state.encode_design_snapshot(candidate)
            budget.charge(post)
            entry = SnapshotLogEntry(op_kind='placement-poses', label='Move/Rotate', params=params,
                design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
                post_state_gz_b64=post, post_state_size_bytes=post_size)
            candidate = candidate.copy_with(feature_log=[*source.feature_log, entry])
            return _publish(session, source, revision, identity, candidate)
        except ValueError as error:
            raise HTTPException(422, detail=str(error)) from error
