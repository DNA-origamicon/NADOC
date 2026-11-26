"""Atomistic DISPLAY projection of strand-owned loops.

Rigid measured nucleotide templates follow the existing Full loop pose. O5′ is
anchored to its backbone bead; ring orientation follows its slab. Connectivity
is explicit but linker geometry is unrelaxed. This is not a simulation seed.
"""
from collections import defaultdict
from functools import lru_cache

import numpy as np
from scipy.spatial.transform import Rotation

VERSION = 'strand-loop-display-atoms-v3-ring-priority'


@lru_cache(maxsize=8)
def loop_template(residue, direction):
    from backend.core.atomistic import _native_local_defs
    from backend.core.md_base_frames import measured_base_frames, ordered_ring_indices
    from backend.core.native_slab_placement import _frame
    definitions = _native_local_defs(residue, direction)
    names = {atom[0]: i for i, atom in enumerate(definitions)}
    xyz = np.array([atom[2:] for atom in definitions])
    anchor = names["O5'"]
    ring = ordered_ring_indices(names)
    inward = np.full((1, 3), np.nan)
    _, normals = measured_base_frames(xyz, np.array([anchor]),
        [(np.array([0]), ring[None])], xyz[[anchor]], None, None, inward_out=inward)
    # Match the same chemically named ring span used by native measured slabs.
    frame = _frame(inward[0], normals[0])
    return definitions, xyz[anchor].copy(), frame


def append_loop_atoms(model, design, exclude_helix_ids=None):
    """Append loop residues after all parent atom placement; never move host atoms."""
    from backend.core.atomistic import Atom, BASE_TEMPLATES, _SUGAR_BONDS, _BASE_CHAR_TO_RESIDUE
    from backend.core.design_geometry import _geometry_for_design
    if not any(s.loops for s in design.strands):
        return model
    records = _geometry_for_design(design, extension_slabs=False)
    loops = [r for r in records if r.get('loop_order', 0) > 0
             and r['helix_id'] not in (exclude_helix_ids or set())]
    if not loops:
        return model
    residues = defaultdict(dict)
    for atom in model.atoms:
        if atom.crossover_id is None and atom.extension_id is None:
            key = atom.strand_id, atom.helix_id, atom.bp_index, atom.direction, atom.copy_k or 0
            residues[key][atom.name] = atom
    original_order = {a.serial: (a.seq_num, 0) for a in model.atoms}
    additions = defaultdict(list)
    unknown = 0
    for record in loops:
        key = (record['strand_id'], record['helix_id'], record['bp_index'], record['direction'])
        ordinal = record['loop_order']
        if (*key, ordinal) in residues:
            raise ValueError('Atomistic reference already contains loop copies; cannot safely merge loop display atoms')
        anchor = residues.get((*key, 0))
        if not anchor:
            raise ValueError('Loop atomistic display is missing its attachment residue')
        residue = _BASE_CHAR_TO_RESIDUE.get(record.get('nucleobase'), 'DT')
        unknown += int(record.get('nucleobase', 'N').upper() not in 'ACGT')
        definitions, local_o5, local_frame = loop_template(residue, record['direction'])
        rotation = Rotation.from_quat(record['slab_quaternion']).as_matrix() @ local_frame.T
        origin = np.array(record['backbone_position']) - rotation @ local_o5
        new = {}
        for name, element, *position in definitions:
            xyz = origin + rotation @ np.asarray(position)
            atom = Atom(serial=len(model.atoms), name=name, element=element, residue=residue,
                chain_id=anchor['P'].chain_id, seq_num=anchor['P'].seq_num,
                x=float(xyz[0]), y=float(xyz[1]), z=float(xyz[2]),
                strand_id=key[0], helix_id=key[1], bp_index=key[2], direction=key[3], copy_k=ordinal)
            original_order[atom.serial] = (anchor['P'].seq_num, ordinal)
            model.atoms.append(atom)
            new[name] = atom
        for a, b in [*_SUGAR_BONDS, *BASE_TEMPLATES[residue][1]]:
            if a in new and b in new:
                model.bonds.append((new[a].serial, new[b].serial))
        additions[key].append((ordinal, new))
    # Replace the actual outgoing bond, including a domain/crossover boundary.
    # No synthetic shortcut remains between the original attachment residues.
    for key, inserted in additions.items():
        anchor = residues[(*key, 0)]
        src = anchor["O3'"].serial
        outgoing = [(index, b if a == src else a) for index, (a, b) in enumerate(model.bonds)
                    if (a == src or b == src) and model.atoms[b if a == src else a].name == 'P']
        if len(outgoing) != 1:
            raise ValueError('Loop attachment needs exactly one outgoing phosphodiester bond')
        index, dst = outgoing[0]
        model.bonds.pop(index)
        previous = src
        for _, atoms in sorted(inserted):
            model.bonds.append((previous, atoms['P'].serial))
            previous = atoms["O3'"].serial
        model.bonds.append((previous, dst))
    # Re-number residues and atom serials in true 5′→3′ chain order, preserving
    # existing extension/crossover ordering and every original coordinate.
    chains = {}
    for a in model.atoms:
        chains.setdefault(a.chain_id, len(chains))
    ordered = sorted(model.atoms, key=lambda a: (chains[a.chain_id], original_order[a.serial], a.serial))
    serial_map = {atom.serial: i for i, atom in enumerate(ordered)}
    residue_numbers = {}
    for atom in ordered:
        chain = residue_numbers.setdefault(atom.chain_id, {})
        ordering = original_order[atom.serial]
        atom.seq_num = chain.setdefault(ordering, len(chain) + 1)
        atom.serial = serial_map[atom.serial]
    model.atoms = ordered
    model.bonds = [(serial_map[a], serial_map[b]) for a, b in model.bonds]
    model.warnings.append('Insertion-loop atoms are rigid display templates; inter-residue linkers are unrelaxed.')
    if unknown:
        model.warnings.append(f'{unknown} unassigned loop bases use the standard thymine display placeholder; their sequence remains N.')
    return model


def loop_surface_cloud(design):
    """Exact display atom cloud, including all loop copies and their identities."""
    from backend.core.atomistic import build_atomistic_model, VDW_RADIUS, DEFAULT_VDW_RADIUS
    from backend.core.surface import _nuc_key
    model = build_atomistic_model(design, fast_bridges=True, strand_loop_display=True)
    return (np.array([[a.x, a.y, a.z] for a in model.atoms], dtype=np.float32),
            np.array([VDW_RADIUS.get(a.element, DEFAULT_VDW_RADIUS) for a in model.atoms], dtype=np.float32),
            [a.strand_id for a in model.atoms], [_nuc_key(a) for a in model.atoms])
