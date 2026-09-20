"""Freeze a thermal failure conformer and its predictions before independent DFT."""
import argparse
import json
from pathlib import Path
import re
import sys

import numpy as np
from openmm import unit as u

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import AdiabaticNonbonded,checked,source,write
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms
from backend.core.dcd_fast import read_layout,read_frame
from backend.parameterization.photoproduct_esp import build_esp_grid
from backend.parameterization.photoproduct_models import audit_product_chirality

parser=argparse.ArgumentParser()
parser.add_argument('--root', type=Path, default=Path('.development-artifacts/cpd-thermal-conformer-qm-v1'))
parser.add_argument('--prior', type=Path, default=Path('.development-artifacts/cpd-thermal-adiabatic-check-v1/assessment.json'))
parser.add_argument('--all-excursions', action='store_true')
args=parser.parse_args()
root=args.root.resolve()
root.mkdir(exist_ok=False)
prior_path=args.prior.resolve()
prior=json.loads(prior_path.read_text())
if args.all_excursions:
    selected=max(prior['records'],key=lambda r:r['stationary_max_angstrom'])
    trajectory=next(checked(r) for r in prior['trajectory_sources'] if Path(r['path']).stem==selected['case'])
    frame=selected['frame']
    expected_displacement=selected['stationary_max_angstrom']
else:
    selected=max(prior['records'],key=lambda r:r['dynamic_c2_displacement_angstrom'])
    trajectory=checked(selected['trajectory'])
    frame=selected['worst_c2_frame']
    expected_displacement=selected['adiabatic_max_displacement_angstrom']
xyz_all,_=read_frame(trajectory,read_layout(trajectory),frame)
psf=trajectory.parent/'candidate.psf'
_,atoms,_=atoms_and_terms(psf.read_text())
serials={int(row[5][1:]):i-1 for i,row in atoms.items() if row[5].startswith('X')}
xyz=xyz_all[[serials[i] for i in range(36)]].astype(float)
recovery=Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve()
frozen=recovery/'corrected_parameters.training_frozen.json'
physical=AdiabaticNonbonded(recovery,frozen)
error=None
try:physical.energy_gradient(xyz)
except ValueError as exc:error=str(exc)
m=physical.model
state=m.context.getState(getPositions=True,getForces=True)
positions=np.array(state.getPositions(asNumpy=True).value_in_unit(u.nanometer))
indices=m.drude_indices
residual=float(abs(np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))[indices]).max())
assert residual<1e-4

def gradient(flat):
    x=positions.copy()
    x[indices]=flat.reshape(-1,3)/10
    m.context.setPositions(x)
    m.context.computeVirtualSites()
    return -np.array(m.context.getState(getForces=True).getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))[indices].ravel()

center=positions[indices].ravel()*10
hessians=[]
for step in (1e-4,5e-5):
    h=np.empty((len(center),len(center)))
    for j in range(len(center)):
        a=center.copy();b=center.copy();a[j]+=step;b[j]-=step
        h[:,j]=(gradient(a)-gradient(b))/(2*step)
    hessians.append((h+h.T)/2)
    assert np.linalg.eigvalsh(hessians[-1])[0]>0
m.context.setPositions(positions)
m.context.computeVirtualSites()
elements=[name.split(':')[1][0] for name in physical.d.ATOM_NAMES]
atoms_xyz=[(e,*p) for e,p in zip(elements,xyz)]
grid=np.array(build_esp_grid(atoms_xyz,radius_scales=[1.4,1.6,1.8,2.0],directions_per_atom=50))
np.savetxt(root/'grid.dat',grid,fmt='%.12f')
np.savetxt(root/'nuclear_coordinates_angstrom.txt',xyz,fmt='%.12f')
charges=np.array([m.nonbonded.getParticleParameters(i)[0].value_in_unit(u.elementary_charge) for i in range(m.system.getNumParticles())])
pos_ang=positions*10
bohr=.529177210903
potential=(charges[None,:]/np.linalg.norm(grid[:,None,:]-pos_ang[None,:,:],axis=2)).sum(axis=1)*bohr
mu=(charges[:,None]*pos_ang).sum(axis=0)/bohr
np.savetxt(root/'frozen_model_esp_au.txt',potential,fmt='%.14e')
definition_path=Path('backend/data/forcefield/photoproducts/tt-cpd-cis-anti-i/chemical_definition.json').resolve()
lesion=audit_product_chirality(json.loads(definition_path.read_text()),dict(zip(physical.d.ATOM_NAMES,xyz.tolist())))
assert lesion['passed']
template=Path('.development-artifacts/cpd-fresh-esp-validation-v1/case-000/input.dat').resolve()
text=template.read_text().replace('memory 10 GB','memory 4 GB').replace('set_num_threads(8)','set_num_threads(4)')
molecule='molecule model {\n 0 1\n'+'\n'.join(f' {e} {p[0]:.12f} {p[1]:.12f} {p[2]:.12f}' for e,p in zip(elements,xyz))+'\n units angstrom\n symmetry c1\n no_reorient\n no_com\n}'
text=re.sub(r'molecule model \{.*?\}',molecule,text,flags=re.S)
text=text.replace('# Case 000; B3LYP/aug-cc-pVDZ on audited MP2/6-31G(d) geometry','# Thermal failure snapshot; B3LYP/aug-cc-pVDZ fixed geometry, not an optimized QM minimum')
(root/'input.dat').write_text(text)
(root/'scratch').mkdir()
write(root/'plan.json',{'simulation_ready':False,'gate_effect':'none','role':'Independent conformer-transfer diagnostic selected by largest stationary excursion across all offending frames when --all-excursions is set; otherwise largest observed endpoint2 C2 thermal displacement; no QM fitting or optimization. Static ESP/dipole only; does not validate response by itself.','selected_case':selected['case'],'frame':frame,'model_dipole_au':mu.tolist(),'grid_points':len(grid),'model_domain_error':error,'model_max_displacement_angstrom':expected_displacement,'model_drude_force_max':residual,'minimum_drude_hessian_eigenvalues_kcal_mol_angstrom2':[float(np.linalg.eigvalsh(h)[0]) for h in hessians],'hessian_step_halving_relative_error':float(np.linalg.norm(hessians[0]-hessians[1])/np.linalg.norm(hessians[1])),'lesion_audit':lesion,'sources':[source(p) for p in (prior_path,trajectory,psf,frozen,definition_path,template,root/'input.dat',root/'grid.dat',root/'frozen_model_esp_au.txt',Path(__file__))],'resources':{'threads':4,'psi4_memory_gb':4,'cgroup_memory_gib':8,'runtime_seconds':3600}})
print('Frozen thermal QM test',len(grid),'grid points; minimum Drude curvature',np.linalg.eigvalsh(hessians[-1])[0],'dipole',mu)
