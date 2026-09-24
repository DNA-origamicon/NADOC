"""Materialize screened anti boundary and audit both neutral sugar fragments."""
import json
from pathlib import Path
import sys

import numpy as np
from rdkit import Chem

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from experiments.cpd_drude_recovery.audit_boundary_seeds import read_outputs, volume
from backend.parameterization.photoproduct_fragments import build_single_endpoint_glycosidic_fragment
from backend.parameterization.photoproduct_qm import parse_xyz


def main():
    repair = Path('.development-artifacts/cpd-anti-boundary-chirality-repair-v2').resolve()
    root = Path('.development-artifacts/cpd-repaired-anti-fragments-v1').resolve()
    audit_path = repair / 'independent_structural_audit.json'
    audit = json.loads(audit_path.read_text())
    assert audit['passed_starting_geometry_screen']
    for record in audit['sources']:
        checked(record)
    policy = json.loads((repair / 'policy.json').read_text())
    original = checked(policy['source'])
    old = json.loads(original.read_text())
    paths, names, _, mol, _ = read_outputs(original, old)
    xyz = np.loadtxt(repair / 'candidate_coordinates_angstrom.txt')
    root.mkdir(exist_ok=False)
    (root / 'source_snapshot.py').write_text(Path(__file__).read_text())
    boundary = root / 'boundary'
    boundary.mkdir()
    for i, point in enumerate(xyz):
        mol.GetConformer().SetAtomPosition(i, point)
    writer = Chem.SDWriter(str(boundary / 'candidate.sdf'))
    writer.write(mol)
    writer.close()
    # SDF serialization rounds to four decimals; make XYZ agree with the actual
    # serialized coordinates that the existing fragment constructor consumes.
    serialized = Chem.SDMolSupplier(str(boundary / 'candidate.sdf'), removeHs=False)[0]
    sx = np.array(serialized.GetConformer().GetPositions())
    error = float(abs(sx - xyz).max())
    assert error <= 5.01e-5
    elements = [a.GetSymbol() for a in serialized.GetAtoms()]
    (boundary / 'candidate.xyz').write_text('63\nIsolated screened anti nucleotide seed\n' + '\n'.join(f'{e} {x:.8f} {y:.8f} {z:.8f}' for e,(x,y,z) in zip(elements,sx))+'\n')
    write(boundary / 'atom_map.json', names)
    manifest = {
        'schema':'nadoc.photoproduct-dna-boundary-model-candidate.v1',
        'status':'quantitatively_screened_boundary', 'gate_effect':'none',
        'simulation_ready':False, 'product_id':old['product_id'],
        'atom_count':63, 'formal_charge':-1,
        'chemical_definition':old['chemical_definition'],
        'source_manifest':source(original), 'structural_screen':source(audit_path),
        'serialization_max_error_angstrom':error,
        'scope':'Isolated QM seed only; repaired coordinates, no inherited UFF screening claims.',
        'outputs':{k:source(boundary / v) for k,v in {'xyz':'candidate.xyz','sdf':'candidate.sdf','atom_map':'atom_map.json'}.items()},
    }
    write(boundary / 'candidate_manifest.json', manifest)
    refpath = checked(policy['reference'])
    _, refnames, refxyz, _, _ = read_outputs(refpath,json.loads(refpath.read_text()))
    rows = []
    for endpoint in (1,2):
        folder = root / f'endpoint-{endpoint}'
        fragment = build_single_endpoint_glycosidic_fragment(source_manifest_path=boundary / 'candidate_manifest.json',retained_endpoint=endpoint,output_dir=folder)
        fnames = fragment['atom_map']
        fxyz = np.array([a[1:] for a in parse_xyz(checked(fragment['outputs']['xyz']).read_text())[0]])
        centers = []
        for constraint in policy['sugar_constraints']:
            if not constraint['center'].startswith(f'{endpoint}:'):
                continue
            before = volume(refxyz,refnames,constraint['ordered'])
            after = volume(fxyz,fnames,constraint['ordered'])
            centers.append({'center':constraint['center'],'reference_volume':before,'fragment_volume':after,'preserved':bool(before*after>0 and abs(after)>1e-8)})
        # Every retained coordinate must come from the repaired source.
        renames = fragment['construction']['renamed']
        inverse = {v:k for k,v in renames.items()}
        retained_error = max(float(abs(fxyz[i]-sx[names.index(inverse.get(key,key))]).max()) for i,key in enumerate(fnames[:46]))
        passed = len(centers)==3 and all(c['preserved'] for c in centers) and fragment['chirality_audit']['passed'] and retained_error<1e-7
        rows.append({'endpoint':endpoint,'passed_seed_identity_and_stereochemistry':bool(passed),'sugar_centers':centers,'retained_coordinate_max_error_angstrom':retained_error,'model_manifest':source(folder/'model_manifest.json')})
        assert passed
    write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none','all_fragment_seed_checks_passed':all(r['passed_seed_identity_and_stereochemistry'] for r in rows),'records':rows,'reference':source(refpath),'script':source(root/'source_snapshot.py'),'scope':'Input identity and stereochemistry only; QM and parameter validation outstanding.'})
    print(json.dumps(rows,indent=2))

if __name__ == '__main__':
    main()
