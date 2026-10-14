"""Graph-only regression tests; run with the nadoc-qm Python for RDKit coverage."""
import json
from pathlib import Path

import pytest

Chem = pytest.importorskip('rdkit.Chem')
from backend.parameterization.photoproduct_stereo_candidates import _candidate_full_molecule, _cip_codes

# Independent target table: DNA-attached ordered stereocenters C5,C6,C5T,C6T.
EXPECTED = {
    'cis-syn': ('R','R','S','S'), 'cis-syn-II': ('S','S','R','R'),
    'trans-syn-I': ('S','S','S','S'), 'trans-syn-II': ('R','R','R','R'),
    'cis-anti-I': ('S','R','S','R'), 'cis-anti-II': ('R','S','R','S'),
    'trans-anti-I': ('R','S','S','R'), 'trans-anti-II': ('S','R','R','S'),
}


def source():
    fixture = json.loads((Path(__file__).parent/'fixtures/photoproducts/ttd_stereo_source.json').read_text())
    params = Chem.SmilesParserParams()
    params.removeHs = False
    mol = Chem.MolFromSmiles(fixture['smiles'], params)
    for atom in mol.GetAtoms():
        key = str(atom.GetAtomMapNum())
        if key in fixture['ring_atom_maps']:
            atom.SetProp('ccd_atom_id', fixture['ring_atom_maps'][key])
        atom.SetAtomMapNum(0)
    return mol


@pytest.mark.parametrize('stereo', EXPECTED)
@pytest.mark.parametrize('order', ['original', 'reverse', 'rotate'])
def test_ordered_stereochemistry_survives_bond_edits_and_atom_renumbering(stereo, order):
    mol = source()
    indices = list(range(mol.GetNumAtoms()))
    if order == 'reverse':
        indices.reverse()
    elif order == 'rotate':
        indices = indices[11:] + indices[:11]
    mol = Chem.RenumberAtoms(mol, indices)
    product = _candidate_full_molecule(mol, stereo)
    codes = _cip_codes(product)
    assert tuple(codes[k] for k in ('C5','C6','C5T','C6T')) == EXPECTED[stereo]
    # All source sugar configurations survive; only ring centers may change.
    for atom in mol.GetAtoms():
        if not atom.HasProp('ccd_atom_id'):
            assert product.GetAtomWithIdx(atom.GetIdx()).GetChiralTag() == atom.GetChiralTag()
