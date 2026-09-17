"""Rigidly adsorbed/tethered coating and permanently occupied biotin pockets.

No independent protein dynamics. Each monomer has a coarse steric sphere;
the authored biotin pocket is a body-fixed anchor on the mobile composite core.
"""
import numpy as np
from backend.core.constants import NM_TO_OXDNA
from backend.core.gold_strep_dna import pocket_geometry


def coating_grafts(particles, by_strand, seen):
    spheres, grafts = [], []
    for j, p in enumerate(particles):
        if not p.coating:
            if p.biotin_dna:
                raise ValueError('Biotin DNA requires a streptavidin coating')
            continue
        if not p.coating.poses:
            raise ValueError('Streptavidin coating has no authored poses')
        for ti, pose in enumerate(p.coating.poses):
            m = pose.to_array()
            for chain in 'ABCD':
                xyz = np.array([[a.x, a.y, a.z] for a in p.coating.protein.atoms
                                if a.chain_id == chain and a.name == 'CA'])
                if not len(xyz):
                    raise ValueError('Streptavidin requires four resolved monomer chains')
                center = m[:3, :3] @ xyz.mean(0) + m[:3, 3]
                spheres.append(dict(core=j, tetramer=ti, chain=chain,
                                    center=(center*NM_TO_OXDNA).tolist(),
                                    radius=1.1*NM_TO_OXDNA))
        occupied = set()
        for r in p.biotin_dna:
            if r.tetramer_index >= len(p.coating.poses):
                raise ValueError('Missing streptavidin tetramer')
            pocket = (r.tetramer_index, r.chain)
            if pocket in occupied or (p.coating.mode == 'biotin_tether' and r.chain == 'A'):
                raise ValueError('Biotin pocket already occupied or reserved for gold tether')
            occupied.add(pocket)
            indices = by_strand.get(r.strand_id, [])
            if not indices or indices[0] in seen:
                raise ValueError('Missing or multiply grafted biotinylated DNA 5′ terminus')
            seen.add(indices[0])
            anchor, _ = pocket_geometry(p, r.chain, r.tetramer_index)
            pose = p.pose.to_array()
            site = pose[:3, :3].T @ (anchor-pose[:3, 3])
            grafts.append(dict(dna=indices[0], core=j, site=(site*NM_TO_OXDNA).tolist(),
                               length=r.linker_nm*NM_TO_OXDNA, k=1.424,
                               strand_id=r.strand_id, attach_end='5p',
                               chemistry='biotin_teg', tetramer=r.tetramer_index,
                               chain=r.chain, gold_strep='rigid', strep_biotin='permanent'))
    if len(spheres) > 256:
        raise ValueError('Mobile coating approximation supports at most 64 tetramers total')
    return spheres, grafts
