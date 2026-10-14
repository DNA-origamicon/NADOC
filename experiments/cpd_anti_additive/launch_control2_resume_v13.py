"""Admit the user-resumed final0.86ns of control2 with a fresh two-hour cap."""
import os
from pathlib import Path
import shutil
import subprocess
import time
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.sella_pilot import save, now

REPO=Path(__file__).resolve().parents[2]

def launch():
    art=REPO/'.development-artifacts'; root=art/'cpd-anti-gpu-cube-context-v5'
    audit_path=Path('/tmp/cpd_control2_resume_audit_v13.json'); audit=read(audit_path)
    assert audit['passed'] and audit['checkpoint']['step']==5100000
    assert sum(s['frames'] for s in audit['segments'])==914
    for pin in audit['inputs']: checked(pin)
    assert subprocess.run(['pgrep','-x','namd3'],capture_output=True).returncode==1
    for unit in ['cpd-anti-cube-validation-control-2-v6','cpd-anti-cube-validation-control-2-v6-watch']:
        assert subprocess.check_output(['systemctl','--user','show',unit,'--property=ActiveState','--value'],text=True).strip()=='inactive'
    service=art/'cpd-control2-resume-service-v13'; output=root/'control/replica-2/validation-resume-v13'
    plan_path=root/'control2_resume_plan_v13.json';auth=root/'control2_resume_authorization_v13.json'
    assert not any(p.exists() for p in [service,output,plan_path,auth])
    codex=shutil.which('codex');assert codex
    thread=os.environ['CODEX_THREAD_ID'];unit='cpd-control2-resume-v13'
    service.mkdir()
    for name,target in [('launch.py','supervisor.py'),('watch.py','watcher.py'),('resume_control2_v13.py','worker.py'),('launch_control2_resume_v13.py','launch_source.py')]:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/name,service/target)
    shutil.copy2(audit_path,service/'resume_audit_raw.json')
    audit['raw_report']=source(service/'resume_audit_raw.json')
    count=sum(len(s['checkpoints']) for s in audit['segments'])
    assert count==92
    audit['periodic_checkpoint_count']=count
    audit['scope']=audit['scope'].replace('91 periodic restart triples',f'{count} periodic restart triples')
    audit['scope_correction']='Count derived from checkpoint records; absolute50000-step cadence gives92 triples,including5050000 and5100000 in the partial segment.'
    save(service/'resume_audit.json',audit)
    save(auth,dict(at=now(),user_instruction='resume.',supersedes_pause=source(root/'campaign_pause_20261008.json'),scope='control2 remaining430000steps only, then independent aggregate and structural/performance audit before next replica',no_cloud=True,hard_seconds=7200,seed=105027,stochastic_continuity='Full coordinates,velocities,XSC; declared fresh RNG seed,not bitwise Langevin continuation'))
    start=time.time(); old=read(root/'validation_control_2_v6.json')
    inputs=audit['inputs']+[source(service/'resume_audit.json'),source(service/'worker.py'),source(service/'launch_source.py'),source(auth)]
    save(plan_path,dict(at=now(),authorized=True,root=str(root.resolve()),case='control',replica=2,seed=105027,engine=old['engine'],authorization=source(auth),audit=source(service/'resume_audit.json'),inputs=inputs,output=str(output.resolve()),hard_seconds=7200,deadline_epoch=start+7200,first_step=5100000,steps=430000,expected_native_seconds=3100,simulation_ready=False,minimum_certified=False))
    save(service/'watcher_config.json',dict(codex_executable=str(Path(codex).resolve()),expected_seconds=4200,review_deadline_epoch=start+6600,review_deadline_id='control2-remainder-review',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=thread,command=[str(REPO/'.venv/bin/python'),str((service/'worker.py').resolve()),'run',str(plan_path.resolve())],cwd=str(REPO),expected_seconds=4200,runtime_hours=2,plan=source(plan_path),completion_semantics='0.86ns remainder only; full independent control2 audit and matched structural/performance review required before anti3. Preserve failures; no automatic retries or readiness promotion.'))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=16G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=2h',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4','/usr/bin/python3',str((service/'supervisor.py').resolve()),'--supervise',str(service.resolve())],check=True)
    print(service.resolve())

if __name__=='__main__':launch()
