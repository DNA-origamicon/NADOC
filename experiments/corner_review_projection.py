"""Full-style *diagnostic* landmarks read from an exact atom model.

This is not a placement or authoring provider. Both A/B panels use this same
projection so the Full toggle cannot substitute canonical insert positions for
the atoms actually under review. O5′ is the bead, the base heavy-atom centroid
is the slab center, and actual inter-residue O3′–P bonds supply the connectivity.
"""

from collections import defaultdict

import numpy as np


def full_model(model):
    groups = defaultdict(list)
    for atom in model.atoms:
        key = (atom.helix_id, atom.bp_index, atom.direction, atom.copy_k,
               atom.crossover_id, atom.extra_base_k)
        groups[key].append(atom)
    residues, owners = [], {}
    for atoms in groups.values():
        names = {a.name: a for a in atoms}
        if "O5'" not in names or "C1'" not in names:
            raise ValueError('The Corner review needs complete DNA residue landmarks.')
        points = {name: np.array([a.x, a.y, a.z]) for name, a in names.items()}
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
        row = {'strand_id': atoms[0].strand_id,
            'atom_serials': [a.serial for a in atoms],
            'backbone_position': points["O5'"].tolist(), 'base_position': center.tolist(),
            'slab_axes': np.column_stack((transverse, normal, long_axis)).tolist()}
        if not np.isfinite([row['backbone_position'], row['base_position'], *row['slab_axes']]).all():
            raise ValueError('Nonfinite diagnostic Full projection.')
        for atom in atoms:
            owners[atom.serial] = len(residues)
        residues.append(row)
    edges = []
    for i, j in model.bonds:
        if model.atoms[i].name == 'P' and model.atoms[j].name == "O3'":
            i, j = j, i
        if model.atoms[i].name == "O3'" and model.atoms[j].name == 'P' and owners[i] != owners[j]:
            edges.append([owners[i], owners[j]])
    return {'projection': 'diagnostic-atom-landmarks-v1', 'residues': residues, 'backbone_edges': edges}
