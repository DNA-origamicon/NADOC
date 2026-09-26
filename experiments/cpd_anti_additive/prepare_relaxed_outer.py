"""Extend the constrained local profile from ±15 to ±30 degrees, isolated."""
import copy,json,sys,shutil
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked,source,write
from experiments.cpd_anti_additive.geometric_pilot import screen,BOHR
from backend.parameterization.photoproduct_qm import _dihedral_degrees,_circular_difference_degrees

def prepare(root):
    art=REPO/'.development-artifacts';root.mkdir(exist_ok=False);base=json.loads((art/'cpd-anti-matched-mm-v1/plan.json').read_text());tasks=[]
    for e in (1,2):
        template=json.loads((art/f'cpd-anti-qm-reference-multistart-v2/endpoint-{e}-reference/plan.json').read_text());ref=next(p for p in base['points'] if p['label']==f'endpoint-{e}-reference')
        for degree in (-15,15):
            neighbor=next(p for p in base['points'] if p['label']==f'endpoint-{e}-{degree:+g}');checked(neighbor['geometry_source']);checked(neighbor['qm_source']);x=np.array(neighbor['geometry_bohr']);names=json.loads(checked(ref['record']['scan_plan']).read_text())['atom_map'];sugar=[i for i,n in enumerate(names) if n.startswith(f'{e}:') and "'" in n];assert len(sugar)==17
            origin=x[names.index(f'{e}:N1')];axis=x[names.index(f"{e}:C1'")]-origin;axis/=np.linalg.norm(axis);theta=np.radians(degree);v=x[sugar]-origin;z=x.copy();z[sugar]=origin+v*np.cos(theta)+np.cross(axis,v)*np.sin(theta)+np.outer(v@axis,axis)*(1-np.cos(theta))
            label=f'endpoint-{e}-{2*degree:+g}';folder=root/label;folder.mkdir();plan=copy.deepcopy(template)
            for key in ('replay_sources','max_new_evaluations','neighbor','original_reference','input'):plan.pop(key,None)
            record=plan['record'];record.update(label=label,target_degrees=_dihedral_degrees(*z[record['torsion_indices']]))
            for key in ('seed','manifest','job_dir'):record.pop(key,None)
            actual_delta=_circular_difference_degrees(record['target_degrees'],ref['record']['target_degrees']);assert abs(actual_delta-30)<.01
            plan.update(geometry_bohr=z.tolist(),reference=None,seed_reference=neighbor['geometry_source'],max_evaluations=60,scratch_dir=str(Path('/home/jojo/.cache/nadoc-qm')/root.name/label),scope='Outer ±30 degree profile test from ±15 QM neighbors; unchanged electronic method, no fitting or certification');plan['optimizer']['maxiter']=60
            audit=screen(z,dict(plan,geometry_bohr=x.tolist()));assert audit['passed'];graph=json.loads(checked(record['model_graph']).read_text());delta=max(abs(np.linalg.norm(z[i]-z[j])-np.linalg.norm(x[i]-x[j]))*BOHR for i,j in [b['indices'] for b in graph['bonds']]);assert delta<1e-8
            write(folder/'seed_screen.json',dict(audit=audit,max_bond_change_angstrom=delta,actual_absolute_torsion_offset_deg=actual_delta));write(folder/'plan.json',plan);tasks.append(dict(label=label,folder=str(folder),plan=source(folder/'plan.json')))
    write(root/'plan.json',dict(tasks=tasks,worker_source=source(REPO/'experiments/cpd_anti_additive/geometric_pilot.py'),minimum_certified=False));shutil.copyfile(__file__,root/'executed_prepare.py');shutil.copyfile(REPO/'experiments/cpd_anti_additive/geometric_pilot.py',root/'worker_source.py')

if __name__=='__main__':prepare(Path(sys.argv[1]).resolve())
