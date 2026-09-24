"""Recover native convergence history and a traceable near-stationary seed."""
import json
from pathlib import Path
import re
import sys

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source,write
from backend.parameterization.photoproduct_bonded_fit_plan import _dihedral

origin=Path('.development-artifacts/cpd-relaxed-ring-fixed-v2').resolve()
root=Path('.development-artifacts/cpd-ring-convergence-diagnostic-v1').resolve()
root.mkdir(exist_ok=False)
plan=json.loads((origin/'plan.json').read_text())
text=(origin/'ring_minus5/output.dat').read_text()
rows=[]
for match in re.finditer(r'^\s*(\d+)\s+(-\d+\.\d+)\s+([^\n]+)~\s*$',text,re.M):
    tail=match[3].replace('*',' ').replace('o',' ').split()
    if len(tail)!=5:
        continue
    try:values=list(map(float,tail))
    except ValueError:continue
    rows.append({'step':int(match[1]),'energy_hartree':float(match[2]),'delta_energy_hartree':values[0],
        'max_force_au':values[1],'rms_force_au':values[2],'max_displacement_au':values[3],'rms_displacement_au':values[4],
        'offset':match.start()})
unique={}
for row in rows:
    if row['step'] in unique:
        assert all(row[k]==unique[row['step']][k] for k in row if k!='offset')
    else:unique[row['step']]=row
assert len(unique)==80
geometries={}
initial=np.array([[float(v) for v in line.split()[1:]] for line in plan['molecule'].splitlines() if len(line.split())==4])
geometries[1]=initial
atom_pattern=r'^\s*([CHNO])\s+([-+\d.]+)\s+([-+\d.]+)\s+([-+\d.]+)\s*$'
for match in re.finditer('Next Geometry in Ang',text):
    preceding=[row for row in rows if row['offset']<match.start()]
    step=preceding[-1]['step']+1
    atoms=re.findall(atom_pattern,text[match.end():],re.M)[:36]
    assert len(atoms)==36
    geometries[step]=np.array([[float(v) for v in row[1:]] for row in atoms])
best=min(unique.values(),key=lambda r:r['max_force_au'])
seed=geometries[best['step']]
np.savetxt(root/'best_force_seed_angstrom.txt',seed,fmt='%.12f')
angle=_dihedral(*seed[plan['indices_zero_based']])
steps=[]
for n,row in sorted(unique.items()):
    row={k:v for k,v in row.items() if k!='offset'}
    row['constraint_error_degrees']=float((_dihedral(*geometries[n][plan['indices_zero_based']])-plan['cases'][0]['target_degrees']+180)%360-180)
    steps.append(row)
write(root/'assessment.json',{'simulation_ready':False,'gate_effect':'none',
    'scope':'Native history diagnosis; lowest reported projected-force seed is not a converged or certified constrained minimum.',
    'best_force_step':best['step'],'best_force_au':best['max_force_au'],'seed_angle_degrees':angle,
    'energy_increase_steps':sum(r['delta_energy_hartree']>0 for r in steps),
    'maximum_constraint_error_degrees':max(abs(r['constraint_error_degrees']) for r in steps),
    'records':steps,'sources':[source(p) for p in (origin/'plan.json',origin/'ring_minus5/output.dat',Path(__file__))]})
print(json.dumps({'best_force_step':best['step'],'best_force_au':best['max_force_au'],'angle':angle,'energy_increase_steps':sum(r['delta_energy_hartree']>0 for r in steps)}))
