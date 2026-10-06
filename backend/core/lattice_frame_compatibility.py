"""Conservative metadata repair for desktop segments predating frame propagation.

A frame is a logical rest-lattice address, not editable cluster membership.
Only a unique canonical lattice with the same rigid placement may be inferred.
No positions, transforms, deformations, strands or history are changed.
"""
import math


def repair_lattice_frame_membership(design):
    if not design.lattice_frames or all(h.lattice_frame_id for h in design.helices):
        return design
    from backend.core.lattice import _lattice_position

    identity = ([0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0], [0.0, 0.0, 0.0])
    clusters = {c.id: c for c in design.cluster_transforms}
    owners = {}
    domain_helices = {(s.id, i): d.helix_id for s in design.strands for i, d in enumerate(s.domains)}
    for cluster in design.cluster_transforms:
        for hid in set(cluster.helix_ids) | {domain_helices.get((d.strand_id, d.domain_index)) for d in cluster.domain_ids}:
            owners.setdefault(hid, []).append(cluster)

    def pose(cluster):
        return (cluster.translation, cluster.rotation, cluster.pivot)

    def canonical(helix, plane):
        if helix.grid_pos is None:
            return False
        transverse, normal = {'XY': ('xy', 'z'), 'XZ': ('xz', 'y'), 'YZ': ('yz', 'x')}[plane]
        coords = _lattice_position(*helix.grid_pos, design.lattice_type)
        return all(math.isclose(getattr(endpoint, axis), value, abs_tol=1e-5, rel_tol=0)
                   for endpoint in (helix.axis_start, helix.axis_end)
                   for axis, value in zip(transverse, coords)) and abs(
                       getattr(helix.axis_end, normal)-getattr(helix.axis_start, normal)) > 1e-9

    candidates = []
    for frame in design.lattice_frames:
        placement = clusters.get(frame.placement_cluster_id)
        members = [h for h in design.helices if h.lattice_frame_id == frame.id]
        if (placement and not placement.domain_ids and not placement.parent_cluster_id and members
                and all(canonical(h, frame.plane) for h in members)):
            candidates.append((frame, placement))
    helices = []
    changed = False
    for helix in design.helices:
        matches = []
        if helix.lattice_frame_id is None:
            placements = owners.get(helix.id, [])
            if len(placements) <= 1 and not any(c.domain_ids or c.parent_cluster_id for c in placements):
                actual = pose(placements[0]) if placements else identity
                matches = [frame.id for frame, placement in candidates
                           if actual == pose(placement) and canonical(helix, frame.plane)]
        if len(matches) == 1:
            helix = helix.model_copy(update={'lattice_frame_id': matches[0]})
            changed = True
        helices.append(helix)
    return design.copy_with(helices=helices) if changed else design
