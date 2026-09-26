"""Two unfinished constrained points, isolated native workers and common resource cap."""
import argparse,json,os,shutil,subprocess,sys
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor,as_completed
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked,source,write
from experiments.cpd_anti_additive.geometric_pilot import screen
from backend.parameterization.photoproduct_qm import parse_xyz
ART=REPO/'.development-artifacts'


def prepare(root):
    root.mkdir(exist_ok=False)
    template=json.loads((ART/'cpd-anti-geometric-pilot-v1/plan.json').read_text())
    records=json.loads((ART/'cpd-anti-relaxed-glycosidic-v4/plan.json').read_text())['records']
    tasks=[]
    for r in records:
        if r['label']=='endpoint-2-+15':continue
        atoms,_=parse_xyz(checked(r['seed']).read_text());x=np.array([a[1:] for a in atoms])/.529177210903
        p=dict(template,record=r,reference=None,input=r['seed'],elements=[a[0] for a in atoms],geometry_bohr=x.tolist())
        audit=screen(x,p);assert audit['passed'];folder=root/r['label'];folder.mkdir();write(folder/'plan.json',p);write(folder/'seed_screen.json',audit)
        tasks.append(dict(label=r['label'],folder=str(folder),plan=source(folder/'plan.json')))
    assert len(tasks)==2
    shutil.copyfile(REPO/'experiments/cpd_anti_additive/geometric_pilot.py',root/'geometric_pilot_source.py')
    shutil.copyfile(__file__,root/'executed_pair.py')
    write(root/'plan.json',dict(tasks=tasks,worker_source=source(REPO/'experiments/cpd_anti_additive/geometric_pilot.py'),minimum_certified=False))


def run(root):
    plan=json.loads((root/'plan.json').read_text());script=checked(plan['worker_source']);os.sched_setaffinity(0,set(range(16)))
    def task(t):
        checked(t['plan']);folder=Path(t['folder'])
        with (folder/'run.log').open('w') as log:
            p=subprocess.run([sys.executable,str(script),'run',str(folder)],stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'PYTHONPATH':str(REPO)})
        return dict(label=t['label'],returncode=p.returncode,assessment=source(folder/'assessment.json') if (folder/'assessment.json').exists() else None)
    records=[]
    with ThreadPoolExecutor(max_workers=2) as pool:
        for f in as_completed([pool.submit(task,t) for t in plan['tasks']]):
            records.append(f.result());write(root/'progress.json',dict(records=records,total=len(plan['tasks'])))
    write(root/'assessment.json',dict(records=records,minimum_certified=False,simulation_ready=False))
    if any(r['returncode'] for r in records):raise RuntimeError('One or more bounded points failed; preserve each outcome')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('action',choices=['prepare','run']);p.add_argument('root',type=Path);a=p.parse_args();globals()[a.action](a.root.resolve())
