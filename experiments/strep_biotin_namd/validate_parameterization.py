"""Check chemical roundtrip and native CHARMM reference-residue coverage, no MD."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))


def validate(root):
    import parmed
    from rdkit import Chem
    from backend.core.namd_topology import find_psfgen
    from experiments.strep_biotin_namd.prepare_parameterization import digest, dump

    root = root.resolve()
    manifest = json.loads((root / 'manifest.json').read_text())
    mol = Chem.MolFromMol2File(str(root / 'BTMP.mol2'), removeHs=False)
    sdf = next(iter(Chem.SDMolSupplier(str(root / 'BTMP.sdf'), removeHs=False)))
    assert mol is not None and sdf is not None
    assert Chem.MolToSmiles(mol) == Chem.MolToSmiles(sdf), 'MOL2/SDF chemistry mismatch'
    assert Chem.GetFormalCharge(mol) == -1
    assert mol.GetNumHeavyAtoms() == 33 and mol.GetNumAtoms() == 68
    assert len(Chem.GetMolFrags(mol)) == 1
    assert mol.GetRingInfo().NumRings() == 2
    identity = json.loads((root / 'atom_mapping.json').read_text())
    assert len({a['name'] for a in identity}) == 68
    lookup = {a['name']: a['index_1based'] - 1 for a in identity}
    Chem.AssignAtomChiralTagsFromStructure(mol, replaceExistingTags=True)
    Chem.AssignStereochemistry(mol, cleanIt=True, force=True)
    for name, expected in manifest['stereo'].items():
        atom = mol.GetAtomWithIdx(lookup[name])
        assert atom.HasProp('_CIPCode') and atom.GetProp('_CIPCode') == expected
    assert not any(n.GetAtomicNum() == 1 for n in mol.GetAtomWithIdx(lookup['O4T']).GetNeighbors())
    assert mol.GetAtomWithIdx(lookup['P']).GetDegree() == 4
    assert set(manifest['stereo']) == {'C2', 'C4', 'C5'}
    for item in json.loads((root / 'reference_forcefield.json').read_text()):
        assert digest(root / item['file']) == item['sha256']

    # Exercise real parameter values without inventing a biotin assignment.
    ff = root / 'reference_forcefield'
    result = {}
    parameters = parmed.charmm.CharmmParameterSet(str(ff / 'par_all36_cgenff.prm'))
    with tempfile.TemporaryDirectory(prefix='reference_psf_', dir=root) as temp:
        work = Path(temp)
        for residue, expected_charge in [('DME', 0), ('DMEP', -1), ('NMA', 0), ('UREA', 0)]:
            script = work / f'{residue}.tcl'
            output = work / f'{residue}.psf'
            script.write_text(f'topology {{{ff / "top_all36_cgenff.rtf"}}}\n'
                              f'segment REF {{\nfirst NONE\nlast NONE\nresidue 1 {residue}\n}}\n'
                              'regenerate angles dihedrals\n'
                              f'writepsf {{{output}}}\n')
            proc = subprocess.run([find_psfgen(), str(script)], capture_output=True, text=True, timeout=30)
            proc.check_returncode()
            structure = parmed.charmm.CharmmPsfFile(str(output))
            structure.load_parameters(parameters)
            charge = sum(a.charge for a in structure.atoms)
            assert abs(charge - expected_charge) < 1e-6
            result[residue] = dict(atoms=len(structure.atoms), charge=round(charge, 6),
                                   bonds=len(structure.bonds), angles=len(structure.angles),
                                   dihedrals=len(structure.dihedrals), parameters_resolved=True)
    record = dict(chemical_roundtrip=True, graph_connected=True, heavy_atoms=33, hydrogens=35,
                  rings=2, phosphate_coordination=4, formal_charge=-1,
                  reference_hashes_verified=True, native_reference_checks=result,
                  ligand_parameters_validated=False, simulation_ready=False,
                  molecular_dynamics_run=False)
    dump(root / 'validation.json', record)
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    print(json.dumps(validate(parser.parse_args().package), indent=2))
