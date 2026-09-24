"""Independent identity/geometry audit; deliberately does not certify a QM minimum."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import checked, source, write
from backend.parameterization.photoproduct_qm import parse_xyz, _last_psi4_geometry
from backend.parameterization.photoproduct_models import (
    audit_product_chirality, _covalent_bond_radius_ratio_range,
    _minimum_nonbonded_covalent_ratio,
)


def sugar_checks(xyz, names, endpoint, reference_centers):
    xyz = np.asarray(xyz, dtype=float)
    if xyz.shape != (len(names), 3) or not np.isfinite(xyz).all() or len(set(names)) != len(names):
        raise ValueError('Invalid coordinates or atom identities')
    records = []
    for center, neighbors in [("C1'",["O4'","C2'","N1","H1'"]),("C3'",["C2'","C4'","O3'","H3'"]),("C4'",["O4'","C3'","C5'","H4'"])]:
        key = f'{endpoint}:{center}'
        a,b,c,d = xyz[[names.index(f'{endpoint}:{n}') for n in neighbors]]
        value = float(np.dot(b-a,np.cross(c-a,d-a)))
        ref = next(c['reference_volume'] for c in reference_centers if c['center']==key)
        records.append({'center':key,'volume':value,'reference_volume':ref,'preserved':bool(np.isfinite(ref) and value*ref>0 and abs(value)>1e-8)})
    return records


def main(root):
    from rdkit import Chem
    plan_path=root/'qm_plan.json'
    plan=json.loads(plan_path.read_text())
    checked(plan['worker'])
    assessment_path=checked(plan['seed_assessment'])
    seeds=json.loads(assessment_path.read_text())
    checked(seeds['reference'])
    limits_path=Path('backend/data/forcefield/photoproduct_flexible_boundary_seed_policy_v1.json')
    limits=json.loads(limits_path.read_text())['thresholds']
    rows=[]
    missing=[]
    for seed in seeds['records']:
        endpoint=seed['endpoint']
        folder=root/f'qm-endpoint-{endpoint}'
        result_path=folder/'result.json'
        if not result_path.exists():
            missing.append(endpoint)
            continue
        model_path=checked(seed['model_manifest'])
        model=json.loads(model_path.read_text())
        boundary_path=checked(model['source_boundary_manifest'])
        boundary=json.loads(boundary_path.read_text())
        definition_path=checked(boundary['chemical_definition'])
        definition=json.loads(definition_path.read_text())
        result=json.loads(result_path.read_text())
        if result['plan_sha256']!=source(plan_path)['sha256']:
            raise ValueError('Result plan mismatch')
        native=(folder/'output.dat').read_text()
        complete='Final optimized geometry and variables:' in native and 'DF-MP2' in native and 'Could not converge geometry' not in native
        atoms,_=parse_xyz((folder/'optimized.xyz').read_text())
        xyz=np.array([a[1:] for a in atoms])
        names=model['atom_map']
        mol=Chem.SDMolSupplier(str(checked(model['outputs']['sdf'])),removeHs=False)[0]
        elements=[a.GetSymbol() for a in mol.GetAtoms()]
        printed=_last_psi4_geometry(native,len(names))
        same_elements=[a[0] for a in atoms]==elements==[a[0] for a in printed]
        correspondence=max(float(abs(xyz-np.array(result['geometry_angstrom'])).max()),float(abs(xyz-np.array([a[1:] for a in printed])).max()))
        sugar=sugar_checks(xyz,names,endpoint,seed['sugar_centers'])
        lesion=audit_product_chirality(definition,dict(zip(names,xyz.tolist())))
        low,high=_covalent_bond_radius_ratio_range(mol,xyz,elements)
        contact=_minimum_nonbonded_covalent_ratio(mol,xyz,elements)
        bound=limits['covalent_bond_radius_ratio']
        checks={'native_optimization_completed':complete,'atom_order_and_elements':same_elements,'native_result_xyz_agree':correspondence<1e-6,'neutral_model':Chem.GetFormalCharge(mol)==0,'all_sugar_centers':all(c['preserved'] for c in sugar),'all_lesion_centers':lesion['passed'],'all_covalent_distances':bound['minimum']<=low<=high<=bound['maximum'],'no_catastrophic_heavy_contact':contact>=limits['minimum_nonbonded_covalent_radius_ratio'],'finite_energy':bool(np.isfinite(result['energy_hartree']))}
        rows.append({'endpoint':endpoint,'passed_identity_geometry_audit':all(checks.values()),'checks':checks,'sugar':sugar,'lesion':lesion,'covalent_radius_ratio_range':[low,high],'minimum_heavy_contact_ratio':contact,'coordinate_agreement_max_angstrom':correspondence,'sources':[source(p) for p in (model_path,boundary_path,definition_path,result_path,folder/'optimized.xyz',folder/'output.dat')]})
    report={'simulation_ready':False,'gate_effect':'none','status':'incomplete' if missing else 'audited','missing_endpoints':missing,'records':rows,'all_endpoints_passed':not missing and all(r['passed_identity_geometry_audit'] for r in rows),'scope':'Identity, native convergence and catastrophic geometry screen only. Connectivity is distance-consistency with the hash-verified input graph; no inference of electronic bond orders. Positive Hessians, Drude transfer, nucleotide and DNA validation remain required.','sources':[source(p) for p in (plan_path,assessment_path,limits_path,Path(__file__))]}
    write(root/'independent_qm_geometry_audit.json',report)
    print(json.dumps({'status':report['status'],'missing':missing,'records':[{k:r[k] for k in ('endpoint','checks')} for r in rows]},indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--root',type=Path,required=True)
    main(parser.parse_args().root.resolve())
