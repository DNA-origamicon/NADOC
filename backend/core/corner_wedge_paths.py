"""Derive native indexed wedge paths from an existing deformed duplex.

These are outputs of the Corner command, not user-supplied coordinate snapshots.
Replay regenerates them from the preceding source and Corner's plane/rotation.
Existing twist, bend and sweep transport is retained at every nucleotide station.
"""

import numpy as np

from backend.core.corner_topology import corner_output_id
from backend.core.deformation import deformed_nucleotide_arrays, effective_helix_for_geometry
from backend.core.geometry import nucleotide_positions_arrays
from backend.core.models import DeformationOp
from backend.core.sweep_model import SweepParams


def _triads(arrays):
    x = arrays['radial_hats']
    z = arrays['axis_tangents']
    return np.stack((x, np.cross(z, x), z), axis=-1)


def _indexed_path(design, *, operation_id, side, source_id, helix_ids, start_bp, points, matrices):
    params = SweepParams(
        points_nm=points[:2].tolist(), origin_nm=points[0].tolist(),
        initial_rotation=matrices[0].ravel().tolist(), steps=len(points) - 1,
        path_length_nm=float(np.linalg.norm(np.diff(points, axis=0), axis=1).sum()),
        bp_positions_nm=points.tolist(), bp_frames=matrices.reshape(-1, 9).tolist(),
        preceding_op_ids=[op.id for op in design.deformations],
    )
    return DeformationOp(id=corner_output_id(operation_id, side, source_id), type='sweep',
        plane_a_bp=start_bp, plane_b_bp=start_bp + len(points) - 1,
        affected_helix_ids=list(helix_ids), params=params)


def paths_in_cluster_frame(paths, cluster):
    """Unapply the retained owner pose from derived world-space paths.

    Only the cut helices relinquish other placement memberships. Keeping this
    owner's pose preserves the placement of its uncut members and children.
    """
    from backend.core.deformation import _rot_from_quaternion

    rotation = _rot_from_quaternion(*cluster.rotation)
    pivot, translation = np.asarray(cluster.pivot), np.asarray(cluster.translation)
    result = []
    for path in paths:
        points = (np.asarray(path.params.bp_positions_nm) - pivot - translation) @ rotation + pivot
        frames = rotation.T @ np.asarray(path.params.bp_frames).reshape(-1, 3, 3)
        params = SweepParams.model_validate({**path.params.model_dump(),
            'points_nm': points[:2].tolist(), 'origin_nm': points[0].tolist(),
            'initial_rotation': frames[0].ravel().tolist(),
            'bp_positions_nm': points.tolist(), 'bp_frames': frames.reshape(-1, 9).tolist(),
        })
        result.append(path.model_copy(update={'params': params}))
    return tuple(result)


def corner_wedge_paths(design, helix, *, operation_id, outgoing_helix_id, center_nm, rotation):
    """Return incoming/outgoing native paths without creating or changing a Design.

    The owning command must remove superseded deformation scope for these
    helices and convert these world-space paths into their retained owner's
    frame with paths_in_cluster_frame. Other helices' ownership is unchanged.
    """
    if helix.native_residues or not 2 <= helix.length_bp <= 2048:
        raise ValueError('Corner indexed paths need 2–2048 duplex stations.')
    if any(t.helix_id == helix.id for t in design.nucleotide_transforms if t.kind == 'base'):
        raise ValueError('Corner must preserve independently posed residues before rebuilding this duplex path.')
    # Sample the material frame at every nominal station, including deleted
    # stations. The authored helix and its loop/skip marks are retained; native
    # projection later applies their per-copy offsets within these same frames.
    frame_helix = helix.model_copy(update={'loop_skips': []})
    native = effective_helix_for_geometry(frame_helix, design)
    raw = nucleotide_positions_arrays(native)
    current = deformed_nucleotide_arrays(frame_helix, design)
    if not np.array_equal(raw['bp_indices'], current['bp_indices']):
        raise ValueError('Corner source station identities changed during geometry preparation.')
    frames = _triads(current) @ _triads(raw).transpose(0, 2, 1)
    positions = current['axis_points']
    if (not np.allclose(frames[0::2], frames[1::2], atol=1e-8, rtol=0)
            or not np.allclose(positions[0::2], positions[1::2], atol=1e-8, rtol=0)):
        raise ValueError('Corner needs a common material frame for both strands of each duplex.')
    positions, frames = positions[0::2], frames[0::2]
    center, rotation = np.asarray(center_nm, dtype=float), np.asarray(rotation, dtype=float)
    if (center.shape != (3,) or rotation.shape != (3, 3)
            or not np.isfinite(center).all() or not np.isfinite(rotation).all()
            or not np.allclose(rotation.T @ rotation, np.eye(3), atol=1e-8, rtol=0)
            or not np.isclose(np.linalg.det(rotation), 1, atol=1e-8, rtol=0)):
        raise ValueError('Corner requires a proper world-space rigid rotation.')

    def path(identity, side, points, matrices):
        return _indexed_path(design, operation_id=operation_id, side=side, source_id=helix.id,
            helix_ids=[identity], start_bp=helix.bp_start, points=points, matrices=matrices)

    return (path(helix.id, 'incoming-path', positions, frames),
            path(outgoing_helix_id, 'outgoing-path', (positions - center) @ rotation.T + center,
                 rotation @ frames))


def corner_bundle_paths(design, helices, *, operation_id, outgoing_helix_ids, center_nm, rotation):
    """Preserve one shared cross-section frame per wedge, including staggered ends.

    A bundle with independently posed helices may not have one shared material
    frame. Reject that case rather than fitting a frame that silently moves it.
    """
    from backend.core.deformation import _bundle_centroid_and_tangent

    helices = tuple(helices)
    identities = [h.id for h in helices]
    if not helices or len(set(identities)) != len(identities) or set(outgoing_helix_ids) != set(identities):
        raise ValueError('Corner bundle requires unique source helices and a complete outgoing map.')
    start = min(h.bp_start for h in helices)
    end = max(h.bp_start + h.length_bp for h in helices)
    if end - start > 2048:
        raise ValueError('Corner bundle path exceeds the indexed station budget.')
    effective = [effective_helix_for_geometry(h, design) for h in helices]
    centroid, tangent = _bundle_centroid_and_tangent(effective)
    positions = np.full((end - start, 3), np.nan)
    frames = np.full((end - start, 3, 3), np.nan)
    filled = np.zeros(end - start, dtype=bool)
    for helix, rest in zip(helices, effective):
        incoming, _ = corner_wedge_paths(design, helix, operation_id=operation_id,
            outgoing_helix_id=outgoing_helix_ids[helix.id], center_nm=center_nm, rotation=rotation)
        local_frames = np.asarray(incoming.params.bp_frames).reshape(-1, 3, 3)
        offset = rest.axis_start.to_array() - centroid
        offset -= np.dot(offset, tangent) * tangent
        local_positions = np.asarray(incoming.params.bp_positions_nm) - local_frames @ offset
        indices = np.arange(helix.bp_start - start, helix.bp_start - start + helix.length_bp)
        occupied = filled[indices]
        if (not np.allclose(positions[indices[occupied]], local_positions[occupied], atol=1e-8, rtol=0)
                or not np.allclose(frames[indices[occupied]], local_frames[occupied], atol=1e-8, rtol=0)):
            raise ValueError('Selected helices do not share a common material frame along the path.')
        positions[indices], frames[indices], filled[indices] = local_positions, local_frames, True
    if not filled.all():
        raise ValueError('Corner bundle has a gap in its source axis stations.')
    center, matrix = np.asarray(center_nm), np.asarray(rotation)
    source_id = '\n'.join(sorted(identities))
    return (
        _indexed_path(design, operation_id=operation_id, side='incoming-bundle', source_id=source_id,
            helix_ids=identities, start_bp=start, points=positions, matrices=frames),
        _indexed_path(design, operation_id=operation_id, side='outgoing-bundle', source_id=source_id,
            helix_ids=[outgoing_helix_ids[h] for h in identities], start_bp=start,
            points=(positions - center) @ matrix.T + center, matrices=matrix @ frames),
    )
