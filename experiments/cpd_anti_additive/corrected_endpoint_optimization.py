"""Checkpointed corrected endpoint Sella chunk, with one native gradient at a time."""
from __future__ import annotations
import argparse
import importlib.metadata as metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import (
    BOHR,FORCE_FACTOR,HARTREE_EV,checked,metrics,now,pin,read,save,stationary,xyz,
)
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_anti_additive.endpoint_native import audit_native

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')
ROOT=CAMPAIGN/'endpoint-1-optimization-v1'


class ChunkBoundary(RuntimeError):
    """A planned allocation boundary, distinct from native or chemical failure."""


def admit(attempts, remaining, plan):
    if attempts>=plan['max_new_gradients']:
        raise ChunkBoundary('Gradient allocation exhausted; audit before continuation')
    if remaining<=plan['task_timeout_seconds']+30:
        raise ChunkBoundary('Reserve next-gradient timeout and checkpoint time; audit before continuation')


def context(root):
    plan=read(root/'plan.json')
    if checked(plan['worker'])!=Path(__file__).resolve():raise ValueError('Frozen worker changed')
    for ref in plan['sources']:checked(ref)
    for key in ['authorization','pilot_audit','reference_design','model']:checked(plan[key])
    if plan.get('seed_result'):checked(plan['seed_result'])
    auth=read(checked(plan['authorization']))
    if not auth['user_authorized'] or auth['compute_policy']['cloud_spending_usd']!=0:raise ValueError('Missing local authorization')
    if not read(checked(plan['pilot_audit']))['passed']:raise ValueError('Pilot not audited')
    allocation=(20,5400,600) if plan.get('constraint') else (15,3600,600) if plan.get('continuation_audit') else (30,7200,600)
    if (plan['max_new_gradients'],plan['hard_seconds'],plan['task_timeout_seconds'])!=allocation:raise ValueError('Allocation changed')
    if plan.get('continuation_audit'):
        preceding=read(checked(plan['continuation_audit']))
        if not preceding['passed'] or preceding['last_accepted_result']!=plan['seed_result']:
            raise ValueError('Continuation seed lacks preceding accepted-state audit')
    if plan.get('constraint'):
        from experiments.cpd_anti_additive.endpoint_scan_restart import validate_scan_seed
        validate_scan_seed(plan)
    for name,version in plan['versions'].items():
        if metadata.version(name)!=version:raise ValueError(f'Runtime changed: {name}')
    pause=CAMPAIGN/'pause.json'
    if pause.exists() and read(pause).get('paused'):raise RuntimeError('Campaign paused')
    if (root/'launch_receipt.json').exists():
        execution=read(checked(read(root/'launch_receipt.json')['execution_plan']))
        if checked(execution['plan'])!=root/'plan.json':raise ValueError('Launched plan changed')
    return plan,read(checked(plan['model']))


def prepare():
    import sella,ase
    pilot=CAMPAIGN/'endpoint-1-pilot-v1';recovery=CAMPAIGN/'endpoint-1-pilot-recovery-v1'
    audit=read(recovery/'completion_audit.json');old=read(pilot/'plan.json')
    if not audit['passed']:raise ValueError('Pilot recovery failed')
    seed=read(checked(audit['recovered_result']));model=read(checked(old['model']))
    x=np.load(checked(seed['geometry']))
    if not audit_endpoint(x,model)['passed']:raise ValueError('Seed identity failed')
    ROOT.mkdir(exist_ok=False);(ROOT/'tmp').mkdir()
    shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    versions={n:metadata.version(n) for n in ('sella','ase','numpy','scipy','rdkit','jax','jaxlib')}
    sources=[*old['sources'],*audit['settings_sources'],pin(recovery/'completion_audit.json'),
        seed['native'],seed['input'],seed['geometry'],
        pin(REPO/'experiments/cpd_anti_additive/endpoint_native.py')]
    sources += [pin(p) for p in sorted(Path(sella.__file__).parent.rglob('*.py'))]
    sources += [pin(Path(ase.__file__).parent/n) for n in ('atoms.py','calculators/calculator.py','optimize/optimize.py')]
    plan=dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=sources,versions=versions,
        authorization=old['authorization'],pilot_audit=pin(recovery/'completion_audit.json'),
        reference_design=old['reference_design'],model=old['model'],seed_result=audit['recovered_result'],
        options=old['options'],psi4_version=old['psi4_version'],elements=model['elements'],
        max_new_gradients=30,hard_seconds=7200,task_timeout_seconds=600,expected_seconds=6000,
        threads=4,psi4_memory_gib=4,service_memory_gib=8,
        optimizer=dict(order=0,internal=True,eig=False,delta0=.1,refine_initial_hessian=False,max_cpu_threads=1),
        seed_precision='Native 12-decimal gradient, <=5e-13 au component rounding; reuse instead of duplicate calculation.',
        restart_policy='Last accepted geometry with matching native gradient; fresh Sella history on a separately audited continuation. All evaluated trials retained.',
        stopping_policy='Convergence, 30 new gradients or 2-hour cap; 10-minute timeout per native gradient. Chemistry failures stop immediately. Audit progress at chunk boundary; no automatic continuation.',
        completion_semantics='Chunk completion may mean allocation boundary, not optimizer convergence. Neither optimizer convergence nor service completion certifies a minimum.',
        minimum_certified=False,simulation_ready=False)
    save(ROOT/'plan.json',plan)
    save(ROOT/'preflight.json',dict(at=now(),passed=True,seed_identity=audit_endpoint(x,model),
        measured_pilot_seconds=197,expected_upper_allocation_seconds=30*197,
        startup_force_metrics=metrics(seed['gradient_hartree_bohr']),new_qm_evaluations=0,
        source_optimizer_preflight=pin(CAMPAIGN/'optimization/preflight.json')))
    print(ROOT)


def gradient(root,index):
    plan,model=context(root);folder=root/f'evaluation-{index:03d}'
    inp=read(folder/'input.json');x=np.load(folder/'geometry_bohr.npy')
    if not np.array_equal(x,np.array(inp['geometry_bohr'])) or inp['options']!=plan['options']:
        raise ValueError('Native input differs from plan')
    if not audit_endpoint(x,model)['passed']:raise ValueError('Trial identity failed')
    if plan.get('constraint'):
        from experiments.cpd_anti_additive.endpoint_scan_constraints import require_scan_angle
        require_scan_angle(x,plan['constraint'])
    with (folder/'started.json').open('x') as f:f.write(now()+'\n')
    import psi4
    if psi4.__version__!=plan['psi4_version']:raise ValueError('Psi4 changed')
    os.chdir(folder);psi4.set_output_file(str(folder/'output.dat'),False)
    psi4.set_memory('4 GiB');psi4.set_num_threads(4)
    psi4.core.IOManager.shared_object().set_default_path(str(folder/'scratch'))
    psi4.set_options(plan['options'])
    text='\n'.join(el+' '+' '.join(f'{v:.17g}' for v in pos) for el,pos in zip(plan['elements'],x))
    molecule=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
    stamp=time.monotonic();grad,wfn=psi4.gradient('mp2',molecule=molecule,return_wfn=True)
    elapsed=time.monotonic()-stamp;e=float(wfn.energy());g=np.asarray(grad).copy()
    actual=np.asarray(wfn.molecule().geometry()).copy()
    # Save returned evidence before any downstream parser or geometry check.
    np.save(folder/'returned_geometry_bohr.npy',actual);np.save(folder/'gradient_hartree_bohr.npy',g)
    result=dict(at=now(),energy_hartree=e,gradient_hartree_bohr=g.tolist(),wall_seconds=elapsed,
        input=pin(folder/'input.json'),geometry=pin(folder/'geometry_bohr.npy'),
        returned_geometry=pin(folder/'returned_geometry_bohr.npy'),gradient_binary=pin(folder/'gradient_hartree_bohr.npy'))
    save(folder/'raw_result.json',result)
    psi4.core.clean();psi4.core.flush_outfile();psi4.core.close_outfile()
    if np.max(abs(actual-x))>1e-14 or not audit_endpoint(actual,model)['passed']:raise ValueError('Returned coordinates failed')
    en,gn,audit=audit_native((folder/'output.dat').read_text(),plan['elements'],x)
    if abs(en-e)>1e-9 or np.max(abs(gn-g))>5.1e-13:raise ValueError('Native values differ')
    save(folder/'result.json',dict(**result,native=pin(folder/'output.dat'),native_audit=audit,minimum_certified=False))


def run(root):
    from ase import Atoms
    from ase.calculators.calculator import Calculator,all_changes
    from sella import Sella
    plan,model=context(root)
    seed=read(checked(plan['seed_result'])) if plan.get('seed_result') else None
    seed_x=np.load(checked(seed['geometry'] if seed else plan['starting_geometry']))
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    start=time.monotonic();deadline=read(root/'launch_receipt.json')['deadline_epoch']-30
    rows=[];attempts=0;error=None;boundary=None;converged=False

    def persist():
        save(root/'progress.json',dict(at=now(),evaluations=rows,attempts=attempts,minimum_certified=False))

    def evaluate(x):
        nonlocal attempts
        context(root);admit(attempts,deadline-time.time(),plan)
        audit=audit_endpoint(x,model)
        if not audit['passed']:
            save(root/'rejected_trial.json',dict(geometry_bohr=x.tolist(),audit=audit))
            raise RuntimeError('Trial chemistry failed before QM')
        attempts+=1;folder=root/f'evaluation-{attempts:03d}';folder.mkdir();(folder/'scratch').mkdir()
        np.save(folder/'geometry_bohr.npy',x)
        save(folder/'input.json',dict(geometry_bohr=x.tolist(),elements=plan['elements'],method='mp2',
            options=plan['options'],charge=0,multiplicity=1,at=now(),geometry_audit=audit))
        persist()
        env={**os.environ,'PSI_SCRATCH':str(folder/'scratch'),'TMPDIR':str(folder/'scratch')}
        with (folder/'runner.log').open('x') as log:
            child=subprocess.run([str(PYTHON),str(checked(plan['worker'])),'gradient',str(root),'--index',str(attempts)],
                env=env,cwd=folder,stdout=log,stderr=subprocess.STDOUT,timeout=plan['task_timeout_seconds'])
        if child.returncode:raise RuntimeError(f'Native gradient {attempts} failed: {child.returncode}')
        result=read(folder/'result.json');g=np.asarray(result['gradient_hartree_bohr'])
        checked(result['native']);checked(result['input']);checked(result['geometry'])
        rows.append(dict(result=pin(folder/'result.json'),**metrics(g)));persist()
        return result['energy_hartree'],g

    class CalculatorWithEvidence(Calculator):
        implemented_properties=['energy','forces']
        def calculate(self,atoms=None,properties=('energy','forces'),system_changes=all_changes):
            super().calculate(atoms,properties,system_changes)
            x=self.atoms.positions/BOHR
            if plan.get('constraint'):
                from experiments.cpd_anti_additive.endpoint_scan_constraints import require_scan_angle
                try:require_scan_angle(x,plan['constraint'])
                except ValueError as exc:
                    save(root/'rejected_constraint_trial.json',dict(at=now(),geometry_bohr=x.tolist(),constraint=plan['constraint'],error=str(exc)))
                    raise
            if seed is not None and not rows and np.allclose(x,seed_x,atol=1e-12,rtol=0):
                e,g=seed['energy_hartree'],np.asarray(seed['gradient_hartree_bohr'])
                rows.append(dict(result=plan['seed_result'],reused=True,**metrics(g)));persist()
            else:e,g=evaluate(x)
            self.results=dict(energy=e*HARTREE_EV,forces=-g*FORCE_FACTOR)

    atoms=Atoms(plan['elements'],positions=seed_x*BOHR);atoms.calc=CalculatorWithEvidence()
    constraints=None
    if plan.get('constraint'):
        from experiments.cpd_anti_additive.endpoint_scan_geometry import constraint_metrics
    class AuditedSella(Sella):
        def converged(self,forces=None):
            native=bool(super().converged(forces));g=-atoms.get_forces(apply_constraint=False)/FORCE_FACTOR
            values=metrics(g);identity=audit_endpoint(atoms.positions/BOHR,model)
            passed=stationary(values)
            if plan.get('constraint'):
                values,_=constraint_metrics(atoms.positions/BOHR,g,plan['constraint'])
                passed=values['passed']
            save(root/'latest_convergence.json',dict(at=now(),optimizer_converged=native,
                independent_stationarity_passed=passed,gradient_metrics=values,geometry=identity))
            return native and passed and identity['passed']

    try:
        if plan.get('constraint'):
            from experiments.cpd_anti_additive.endpoint_scan_constraints import make_scan_constraints
            constraints,configuration=make_scan_constraints(atoms,plan['constraint'])
            save(root/'constraint_configuration.json',dict(at=now(),**configuration))
        optimizer=AuditedSella(atoms,constraints=constraints,**plan['optimizer'],logfile=str(root/'sella.log'),trajectory=str(root/'sella.traj'))
        def checkpoint():
            x=atoms.positions/BOHR
            if plan.get('constraint'):
                from experiments.cpd_anti_additive.endpoint_scan_constraints import require_scan_angle
                require_scan_angle(x,plan['constraint'])
            if not audit_endpoint(x,model)['passed']:raise RuntimeError('Accepted geometry identity failed')
            matches=[v['result'] for v in rows if np.allclose(np.load(checked(read(checked(v['result']))['geometry'])),x,atol=1e-12,rtol=0)]
            if not matches:raise RuntimeError('Accepted checkpoint lacks native evaluation')
            path=root/f'accepted-{optimizer.nsteps:03d}.xyz'
            path.write_text(xyz(plan['elements'],x,'Accepted endpoint; minimum not certified'))
            save(root/'restart_checkpoint.json',dict(at=now(),geometry=pin(path),evaluated_source=matches[-1],
                step=optimizer.nsteps,optimizer_state_restorable=False,minimum_certified=False))
        optimizer.attach(checkpoint,interval=1)
        converged=bool(optimizer.run(fmax=1.5e-5*FORCE_FACTOR,steps=60))
        if not converged:raise ChunkBoundary('Optimizer step boundary; audit before continuation')
        (root/'optimized.xyz').write_text(xyz(plan['elements'],atoms.positions/BOHR,
            'Constrained stationary scan target; minimum not certified' if plan.get('constraint') else 'Stationary endpoint; minimum not certified'))
    except ChunkBoundary as exc:boundary=str(exc)
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json',dict(at=now(),error=error,allocation_boundary=boundary,optimizer_converged=converged,
        new_gradient_attempts=attempts,new_gradients_completed=sum(not v.get('reused',False) for v in rows),
        evaluated_records=len(rows),wall_seconds=time.monotonic()-start,minimum_certified=False,simulation_ready=False,
        requires_completion_audit=True,stationarity_scope='constrained glycosidic scan' if plan.get('constraint') else 'unconstrained endpoint'))
    return 1 if error else 0


def launch(root):
    import importlib.util
    from experiments.cpd_anti_additive.endpoint_resource_admission import memory_requirement
    spec=importlib.util.spec_from_file_location('frozen_endpoint_optimization',root/'executed_source.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);plan,_=module.context(root)
    if not read(root/'preflight.json')['passed']:raise ValueError('Preflight failed')
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in row and '-watch' not in row for row in units.splitlines()):raise RuntimeError('Other CPD job active')
    processes=subprocess.check_output(['ps','-eo','args='],text=True).splitlines()
    if any(row.strip().split(' ')[0].split('/')[-1] in ('namd2','namd3','psi4') for row in processes):raise RuntimeError('Other native job active')
    mem={row.split(':')[0]:int(row.split()[1])*1024 for row in Path('/proc/meminfo').read_text().splitlines() if row.startswith(('MemAvailable:','SwapFree:'))}
    required_memory,resource_review=memory_requirement(root,plan)
    if mem['MemAvailable']<required_memory or shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Insufficient resource headroom')
    service=CAMPAIGN/(root.name+'-service');service.mkdir(exist_ok=False)
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    stamp=time.time();seconds=plan['hard_seconds'];unit=plan.get('unit','cpd-corrected-anti1-endpoint1-optimization-v1')
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),expected_seconds=plan['expected_seconds'],review_deadline_epoch=stamp+seconds-600,review_deadline_id='endpoint1-optimization-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(PYTHON),str(root/'executed_source.py'),'run',str(root)],cwd=str(root),runtime_hours=seconds/3600,memory_gib=8,omp_threads=4,plan=pin(root/'plan.json'),completion_semantics=plan['completion_semantics']))
    shutil.copy2(Path(__file__),root/'admitted_launcher_source.py')
    save(root/'launch_receipt.json',dict(at=now(),unit=unit,deadline_epoch=stamp+seconds,prelaunch_memory=mem,
        required_available_memory_bytes=required_memory,resource_review=resource_review,launcher_source=pin(root/'admitted_launcher_source.py'),
        resource_admission_source=pin(REPO/'experiments/cpd_anti_additive/endpoint_resource_admission.py'),
        execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G','--property=MemorySwapMax=0',f'--property=RuntimeMaxSec={seconds-15}s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=400%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4','--setenv=JAX_PLATFORMS=cpu',f'--setenv=PSI_SCRATCH={root}/tmp',f'--setenv=TMPDIR={root}/tmp','/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=('prepare','launch','run','gradient'));p.add_argument('root',nargs='?',type=Path,default=ROOT);p.add_argument('--index',type=int)
    args=p.parse_args();root=args.root.resolve()
    if args.action=='prepare':prepare()
    elif args.action=='gradient':gradient(root,args.index)
    elif args.action=='run':sys.exit(run(root))
    else:launch(root)
