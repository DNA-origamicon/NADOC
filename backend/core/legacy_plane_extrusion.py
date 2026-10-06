"""Append painted cells to an unambiguous, pre-frame desktop lattice."""
import math
from backend.core.lattice import _lattice_position, make_bundle_segment
from backend.core.vr_extrude_draft import validate_painted_footprint


def legacy_plane_source(design, plane):
    """Resolve the exact transverse origin and placement used by new cells."""
    # Older desktop parts have grid addresses but no LatticeFrame records.
    # Verify every helix shares one rest lattice rather than guessing from the
    # first helix (the desktop segment builder's origin convention).
    if not design.helices or design.lattice_frames or any(
        h.lattice_frame_id or h.grid_pos is None for h in design.helices
    ):
        raise ValueError('unambiguous legacy lattice required')
    if design.deformations or design.nucleotide_transforms:
        raise ValueError('select an end or place freeform for a deformed lattice')
    transverse, normal = {'XY': (('x', 'y'), 'z'), 'XZ': (('x', 'z'), 'y'),
                          'YZ': (('y', 'z'), 'x')}[plane]
    origin = None
    for helix in design.helices:
        lattice = _lattice_position(*helix.grid_pos, design.lattice_type)
        offset = tuple(getattr(helix.axis_start, a)-v for a, v in zip(transverse, lattice))
        if origin is None:
            origin = offset
        if (any(not math.isclose(a, b, abs_tol=1e-5, rel_tol=0) for a, b in zip(origin, offset))
                or any(not math.isclose(getattr(helix.axis_start, a), getattr(helix.axis_end, a),
                                        abs_tol=1e-5, rel_tol=0) for a in transverse)
                or abs(getattr(helix.axis_end, normal)-getattr(helix.axis_start, normal)) < 1e-9):
            raise ValueError('select an end or place freeform for mixed source planes')
    clusters = design.cluster_transforms
    if clusters and (len(clusters) != 1 or clusters[0].domain_ids or
                     clusters[0].parent_cluster_id or
                     set(clusters[0].helix_ids) != {h.id for h in design.helices}):
        raise ValueError('select an end or place freeform for multiple placements')
    return origin, clusters


def append_legacy_plane_bundle(design, cells, length_bp, *, plane):
    _, clusters = legacy_plane_source(design, plane)
    footprint = validate_painted_footprint({'lattice_type': design.lattice_type.value, 'cells': cells})
    occupied = {tuple(h.grid_pos) for h in design.helices}
    if any(tuple(cell) in occupied for cell in footprint['cells']):
        raise ValueError('painted cell already occupied')
    updated = make_bundle_segment(design, [tuple(c) for c in footprint['cells']], length_bp, plane=plane)
    if clusters:
        updated = updated.copy_with(cluster_transforms=[clusters[0].model_copy(update={
            'helix_ids': [*clusters[0].helix_ids, *(h.id for h in updated.helices[len(design.helices):])],
        })])
    return updated
