"""Bounded neutral anti sugar-fragment QM with post-optimization stereo audit."""
import hashlib
import json
from pathlib import Path
import time

import numpy as np
import psi4


def checked(record):
    path = Path(record['path'])
    assert hashlib.sha256(path.read_bytes()).hexdigest() == record['sha256']
    return path


def write(path, data):
    path.write_text(json.dumps(data, indent=2)+'\n')


def volume(xyz, names, ordered):
    a,b,c,d = xyz[[names.index(n) for n in ordered]]
    return float(np.dot(b-a,np.cross(c-a,d-a)))


root = Path.cwd()
plan = json.loads((root/'qm_plan.json').read_text())
checked(plan['worker'])
assessment = json.loads(checked(plan['seed_assessment']).read_text())
assert assessment['all_fragment_seed_checks_passed']
assert psi4.__version__ == '1.11'
psi4.set_num_threads(4)
psi4.set_memory('4 GiB')
for row in assessment['records']:
    manifest = json.loads(checked(row['model_manifest']).read_text())
    seed = checked(manifest['outputs']['xyz'])
    names = manifest['atom_map']
    folder = root / f"qm-endpoint-{row['endpoint']}"
    folder.mkdir(exist_ok=False)
    (folder/'scratch').mkdir()
    psi4.core.clean()
    psi4.core.clean_options()
    psi4.core.clean_variables()
    psi4.core.IOManager.shared_object().set_default_path(str(folder/'scratch'))
    psi4.set_output_file(str(folder/'output.dat'),False)
    mol = psi4.geometry('0 1\n'+'\n'.join(seed.read_text().splitlines()[2:])+'\nunits angstrom\nsymmetry c1\nno_reorient\nno_com')
    psi4.set_options(plan['electronic_options'])
    write(root/'qm_progress.json',{'state':'running','endpoint':row['endpoint'],'started_epoch':time.time()})
    energy,wfn = psi4.optimize('mp2',molecule=mol,return_wfn=True,optimizer_keywords=plan['optimizer_options'])
    xyz = np.asarray(wfn.molecule().geometry())*psi4.constants.bohr2angstroms
    assert np.isfinite(xyz).all() and np.isfinite(energy)
    wfn.molecule().save_xyz_file(str(folder/'optimized.xyz'),True)
    centers=[]
    for center, ordered in [("C1'",["O4'","C2'","N1","H1'"]),("C3'",["C2'","C4'","O3'","H3'"]),("C4'",["O4'","C3'","C5'","H4'"])]:
        key=f"{row['endpoint']}:{center}"
        reference=next(c['reference_volume'] for c in row['sugar_centers'] if c['center']==key)
        value=volume(xyz,names,[f"{row['endpoint']}:{n}" for n in ordered])
        centers.append({'center':key,'volume':value,'preserved':bool(reference*value>0 and abs(value)>1e-8)})
    write(folder/'result.json',{'status':'optimized_pending_independent_graph_lesion_and_frequency_audits','energy_hartree':float(energy),'geometry_angstrom':xyz.tolist(),'sugar_centers':centers,'all_sugar_centers_preserved':all(c['preserved'] for c in centers),'simulation_ready':False,'gate_effect':'none','plan_sha256':hashlib.sha256((root/'qm_plan.json').read_bytes()).hexdigest()})
    assert all(c['preserved'] for c in centers)
    psi4.core.clean()
write(root/'qm_progress.json',{'state':'optimizations_completed_pending_independent_audits','simulation_ready':False})
