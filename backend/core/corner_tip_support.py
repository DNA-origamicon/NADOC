"""Native rigid-residue support for topological Corner endpoint planning.

Read-only template/frame queries. No molecular positions, constants or source
topology are changed. Flexible phosphate atoms are reconstructed at the seam;
retained sugar/base atoms must fit inside their own miter half-space.
"""

import numpy as np

from backend.core.corner_routing import DuplexCut

FLEXIBLE_PHOSPHATE_ATOMS = frozenset({"O3'", 'P', 'OP1', 'OP2', "O5'"})


def rigid_tip_support(design, helices, center_nm, normal, rotation, *, check_cancel=None,
                      station_ranges=None):
    """Return native van der Waals signed support at each nominal bp station."""
    from backend.core.atomistic import (
        _atom_frames_batch, _build_sequence_map, _fold_design_geometry_into_frames,
        _native_local_defs, atomistic_phase_offset_rad, VDW_RADIUS, DEFAULT_VDW_RADIUS,
    )
    from backend.core.constants import BDNA_RISE_PER_BP
    from backend.core.deformation import effective_helix_for_geometry
    from backend.core.geometry import nucleotide_positions_arrays

    center, normal, rotation = np.asarray(center_nm), np.asarray(normal), np.asarray(rotation)
    sequences = _build_sequence_map(design)
    support = {}
    for helix in helices:
        if check_cancel:
            check_cancel()
        rest = effective_helix_for_geometry(helix, design)
        raw = nucleotide_positions_arrays(rest)
        bps, directions = raw['bp_indices'], raw['directions']
        if not len(bps):
            raise ValueError('Corner has no native duplex sites at the selected plane.')
        strings = np.where(directions == 0, 'FORWARD', 'REVERSE')
        axis_points = rest.axis_start.to_array() + (bps-rest.bp_start)[:, None] * BDNA_RISE_PER_BP * raw['axis_tangents']
        origins, frames = _atom_frames_batch(raw['positions'], raw['axis_tangents'], raw['base_normals'],
            axis_points, directions == 0, np.full(len(bps), rest.direction.value == 'FORWARD'),
            phase_rad=atomistic_phase_offset_rad(design), radial_hat=raw['radial_hats'])
        origins, frames = _fold_design_geometry_into_frames(design, origins, frames,
            [(helix.id, int(bp), str(direction)) for bp, direction in zip(bps, strings)])
        copies, residues = {}, []
        for bp, direction in zip(bps, strings):
            key = (helix.id, int(bp), str(direction))
            copy = copies.get(key, 0)
            copies[key] = copy + 1
            base = sequences.get((*key, copy) if copy else key, 'N')
            residues.append({'A': 'DA', 'C': 'DC', 'G': 'DG', 'T': 'DT'}.get(base, 'DT'))
        residues = np.asarray(residues)
        incoming = np.empty(len(bps))
        outgoing = np.empty(len(bps))
        for residue, direction in sorted(set(zip(residues, strings))):
            rows = (residues == residue) & (strings == direction)
            defs = [a for a in _native_local_defs(str(residue), str(direction))
                    if a[0] not in FLEXIBLE_PHOSPHATE_ATOMS]
            local = np.asarray([a[2:] for a in defs])
            radii = np.asarray([VDW_RADIUS.get(a[1], DEFAULT_VDW_RADIUS) for a in defs])
            world = origins[rows, None, :] + np.einsum('nij,kj->nki', frames[rows], local)
            incoming[rows] = ((world-center) @ normal + radii).max(axis=1)
            moved = (world-center) @ rotation.T
            outgoing[rows] = (moved @ normal - radii).min(axis=1)
        stations, indices = np.unique(bps, return_inverse=True)
        maximum = np.full(len(stations), -np.inf)
        minimum = np.full(len(stations), np.inf)
        np.maximum.at(maximum, indices, incoming)
        np.minimum.at(minimum, indices, outgoing)
        if station_ranges is not None:
            lo, hi = station_ranges[helix.id]
            occupied = (stations >= lo) & (stations <= hi)
            stations, maximum, minimum = stations[occupied], maximum[occupied], minimum[occupied]
        support[helix.id] = {'stations': stations, 'incoming_max': maximum, 'outgoing_min': minimum}
    return support


def refine_duplex_cuts(cuts, support):
    """Retreat each endpoint to retain complete, separated rigid duplex tips."""
    result = []
    for cut in cuts:
        row = support[cut.helix_id]
        stations = row['stations']
        incoming = stations[(stations <= cut.incoming_last_bp)
                            & (np.maximum.accumulate(row['incoming_max']) <= 0)]
        outgoing = stations[(stations >= cut.outgoing_first_bp)
                            & (np.minimum.accumulate(row['outgoing_min'][::-1])[::-1] >= 0)]
        if not len(incoming) or not len(outgoing):
            raise ValueError('The corner leaves insufficient duplex material after tip clearance.')
        result.append(DuplexCut(cut.helix_id, int(incoming[-1]), int(outgoing[0])))
    return tuple(result)
