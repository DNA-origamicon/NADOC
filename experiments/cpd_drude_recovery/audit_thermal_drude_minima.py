"""Separate extended-system excursions from the adiabatic polarization surface."""
import argparse
import json
from pathlib import Path
import sys

import numpy as np
from openmm import unit as u

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import AdiabaticNonbonded,source,write
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms
from backend.core.dcd_fast import read_layout,read_frame

parser=argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path('.development-artifacts/cpd-thermal-adiabatic-check-v1'))
parser.add_argument('--trajectory-root', type=Path, default=Path('.development-artifacts/cpd-capped-dynamics-v1'))
args=parser.parse_args()
root=args.root.resolve()
root.mkdir(exist_ok=False)
trajectory_root=args.trajectory_root.resolve()
recovery=Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve()
frozen=recovery/'corrected_parameters.training_frozen.json'
model=AdiabaticNonbonded(recovery,frozen)
_,atoms,sections=atoms_and_terms((trajectory_root/'candidate.psf').read_text())
serials={int(row[5][1:]):i-1 for i,row in atoms.items() if row[5].startswith('X')}
parent=serials[model.d.ATOM_NAMES.index('2:C2')]
dparent=next((b-1 if a-1==parent else a-1) for a,b in sections['NBOND'][3] if (a-1==parent and atoms[b][5]=='DRUD') or (b-1==parent and atoms[a][5]=='DRUD'))
records=[]
for case in json.loads((trajectory_root/'plan.json').read_text())['cases']:
    p=trajectory_root/(case['id']+'.dcd')
    layout=read_layout(p)
    frames=[read_frame(p,layout,i)[0] for i in range(layout.n_frames)]
    distances=[np.linalg.norm(x[parent]-x[dparent]) for x in frames]
    selected=int(np.argmax(distances))
    xyz=frames[selected][[serials[i] for i in range(36)]].astype(float)
    error=None
    try:
        model.energy_gradient(xyz)
    except ValueError as exc:
        error=str(exc)
    m=model.model
    state=m.context.getState(getPositions=True,getForces=True)
    pos=np.array(state.getPositions(asNumpy=True).value_in_unit(u.angstrom))
    forces=np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    disp=np.linalg.norm(pos[m.drude_indices]-pos[:20],axis=1)
    residual=float(abs(forces[m.drude_indices]).max())
    assert residual<1e-4
    records.append({'case':case['id'],'worst_c2_frame':selected,'dynamic_c2_displacement_angstrom':float(distances[selected]),'adiabatic_c2_displacement_angstrom':float(disp[model.d.POLARIZABLE.index('2:C2')]),'adiabatic_max_displacement_angstrom':float(disp.max()),'adiabatic_drude_force_max':residual,'original_domain_passed':bool(disp.max()<=.2),'evaluator_domain_error':error,'trajectory':source(p)})
write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none','scope':'Worst observed endpoint2 C2 frame per short thermal trajectory, with fixed nuclear coordinates and re-minimized Drudes. Distinguishes a stationary polarization-domain failure from transient extended-system heating. Not a QM validation or minimum-Hessian certificate.','records':records,'sources':[source(p) for p in (frozen,trajectory_root/'plan.json',trajectory_root/'candidate.psf',Path(__file__))]})
print(json.dumps(records,indent=2))
