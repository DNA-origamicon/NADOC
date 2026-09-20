"""Prepare exact fixed-torsion restart from terminal ranged-pilot geometry."""
import json
from pathlib import Path
import re
import sys

import numpy as np
from optking.tors import Tors

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_drude_recovery.campaign import source, checked, write
from experiments.cpd_drude_recovery.audit_relaxed_ring import geometry_checks

old = Path('.development-artifacts/cpd-relaxed-ring-pilot-v1').resolve()
root = Path('.development-artifacts/cpd-relaxed-ring-fixed-v2').resolve()
terminal = json.loads((old/'terminal_service_state.json').read_text())
assert terminal['ActiveState']=='failed'
plan = json.loads((old/'plan.json').read_text())
checked(plan['worker'])
text=(old/'ring_minus5/output.dat').read_text()
assert 'Could not converge geometry optimization in 40 iterations.' in text
block=text.rsplit('Geometry (in Angstrom), charge = 0, multiplicity = 1:',1)[1]
rows=re.findall(r'^\s*([CHNO])\s+([-\d.]+)\s+([-\d.]+)\s+([-\d.]+)\s*$',block,re.M)
xyz=np.array([[float(v) for v in row[1:]] for row in rows])
assert xyz.shape==(36,3)
initial=xyz.copy()
indices=plan['indices_zero_based']
tors=Tors(*indices)
target=plan['cases'][0]['target_degrees']
# Minimum-norm Cartesian correction to the exact original target; tiny shift
# removes the finite width of the old range without changing the target.
for _ in range(5):
    angle=tors.q(xyz)
    residual=(angle-np.radians(target)+np.pi)%(2*np.pi)-np.pi
    if abs(residual)<1e-13:
        break
    gradient=np.zeros_like(xyz)
    for i in indices:
        for j in range(3):
            xp=xyz.copy(); xm=xyz.copy()
            xp[i,j]+=1e-5; xm[i,j]-=1e-5
            gradient[i,j]=(tors.q(xp)-tors.q(xm))/2e-5
    xyz-=residual*gradient/np.sum(gradient**2)
assert abs(np.degrees(tors.q(xyz))-target)<1e-8
assert abs(xyz-initial).max()<1e-5
recovery=Path('.development-artifacts/cpd-drude-anti-graph-recovery-v1').resolve()
sys.path.insert(0,str(recovery))
import drude_model as d
fit_path=Path('.development-artifacts/cpd-drude-bonded-h6-endpoints-v1/bonded_fit_plan.json').resolve()
fit=json.loads(fit_path.read_text())
reference=np.array([[float(v) for v in line.split()[1:]] for line in plan['molecule'].splitlines() if len(line.split())==4])
audit=geometry_checks(xyz,reference,d.ATOM_NAMES,d._bonds(),fit['stereochemical_impropers'],indices,target)
assert audit['constraint_satisfied'] and audit['all_stereo_preserved']
root.mkdir(exist_ok=False)
(root/'preparation_snapshot.py').write_text(Path(__file__).read_text())
worker=Path('experiments/cpd_drude_recovery/relaxed_ring_worker.py').read_text()
worker=worker.replace('"ranged_dihedral": constraint,','"frozen_dihedral": " ".join(str(i + 1) for i in plan["indices_zero_based"]),')
worker=worker.replace('"geom_maxiter": 40,','"geom_maxiter": 80,\n            "intrafrag_step_limit": 0.1,\n            "intrafrag_step_limit_max": 0.25,')
(root/'worker.py').write_text(worker)
plan['molecule']='0 1\n'+'\n'.join(f'{row[0]} {p[0]:.12f} {p[1]:.12f} {p[2]:.12f}' for row,p in zip(rows,xyz))+'\nunits angstrom\nno_com\nno_reorient\nsymmetry c1\n'
plan['reference_dihedral_degrees']=target
plan['cases']=plan['cases'][:1]
plan['worker']=source(root/'worker.py')
plan['continuation']={'parent_plan':source(old/'plan.json'),'terminal_state':source(old/'terminal_service_state.json'),'failed_native_output':source(old/'ring_minus5/output.dat'),'projection_max_displacement_angstrom':float(abs(xyz-initial).max()),'constraint':'Exact frozen dihedral at unchanged target; original GAU_TIGHT limits retained.','scope':'Only minus5 continuation; plus5 remains outstanding.'}
plan['role']='Fixed-torsion diagnostic continuation of failed ranged pilot; no force-field fit or release.'
write(root/'plan.json',plan)
write(root/'starting_geometry_audit.json',{'checks':audit,'sources':[source(fit_path),source(Path(d.__file__)),source(root/'preparation_snapshot.py')],'simulation_ready':False})
print('Prepared fixed-torsion continuation; max projection',abs(xyz-initial).max())
