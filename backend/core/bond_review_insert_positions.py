"""Read-only junction positions from the existing desktop Full placement.

Keep recorded half order for placement and use sim_k for strand-walker identity.
Reversing the input endpoints changes the native local frame, so it is not an
equivalent way to reverse the strand traversal.
"""

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.topology_integrity import forced_edge, half_slot
from backend.core.vr_scene_projection import crossover_extra_base_full_projections


def insert_positions(design, nucleotides):
    sites = {(n['helix_id'], n['bp_index'], n['direction']): n
             for n in nucleotides if not n.get('copy_k') and not n.get('is_modification')}
    ends = {(d.helix_id, d.end_bp, d.direction.value)
            for s in design.strands for d in s.domains}
    poses = {(p.crossover_id, p.extra_base_k): p
             for p in design.nucleotide_transforms if p.kind == 'extra_base'}
    # Photoproduct coordinates have a separate placement authority. Leave them
    # unmeasured here rather than accidentally certify their precursor geometry.
    products = {key for lesion in design.photoproduct_junctions
                for key in lesion.design_coordinates}
    records = [(r, half_slot(r.half_a), half_slot(r.half_b)) for r in design.crossovers]
    records += [(r, *forced_edge(r)) for r in design.forced_ligations]
    positions = {}
    for record, first, second in records:
        if not record.extra_bases or first not in sites or second not in sites:
            continue
        corner = sites[first].get('corner_inserts', {}).get(record.id)
        if corner:
            from types import SimpleNamespace
            projections = [SimpleNamespace(sim_k=int(k), bead_center=np.asarray(row['backbone_position']))
                           for k, row in corner.items()]
        else:
            projections = crossover_extra_base_full_projections(
                sites[first], sites[second], record.extra_bases,
                sim_reversed=first not in ends, local_frame_reversed=first[2] == 'REVERSE')
        for row in projections:
            if f'__xb__:{record.id}:{row.sim_k}' in products:
                continue
            point = row.bead_center
            pose = poses.get((record.id, row.sim_k))
            if pose:
                pivot = np.asarray(pose.pivot)
                point = pivot + Rotation.from_quat(pose.rotation).apply(point-pivot) + pose.translation
            if np.isfinite(point).all():
                positions[('__xb__', record.id, row.sim_k)] = tuple(float(v) for v in point)
    return positions
