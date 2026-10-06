"""Launch the explicitly authorized v4 scope while keeping old NVT jobs held."""
import argparse
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now
from experiments.cpd_anti_additive.gpu_npt_context_v4 import ROOT,ART,authorize


def launch(mode,case=None,rep=None):
    assert os.environ['CODEX_THREAD_ID']=='01a104a1-db92-7162-8c04-7829f85dc38b'
    # A second active NAMD process on this GPU would invalidate timing comparisons.
    p=subprocess.run(['pgrep','-x','namd3'],capture_output=True,text=True)
    assert p.returncode==1,'An existing NAMD process requires review; do not duplicate jobs'
    subprocess.run(['nvidia-smi','--query-gpu=name,uuid,driver_version,memory.total','--format=csv'],check=True)
    qual=ART/'cpd-anti-gpu-force-switch-qualification-v3/qualification_review_20261005.json'
    if mode=='startup':
        assert not (ROOT/'activation.json').exists()
        approval=read(ROOT/'budget_extension_approval.json')
        assert approval['explicit_user_approval'] and approval['context_max_hours']==48
        proposal=read(REPO/'docs/cpd_corrected_context_proposal_20261005.json')
        contract=read(ART/'cpd-anti-readiness-v3-20261003/contract.json')
        context=read(ART/'cpd-anti-context-v3/started.json')
        assert read(qual)['physical_review_complete_for_this_bounded_diagnostic']
        deadline=proposal['budget']['context_proposed_deadline_epoch']
        assert deadline==context['epoch']+48*3600 and deadline<contract['deadline_epoch']
        assert approval['context_deadline_epoch']==deadline
        assert approval['overall_deadline_epoch']==contract['deadline_epoch']
        assert deadline-time.time()>24*3600,'Insufficient remaining time for the complete proposed campaign'
        activation=dict(at=now(),authorized=True,scope='Six fresh matched 10 ns GPU-resident NPT validation runs only',
            user_instruction=approval['user_instruction'],budget_extension_approval=source(ROOT/'budget_extension_approval.json'),
            interpretation='Explicit approval of the concrete 36-to-48-hour context proposal; no change to scientific gates or 72-hour overall cap.',
            context_max_hours=48,context_original_deadline_epoch=context['deadline_epoch'],context_deadline_epoch=deadline,
            overall_deadline_epoch=contract['deadline_epoch'],original_context=source(ART/'cpd-anti-context-v3/started.json'),
            original_contract=source(ART/'cpd-anti-readiness-v3-20261003/contract.json'),
            approved_proposal=source(REPO/'docs/cpd_corrected_context_proposal_20261005.json'),
            qualification_review=source(qual),legacy_hold=source(ART/'cpd-anti-validation-v1/campaign_pause.json'),
            legacy_hold_policy='Preserve the old hold and failed NVT runs. This record admits only the corrected fresh v4 NPT campaign. Any subsequent change to the hold blocks new v4 stages.',
            no_cloud=True,simulation_ready=False,minimum_certified=False)
        for pin in read(ROOT/'inputs_lock.json')['files']:checked(pin)
        save(ROOT/'activation.json',activation)
        worker=REPO/'experiments/cpd_anti_additive/gpu_npt_context_v4.py'
        shutil.copy2(worker,ROOT/'campaign_worker.py');shutil.copy2(Path(__file__),ROOT/'launch_source.py')
        inputs=read(ROOT/'inputs_lock.json')['files']+[source(ROOT/'inputs_lock.json'),source(ROOT/'activation.json'),source(qual),source(ROOT/'campaign_worker.py'),source(ROOT/'launch_source.py')]
        inputs += [source(p) for p in sorted((REPO/'experiments/cpd_anti_additive').glob('*.py'))]
        inputs += [source(REPO/'backend/core'/name) for name in ['dcd_fast.py','namd_solvate.py']]
        inputs += read(ART/'cpd-anti-gpu-force-switch-qualification-v3/plan.json')['inputs']
        # Deduplicate identical pins, retaining all historical inputs without rewriting them.
        inputs=list({(p['path'],p['sha256']):(p) for p in inputs}.values())
        for pin in inputs:checked(pin)
        plan=dict(at=now(),inputs=inputs,activation=source(ROOT/'activation.json'),context_deadline_epoch=deadline,
            cases=['anti','control'],paired_seeds=[41017,52027,63037],atoms=70624,waters=22454,mass_Da=439755.32252,
            stages=dict(common_minimization_steps=1000,per_replica_heating_steps=25000,per_replica_NPT_steps=500000,per_replica_restart_steps=5000),
            ensemble='NPT at 300 K, 1.01325 bar; force switching 10-12 A; ordinary masses, 2 fs; all dynamics GPU resident',
            cell='Isotropic Langevin piston; period200fs/decay100fs; full XSC strain retained; fixed PME72/88/144; actual per-frame cells',
            checkpoint_policy='Unique complete checkpoint.<step>.coor/.vel/.xsc every50000steps (100ps), plus explicit result.restart at each stage/1ns endpoint; archive all sets and verify against saved coordinates/cells.',
            hard_checks='Unchanged stereo/bond/contact, image>12A, waterOO>2A, OH residual beyond storage<1e-5A; static and restart/endpoint tolerances unchanged. Initial unminimized waterOO>1.5A remains static-only.',
            physical_review='Raw 50ps pressure/temperature/density blocks, actual salt concentration, spatial void witnesses; no new favorable threshold or equilibrium claim. Review all six startup states before admission.',
            performance=dict(cores=[4,2,8],affinity=True,steps_per_core_test=100000,ns_per_core_test=.2,selection='Retain4 unless another improves late median step time >5%',
                historical_same_hardware_seconds_per_ns=898.137787,historical_atoms=70604,outputTiming=1000,
                telemetry='Local nvidia-smi every10s during native execution only; no model polling',
                comparison='Same-system NPT benchmark is primary. Report ns/day, wall ns/atom/step, GPU clocks/power/utilization and total review overhead; published unmatched hardware/timestep results are not an acceptance target.'),
            startup_hard_hours=3,subsequent_run_order=[['anti',1],['control',1],['anti',2],['control',2],['anti',3],['control',3]],
            next_stage='Completion wake: inspect native/physical/performance evidence and remaining budget. Freeze validation plan, then launch only first10ns. Each subsequent10ns requires preceding completion_review.json.',
            no_automatic_retries=True,simulation_ready=False,minimum_certified=False)
        save(ROOT/'startup_plan.json',plan)
        unit='cpd-anti-gpu-npt-startup-v4';expected=8500;hours=3
        command=[str(REPO/'.venv/bin/python'),str((ROOT/'campaign_worker.py').resolve()),'startup']
    else:
        activation=authorize();plan=read(ROOT/'validation_plan.json')
        for pin in plan['inputs']:checked(pin)
        assert case in ['anti','control'] and rep in [1,2,3]
        order=[tuple(r) for r in plan['run_order']];idx=order.index((case,rep))
        if idx:
            c,r=order[idx-1];assert read(ROOT/c/f'replica-{r}/validation/completion_review.json')['approved_for_next_run']
        assert not (ROOT/case/f'replica-{rep}/validation').exists()
        remaining=activation['context_deadline_epoch']-time.time()
        expected=plan['expected_seconds_per_10ns']
        assert remaining>(6-idx)*expected+plan['final_context_review_reserve_seconds'],'Remaining complete campaign no longer fits approved absolute deadline'
        hours=min(remaining/3600,expected*1.5/3600)
        unit=f'cpd-anti-gpu-npt-{case}-{rep}-v4'
        command=[str(REPO/'.venv/bin/python'),str((ROOT/'campaign_worker.py').resolve()),'replica','--case',case,'--replica',str(rep)]
    service=ART/(unit.replace('-v4','-service-v4'));service.mkdir(exist_ok=False)
    codex=shutil.which('codex');assert codex
    for name,target in [('watch.py','watcher.py'),('launch.py','supervisor.py')]:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/name,service/target)
    save(service/'watcher_config.json',dict(codex_executable=str(Path(codex).resolve()),expected_seconds=expected,self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,command=command,thread=os.environ['CODEX_THREAD_ID'],cwd=str(REPO),
        expected_seconds=expected,memory_gib=16,omp_threads=8,runtime_hours=hours,
        completion_semantics='Native termination only; mandatory scientific and throughput review before the next10ns replica.',
        approved_campaign_scope=source(ROOT/'activation.json'),scientific_hold_scope='Only corrected v4 campaign authorized; legacy NVT hold remains.',
        plan=source(ROOT/('startup_plan.json' if mode=='startup' else 'validation_plan.json'))))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=16G','--property=MemorySwapMax=0',
        f'--property=RuntimeMaxSec={hours}h',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}',
        '--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=8',
        '/usr/bin/python3',str((service/'supervisor.py').resolve()),'--supervise',str(service.resolve())],check=True)
    # Short startup handshake only. Long-run reviews are exclusively completion-triggered.
    until=time.monotonic()+25
    while time.monotonic()<until:
        if (service/'completion_wake.json').exists() and (service/'status.json').exists():
            wake=read(service/'completion_wake.json');state=read(service/'status.json')
            if wake['state']=='armed' and state['state']=='running':
                print(dict(service=str(service.resolve()),token=wake['token'],watcher_armed=True,status=state['state']));return
            if state['state'] in ['failed','complete']:
                print(dict(service=str(service.resolve()),status=state['state'],review_required=True));return
        time.sleep(.2)
    raise RuntimeError('Startup handshake unresolved; inspect existing service, do not relaunch')


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('mode',choices=['startup','replica']);p.add_argument('--case',choices=['anti','control']);p.add_argument('--replica',type=int,choices=[1,2,3]);a=p.parse_args()
    launch(a.mode,a.case,a.replica)
