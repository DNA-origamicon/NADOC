"""Construct and audit anti definition proposals; no MD, QM or force-field fitting.

Run in the nadoc-qm environment (RDKit). Writes a NEW output directory only.
The pre-correction archive and the RCSB source hashes are required inputs.
"""
from __future__ import annotations
import argparse
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from backend.parameterization.photoproduct_models import _ccd_atom_rows
from backend.parameterization.photoproduct_stereo_candidates import (
    _candidate_full_molecule, _cip_codes, _prune_to_n1_methyl_model,
    _stable_atom_map, _atom_index,
)
from backend.parameterization.photoproduct_stereo_independent import _openbabel_value
from backend.core.photoproduct_chemistry import signed_tetrahedron_volume


def pin(p):
    return {"path": str(p.resolve()), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}


def write(p, value):
    p.write_text(json.dumps(value, indent=2) + "\n")


def main():
    from rdkit import Chem, rdBase
    from rdkit.Chem import AllChem
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference-dir', type=Path, required=True)
    parser.add_argument('--before', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    parser.add_argument('--openbabel', type=Path, required=True)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=False)
    ff = Path('backend/data/forcefield')
    registry = json.loads((args.before / ff / 'photoproduct_registry.json').read_text())
    canonical = json.loads((ROOT / ff / 'photoproducts/tt-cpd-cis-syn/chemical_definition.json').read_text())
    refs = {x['filename']: x['sha256'] for x in canonical['source_assets']}
    for filename in ('TTD.cif', 'TTD_ideal.sdf'):
        assert pin(args.reference_dir / filename)['sha256'] == refs[filename]
    source = Chem.MolFromMolFile(str(args.reference_dir / 'TTD_ideal.sdf'), removeHs=False)
    rows = _ccd_atom_rows(args.reference_dir / 'TTD.cif')
    assert source.GetNumAtoms() == len(rows)
    for atom, row in zip(source.GetAtoms(), rows):
        atom.SetProp('ccd_atom_id', row['_chem_comp_atom.atom_id'])
    assert _cip_codes(source) == dict(zip(('C5','C6','C5T','C6T'), ('R','R','S','S')))
    # Portable graph-only fixture for future neighbor/atom-order regressions.
    fixture = Chem.Mol(source)
    for i, name in enumerate(('C5','C6','C5T','C6T'), 1):
        fixture.GetAtomWithIdx(_atom_index(fixture, name)).SetAtomMapNum(i)
    write(args.out / 'source_fixture.json', {
        'source': pin(args.reference_dir / 'TTD_ideal.sdf'), 'license': 'CC0 1.0 Universal',
        'ring_atom_maps': {'1':'C5', '2':'C6', '3':'C5T', '4':'C6T'},
        'smiles': Chem.MolToSmiles(fixture),
    })
    records, definitions = [], []
    for i, entry in enumerate(registry['products']):
        full = _candidate_full_molecule(source, entry['stereochemistry'])
        cip = _cip_codes(full)
        assert [cip['C5'], cip['C5T']] == entry['structural_class']['ordered_c5_configurations']
        reordered = Chem.RenumberAtoms(source, list(reversed(range(source.GetNumAtoms()))))
        assert _cip_codes(_candidate_full_molecule(reordered, entry['stereochemistry'])) == cip
        model = _prune_to_n1_methyl_model(full, canonical)
        keys = _stable_atom_map(model, canonical)
        ring_indices = [_atom_index(model, n) for n in ('C5','C6','C5T','C6T')]
        tags = [model.GetAtomWithIdx(j).GetChiralTag() for j in ring_indices]
        params = AllChem.ETKDGv3()
        params.randomSeed = 7300 + i
        params.enforceChirality = True
        params.useRandomCoords = True
        params.maxIterations = 100
        assert AllChem.EmbedMolecule(model, params) == 0
        # Perceive geometry afresh; comparison uses neighbor parity, not CIP
        # labels of a symmetric capped graph or stored SDF tag assertions.
        perceived = Chem.Mol(model)
        Chem.AssignAtomChiralTagsFromStructure(perceived, replaceExistingTags=True)
        assert [perceived.GetAtomWithIdx(j).GetChiralTag() for j in ring_indices] == tags
        item = args.out / entry['id']
        item.mkdir()
        sdf = item / 'construction.sdf'
        writer = Chem.SDWriter(str(sdf)); writer.write(model); writer.close()
        conf = model.GetConformer()
        coords = {key: list(conf.GetAtomPosition(j)) for j, key in enumerate(keys)}
        write(item / 'coordinates.json', coords)
        write(item / 'atom_map.json', keys)
        obkey = _openbabel_value(args.openbabel, sdf, 'inchikey')
        assert obkey == Chem.MolToInchiKey(model)
        record = {
            'product_id': entry['id'], 'full_dna_graph_cip': cip,
            'atom_reordering_passed': True, 'coordinate_tag_reperception_passed': True,
            'rdkit_version': rdBase.rdkitVersion, 'cip_algorithm': 'rdCIPLabeler.AssignCIPLabels',
            'coordinate_method': 'ETKDGv3 static distance-geometry construction; no UFF, MD or QM',
            'seed': params.randomSeed, 'minimum_certified': False,
            'sdf': pin(sdf), 'coordinates': pin(item / 'coordinates.json'),
            'atom_map': pin(item / 'atom_map.json'),
            'openbabel_inchikey': obkey,
            'openbabel_smiles': _openbabel_value(args.openbabel, sdf, 'can'),
            'openbabel_rdkit_identifier_agreement': True,
        }
        write(item / 'construction_audit.json', record)
        records.append(record)
        if entry['structural_class']['double_bond_orientation'] != 'anti':
            continue
        oldpath = args.before / ff / entry['assets']['chemical_definition']['path']
        assert pin(oldpath)['sha256'] == entry['assets']['chemical_definition']['sha256']
        old = json.loads(oldpath.read_text())
        definition = deepcopy(old)
        for center in definition['product_stereocenters']:
            key = center['atom']
            name = key.split(':')[1] + ('T' if key.startswith('2:') else '')
            center['ccd_configuration'] = cip[name]
            volume = signed_tetrahedron_volume(coords, key, center['signed_volume_reference_atoms'])
            assert abs(volume) > .1
            center['expected_signed_volume'] = 'positive' if volume > 0 else 'negative'
            center['authority'] = ('Taylor 2023 ordered C5 identity; accurate CIP and suprafacial '
                                   'neighbor-parity reconstruction 2026-10-10; no minimum claim')
        changed = [a['atom'] for a,b in zip(definition['product_stereocenters'],old['product_stereocenters'])
                   if a['expected_signed_volume'] != b['expected_signed_volume']]
        assert changed == ['1:C5'], changed
        definition['source_ring_coordinates_angstrom'] = {
            key: coords[key] for key in old['source_ring_coordinates_angstrom']}
        definition['superseded_minimum_geometry_evidence'] = {
            'applies_to': pin(oldpath), 'reason': 'Pre-correction stereochemistry only; not evidence for this definition',
            'evidence': definition.pop('minimum_geometry_evidence', None),
        }
        definition['model_compounds']['charge_model']['source_asset'] = (
            'Static stereochemical construction only; corrected model has no certified QM minimum')
        definition['stereochemistry_correction'] = {
            'date': '2026-10-10', 'status': 'automated_identity_checks_passed_release_review_pending',
            'previous_definition': pin(oldpath), 'construction_audit': pin(item / 'construction_audit.json'),
            'scope': 'Setup and geometric detection only; old anti QM/MM/MD evidence is not transferred',
            'minimum_certified': False,
        }
        write(item / 'chemical_definition.json', definition)
        definitions.append(pin(item / 'chemical_definition.json'))
    byid = {r['product_id']: r['openbabel_inchikey'] for r in records}
    assert byid['tt-cpd-cis-syn'] == byid['tt-cpd-cis-syn-ii']
    assert byid['tt-cpd-trans-anti-i'] == byid['tt-cpd-trans-anti-ii']
    assert byid['tt-cpd-cis-anti-i'] != byid['tt-cpd-cis-anti-ii']
    assert len(set(byid.values())) == 6
    write(args.out / 'audit.json', {
        'created_at': datetime.now(timezone.utc).isoformat(), 'passed': True,
        'scope': 'Graph and static identity reconstruction; not energetic or simulation validation',
        'script': pin(Path(__file__)),
        'builder': pin(ROOT / 'backend/parameterization/photoproduct_stereo_candidates.py'),
        'openbabel': pin(args.openbabel),
        'sources': [pin(args.reference_dir / name) for name in ('TTD.cif', 'TTD_ideal.sdf')],
        'records': records, 'proposed_definitions': definitions,
        'six_capped_isomers_passed': True,
        'references': ['https://doi.org/10.1111/php.13694',
                       'https://www.rdkit.org/docs/source/rdkit.Chem.rdCIPLabeler.html'],
    })
    print(json.dumps({'passed': True, 'products': len(records), 'anti_proposals': len(definitions)}))


if __name__ == '__main__':
    main()
