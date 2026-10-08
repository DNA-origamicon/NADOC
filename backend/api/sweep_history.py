"""Read-only edit preview in the same placement as the replayed feature."""
import numpy as np
from fastapi import HTTPException
from backend.api import state
from backend.core.sweep import sweep_preview
from backend.core.deformation import _clusters_for_helix, _apply_cluster_transforms_to_point


def _placement(design, helix):
    clusters = _clusters_for_helix(design, helix.id)
    def transform(point):
        return np.asarray(_apply_cluster_transforms_to_point(point, clusters, helix, design))
    offset = transform(np.zeros(3))
    return np.column_stack([transform(axis) - offset for axis in np.eye(3)]), offset


def preview_sweep_edit(design, body, index):
    if not 0 <= index < len(design.feature_log):
        raise HTTPException(404, detail='Sweep feature no longer exists')
    entry = design.feature_log[index]
    if getattr(entry, 'op_kind', None) != 'sweep':
        raise HTTPException(422, detail='Select a sweep feature')
    if entry.evicted or not entry.design_snapshot_gz_b64 or not entry.post_state_gz_b64:
        raise HTTPException(410, detail='Sweep snapshot is unavailable')
    if any(e.feature_type == 'snapshot' for e in design.feature_log[index + 1:]):
        raise HTTPException(409, detail='Revert later snapshot features before editing this sweep')
    before = state.decode_design_snapshot(entry.design_snapshot_gz_b64)
    created = state.decode_design_snapshot(entry.post_state_gz_b64)
    result, _ = sweep_preview(before, body, include_geometry=True)
    op = next(o for o in created.deformations if o.id == 'sweep_' + entry.params['sweep_id'])
    helix = created.find_helix(op.affected_helix_ids[0])
    current = design.find_helix(helix.id)
    if current is None:
        raise HTTPException(409, detail='Restore this sweep before editing it')
    old_rotation, old_offset = _placement(created, helix)
    new_rotation, new_offset = _placement(design, current)
    rotation = new_rotation @ old_rotation.T
    offset = new_offset - rotation @ old_offset
    for key in ('origin_nm', 'path_nm', 'points_nm', 'helix_paths_nm'):
        result[key] = (np.asarray(result[key]) @ rotation.T + offset).tolist()
    result['point_rotation'] = rotation.tolist()
    frame = result['source_frame']
    frame['grid_origin'] = (rotation @ frame['grid_origin'] + offset).tolist()
    for key in ('frame_right', 'frame_up', 'axis_dir'):
        frame[key] = (rotation @ frame[key]).tolist()
    return result
