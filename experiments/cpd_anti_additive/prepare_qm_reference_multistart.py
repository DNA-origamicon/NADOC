"""Screen back-rotated QM neighbors for reference-torsion basin checks."""
import json,sys,shutil
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.geometric_pilot import screen,BOHR
from experiments.cpd_anti_additive.core_baseline import checked,source,write
from backend.parameterization.photoproduct_qm import _dihedral_degrees,_circular_difference_degrees
ART=REPO/'.development-artifacts'
root=Path(sys.argv[1]).resolve();root.mkdir(exist_ok=False);base=json.loads((ART/'cpd-anti-matched-mm-v1/plan.json').read_text());template=json.loads((ART/'cpd-anti-geometric-pilot-v1/plan.json').read_text());tasks=[]
for e,degree in [(1,-15),(2,15)]:
    neighbor=next(p for p in base['points'] if p['label']==f'endpoint-{e}-{degree:+g}');ref=next(p for p in base['points'] if p['label']==f'endpoint-{e}-reference');checked(neighbor['geometry_source']);checked(ref['qm_source']);x=np.array(neighbor['geometry_bohr']);names=json.loads(checked(ref['record']['scan_plan']).read_text())['atom_map'];sugar=[i for i,n in enumerate(names) if n.startswith(f'{e}:') and "'" in n];assert len(sugar)==17
    idx=ref['record']['torsion_indices'];target=ref['record']['target_degrees'];angle=_dihedral_degrees(*x[idx]);delta=np.radians((target-angle+180)%360-180);origin=x[names.index(f'{e}:N1')];axis=x[names.index(f"{e}:C1'")]-origin;axis/=np.linalg.norm(axis);options=[]
    for theta in (delta,-delta):
        z=x.copy();v=x[sugar]-origin;z[sugar]=origin+v*np.cos(theta)+np.cross(axis,v)*np.sin(theta)+np.outer(v@axis,axis)*(1-np.cos(theta));options.append(z)
    z=min(options,key=lambda z:_circular_difference_degrees(_dihedral_degrees(*z[idx]),target));assert _circular_difference_degrees(_dihedral_degrees(*z[idx]),target)<1e-6
    plan=dict(template,record=ref['record'],reference=None,elements=ref['elements'],geometry_bohr=z.tolist(),neighbor=neighbor['geometry_source'],original_reference=ref['qm_source'],scope='Reference torsion relaxation from back-rotated QM neighbor; not unconstrained minimum certification')
    assert screen(z,dict(plan,geometry_bohr=x.tolist()))['passed'];assert screen(z,dict(plan,geometry_bohr=ref['geometry_bohr']))['passed']
    folder=root/f'endpoint-{e}-reference';folder.mkdir();write(folder/'plan.json',plan);write(folder/'seed_screen.json',screen(z,dict(plan,geometry_bohr=x.tolist())));tasks.append(dict(label=folder.name,folder=str(folder),plan=source(folder/'plan.json')))
write(root/'plan.json',dict(tasks=tasks,worker_source=source(REPO/'experiments/cpd_anti_additive/geometric_pilot.py'),minimum_certified=False));shutil.copyfile(__file__,root/'executed_prepare.py');shutil.copyfile(REPO/'experiments/cpd_anti_additive/geometric_pilot.py',root/'worker_source.py')
