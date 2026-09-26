"""Prepare one guarded pilot from preserved screened v2 seeds, no duplicate runs."""
import argparse
import json
from pathlib import Path
import shutil
import sys
REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.continue_relaxed import prepare
from experiments.cpd_anti_additive.core_baseline import source,write


def main(root):
    prepare(root,REPO/'.development-artifacts/cpd-anti-relaxed-glycosidic-v2',tighter=True)
    plan=json.loads((root/'plan.json').read_text())
    write(root/'prepared_three_point_plan.json',plan)
    r=next(r for r in plan['records'] if r['label']=='endpoint-2-+15')
    job=Path(r['job_dir']);guard=job/'guard_snapshot.py'
    shutil.copyfile(REPO/'experiments/cpd_anti_additive/optimization_guard.py',guard)
    p=job/'input.dat';original=p.read_text();(job/'input_before_guard.dat').write_text(original)
    text=original.replace('  cphf_r_convergence 10','  solver_convergence 10').replace('  geom_maxiter 150','  geom_maxiter 60')
    text=text.replace("energy, wavefunction = optimize('mp2', return_wfn=True)","import sys\nsys.path.insert(0, "+repr(str(job))+")\nfrom guard_snapshot import install, OPTIMIZER\ninstall()\nenergy, wavefunction = optimize('mp2', return_wfn=True, optimizer_keywords=OPTIMIZER)")
    p.write_text(text)
    m=json.loads((job/'job_manifest.json').read_text());m['input']['sha256']=source(p)['sha256']
    m['campaign_override'].update(solver_convergence=1e-10,geom_maxiter=60,guard_source=source(guard),reason='Guarded pilot with verified effective option aliases; reject mismatched options before first gradient')
    m['campaign_override'].pop('cphf_r_convergence',None)
    write(job/'job_manifest.json',m);r['manifest']=source(job/'job_manifest.json')
    plan.update(records=[r],workers=1,scope='Single guarded endpoint2+15 pilot; other points held; no minimum certification',guard=source(guard))
    write(root/'plan.json',plan)
    shutil.copyfile(__file__,root/'executed_prepare_guarded.py')

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('root',type=Path);a=p.parse_args();main(a.root.resolve())
