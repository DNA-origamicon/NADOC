"""Full-view landmarks projected from the approved Corner atom placement.

These records are derived display data, never persisted construction inputs.
Residue poses are applied by the existing consumers after this projection.
"""

from collections import defaultdict

import numpy as np
from scipy.spatial.transform import Rotation

from backend.core.corner_seam_placement import corner_insert_links


def attach_corner_projection(design, nucleotides):
    links = corner_insert_links(design)
    if not links:
        return
    from backend.core.atomistic_cache import build_atomistic_model_cached

    source = design.model_copy(update={'nucleotide_transforms': []})
    model = build_atomistic_model_cached(source)
    owned = {link.id for link in links}
    inserts, endpoints = defaultdict(list), {}
    for atom in model.atoms:
        if atom.crossover_id in owned:
            inserts[(atom.crossover_id, atom.extra_base_k)].append(atom)
        elif atom.name == "O5'" and not atom.crossover_id and not atom.extension_id and not atom.copy_k:
            endpoints[(atom.helix_id, atom.bp_index, atom.direction)] = [atom.x, atom.y, atom.z]
    by_link = defaultdict(dict)
    for (link_id, k), atoms in inserts.items():
        points = {a.name: np.array([a.x, a.y, a.z]) for a in atoms}
        base = np.array([p for name, p in points.items()
                         if "'" not in name and name not in ('P', 'OP1', 'OP2')])
        center = base.mean(axis=0)
        _, _, axes = np.linalg.svd(base-center)
        normal = axes[-1]
        nitrogen = points['N9'] if 'N9' in points else points['N1']
        long_axis = nitrogen-points["C1'"]
        long_axis -= normal*np.dot(normal, long_axis)
        long_axis /= np.linalg.norm(long_axis)
        transverse = np.cross(normal, long_axis)
        frame = np.column_stack((long_axis, transverse, normal))
        by_link[link_id][str(k)] = {
            'backbone_position': points["O5'"].tolist(),
            'base_position': center.tolist(),
            'frame_rotation': Rotation.from_matrix(frame).as_quat().tolist(),
        }
    sites = {(n['helix_id'], n['bp_index'], n['direction']): n for n in nucleotides
             if not n.get('copy_k') and not n.get('is_modification')}
    for link in links:
        for end in ('three_prime', 'five_prime'):
            key = (getattr(link, end+'_helix_id'), getattr(link, end+'_bp'),
                   getattr(link, end+'_direction').value)
            if key not in sites:
                continue
            sites[key]['corner_native_backbone'] = sites[key]['backbone_position']
            sites[key]['backbone_position'] = endpoints[key]
            sites[key]['placement_source'] = 'corner-seam-o5-v1'
            # Carry on both endpoints so partial helix updates retain the seam.
            sites[key].setdefault('corner_inserts', {})[link.id] = by_link[link.id]
