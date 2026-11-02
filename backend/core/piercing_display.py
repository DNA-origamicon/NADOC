"""Read-only ring-piercing markers from the atomistic display model.

Retain native nucleotide identity (including inserts, loop copies and extensions)
instead of exposing export-chain labels to the visualizer. The existing detector
owns all intersection criteria; this module only bounds and packages its results.
"""
from backend.core.ring_piercing import model_piercings, residue_key

_IDENTITY = ('helix_id', 'bp_index', 'direction', 'strand_id', 'copy_k',
             'crossover_id', 'extra_base_k', 'extension_id', 'ext_k')


def _atom(atom):
    return {**{key: getattr(atom, key) for key in _IDENTITY},
            'name': atom.name, 'position': [atom.x, atom.y, atom.z]}


def display_piercings(model, *, limit=200, progress=None):
    """Return at most ``limit`` hits, explicitly marking a truncated count."""
    measured = model_piercings(model, max_report=limit + 1, progress=progress)
    hits, residues = [], {}
    for hit in measured[:limit]:
        bond = [model.atoms[i] for i in hit['bond_serials']]
        ring = [model.atoms[i] for i in hit['ring_serials']]
        for atom in bond + ring:
            residues.setdefault(residue_key(atom), atom)
        hits.append({'bond': [_atom(a) for a in bond], 'ring': [_atom(a) for a in ring],
                     'ring_kind': hit['ring_kind']})
    # O5′ is the native Full backbone landmark. Use it when available, with the
    # detector atom as a fallback for incomplete/imported residues.
    for atom in model.atoms:
        key = residue_key(atom)
        if atom.name == "O5'" and key in residues:
            residues[key] = atom
    return {'count': len(hits), 'hits': hits, 'truncated': len(measured) > limit,
            'limit': limit, 'nucleotides': [_atom(a) for a in residues.values()]}
