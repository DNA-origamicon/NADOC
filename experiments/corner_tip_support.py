"""Measure rigid duplex support against a Corner face without authoring a cut.

Outputs are endpoint proposals and measurements, not a Design. No atoms,
topology, phase or molecular placement are changed. Flexible phosphate atoms
are excluded because the seam builder will reconstruct them; complete sugar
and base rings retain their actual native coordinates.
"""

import math

import numpy as np
from scipy.spatial import cKDTree

from backend.core.atomistic import build_atomistic_model, VDW_RADIUS, DEFAULT_VDW_RADIUS

FLEXIBLE = {"O3'", 'P', 'OP1', 'OP2', "O5'"}


def measure_support(source, guide):
    selected = {row['helix_id'] for row in guide['cuts']}
    model = build_atomistic_model(source, exclude_helix_ids={h.id for h in source.helices}-selected,
                                  fast_bridges=True)
    by_helix = {hid: [] for hid in selected}
    for atom in model.atoms:
        if atom.helix_id in selected and atom.name not in FLEXIBLE and not atom.crossover_id:
            by_helix[atom.helix_id].append(atom)
    center, normal, matrix = (np.asarray(guide[key]) for key in ('center_nm', 'plane_normal', 'rotation'))
    labels = {h.id: h.label if h.label is not None else i for i, h in enumerate(source.helices)}
    rows, incoming_points, outgoing_points = [], [], []
    for cut in guide['cuts']:
        hid = cut['helix_id']
        atoms = by_helix[hid]
        positions = np.asarray([[a.x, a.y, a.z] for a in atoms])
        bps = np.asarray([a.bp_index for a in atoms])
        moved = (positions-center) @ matrix.T + center
        signed = (positions-center) @ normal
        moved_signed = (moved-center) @ normal
        radii = np.asarray([VDW_RADIUS.get(a.element, DEFAULT_VDW_RADIUS) for a in atoms])
        old_a, old_b = math.floor(cut['incoming_bp']), math.ceil(cut['outgoing_bp'])
        stations = np.unique(bps)
        maxima = np.asarray([(signed+radii)[bps == bp].max() for bp in stations])
        minima = np.asarray([(moved_signed-radii)[bps == bp].min() for bp in stations])
        prefix = np.maximum.accumulate(maxima)
        suffix = np.minimum.accumulate(minima[::-1])[::-1]
        incoming = stations[(stations <= old_a) & (prefix <= 0)]
        outgoing = stations[(stations >= old_b) & (suffix >= 0)]
        if not len(incoming) or not len(outgoing):
            raise ValueError('No complete native duplex tip fits its retained half-space.')
        a, b = int(incoming[-1]), int(outgoing[0])
        incoming_points.extend(positions[bps <= old_a])
        outgoing_points.extend(moved[bps >= old_b])
        rows.append({'helix_label': labels[hid], 'helix_id': hid,
            'incoming_original': old_a, 'outgoing_original': old_b,
            'incoming_proposal': a, 'outgoing_proposal': b,
            'incoming_rigid_atoms_across_face': int(np.count_nonzero((bps <= old_a) & (signed > 0))),
            'outgoing_rigid_atoms_across_face': int(np.count_nonzero((bps >= old_b) & (moved_signed < 0))),
            'proposed_incoming_vdw_clearance_nm': float(-(signed+radii)[bps <= a].max()),
            'proposed_outgoing_vdw_clearance_nm': float((moved_signed-radii)[bps >= b].min())})
    nearest = cKDTree(incoming_points).query(outgoing_points)[0]
    return {'interpretation': 'Native rigid-atom van der Waals half-space support; no seam acceptance.',
            'original_min_cross_wedge_distance_nm': float(nearest.min()),
            'original_outgoing_atoms_with_contact_below_008nm': int(np.count_nonzero(nearest < .08)),
            'proposals': rows}
