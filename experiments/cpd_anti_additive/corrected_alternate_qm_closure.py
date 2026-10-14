"""One checkpointed fixed-core QM branch-closure chunk; reuse native pilot."""
from pathlib import Path
import argparse
import importlib.metadata as metadata
import os
import shutil
import subprocess
import sys
import time
import traceback
import numpy as np

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]));sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now,BOHR,FORCE_FACTOR,HARTREE_EV
from experiments.cpd_anti_additive.corrected_coupled_ring import require_archive
from experiments.cpd_anti_additive.corrected_fixed_core_boundary import free_projection
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_anti_additive.endpoint_scan_constraints_v2 import make_scan_constraints
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion,wrapped

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT=CAMPAIGN/'alternate-sugar-qm-closure-v1'
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')


class ChunkBoundary(RuntimeError):
    """A planned stop requiring audit, not a scientific convergence claim."""


def admit(attempts,remaining,plan):
    if attempts>=plan['max_new_gradients']:raise ChunkBoundary('New-gradient allocation exhausted')
    if remaining<=plan['task_timeout_seconds']+30:raise ChunkBoundary('Insufficient time for another complete gradient and checkpoint')


def geometry_constraints(x_bohr,reference_bohr,fixed,spec):
    x=np.asarray(x_bohr,float);reference=np.asarray(reference_bohr,float)
    if x.shape!=reference.shape or not np.isfinite(x).all():raise ValueError('Invalid constrained geometry')
    drift=float(np.max(abs(x[list(fixed)]-reference[list(fixed)]))*BOHR)
    chi_error=abs(wrapped(torsion(x,spec['indices'])-spec['target_degrees']))
    if drift>1e-7 or chi_error>min(.01,spec['tolerance_degrees']):raise ValueError('Trial violates fixed-core or chi target')
    return dict(maximum_fixed_drift_A=drift,chi_error_degrees=chi_error)


def stationarity(x_bohr,gradient_au,fixed,free,spec):
    tangent=free_projection(np.asarray(x_bohr)*BOHR,gradient_au,fixed,spec['indices'])
    norms=np.linalg.norm(tangent[list(free)],axis=1)
    maximum=float(norms.max());rms=float(np.sqrt(np.mean(norms**2)))
    return dict(max_free_projected_atom_gradient_au=maximum,rms_free_projected_atom_gradient_au=rms,
                passed=maximum<1.5e-5 and rms<1e-5,
                scope='Gradient projected tangent to fixed32core atoms and chi; RMS uses only17free atoms, not fixed-atom zeros.')


def constraints_for(atoms,reference_bohr,fixed,spec):
    constraints,configuration=make_scan_constraints(atoms,spec,accepted_restart=True)
    for i in fixed:
        for axis in range(3):constraints.fix_translation(index=int(i),dim=axis,target=float(reference_bohr[i,axis]*BOHR))
    rank=int(np.linalg.matrix_rank(constraints.jacobian(),tol=1e-8))
    if rank!=97:raise ValueError('Expected97independent constraints')
    return constraints,dict(**configuration,rank=rank,free_dimensions=3*len(atoms)-rank,
                           fixed_target='Original native QM reference coordinates, retained across restarts.')


def context(root):
    require_archive(root);p=read(root/'plan.json')
    if checked(p['worker'])!=Path(__file__).resolve():raise ValueError('Use frozen optimizer worker')
    for ref in p['sources']:checked(ref)
    for key in ['model','seed_result','reference_geometry','native_template','native_worker','pilot_audit','authorization']:checked(p[key])
    assert read(checked(p['authorization']))['user_authorized'] and read(checked(p['authorization']))['compute_policy']['cloud_spending_usd']==0
    assert read(checked(p['pilot_audit']))['fixed_core_qm_chunk_admitted']
    assert (p['max_new_gradients'],p['hard_seconds'],p['task_timeout_seconds'])==(12,3600,600)
    if (CAMPAIGN/'pause.json').exists() and read(CAMPAIGN/'pause.json').get('paused'):raise RuntimeError('Campaign paused')
    for name,version in p['versions'].items():
        if metadata.version(name)!=version:raise ValueError(f'Runtime changed:{name}')
    if (root/'launch_receipt.json').exists():
        assert checked(read(checked(read(root/'launch_receipt.json')['execution_plan']))['plan'])==root/'plan.json'
    return p,read(checked(p['model']))


def prepare():
    from ase import Atoms
    require_archive(CAMPAIGN)
    pilot=CAMPAIGN/'alternate-sugar-qm-pilot-v1';audit=read(pilot/'completion_audit.json');assert audit['passed'] and audit['fixed_core_qm_chunk_admitted']
    old=read(checked(audit['plan']));seed=read(checked(audit['result']));model=read(checked(old['model']))
    x=np.load(checked(seed['geometry']));reference=np.load(checked(old['reference_geometry']));g=np.load(checked(seed['gradient_binary']))
    geometry=geometry_constraints(x,reference,old['fixed_indices'],old['constraint']);assert audit_endpoint(x,model)['passed']
    atoms=Atoms(model['elements'],positions=x*BOHR);constraints,configuration=constraints_for(atoms,reference,old['fixed_indices'],old['constraint'])
    jac=np.array(constraints.jacobian());_,s,v=np.linalg.svd(jac,full_matrices=True);q=v[len(s):].T
    projected=free_projection(atoms.positions,g,old['fixed_indices'],old['constraint']['indices'])
    projection_error=float(np.max(abs(projected.ravel()-q@(q.T@g.ravel()))));assert projection_error<1e-9
    ROOT.mkdir();(ROOT/'tmp').mkdir();shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    sources=[pin(pilot/'completion_audit.json'),audit['plan'],audit['result'],seed['native'],seed['input'],seed['geometry'],seed['gradient_binary'],old['reference_geometry'],old['worker']]
    for name in ['corrected_core_stage1.py','corrected_coupled_ring.py','corrected_fixed_core_boundary.py','corrected_mm_endpoint_profile.py',
                 'prepare_corrected_endpoints.py','endpoint_scan_constraints_v2.py','endpoint_scan_constraints.py','endpoint_scan_geometry.py']:
        sources.append(pin(REPO/'experiments/cpd_anti_additive'/name))
    plan=dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=sources,authorization=old['authorization'],model=old['model'],
        pilot_audit=pin(pilot/'completion_audit.json'),seed_result=audit['result'],reference_geometry=old['reference_geometry'],reference_result=old['reference_result'],
        native_template=audit['plan'],native_worker=old['worker'],fixed_indices=old['fixed_indices'],free_indices=old['free_indices'],constraint=old['constraint'],
        versions={n:metadata.version(n) for n in ['numpy','scipy','rdkit','sella','ase','jax','jaxlib']},
        optimizer=dict(order=0,internal=True,eig=False,delta0=.1,constraints_tol=1e-9,refine_initial_hessian=False,max_cpu_threads=1),
        max_new_gradients=12,hard_seconds=3600,task_timeout_seconds=600,expected_seconds=12*audit['native_seconds']+120,
        threads=4,psi4_memory_gib=4,service_memory_gib=8,
        stationarity='Independent tangent max atom gradient<1.5e-5au and RMS over17free atoms<1e-5au; native Sella convergence also required. No curvature or minimum certification.',
        fixed_target_policy='Keep original QM reference positions for all32fixed atoms, including accepted restarts; do not reset fixed targets to residual-shifted checkpoints. Exact same chi target. Solver constraint tolerance1e-9; pre-QM fixed-position1e-7A/chi0.01degree checks unchanged.',
        native_execution='Reuse audited pilot native gradient worker unchanged, with one immutable input/plan/scratch folder per new gradient. Parent subprocess timeout600seconds. No change to MP2, basis, frozen core, SCF/response tolerances or fitting condition.',
        restart_policy='Reuse full-precision pilot gradient at startup; every accepted Sella checkpoint names an actually evaluated native geometry/gradient. All evaluated trials retained. Fresh optimizer history only on a separately audited continuation.',
        completion_semantics='Convergence or planned12-gradient/time boundary. Both are service completion, not minimum or basin certification. Audit progress and necessity before continuation.',
        fit_round_consumed=False,heldout_accessed=False,minimum_certified=False,basin_closure_certified=False,simulation_ready=False,cloud_spending_usd=0)
    save(ROOT/'plan.json',plan)
    save(ROOT/'preflight.json',dict(at=now(),passed=True,plan=pin(ROOT/'plan.json'),geometry=geometry,identity=audit_endpoint(x,model),
        constraints=configuration,independent_projection_error_au=projection_error,initial_stationarity=stationarity(x,g,old['fixed_indices'],old['free_indices'],old['constraint']),
        pilot_gradient_reused=True,new_qm_evaluations=0,expected_minutes=plan['expected_seconds']/60))
    print(dict(root=str(ROOT),configuration=configuration,projection_error=projection_error,expected_minutes=plan['expected_seconds']/60))


def run(root):
    from ase import Atoms
    from ase.calculators.calculator import Calculator,all_changes
    from sella import Sella
    p,model=context(root);assert read(root/'admission.json')['passed']
    seed=read(checked(p['seed_result']));seed_x=np.load(checked(seed['geometry']));reference=np.load(checked(p['reference_geometry']))
    deadline=read(root/'launch_receipt.json')['deadline_epoch']-30;attempts=0;rows=[];accepted=[];error=None;boundary=None;converged=False
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    def persist():save(root/'progress.json',dict(at=now(),attempts=attempts,evaluations=rows,accepted=accepted,minimum_certified=False))
    def evaluate(x):
        nonlocal attempts
        context(root);admit(attempts,deadline-time.time(),p)
        check=geometry_constraints(x,reference,p['fixed_indices'],p['constraint']);identity=audit_endpoint(x,model)
        if not identity['passed']:
            save(root/'rejected_trial.json',dict(at=now(),geometry_bohr=x.tolist(),identity=identity));raise RuntimeError('Trial chemistry failed before QM')
        attempts+=1;folder=root/f'evaluation-{attempts:03d}';folder.mkdir();(folder/'scratch').mkdir();(folder/'tmp').mkdir()
        np.save(folder/'geometry_bohr.npy',x)
        template=read(checked(p['native_template']))
        save(folder/'input.json',dict(at=now(),elements=model['elements'],geometry_bohr=x.tolist(),options=template['options'],method='mp2',charge=0,multiplicity=1,
            geometry_audit=identity,constraint_audit=check))
        native_plan={**template,'at':now(),'worker':p['native_worker'],'geometry':pin(folder/'geometry_bohr.npy'),'input':pin(folder/'input.json'),
            'sources':[*template['sources'],pin(root/'plan.json'),p['seed_result']],
            'coordinate_conversion':dict(angstrom_per_bohr=BOHR,rule='Native Bohr geometry from current accepted/trial ASE positions; original fixed reference/chi enforced before QM. No position restoration during optimization.'),
            'purpose':'One trial gradient for the bounded alternate-sugar QM closure; original native method unchanged.',
            'parent_optimization_plan':pin(root/'plan.json')}
        save(folder/'plan.json',native_plan)
        row=dict(index=attempts,folder=str(folder),state='running',native_plan=pin(folder/'plan.json'));rows.append(row);persist()
        env={**os.environ,'TMPDIR':str(folder/'tmp'),'PSI_SCRATCH':str(folder/'scratch')}
        with (folder/'runner.log').open('x') as log:
            child=subprocess.run([str(PYTHON),str(checked(p['native_worker'])),'gradient',str(folder)],cwd=folder,env=env,
                stdout=log,stderr=subprocess.STDOUT,timeout=p['task_timeout_seconds'])
        if child.returncode:
            row['state']='failed';row['returncode']=child.returncode;persist();raise RuntimeError(f'Native gradient{attempts} failed')
        result=read(folder/'result.json');gradient=np.load(checked(result['gradient_binary']))
        assert np.array_equal(x,np.load(checked(result['geometry'])))
        row.update(state='complete',result=pin(folder/'result.json'),stationarity=stationarity(x,gradient,p['fixed_indices'],p['free_indices'],p['constraint']))
        persist();return result['energy_hartree'],gradient
    class NativeCalculator(Calculator):
        implemented_properties=['energy','forces']
        def calculate(self,atoms=None,properties=None,system_changes=all_changes):
            super().calculate(atoms,properties,system_changes);x=self.atoms.positions/BOHR
            geometry_constraints(x,reference,p['fixed_indices'],p['constraint'])
            if not rows and np.allclose(x,seed_x,atol=1e-12,rtol=0):
                e=seed['energy_hartree'];g=np.load(checked(seed['gradient_binary']))
                rows.append(dict(state='complete',reused=True,result=p['seed_result'],stationarity=stationarity(x,g,p['fixed_indices'],p['free_indices'],p['constraint'])));persist()
            else:e,g=evaluate(x)
            self.results=dict(energy=e*HARTREE_EV,forces=-g*FORCE_FACTOR)
    atoms=Atoms(model['elements'],positions=seed_x*BOHR);atoms.calc=NativeCalculator()
    constraints,configuration=constraints_for(atoms,reference,p['fixed_indices'],p['constraint']);save(root/'constraint_configuration.json',configuration)
    class AuditedSella(Sella):
        def converged(self,forces=None):
            native=bool(super().converged(forces));x=atoms.positions/BOHR;g=-atoms.get_forces(apply_constraint=False)/FORCE_FACTOR
            values=stationarity(x,g,p['fixed_indices'],p['free_indices'],p['constraint']);identity=audit_endpoint(x,model)
            check=geometry_constraints(x,reference,p['fixed_indices'],p['constraint'])
            save(root/'latest_convergence.json',dict(at=now(),native_converged=native,stationarity=values,identity=identity,constraint_audit=check))
            return native and values['passed'] and identity['passed']
    def checkpoint():
        x=atoms.positions/BOHR;geometry_constraints(x,reference,p['fixed_indices'],p['constraint'])
        if not audit_endpoint(x,model)['passed']:raise RuntimeError('Accepted geometry identity failed')
        matching=[row['result'] for row in rows if row.get('result') and np.allclose(x,np.load(checked(read(checked(row['result']))['geometry'])),atol=1e-12,rtol=0)]
        if not matching:raise RuntimeError('Accepted state has no native evidence')
        result=read(checked(matching[-1]));record=dict(at=now(),step=int(optimizer.nsteps),evaluated_source=matching[-1],geometry=result['geometry'],gradient=result['gradient_binary'])
        accepted.append(record);save(root/'restart_checkpoint.json',dict(**record,optimizer_state_restorable=False,minimum_certified=False));persist()
    try:
        optimizer=AuditedSella(atoms,constraints=constraints,**p['optimizer'],logfile=str(root/'sella.log'),trajectory=str(root/'sella.traj'))
        optimizer.attach(checkpoint,interval=1);converged=bool(optimizer.run(fmax=1.5e-5*FORCE_FACTOR,steps=24))
        if not converged:raise ChunkBoundary('Optimizer step boundary reached')
    except ChunkBoundary as exc:boundary=str(exc)
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    persist()
    save(root/'assessment.json',dict(at=now(),error=error,planned_boundary=boundary,optimizer_converged=converged,
        attempts=attempts,completed_new_gradients=sum(row.get('state')=='complete' and not row.get('reused') for row in rows),
        pilot_reused=any(row.get('reused') for row in rows),accepted_states=len(accepted),
        last_accepted=accepted[-1] if accepted else None,requires_completion_audit=True,
        minimum_certified=False,basin_closure_certified=False,simulation_ready=False))
    return 1 if error else 0


def launch(root):
    p,_=context(root);assert read(root/'preflight.json')['passed'] and read(root/'admission.json')['passed']
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line and '-watch' not in line for line in units.splitlines()):raise RuntimeError('Another CPD calculation active')
    processes=subprocess.check_output(['ps','-eo','args='],text=True).splitlines()
    if any(row.strip().split(' ')[0].split('/')[-1] in ('namd2','namd3','psi4') for row in processes):raise RuntimeError('Another native job active')
    available=int(next(v.split()[1] for v in Path('/proc/meminfo').read_text().splitlines() if v.startswith('MemAvailable:')))*1024
    if available<12*1024**3 or shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Insufficient headroom')
    service=CAMPAIGN/(root.name+'-service');service.mkdir()
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    start=time.time();unit='cpd-corrected-anti1-alternate-sugar-qm-closure-v1'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),expected_seconds=p['expected_seconds'],review_deadline_epoch=start+3000,review_deadline_id='alternate-sugar-qm-closure-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(PYTHON),str(checked(p['worker'])),'run',str(root)],cwd=str(root),runtime_hours=1.,memory_gib=8,omp_threads=4,plan=pin(root/'plan.json'),completion_semantics=p['completion_semantics']))
    save(root/'launch_receipt.json',dict(at=now(),deadline_epoch=start+3600,unit=unit,available_memory_gib=available/1024**3,execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=8G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=3585s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=400%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=4',f'--setenv=TMPDIR={root}/tmp',f'--setenv=PSI_SCRATCH={root}/tmp','/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','run','launch']);parser.add_argument('root',nargs='?',type=Path,default=ROOT)
    args=parser.parse_args();root=args.root.resolve()
    if args.action=='prepare':prepare()
    elif args.action=='run':sys.exit(run(root))
    else:launch(root)
