"""Resolve failed soft-mode step agreement without discarding earlier evidence."""
import json,sys,subprocess,os,shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import numpy as np
REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.core_baseline import checked,source,write
ART=REPO/'.development-artifacts'

def prepare(root):
    root.mkdir(exist_ok=False);prior=ART/'cpd-anti-remote-soft-mode-v1';p=json.loads((prior/'plan.json').read_text());ref=json.loads((prior/'reference/input.json').read_text());x=np.array(ref['geometry_bohr']);q=np.array(p['direction']).reshape(-1,3);cases=[]
    for label,h in [('plus-001',.01),('minus-001',-.01),('plus-008',.08),('minus-008',-.08),('reference-repeat',0)]:
        folder=root/label;folder.mkdir();write(folder/'input.json',dict(label=label,displacement_bohr=h,elements=ref['elements'],geometry_bohr=(x+h*q).tolist()));cases.append(dict(label=label,input=source(folder/'input.json')))
    p.update(cases=cases,prior_results=[source(prior/c['label']/'result.json') for c in json.loads((prior/'plan.json').read_text())['cases']],scope='Four displacement scales plus repeated reference; original failed 10-percent check preserved; no automatic certification',worker_source=source(REPO/'experiments/cpd_anti_additive/soft_mode_check.py'));write(root/'plan.json',p);shutil.copyfile(__file__,root/'executed_source.py')

def run(root):
    p=json.loads((root/'plan.json').read_text());script=checked(p['worker_source']);os.sched_setaffinity(0,set(range(12)))
    def task(c):
        with (root/c['label']/'run.log').open('w') as log:subprocess.run([sys.executable,str(script),'worker',str(root),'--label',c['label']],stdout=log,stderr=subprocess.STDOUT,cwd=REPO,env={**os.environ,'PYTHONPATH':str(REPO)},check=True)
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(task,p['cases']))
    rows={};sources=p['prior_results']+[source(root/c['label']/'result.json') for c in p['cases']]
    for s in sources:
        r=json.loads(checked(s).read_text());d=json.loads(checked(r['input']).read_text());checked(r['native']);checked(r['plan']);rows[d['label']]=r
    q=np.array(p['direction']);curves=[]
    for suffix,h in [('001',.01),('002',.02),('004',.04),('008',.08)]:
        gp=np.array(rows['plus-'+suffix]['gradient_au']).ravel();gm=np.array(rows['minus-'+suffix]['gradient_au']).ravel();curves.append(dict(step_bohr=h,curvature=float(q@(gp-gm)/(2*h))))
    g0=np.array(rows['reference']['gradient_au']).ravel();g1=np.array(rows['reference-repeat']['gradient_au']).ravel();noise=float(abs(q@(g1-g0)));adj=[abs(a['curvature']-b['curvature'])/max(abs(a['curvature']),abs(b['curvature'])) for a,b in zip(curves,curves[1:])]
    write(root/'assessment.json',dict(curvatures=curves,adjacent_relative_differences=adj,reference_repeat_projected_gradient_difference=noise,reference_repeat_max_component_difference=float(abs(g1-g0).max()),reference_repeat_energy_difference_hartree=rows['reference-repeat']['energy_hartree']-rows['reference']['energy_hartree'],original_hessian_curvature=p['original_directional_curvature'],original_step_halving_check_preserved_failed=True,sources=sources,scope='Diagnostic completed; inspect trend and noise before changing scientific status. No automatic minimum certification or parameter release.',simulation_ready=False))

if __name__=='__main__':globals()[sys.argv[1]](Path(sys.argv[2]).resolve())
