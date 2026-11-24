"""Native Corner display data, including explicit unpaired seam inventory.

The older deformation comparison DTO deliberately excludes inserted bases.
Corner uses the ordinary Full geometry and connection renderer contract instead
of weakening that closed DTO or silently omitting the inserted residues.
"""

from backend.core.bond_review_insert_positions import insert_positions
from backend.core.corner_seam_placement import observe_corner_placement
import numpy as np
from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design, _positions_for_design, _apply_ovhg_rotations_to_axes


def project_corner_straight(design, *, on_progress=None):
    straight = design.model_copy(update={'deformations': [], 'cluster_transforms': []})
    with observe_corner_placement(on_progress):
        positions, axes = _positions_for_design(straight)
    return {'straight_positions_by_helix': positions, 'straight_helix_axes': axes}


def project_corner_preview(design, *, on_progress=None, include_straight=True):
    with observe_corner_placement(on_progress):
        records = _geometry_for_design(design)
    sites = {(n['helix_id'], n['bp_index'], n['direction']): n for n in records}
    positions = insert_positions(design, records)
    inserts = []
    for link in design.forced_ligations:
        if not link.extra_bases:
            continue
        ends = [sites.get((getattr(link, end + '_helix_id'), getattr(link, end + '_bp'),
                          getattr(link, end + '_direction').value))
                for end in ('three_prime', 'five_prime')]
        if any(end is None for end in ends):
            raise ValueError('Corner preview cannot resolve an inserted seam endpoint.')
        points = [positions[('__xb__', link.id, k)] for k in range(len(link.extra_bases))]
        path = np.array([ends[0]['backbone_position'], *points, ends[1]['backbone_position']])
        inserts.append({'connection_id': link.id, 'sequence': link.extra_bases,
                        'backbone_positions': points,
                        'backbone_lengths_nm': np.linalg.norm(np.diff(path, axis=0), axis=1).tolist()})
    fields = ('helices', 'strands', 'crossovers', 'forced_ligations', 'deformations',
              'cluster_transforms', 'lattice_frames', 'overhangs')
    topology = {field: [value.model_dump(mode='json') for value in getattr(design, field)]
                for field in fields}
    topology['lattice_type'] = design.lattice_type.value
    axes = deformed_helix_axes(design)
    _apply_ovhg_rotations_to_axes(design, axes, records)
    component = {'component_kind': 'corner-preview-dna', 'component_version': 1,
            'representation': 'native-full-v1', 'units': 'nm', 'nucleotides': records,
            'helix_axes': axes,
            'display_topology': topology,
            'seam_inserts': inserts}
    if include_straight:
        component.update(project_corner_straight(design))
    return component
