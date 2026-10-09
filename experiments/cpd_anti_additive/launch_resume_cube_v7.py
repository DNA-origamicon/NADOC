"""Launch the explicitly resumed 0.46 ns remainder, then stop for review."""
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
REPO=Path('/home/jojo/Work/NADOC');sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
art=REPO/'.development-artifacts';root=art/'cpd-anti-gpu-cube-context-v5'
audit=read(Path('/tmp/cpd_resume_audit_v7.json'));assert audit['passed']
for pin in audit['inputs']:checked(pin)
assert subprocess.run(['pgrep','-x','namd3'],capture_output=True).returncode==1
out=root/'anti/replica-1/validation-resume-v7';assert not out.exists()
service=art/'cpd-anti-cube-resume-anti-1-service-v7';service.mkdir(exist_ok=False)
shutil.copy2('/tmp/cpd_resume_audit_v7.json',service/'resume_audit.json')
worker=service/'resume_worker.py';shutil.copy2(REPO/'experiments/cpd_anti_additive/resume_cube_v7.py',worker)
shutil.copy2(Path(__file__),service/'launch_source.py')
authorization=service/'resume_authorization.json'
save(authorization,dict(at=now(),authorized=True,user_instruction='resume',scope='Continue from verified step1300000 through1530000 (0.46ns) only, then audit before next job.',historical_pause=source(root/'campaign_pause_v6.json'),policy='Explicit resume supersedes pause for this bounded job; retain original clocks/pause and all scientific gates.',no_cloud=True,simulation_ready=False))
plan=service/'plan.json';start=time.time()
inputs=audit['inputs']+[source(worker),source(authorization),source(service/'resume_audit.json')]
save(plan,dict(at=now(),authorized=True,root=str(root.resolve()),case='anti',replica=1,engine=source(root/'preparation_engine_v6.py'),authorization=source(authorization),audit=source(service/'resume_audit.json'),inputs=inputs,output=str(out.resolve()),seed=74217,hard_seconds=7200,deadline_epoch=start+7200,seed_policy='New declared Langevin seed74217 for restart; coor,vel and fullXSC from checkpoint1300000 retained. No bitwise trajectory equivalence claimed.',expected_seconds=2400,scientific_review='Saved154frames pass through checkpoint; partial tail after1300000 excluded. Resume exact checkpoint energy checked by CPU run0 and resident initial energy; unchanged geometry/water/image gates,2fs,p4,PME144,NPT force-switch. Stop at1530000 for review.',simulation_ready=False))
unit='cpd-anti-cube-resume-anti-1-v7';codex=shutil.which('codex');assert codex
for src,dst in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/src,service/dst)
save(service/'watcher_config.json',dict(codex_executable=str(Path(codex).resolve()),expected_seconds=2400,self_test=False))
save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(REPO/'.venv/bin/python'),str(worker.resolve()),'run',str(plan.resolve())],cwd=str(REPO),expected_seconds=2400,runtime_hours=2,plan=source(plan),completion_semantics='Only0.46ns remainder; model audit required before subsequent8ns.'))
subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=16G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=2h',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4','/usr/bin/python3',str((service/'supervisor.py').resolve()),'--supervise',str(service.resolve())],check=True)
print(service.resolve())
