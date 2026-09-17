"""Chemical graph contract for the existing 5′ Biotin-TEG modification.

Bond orders/valence are chemical identity, not force-field atom types or charges.
"""
from backend.core.biotin_atomistic import _unconnected_teg


def chemical_definition():
    names, elements, _, pairs = _unconnected_teg()
    doubles = {frozenset(('C3', 'O3')), frozenset(('C11', 'O11'))}
    bonds = [dict(atoms=[names[i], names[j]], order=2 if frozenset((names[i], names[j])) in doubles else 1)
             for i, j in pairs]
    valence = dict.fromkeys(names, 0)
    for b in bonds:
        for a in b['atoms']: valence[a] += b['order']
    valence['O4T'] += 1  # Actual fourth phosphate oxygen; no terminal O–H.
    atoms = [dict(name=n, element=e, hydrogen_count={'C': 4, 'N': 3, 'O': 2, 'S': 2}[e]-valence[n])
             for n, e in zip(names, elements)]
    return dict(schema='nadoc.biotin-teg-chemistry.v1', atoms=atoms, bonds=bonds,
                boundary=dict(ligand_atom='O4T', dna_atom='P', order=1,
                              retain_dna_atoms=['P', 'OP1', 'OP2', "O5'"],
                              forbid_dna_patch='5TER'),
                ring_centers=['C2', 'C4', 'C5'], stereochemistry='retain 1STP bound D-biotin coordinates',
                sources=['https://www.rcsb.org/ligand/BTN',
                         'https://www.idtdna.com/site/Catalog/Modifications/GetStructureImage/2100'],
                forcefield_parameters_present=False)
