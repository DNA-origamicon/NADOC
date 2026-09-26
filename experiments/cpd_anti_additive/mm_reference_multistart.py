"""Check reference-basin dependence using screened back-rotated MM neighboring points."""
import argparse,json,sys,os,shutil
from pathlib import Path
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.matched_mm import one,screen,BOHR,checked,source,write
from backend.parameterization.photoproduct_qm import parse_xyz,_dihedral_degrees,_circular_difference_degrees
ART=REPO/'.development-artifacts'


def prepare(root):
    old=ART/'cpd-anti-matched-mm-v1';base=json.loads((old/'plan.json').read_text());root.mkdir(exist_ok=False);shutil.copyfile(__file__,root/'executed_source.py');tasks=[]
    for c in base['candidates']:
        for e in (1,2):
            ref=next(p for p in base['points'] if p['label']==f'endpoint-{e}-reference')
            names=json.loads(checked(ref['record']['scan_plan']).read_text())['atom_map'];sugar=[i for i,n in enumerate(names) if n.startswith(f'{e}:') and "'" in n];assert len(sugar)==17
            for degree in (-15,15):
                label=f'endpoint-{e}-{degree:+g}';xyz=old/c['label']/label/'optimized.xyz';prior=json.loads((xyz.parent/'assessment.json').read_text());assert prior['converged']
                atoms,_=parse_xyz(xyz.read_text());x=np.array([a[1:] for a in atoms])/BOHR;idx=ref['record']['torsion_indices'];target=ref['record']['target_degrees'];angle=_dihedral_degrees(*x[idx]);delta=np.radians((target-angle+180)%360-180)
                origin=x[names.index(f'{e}:N1')];axis=x[names.index(f"{e}:C1'")]-origin;axis/=np.linalg.norm(axis)
                options=[]
                for theta in (delta,-delta):
                    z=x.copy();v=x[sugar]-origin;z[sugar]=origin+v*np.cos(theta)+np.cross(axis,v)*np.sin(theta)+np.outer(v@axis,axis)*(1-np.cos(theta));options.append(z)
                z=min(options,key=lambda z:_circular_difference_degrees(_dihedral_degrees(*z[idx]),target));assert _circular_difference_degrees(_dihedral_degrees(*z[idx]),target)<1e-6
                p=dict(ref,label=f'endpoint-{e}-reference-from-{degree:+g}',geometry_bohr=z.tolist(),source_neighbor=source(xyz))
                assert screen(z,dict(p,geometry_bohr=x.tolist()))['passed'];seed=root/f"{c['label']}-{p['label']}-seed.json";write(seed,dict(elements=p['elements'],geometry_bohr=z.tolist(),source_neighbor=source(xyz)));p['geometry_source']=source(seed)
                tasks.append(dict(point=p,candidate=c,prior_reference=source(old/c['label']/f'endpoint-{e}-reference/assessment.json')))
    write(root/'plan.json',dict(tasks=tasks,source=source(old/'assessment.json'),scope='Reference torsion multistart; no fitting, no proof of global minimum'))


def run(root):
    os.chdir(root);plan=json.loads((root/'plan.json').read_text());checked(plan['source']);records=[]
    for t in plan['tasks']:
        checked(t['point']['geometry_source']);r=one(root,t['point'],t['candidate']);prior=json.loads(checked(t['prior_reference']).read_text())
        if r['converged']:r['reference_energy_change_kcal_mol']=r['energy_kcal_mol']-prior['energy_kcal_mol']
        records.append(r);write(root/'progress.json',dict(records=records,total=len(plan['tasks'])))
    write(root/'assessment.json',dict(records=records,scope=plan['scope'],simulation_ready=False,minimum_certified=False))
    if any(not r['converged'] for r in records):raise RuntimeError('Some multistart references failed; preserve all outcomes')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run']);p.add_argument('root',type=Path);a=p.parse_args();globals()[a.action](a.root.resolve())
