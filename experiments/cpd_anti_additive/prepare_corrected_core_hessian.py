"""Freeze and launch a single reviewed corrected-core Hessian batch."""
from pathlib import Path
import argparse
import os
import shutil
import subprocess
import sys
import time

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import checked,now,pin,read,save

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT=CAMPAIGN/'hessian-stage2-v1'
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')


def prepare():
    import psi4,qcelemental,qcengine
    root=ROOT;root.mkdir(exist_ok=False)
    (root/'tmp').mkdir()
    preview=read(CAMPAIGN/'hessian-preview-v1/preview.json')
    auth=CAMPAIGN/'campaign_authorization_20261010.json'
    if not read(auth)['user_authorized']:raise ValueError('Missing authorization')
    proposal=read(checked(read(auth)['approved_hessian_allocation']))
    checked(proposal['preview'])
    records=[]
    for task in preview['tasks']:
        folder=root/'tasks'/f"{task['index']:03d}"
        folder.mkdir(parents=True)
        source=checked(task['input']);shutil.copyfile(source,folder/'input.json')
        records.append(dict(id=f"gradient-{task['index']:03d}",index=task['index'],label=task['label'],
            input=dict(path=str((folder/'input.json').relative_to(root)),sha256=pin(source)['sha256']),
            result=dict(path=str((folder/'result.json').relative_to(root))),
            run_record=dict(path=str((folder/'run_record.json').relative_to(root)))))
    engine=dict(name='Psi4',version=psi4.__version__,qcengine_version=qcengine.__version__,
                qcelemental_version=qcelemental.__version__)
    distributed=dict(schema='nadoc.photoproduct-distributed-hessian-plan.v1',status='prepared_not_run',
         gate_effect='none',product_id='tt-cpd-cis-anti-i',model_id='corrected-n1-methyl-cis-anti-i-v1',
         task_count=211,tasks=records,engine=engine,method='mp2',basis='6-31g(d)',
         default_resources_per_task=dict(threads=4,memory_gib=4),
         exact_preview=proposal['preview'],finite_difference=preview['finite_difference'],
         assembly_scope='Use frozen corrected-core replayer; original generic frequency-job protocol does not encode these exact tighter options.')
    save(root/'distributed_hessian_plan.json',distributed)
    for name in ['corrected_core_hessian.py','prepare_corrected_core_hessian.py']:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/name,root/name)
    sources=[pin(REPO/name) for name in [
         'experiments/cpd_anti_additive/corrected_core_stage1.py',
         'experiments/cpd_anti_additive/audit_corrected_core_stage1.py',
         'backend/parameterization/photoproduct_distributed_hessian.py',
         'backend/parameterization/photoproduct_qm.py']]
    sources += [pin(root/'prepare_corrected_core_hessian.py'),proposal['preview'],
                pin(CAMPAIGN/'hessian_stage2_proposal.json')]
    save(root/'manifest.json',dict(at=now(),campaign_root=str(CAMPAIGN),
         campaign_authorization=pin(auth),stage1_audit=proposal['source_stationarity_audit'],
         worker=pin(root/'corrected_core_hessian.py'),distributed_plan=pin(root/'distributed_hessian_plan.json'),
         sources=sources,engine=engine,allowed_batches=['batch-1','batch-2'],
         expected_gradient_seconds=57.77997862203047,soft_mode_review_threshold_cm_inverse=10.,
         minimum_certified=False,gate_effect='none'))
    print(root)


def launch(batch_id,root=ROOT,unit_version='v1',proposal=None):
    preflight=read(root/'preflight.json')
    if not preflight['passed']:raise ValueError('Preflight failed')
    manifest=read(root/'manifest.json')
    for ref in manifest['sources']:checked(ref)
    checked(manifest['worker']);checked(manifest['campaign_authorization'])
    proposal=proposal or read(CAMPAIGN/'hessian_stage2_proposal.json')
    selected=next(b for b in proposal['batches'] if b['id']==batch_id)
    pause=CAMPAIGN/'pause.json'
    if pause.exists() and read(pause).get('paused'):raise RuntimeError('User paused campaign')
    decision=None
    if batch_id=='batch-2':
        decision=root/'batch1_continuation_decision.json'
        verdict=read(decision)
        if not verdict['proceed'] or not read(checked(verdict['batch_review']))['passed']:
            raise ValueError('Batch-one continuation audit missing or failed')
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line for line in units.splitlines()):raise RuntimeError('A CPD service is active')
    if subprocess.run(['pgrep','-x','namd3'],capture_output=True).returncode==0:raise RuntimeError('NAMD is active')
    mem={line.split(':')[0]:int(line.split()[1])*1024 for line in Path('/proc/meminfo').read_text().splitlines()
         if line.startswith(('MemAvailable:','SwapFree:'))}
    if mem['MemAvailable']<12*1024**3:raise RuntimeError('RAM admission below 12 GiB')
    if shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Insufficient Archive space')
    codex=shutil.which('codex');thread=os.environ['CODEX_THREAD_ID']
    if not codex:raise RuntimeError('Completion watcher executable missing')
    batch=root/batch_id;batch.mkdir(exist_ok=False)
    service=root/(batch_id+'-service');service.mkdir(exist_ok=False)
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:
        shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    unit='cpd-corrected-anti1-hessian-'+batch_id+'-'+unit_version
    allocation=dict(at=now(),batch_id=batch_id,hard_seconds=10800,task_indices=selected['task_indices'],
         manifest=pin(root/'manifest.json'),authorization=manifest['campaign_authorization'],
         preflight=pin(root/'preflight.json'),concurrent_tasks=1)
    if decision:allocation['preceding_audit_decision']=pin(decision)
    save(batch/'plan.json',allocation)
    start=time.time()
    expected=selected['expected_gradient_hours']*3600
    save(service/'watcher_config.json',dict(codex_executable=str(Path(codex).resolve()),
         expected_seconds=expected,review_deadline_epoch=start+min(10200,expected*1.5+300),
         review_deadline_id='corrected-core-hessian-'+batch_id,self_test=False))
    command=[str(PYTHON),str(root/'corrected_core_hessian.py'),'run',str(root),'--batch',batch_id]
    save(service/'execution_plan.json',dict(unit=unit,thread=thread,command=command,cwd=str(batch),
         runtime_hours=3,memory_gib=8,omp_threads=4,plan=pin(batch/'plan.json'),
         completion_semantics='Audit this batch independently. All-stage campaign continuation is authorized, but another job needs a recorded passed audit and finite allocation. No cloud spending.'))
    save(batch/'launch_receipt.json',dict(at=now(),deadline_epoch=start+10800,unit=unit,
         prelaunch_memory=mem,execution_plan=pin(service/'execution_plan.json'),
         supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py'),launcher=pin(Path(__file__))))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G',
         '--property=MemorySwapMax=0','--property=RuntimeMaxSec=10785s','--property=TimeoutStopSec=15s',
         '--property=KillMode=control-group','--property=CPUQuota=400%',
         f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}',
         '--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1',
         '--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4','--setenv=JAX_PLATFORMS=cpu',
         f'--setenv=TMPDIR={root}/tmp',f'--setenv=PSI_SCRATCH={root}/tmp',
         '/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('prepare','launch'))
    parser.add_argument('--batch',choices=('batch-1','batch-2'),default='batch-1')
    args=parser.parse_args()
    prepare() if args.action=='prepare' else launch(args.batch)
