"""Admit a single sequential validation within the user's per-process limit."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
REPO = Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.launch_cube_preparation_v6 import ORDER


def launch(case,rep):
    art=REPO/'.development-artifacts';root=art/'cpd-anti-gpu-cube-context-v5'
    aggregate=root/'startup_admission_v6.json';summary=read(aggregate)
    assert summary['approved_for_validation']
    inputs=list(summary['inputs'])+[source(aggregate)]
    for c,r in ORDER[:ORDER.index((case,rep))]:
        review_path=root/c/f'replica-{r}/validation/completion_review.json'
        review=read(review_path);assert review['approved_for_next_run']
        for key in ['assessment','audit','performance_report']:
            checked(review[key]);inputs.append(review[key])
        inputs.append(source(review_path))
    for pin in inputs:checked(pin)
    assert subprocess.run(['pgrep','-x','namd3'],capture_output=True).returncode==1
    folder=root/case/f'replica-{rep}';assert not (folder/'validation').exists()
    plan_path=root/f'validation_{case}_{rep}_v6.json';assert not plan_path.exists()
    service=art/f'cpd-anti-cube-validation-{case}-{rep}-service-v6';assert not service.exists()
    worker=root/'validation_worker_v6.py'
    current=REPO/'experiments/cpd_anti_additive/gpu_cube_validation_v6.py'
    if worker.exists():assert source(worker)['sha256']==source(current)['sha256']
    else:shutil.copy2(current,worker)
    inputs += [source(worker),source(Path(__file__)),source(REPO/'experiments/cpd_anti_additive/launch_cube_preparation_v6.py')]
    cp=folder/'restart/result.restart'
    for ext in ['coor','vel','xsc']:inputs.append(source(Path(str(cp)+'.'+ext)))
    budget=summary['budget'];assert budget['conservative_total_seconds']<15*3600
    codex=shutil.which('codex');assert codex
    thread=os.environ['CODEX_THREAD_ID'];unit=f'cpd-anti-cube-validation-{case}-{rep}-v6'
    service.mkdir()
    shutil.copy2(Path(__file__),service/'launch_source.py')
    for name,target in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/name,service/target)
    start=time.time()
    save(plan_path,dict(at=now(),authorized=True,root=str(root.resolve()),case=case,replica=rep,seed=[41017,52027,63037][rep-1]+3000,engine=source(root/'preparation_engine_v6.py'),authorization=source(root/'sequential_authorization_20261006.json'),inputs=inputs,startup_admission=source(aggregate),checkpoint_prefix=str(cp.resolve()),hard_seconds=54000,deadline_epoch=start+54000,reference_native_seconds_per_ns=budget['worst_native_seconds_per_ns'],reference_segment_seconds=budget['worst_native_seconds_per_ns']+budget['worst_analysis_seconds_per_ns'],
        dynamics='10 sequential1ns segments,GPUresident NPT300K/1.01325bar,2fs ordinary masses,p4,PME144cubed,force-switch10-12A,fullXSC',
        sampling='DCD10ps,raw native energy2ps,unique restart100ps plus every1ns endpoint; unchanged prior validation cadence and registered observables',
        audits='Every1ns: all saved frame chemistry/water/image,cell/restarts,CPU endpoint energy,physical blocks,voids,observables and performance. Failures stop. >20% native slowdown stops for review. Completed10ns requires independent native replay and model physical/structural/necessity/performance review before next replica.',
        recovery='No automatic rerun. Preserve partial directories; audit last complete checkpoint triple and completed segments before admitting a uniquely named continuation.',simulation_ready=False,minimum_certified=False))
    save(service/'watcher_config.json',dict(codex_executable=str(Path(codex).resolve()),expected_seconds=39600,review_deadline_epoch=start+13*3600,review_deadline_id='validation-13h-review',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=thread,command=[str(REPO/'.venv/bin/python'),str(worker.resolve()),'--plan',str(plan_path.resolve())],cwd=str(REPO),expected_seconds=39600,runtime_hours=15,plan=source(plan_path),completion_semantics='One10ns validation only. Scientific and performance review before next replica; no readiness promotion.'))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=16G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=15h',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4','/usr/bin/python3',str((service/'supervisor.py').resolve()),'--supervise',str(service.resolve())],check=True)
    print(service.resolve())


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--case',choices=['anti','control'],required=True);p.add_argument('--replica',type=int,choices=[1,2,3],required=True);args=p.parse_args();launch(args.case,args.replica)
