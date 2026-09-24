"""Native electrostatic forces including lone-pair redistribution and anisotropy."""
import importlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

import numpy as np
import openmm as mm
from openmm import unit as u

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source,checked,write
from experiments.cpd_drude_recovery.nucleotide import atoms_and_terms
from experiments.cpd_drude_recovery.engine_compare import NAMD

root=Path('.development-artifacts/cpd-drude-nuclear-force-probe-v3').resolve()
root.mkdir(exist_ok=False)
original=Path('.development-artifacts/cpd-corrected-engine-v1').resolve()
recovery=Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve()
sys.path.insert(0,str(recovery))
d=importlib.import_module('drude_model')
assert Path(d.__file__).resolve().parent==recovery
fitpath=recovery/'corrected_parameters.training_frozen.json'
fit=json.loads(fitpath.read_text())
charges=json.loads(checked(fit['permanent_charges']).read_text())['charges_e']
p=fit['parameters']
model=d.AntiCpdDrudeModel(charges,p['alpha_angstrom3'],p['thole'],p['anisotropy'])
idx=d._atom_index()
for ring in (1,2):
    for lp,o,c,n in [('LP2A','O2','C2','N1'),('LP2B','O2','C2','N3'),('LP4A','O4','C4','N3'),('LP4B','O4','C4','C5')]:
        theta=np.radians(110)
        model.system.setVirtualSite(d.NAMES.index(f'{ring}:{lp}'),mm.LocalCoordinatesSite([idx[f'{ring}:{a}'] for a in (o,c,n)],[1,0,0],[-1,1,0],[0,1,-1],mm.Vec3(.035*np.cos(theta),.035*np.sin(theta),0)))
native_names=[l.split()[1] for l in (original/'cpd.rtf').read_text().splitlines() if l.startswith('ATOM ')][:-1]
mapping=dict(zip(native_names,d.NAMES))
_,atoms,sections=atoms_and_terms((original/'cpd_q.psf').read_text())
rows=list(atoms.values())
order=[]
for i,row in enumerate(rows):
    if row[4] in mapping: j=d.NAMES.index(mapping[row[4]])
    elif row[5]=='DRUD': j=model.drude_indices[d.POLARIZABLE.index(mapping[rows[i-1][4]])]
    elif row[4]=='Q': j=model.external_index
    else: raise ValueError('Unmapped native particle')
    order.append(j)
assert len(set(order))==model.system.getNumParticles()
dummy=mm.HarmonicBondForce()
for a,b in sections['NBOND'][3]:
    types=tuple(sorted((atoms[a][5],atoms[b][5])))
    if 'DRUD' in types: continue
    req={('CPDX','CPDX'):1.4,('CPDX','LPDNA1'):.35}[types]
    dummy.addBond(order[a-1],order[b-1],req/10,2*100*4.184*100)
model.system.addForce(dummy)
model.context.reinitialize(preserveState=True)
for filename in ('cpd_q.psf','cpd_q0.psf','cpd_built.pdb','master.prm','cpd.prm'):
    shutil.copy2(original/filename,root/filename)
labels=['baseline',*[f'case{i:03d}' for i in json.loads((original/'policy.json').read_text())['case_ids']]]
write(root/'policy.json',{'simulation_ready':False,'gate_effect':'none','scope':'Fixed-coordinate electrostatic nuclear-force diagnostic with native dummy bonds retained identically in both engines. Virtual-site chain rule included. No candidate bonded or LJ physics in this probe.','absolute_force_diagnostic_tolerance_kcal_mol_angstrom':.001,'energy_diagnostic_tolerance_kcal_mol':.001,'case_labels':labels,'sources':[source(p) for p in (fitpath,NAMD,Path(__file__),original/'policy.json',original/'cpd_q.psf',original/'cpd_q0.psf',original/'cpd.rtf')]})
records=[]
for label in labels:
    coor=original/f'{label}.coor'
    data=coor.read_bytes()
    assert struct.unpack('<i',data[:4])[0]==len(rows)
    xyz=np.frombuffer(data,dtype='<f8',offset=4).reshape(-1,3)
    positions=model.base_positions.copy()
    positions[order]=xyz/10
    model.set_external_charge(0 if label=='baseline' else .5)
    model.context.setPositions(positions)
    model.context.computeVirtualSites()
    actual=np.array(model.context.getState(getPositions=True).getPositions(asNumpy=True).value_in_unit(u.angstrom))
    lp_error=float(abs(actual[36:model.nbase]-positions[36:model.nbase]*10).max())
    conf=f'''structure {'cpd_q0.psf' if label=='baseline' else 'cpd_q.psf'}
coordinates cpd_built.pdb
binCoordinates {coor}
paraTypeCharmm on
parameters master.prm
parameters cpd.prm
exclude scaled1-4
oneFourScaling 1.0
switching off
cutoff 100
pairlistdist 110
margin 2
outputName {label}
temperature 0
rigidBonds water
drude on
drudeTemp 0
drudeDamping 20
drudebondconst 1000
drudeHardWall on
drudeBondLen 0.25
langevin on
langevinTemp 0
langevinDamping 1
langevinHydrogen on
timestep 0.5
stepspercycle 1
outputEnergies 1
run 0
output onlyforces {label}
'''
    (root/f'{label}.conf').write_text(conf)
    with (root/f'{label}.log').open('w') as out:
        subprocess.run([str(NAMD),'+p1',f'{label}.conf'],cwd=root,stdout=out,stderr=subprocess.STDOUT,check=True,timeout=60)
    log=(root/f'{label}.log').read_text()
    assert 'End of program' in log
    titles=next(l.split()[1:] for l in log.splitlines() if l.startswith('ETITLE:'))
    energy=dict(zip(titles,map(float,[l.split()[1:] for l in log.splitlines() if l.startswith('ENERGY:')][-1])))
    force_data=(root/f'{label}.force').read_bytes()
    assert struct.unpack('<i',force_data[:4])[0]==len(rows)
    native=np.frombuffer(force_data,dtype='<f8',offset=4).reshape(-1,3)
    state=model.context.getState(getForces=True,getEnergy=True)
    expected=np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))[order]
    nuclear=[i for i,j in enumerate(order) if j<36]
    drudes=[i for i,j in enumerate(order) if j in model.drude_indices]
    error=float(abs(native[nuclear]-expected[nuclear]).max())
    drude_error=float(abs(native[drudes]-expected[drudes]).max())
    e=float(energy['POTENTIAL']-state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole))
    records.append({'case':label,'maximum_nuclear_force_error':error,'maximum_drude_force_error':drude_error,'energy_error_kcal_mol':e,'lp_coordinate_agreement_angstrom':lp_error,'passed_diagnostic':max(error,drude_error)<.001 and abs(e)<.001,'coordinates':source(coor),'native_log':source(root/f'{label}.log'),'native_forces':source(root/f'{label}.force')})
    write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none','records':records,'completed_cases':len(records),'planned_cases':len(labels),'all_cases_passed':len(records)==len(labels) and all(r['passed_diagnostic'] for r in records)})
print(json.dumps([{k:v for k,v in r.items() if k not in ('coordinates','native_log','native_forces')} for r in records],indent=2))
