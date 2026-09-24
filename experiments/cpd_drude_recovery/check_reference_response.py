"""Recheck all 24 previously exposed reference responses for a frozen candidate."""
import argparse
import json
from pathlib import Path
import re
import sys

import numpy as np
from openmm import unit as u

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import AdiabaticNonbonded,checked,source,write
from experiments.cpd_drude_recovery.run_fresh_esp import read_result

parser=argparse.ArgumentParser()
parser.add_argument('--candidate',required=True,type=Path)
parser.add_argument('--root',required=True,type=Path)
args=parser.parse_args()
root=args.root.resolve();root.mkdir(exist_ok=False)
origin=Path('.development-artifacts/cpd-fresh-esp-validation-v1').resolve()
plan=json.loads((origin/'plan.json').read_text())
for c in plan['cases']:checked(c['input'])
physical=AdiabaticNonbonded(Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve(),args.candidate.resolve())
m=physical.model
block=re.search(r'molecule model \{(.*?)\}',(origin/'case-000/input.dat').read_text(),re.S)[1]
xyz=np.array([[float(v) for v in line.split()[1:]] for line in block.splitlines() if len(line.split())==4 and line.split()[0] in ('C','N','O','H')])
assert xyz.shape==(36,3)
grid=np.loadtxt(origin/'case-000/grid.dat')
zero_esp,zero_dip=read_result(origin/'case-000')

def predict(charge,position):
    m.base_positions[m.external_index]=np.asarray(position)/10
    m.set_external_charge(charge)
    error=None
    try:physical.energy_gradient(xyz)
    except ValueError as exc:error=str(exc)
    state=m.context.getState(getPositions=True,getForces=True)
    pos=np.array(state.getPositions(asNumpy=True).value_in_unit(u.angstrom))
    force=np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    assert abs(force[m.drude_indices]).max()<1e-4
    q=np.array([m.nonbonded.getParticleParameters(i)[0].value_in_unit(u.elementary_charge) for i in range(m.external_index)])
    solute=pos[:m.external_index]
    esp=.529177210903*(1/np.linalg.norm(grid[:,None,:]-solute[None,:,:],axis=2))@q
    dip=(q[:,None]*solute).sum(axis=0)/.529177210903
    disp=float(np.linalg.norm(pos[m.drude_indices]-xyz[:20],axis=1).max())
    return esp,dip,disp,error

baseline_esp,baseline_dip,baseline_disp,baseline_error=predict(0,[100,100,100])
records=[]
for case in plan['cases']:
    folder=origin/f"case-{case['case_id']:03d}"
    assert np.array_equal(np.loadtxt(folder/'grid.dat'),grid)
    qm_esp,qm_dip=read_result(folder)
    esp,dip,disp,error=predict(.5,case['position_angstrom'])
    qe,qd=qm_esp-zero_esp,qm_dip-zero_dip
    assert np.linalg.norm(qe)>0 and np.linalg.norm(qd)>0
    records.append({'case_id':case['case_id'],'response_relative_error':float(np.linalg.norm(esp-baseline_esp-qe)/np.linalg.norm(qe)),
        'dipole_change_relative_error':float(np.linalg.norm(dip-baseline_dip-qd)/np.linalg.norm(qd)),
        'max_drude_angstrom':disp,'domain_error':error,'sources':[source(folder/f) for f in ('output.dat','grid_esp.dat')]})
report={'simulation_ready':False,'gate_effect':'none','scope':'All 24 reference perturbations previously exposed; regression check, not fresh validation.',
    'completed':len(records),'response_relative_rms':float(np.sqrt(np.mean([r['response_relative_error']**2 for r in records]))),
    'dipole_change_relative_rms':float(np.sqrt(np.mean([r['dipole_change_relative_error']**2 for r in records]))),
    'maximum_drude_angstrom':max([baseline_disp]+[r['max_drude_angstrom'] for r in records]),
    'baseline_domain_error':baseline_error,'records':records,'sources':[source(p) for p in (args.candidate,origin/'plan.json',Path(__file__))]}
write(root/'assessment.json',report)
print(json.dumps({k:v for k,v in report.items() if k not in ('records','sources')},indent=2))
