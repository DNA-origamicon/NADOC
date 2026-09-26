"""Probe endpoint2 conformations outside the original local QM profile."""
import json,copy,sys,shutil
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import source,write,checked
from experiments.cpd_anti_additive.geometric_pilot import screen,BOHR
from backend.parameterization.photoproduct_qm import _dihedral_degrees
ART=REPO/'.development-artifacts'

def prepare(root):
    root.mkdir(exist_ok=False);template=json.loads((ART/'cpd-anti-qm-reference-multistart-v2/endpoint-2-reference/plan.json').read_text());base=json.loads((ART/'cpd-anti-matched-mm-v1/plan.json').read_text());ref=next(p for p in base['points'] if p['label']=='endpoint-2-reference');tasks=[]
    seeds=[('baseline-well',ART/'cpd-anti-ordered-fit-v1/endpoint-2/minimum_A.txt'),('zero-torque-well',ART/'cpd-anti-torsion-geometry-v1/baseline-endpoint-2-zero_reference_torque/final_A.txt')]
    for label,seed in seeds:
        x=np.loadtxt(seed)/BOHR;plan=copy.deepcopy(template)
        for key in ('replay_sources','max_new_evaluations','neighbor','original_reference','input'):plan.pop(key,None)
        record=plan['record'];record.update(label='endpoint-2-'+label,target_degrees=_dihedral_degrees(*x[record['torsion_indices']]))
        for key in ('seed','manifest','job_dir'):record.pop(key,None)
        folder=root/record['label'];folder.mkdir();plan.update(geometry_bohr=x.tolist(),reference=None,seed_reference=source(seed),max_evaluations=60,scratch_dir=str(Path('/home/jojo/.cache/nadoc-qm')/root.name/folder.name),scope='Fixed-angle QM relaxation at a remote MM well; no unconstrained QM minimum or parameter acceptance');plan['optimizer']['maxiter']=60;audit=screen(x,dict(plan,geometry_bohr=ref['geometry_bohr']));assert audit['passed'];write(folder/'seed_screen.json',dict(audit=audit,target_degrees=record['target_degrees'],difference_from_qm_reference_deg=(record['target_degrees']-ref['record']['target_degrees']+180)%360-180));write(folder/'plan.json',plan);tasks.append(dict(label=folder.name,folder=str(folder),plan=source(folder/'plan.json')))
    write(root/'plan.json',dict(tasks=tasks,worker_source=source(REPO/'experiments/cpd_anti_additive/geometric_pilot.py'),minimum_certified=False));shutil.copyfile(__file__,root/'executed_prepare.py');shutil.copyfile(REPO/'experiments/cpd_anti_additive/geometric_pilot.py',root/'worker_source.py')

if __name__=='__main__':prepare(Path(sys.argv[1]).resolve())
