"""Independent all-nucleotide rigidity check carried forward from the D003 audit."""

import numpy as np

from backend.core.design_geometry import _geometry_for_design
from experiments.recorded_review_process import ProcessRequired


def audit_fit(before, after):
    fields = ('helices', 'strands', 'crossovers', 'forced_ligations', 'deformations')
    unchanged = {field: getattr(before, field) == getattr(after, field) for field in fields}
    if not all(unchanged.values()):
        raise ProcessRequired('Pose fitting changed molecular authoring fields')

    def keyed(design):
        return {(b['strand_id'], b['domain_index'], b['helix_id'], b['bp_index'],
                 b['direction'], b.get('copy_k', b.get('copy', 0))):
                np.asarray(b['backbone_position']) for b in _geometry_for_design(design)}

    left, right = keyed(before), keyed(after)
    if left.keys() != right.keys():
        raise ProcessRequired('Pose fit changed the nucleotide identity set')
    bodies = []
    for group in after.cluster_transforms:
        keys = [k for k in left if k[2] in group.helix_ids]
        if not keys:
            continue
        x, y = (np.asarray([mapping[k] for k in keys]) for mapping in (left, right))
        x, y = x - x.mean(0), y - y.mean(0)
        u, _, vt = np.linalg.svd(x.T @ y)
        rotation = u @ np.diag([1, 1, np.linalg.det(u @ vt)]) @ vt
        error = float(np.linalg.norm(x @ rotation - y, axis=1).max())
        if error >= 1e-8:
            raise ProcessRequired(f'Rigid body {group.name} changed internally: {error} nm')
        bodies.append({'helix_ids': group.helix_ids, 'nucleotides_checked': len(keys),
                       'max_nonrigid_displacement_nm': error})
    if not bodies:
        raise ProcessRequired('No occupied rigid body was independently checked')
    from tools.design_archive.relax_d003_clashes import audit
    clearance = audit(after)[0]
    if clearance['interbody_helix_pairs_below_2nm']:
        raise ProcessRequired('Clash-aware result retains interbody axis clearance violations')
    return {'unchanged_authoring_fields': unchanged, 'bodies': bodies,
            'clearance': clearance, 'atomistic_validation': False,
            'limitations': 'Coarse interbody clearance; fixed internal geometry; not folding validation.'}
