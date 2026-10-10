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
    from backend.api.crud import _seek_feature_log
    design = _seek_feature_log(design, -1)
    before = state.decode_design_snapshot(entry.design_snapshot_gz_b64)
    created = state.decode_design_snapshot(entry.post_state_gz_b64)
    result, _ = sweep_preview(before, body, include_geometry=True)
    op = next(o for o in created.deformations if o.id == 'sweep_' + entry.params['sweep_id'])
    helix = next((created.find_helix(hid) for hid in op.affected_helix_ids if design.find_helix(hid)), None)
    if helix is None:
        raise HTTPException(409, detail='Restore this sweep before editing it')
    current = design.find_helix(helix.id)
    old_rotation, old_offset = _placement(created, helix)
    new_rotation, new_offset = _placement(design, current)
    rotation = new_rotation @ old_rotation.T
    offset = new_offset - rotation @ old_offset
    for key in ('origin_nm', 'path_nm', 'points_nm', 'helix_paths_nm'):
        result[key] = (np.asarray(result[key]) @ rotation.T + offset).tolist()
    result['point_rotation'] = rotation.tolist()
    result['orientation_basis'] = (rotation @ np.asarray(result['orientation_basis'])).tolist()
    result['point_bases'] = (rotation @ np.asarray(result['point_bases'])).tolist()
    frame = result['source_frame']
    frame['grid_origin'] = (rotation @ frame['grid_origin'] + offset).tolist()
    for key in ('frame_right', 'frame_up', 'axis_dir'):
        frame[key] = (rotation @ frame[key]).tolist()
    candidate, warnings = prepare_sweep_edit(design, index, body.model_dump(mode='json'), history=False)
    from backend.core.deformation import deformed_helix_axes, deformed_nucleotide_arrays
    axes = deformed_helix_axes(candidate)
    result['helix_paths_nm'] = [axis.get('samples') or [axis['start'], axis['end']] for axis in axes]
    original_axes = {a['helix_id']: a for a in deformed_helix_axes(design)}
    affected = set(op.affected_helix_ids)
    result['edit_root_helix_ids'] = sorted(affected)
    attachment_ends = {}
    groups = []
    poses = {c.id: c for c in candidate.cluster_transforms}
    for item in design.feature_log[index+1:]:
        pose = poses.get('sweep-follow:' + item.id)
        if pose is None:
            continue
        source_id = item.params.get('ref_helix_id') or item.params.get('source_helix_id')
        if source_id not in affected:
            continue
        source_helix = design.find_helix(source_id)
        end = attachment_ends.get(source_id) or item.params.get('source_end')
        if end is None:
            bp = item.params.get('source_bp', source_helix.bp_start + source_helix.length_bp - 1)
            end = 'start' if abs(bp-source_helix.bp_start) < abs(bp-(source_helix.bp_start+source_helix.length_bp-1)) else 'end'
        groups.append({'helix_ids': list(pose.helix_ids), 'end': end})
        affected.update(pose.helix_ids)
        attachment_ends.update({hid: end for hid in pose.helix_ids})
    result['edit_attachment_groups'] = groups
    affected.update(a['helix_id'] for a in axes if a != original_axes.get(a['helix_id']))
    result['edit_helix_ids'] = sorted(affected)
    result['helix_path_ids'] = [a['helix_id'] for a in axes]
    arrays = {h.id: deformed_nucleotide_arrays(h, candidate) for h in candidate.helices if h.id in affected}
    paths = []
    def append_path(points):
        if points:
            stride = max(1, len(points) // 2048)
            paths.append(points[::stride] + ([points[-1]] if (len(points)-1) % stride else []))

    for strand in candidate.strands:
        points = []
        for dom in strand.domains:
            if dom.helix_id not in affected:
                append_path(points)
                points = []
                continue
            arr = arrays[dom.helix_id]
            lo, hi = sorted((dom.start_bp, dom.end_bp))
            mask = ((arr['bp_indices'] >= lo) & (arr['bp_indices'] <= hi)
                    & (arr['directions'] == (0 if dom.direction.value == 'FORWARD' else 1)))
            selected = np.flatnonzero(mask)
            selected = selected[np.argsort(arr['bp_indices'][selected], kind='stable')]
            if dom.direction.value == 'REVERSE':
                selected = selected[::-1]
            points.extend(arr['positions'][selected].tolist())
        append_path(points)
    result['edit_backbones_nm'] = paths
    from backend.core.validator import validate_design
    result['edit_warnings'] = list(dict.fromkeys(warnings + [r.message for r in validate_design(candidate).results if not r.ok]))
    return result


def prepare_sweep_edit(design, index, params, *, history=True):
    """Build a candidate and rebase every saved routing boundary atomically."""
    from backend.core.sweep import SweepRequest, build_sweep
    from backend.core.sweep_edit import SweepEdit
    from backend.core.design_diff import encode_child_diff
    from backend.core.models import Direction
    from backend.api.crud import _replay_minor_op, _seek_feature_log
    from backend.core.feature_evaluation import evaluate_child_prefix
    from backend.api.routes_sweep import _guard

    entry = design.feature_log[index]
    if entry.evicted or not entry.design_snapshot_gz_b64 or not entry.post_state_gz_b64:
        raise HTTPException(410, detail='Sweep snapshot is unavailable')
    request = SweepRequest.model_validate({**{k:v for k,v in entry.params.items() if k in SweepRequest.model_fields},
                                          **params, 'sweep_id': entry.params['sweep_id']})
    _guard(design, request)
    before = state.decode_design_snapshot(entry.design_snapshot_gz_b64)
    created = state.decode_design_snapshot(entry.post_state_gz_b64)
    rebuilt = build_sweep(before, request)
    later = design.feature_log[index + 1:]
    if later:
        for key in ('cells', 'plane', 'source_helix_id', 'source_end', 'strand_filter', 'ligate_adjacent'):
            if request.model_dump(mode='json')[key] != entry.params.get(key, SweepRequest.model_fields[key].default):
                raise ValueError('Keep the existing sweep footprint and attachment when editing a path with downstream features.')
    attachments = []
    for item in later:
        if item.feature_type != 'snapshot' or not item.design_snapshot_gz_b64 or not item.post_state_gz_b64:
            continue
        source = item.params.get('ref_helix_id') or item.params.get('source_helix_id')
        if not source or item.params.get('detach_source'):
            continue
        pre = state.decode_design_snapshot(item.design_snapshot_gz_b64)
        post = state.decode_design_snapshot(item.post_state_gz_b64)
        helix = pre.find_helix(source)
        if helix is None:
            continue
        end = item.params.get('source_end')
        if end is None:
            bp = item.params.get('source_bp', helix.bp_start + helix.length_bp - 1)
            end = 'start' if abs(bp-helix.bp_start) < abs(bp-(helix.bp_start+helix.length_bp-1)) else 'end'
        previous_ids = {h.id for h in pre.helices}
        source_bp = item.params.get('source_bp')
        if source_bp is None:
            source_bp = helix.bp_start + (helix.length_bp-1 if end == 'end' else 0)
        attachments.append((item.id, source, end, source_bp, [h.id for h in post.helices if h.id not in previous_ids]))
    if not later:
        log = list(design.feature_log)
        if history:
            payload, size = state.encode_design_snapshot(rebuilt)
            log[index] = entry.model_copy(update={'params': {**entry.params, **request.model_dump(mode='json')},
                'post_state_gz_b64': payload, 'post_state_size_bytes': size})
        return rebuilt.copy_with(feature_log=log, feature_log_cursor=-1), []
    resized = []
    detach_sources = ()
    if request.detach_source and request.source_helix_id and not entry.params.get('detach_source', False):
        from backend.core.sweep import sweep_source
        detach_sources = {h.id for h in sweep_source(before, request)['sources'].values()}
    edit = SweepEdit(created, rebuilt, entry.params['sweep_id'], attachments, resized, detach_sources)
    log = list(design.feature_log)
    if history:
        payload, size = state.encode_design_snapshot(rebuilt)
        log[index] = entry.model_copy(update={'params': {**entry.params, **request.model_dump(mode='json')},
            'post_state_gz_b64': payload, 'post_state_size_bytes': size})

    for j in range(index+1, len(log)):
        item = design.feature_log[j]
        changes = {}
        if item.feature_type == 'routing-cluster':
            if item.evicted or not item.pre_state_gz_b64 or not item.post_state_gz_b64:
                raise HTTPException(410, detail='A later routing snapshot is unavailable; undo to a recoverable state before editing the sweep.')
            children = []
            original = state.decode_design_snapshot(item.pre_state_gz_b64)
            recorded_post = state.decode_design_snapshot(item.post_state_gz_b64)
            overhang_metadata = {o.id:o for o in [*original.overhangs, *recorded_post.overhangs]}
            mapped = edit.rebase(original)
            if history:
                changes['pre_state_gz_b64'], changes['pre_state_size_bytes'] = state.encode_design_snapshot(mapped)
            for child in item.children:
                if child.op_subtype == 'strand-end-resize':
                    for resize in child.params.get('entries', []):
                        sid, end, hid = resize['strand_id'], resize['end'], resize['helix_id']
                        strand = next((s for s in original.strands if s.id == sid), None)
                        if strand and strand.domains:
                            dom = strand.domains[0 if end == '5p' else -1]
                            bp = dom.start_bp if end == '5p' else dom.end_bp
                            upper = (end == '3p') == (dom.direction == Direction.FORWARD)
                            resized.append((hid, dom.direction, bp + int(upper), bp + int(upper) + resize['delta_bp']))
                try:
                    original = evaluate_child_prefix(original, [child], _replay_minor_op, optimized=True)
                except NotImplementedError as exc:
                    raise ValueError(f'Cannot reconstruct legacy routing step {child.label}; its saved diff is unavailable.') from exc
                # Older routing diffs omitted OverhangSpec records. Recover
                # referenced metadata from the enclosing snapshot when available.
                known = {o.id for o in original.overhangs}
                needed = {d.overhang_id for s in original.strands for d in s.domains if d.overhang_id}
                recovered = [overhang_metadata[oid] for oid in needed-known if oid in overhang_metadata]
                if recovered:
                    original = original.copy_with(overhangs=[*original.overhangs, *recovered])
                candidate = edit.rebase(original)
                if history:
                    added, removed, modified, size = encode_child_diff(mapped, candidate)
                    children.append(child.model_copy(update={'params': edit.parameters(child.params), 'diff_added_b64': added,
                        'diff_removed_b64': removed, 'diff_modified_b64': modified, 'diff_size_bytes': size}))
                mapped = candidate
            if history:
                changes['children'] = children
        if history:
            if getattr(item, 'params', None):
                changes['params'] = edit.parameters(item.params)
            if getattr(item, 'op_snapshot', None):
                changes['op_snapshot'] = edit.deformation(item.op_snapshot)
            for payload, size in [('design_snapshot_gz_b64','snapshot_size_bytes'),
                                  ('pre_state_gz_b64','pre_state_size_bytes'),
                                  ('post_state_gz_b64','post_state_size_bytes')]:
                if payload not in changes and getattr(item, payload, None):
                    changes[payload], changes[size] = state.encode_design_snapshot(edit.rebase(state.decode_design_snapshot(getattr(item,payload))))
            log[j] = item.model_copy(update=changes)
    full = _seek_feature_log(design, -1)
    candidate = edit.rebase(full) if later else rebuilt.copy_with(cluster_transforms=full.cluster_transforms)
    if history:
        candidate = _seek_feature_log(candidate.copy_with(feature_log=log, feature_log_cursor=-1), -1)
    return candidate, sorted(edit.warnings)


def commit_sweep_edit(design, index, params):
    from backend.api.crud import _design_replace_response
    from backend.core.validator import validate_design
    try:
        updated, warnings = prepare_sweep_edit(design, index, params)
    except ValueError as exc:
        raise HTTPException(422, detail=str(exc)) from exc
    report = validate_design(updated)
    conflicts = sum(not r.ok for r in report.results)
    if conflicts:
        warnings.append(f'Sweep updated with {conflicts} topology validation issue(s); inspect the Validation report.')
    state.set_design(updated, expected_revision=params.get('expected_revision'))
    response = _design_replace_response(design, updated, report)
    response['placement_warnings'] = list(dict.fromkeys(warnings))
    return response
