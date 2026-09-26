"""Prepare isolated midpoint torsion relaxations from converged reference checks."""
import copy,json,sys,shutil
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked,source,write
from experiments.cpd_anti_additive.geometric_pilot import screen,BOHR
from backend.parameterization.photoproduct_qm import parse_xyz,_dihedral_degrees


def prepare(root):
    art=REPO/'.development-artifacts';root.mkdir(exist_ok=False);tasks=[]
    for e in (1,2):
        prior=art/f'cpd-anti-qm-reference-multistart-v2/endpoint-{e}-reference'
        old=json.loads((prior/'plan.json').read_text());a=json.loads((prior/'assessment.json').read_text());assert a['native_optimizer_converged']
        atoms,_=parse_xyz(checked(a['optimized']).read_text());x=np.array([v[1:] for v in atoms])/BOHR;assert [v[0] for v in atoms]==old['elements'];assert screen(x,old)['passed']
        names=json.loads(checked(old['record']['scan_plan']).read_text())['atom_map'];sugar=[i for i,n in enumerate(names) if n.startswith(f'{e}:') and "'" in n];assert len(sugar)==17
        origin=x[names.index(f'{e}:N1')];axis=x[names.index(f"{e}:C1'")]-origin;axis/=np.linalg.norm(axis)
        for degree in (-7.5,7.5):
            label=f'endpoint-{e}-{degree:+g}';folder=root/label;folder.mkdir();theta=np.radians(degree);v=x[sugar]-origin;z=x.copy();z[sugar]=origin+v*np.cos(theta)+np.cross(axis,v)*np.sin(theta)+np.outer(v@axis,axis)*(1-np.cos(theta))
            plan=copy.deepcopy(old)
            for key in ('replay_sources','max_new_evaluations','neighbor','original_reference','input'):plan.pop(key,None)
            record=plan['record'];record.update(label=label,target_degrees=_dihedral_degrees(*z[record['torsion_indices']]))
            for key in ('seed','manifest','job_dir'):record.pop(key,None)
            plan.update(geometry_bohr=z.tolist(),reference=None,seed_reference=source(prior/'assessment.json'),max_evaluations=60,scratch_dir=str(Path('/home/jojo/.cache/nadoc-qm')/root.name/label),scope='Relaxed midpoint profile at fixed glycosidic angle; unchanged MP2 settings, no fit or minimum certification')
            plan['optimizer']['maxiter']=60
            audit=screen(z,dict(plan,geometry_bohr=x.tolist()));assert audit['passed']
            graph=json.loads(checked(record['model_graph']).read_text());bonds=[b['indices'] for b in graph['bonds']];delta=max(abs(np.linalg.norm(z[i]-z[j])-np.linalg.norm(x[i]-x[j]))*BOHR for i,j in bonds);assert delta<1e-8
            write(folder/'seed_screen.json',dict(audit=audit,max_bond_change_angstrom=delta,reference=source(prior/'optimized.xyz'),rotation_degrees=degree));write(folder/'plan.json',plan);tasks.append(dict(label=label,folder=str(folder),plan=source(folder/'plan.json')))
    write(root/'plan.json',dict(tasks=tasks,worker_source=source(REPO/'experiments/cpd_anti_additive/geometric_pilot.py'),minimum_certified=False));shutil.copyfile(__file__,root/'executed_prepare.py');shutil.copyfile(REPO/'experiments/cpd_anti_additive/geometric_pilot.py',root/'worker_source.py')

if __name__=='__main__':prepare(Path(sys.argv[1]).resolve())
