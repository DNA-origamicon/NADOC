"""Admit exactly one reviewed successor in the final-cube preparation sequence."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO = Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.sella_pilot import save, now

ORDER = [('anti',1),('control',1),('anti',2),('control',2),('anti',3),('control',3)]


def reviewed_predecessors(root, case, rep):
    pins = []
    for previous_case, previous_rep in ORDER[:ORDER.index((case,rep))]:
        review_path = root/previous_case/f'replica-{previous_rep}'/'completion_review.json'
        review = read(review_path)
        assert review['approved_for_next_run'], 'Previous preparation requires scientific review'
        checked(review['audit'])
        assert read(review['audit']['path'])['passed']
        pins += [source(review_path),review['audit']]
    return pins


def launch(case, rep):
    art = REPO/'.development-artifacts'; root = art/'cpd-anti-gpu-cube-context-v5'
    predecessor_pins = reviewed_predecessors(root,case,rep)
    assert not (root/case/f'replica-{rep}').exists(), 'Preserve previous outputs; audit before restart admission'
    assert subprocess.run(['pgrep','-x','namd3'],capture_output=True).returncode == 1, 'Existing NAMD job must finish first'
    authorization = root/'sequential_authorization_20261006.json'
    assert read(authorization)['authorized'] and read(authorization)['no_cloud']
    worker, engine = root/'preparation_worker_v6.py', root/'preparation_engine_v6.py'
    original = read(root/'preparation_anti_1_v6.json')
    # Reuse the qualified frozen implementation, including its pinned imports.
    for pin in original['inputs']:
        checked(pin)
    assert source(engine) == original['engine']
    inputs = original['inputs'] + predecessor_pins + [source(Path(__file__)),source(root/'preparation_anti_1_v6.json')]
    if rep > 1:
        for name in ['static_assessment.json','minimize/geometry.json','minimize/result.coor']:
            inputs.append(source(root/case/name))
    plan_path = root/f'preparation_{case}_{rep}_v6.json'
    service = art/f'cpd-anti-cube-prep-{case}-{rep}-service-v6'
    assert not plan_path.exists() and not service.exists(), 'Admission already exists; do not reset its clock'
    codex = shutil.which('codex'); assert codex
    thread = os.environ['CODEX_THREAD_ID']
    unit = f'cpd-anti-cube-prep-{case}-{rep}-v6'
    service.mkdir()
    shutil.copy2(Path(__file__),service/'launch_source.py')
    for name, target in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/name,service/target)
    save(plan_path,dict(at=now(),authorized=True,root=str(root.resolve()),case=case,replica=rep,seed=[41017,52027,63037][rep-1],engine=source(engine),authorization=source(authorization),inputs=inputs,hard_seconds=10800,deadline_epoch=time.time()+10800,expected_seconds=5400,
        stages='Static CPU/GPU check and common minimization for first replica only; 50 ps heat, 1 ns NPT, 10 ps restart for each replica',
        audit='Stop after this job. Audit native/cell/checkpoint evidence, chemistry, physical blocks, salt, voids, runtime, necessity and alternatives before another admission.',
        interruption='Retain all native outputs and 100 ps coor/vel/full-XSC checkpoints. Audit last complete triple before a newly named continuation; never overwrite stages.',simulation_ready=False))
    save(service/'watcher_config.json',dict(codex_executable=str(Path(codex).resolve()),expected_seconds=5400,self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=thread,command=[str(REPO/'.venv/bin/python'),str(worker.resolve()),'--plan',str(plan_path.resolve())],cwd=str(REPO),expected_seconds=5400,runtime_hours=3,plan=source(plan_path),completion_semantics='One preparation only; mandatory scientific and performance review before the next job.'))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=16G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=3h',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4','/usr/bin/python3',str((service/'supervisor.py').resolve()),'--supervise',str(service.resolve())],check=True)
    print(service.resolve())


if __name__ == '__main__':
    parser = argparse.ArgumentParser(); parser.add_argument('--case',choices=['anti','control'],required=True); parser.add_argument('--replica',type=int,choices=[1,2,3],required=True)
    args = parser.parse_args(); launch(args.case,args.replica)
