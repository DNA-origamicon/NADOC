"""Bounded, independently QM-seeded MM endpoint relaxations before fitting."""
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
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now
from experiments.cpd_anti_additive.corrected_coupled_ring import require_archive
from experiments.cpd_anti_additive.corrected_bonded_baseline import Evaluator,BOHR,EH,proper_rmsd,geometry_differences
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_anti_additive.endpoint_scan_constraints import require_scan_angle
from experiments.cpd_anti_additive.endpoint_scan_constraints_v2 import make_scan_constraints
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion,wrapped

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT=CAMPAIGN/'mm-endpoint-profile-v2'
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')
EV_KCAL=EH/27.211386245988


def torsion_jacobian(x,indices,step=1e-5):
    x=np.asarray(x,float)
    indices=list(indices)
    if x.ndim!=2 or x.shape[1]!=3 or not np.isfinite(x).all() or len(set(indices))!=4 or step<=0:
        raise ValueError('Invalid torsion projection geometry')
    jacobian=np.zeros_like(x)
    for atom in indices:
        for axis in range(3):
            delta=np.zeros_like(x);delta[atom,axis]=step
            jacobian[atom,axis]=np.radians(wrapped(torsion(x+delta,indices)-torsion(x-delta,indices)))/(2*step)
    if not np.isfinite(jacobian).all() or np.linalg.norm(jacobian)<1e-8:
        raise ValueError('Undefined torsion Jacobian')
    return jacobian


def projected_metrics(x,gradient,indices):
    g=np.asarray(gradient,float);jac=torsion_jacobian(x,indices)
    if g.shape!=jac.shape or not np.isfinite(g).all():raise ValueError('Invalid MM gradient')
    projected=g-jac*np.sum(jac*g)/np.sum(jac*jac)
    return dict(max_atom_gradient_kcal_mol_angstrom=float(np.linalg.norm(g,axis=1).max()),
                max_projected_atom_gradient_kcal_mol_angstrom=float(np.linalg.norm(projected,axis=1).max()),
                projected_component_rms_kcal_mol_angstrom=float(np.sqrt(np.mean(projected**2))),
                tangent_dot_normal=float(np.sum(projected*jac)),
                normal_component_norm_kcal_mol_angstrom=float(np.linalg.norm(g-projected)))


def heavy_torsions(fixture):
    keys=fixture['atom_keys'];elements=fixture['elements'];adj={i:set() for i in range(len(keys))}
    for a,b in fixture['bonds']:adj[a].add(b);adj[b].add(a)
    found=set()
    for b,c in fixture['bonds']:
        for a in adj[b]-{c}:
            for d in adj[c]-{b}:
                seq=(a,b,c,d)
                if len(set(seq))==4 and all(elements[i]!='H' for i in seq):found.add(min(seq,seq[::-1]))
    return sorted(found)


def descriptors(reference,x,fixture,torsions):
    torsions=[list(indices) for indices in torsions]
    changes=[dict(atoms=[fixture['atom_keys'][i] for i in ids],reference_degrees=torsion(reference,ids),
                  observed_degrees=torsion(x,ids),change_degrees=wrapped(torsion(x,ids)-torsion(reference,ids))) for ids in torsions]
    maximum=max(abs(v['change_degrees']) for v in changes)
    rmsd=proper_rmsd(reference,x,fixture['elements'])
    return dict(heavy_atom_rmsd_angstrom=rmsd,maximum_heavy_proper_change_degrees=maximum,torsions=changes,
                historical_descriptor_limits=dict(rmsd_angstrom=.25,maximum_torsion_change_degrees=20),
                descriptor_match=bool(rmsd<=.25 and maximum<=20),
                interpretation='Historical geometric screening flags only; passing does not prove basin identity or global-minimum closure.')


def context(root):
    require_archive(root);p=read(root/'plan.json')
    if checked(p['worker'])!=Path(__file__).resolve():raise ValueError('Frozen worker changed')
    for source in p['sources']:checked(source)
    auth=read(checked(p['authorization']))
    if not auth['user_authorized'] or auth['compute_policy']['cloud_spending_usd']!=0:raise ValueError('Missing local authority')
    if (p['hard_seconds'],p['point_timeout_seconds'],len(p['points']))!=(1800,300,5):raise ValueError('Allocation changed')
    if (CAMPAIGN/'pause.json').exists() and read(CAMPAIGN/'pause.json').get('paused'):raise RuntimeError('Campaign paused')
    for name,version in p['versions'].items():
        if metadata.version(name)!=version:raise ValueError(f'Runtime changed: {name}')
    if (root/'launch_receipt.json').exists():
        execution=read(checked(read(root/'launch_receipt.json')['execution_plan']))
        if checked(execution['plan'])!=root/'plan.json':raise ValueError('Launched plan changed')
    return p,read(checked(p['model']))


def prepare():
    from ase import Atoms
    require_archive(CAMPAIGN)
    baseline=CAMPAIGN/'bonded-baseline-v1';audit=read(baseline/'completion_audit.json')
    assert audit['passed'] and audit['constrained_profile_admitted'] and audit['selected_provisional_parent']=='last'
    bp=read(checked(audit['plan']));fixture=bp['fixtures']['endpoint'];model=read(checked(fixture['model']))
    profile_path=CAMPAIGN/'glycosidic-branch-profile-v1/completed_profile_review.json';profile=read(profile_path)
    ROOT.mkdir();(ROOT/'tmp').mkdir();shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    sources=[pin(baseline/'completion_audit.json'),pin(baseline/'plan.json'),pin(profile_path),
             fixture['model'],fixture['psf'],fixture['rtf'],fixture['systems']['last'],model['sdf'],model['graph'],model['definition'],
             pin(CAMPAIGN/'charge-core-fit-v1/candidate_charges.json'),pin(CAMPAIGN/'electrostatic-endpoint-transfer-v1/completion_audit.json')]
    torsions=heavy_torsions(fixture);points=[];checks=[]
    for row in profile['points']:
        offset=row['offset_degrees'];label=f'offset-{offset:+d}'
        prior=read(checked(row['audit']));prior_plan=read(checked(prior['plan']))
        assert prior['passed'] and prior['constrained_stationary'] and prior['last_accepted_result']==row['result']
        x=np.load(checked(row['geometry']))*BOHR;assert audit_endpoint(x/BOHR,model)['passed']
        atoms=Atoms(model['elements'],positions=x)
        constraints,configuration=make_scan_constraints(atoms,prior_plan['constraint'],accepted_restart=True)
        jac=torsion_jacobian(x,prior_plan['constraint']['indices'])
        alternate=torsion_jacobian(x,prior_plan['constraint']['indices'],step=5e-6)
        assert np.max(abs(jac-alternate))<1e-7
        assert np.max(abs(jac.sum(axis=0)))<1e-7
        points.append(dict(label=label,offset_degrees=offset,geometry=row['geometry'],qm_result=row['result'],
                           qm_energy_hartree=row['energy_hartree'],prior_audit=row['audit'],constraint=prior_plan['constraint']))
        checks.append(dict(label=label,constraint=configuration,projection_step_max_difference=float(np.max(abs(jac-alternate)))))
        sources.extend([row['geometry'],row['result'],row['audit'],prior['plan']])
    for name in ['corrected_core_stage1.py','corrected_coupled_ring.py','corrected_bonded_baseline.py',
                 'prepare_corrected_endpoints.py','endpoint_scan_geometry.py','endpoint_scan_constraints.py','endpoint_scan_constraints_v2.py']:
        sources.append(pin(REPO/'experiments/cpd_anti_additive'/name))
    plan=dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=sources,authorization=bp['authorization'],
        model=fixture['model'],fixture=fixture,system=fixture['systems']['last'],points=points,heavy_torsions=torsions,
        versions={n:metadata.version(n) for n in ['openmm','numpy','scipy','ase','sella','jax','jaxlib','rdkit']},
        method='Sella order0,internal=True,eig=False,delta0=0.1,constraints_tol=1e-8; exact degree target via audited helper; independent QM seed for each point. OpenMM Reference, unchanged last-row baseline, full-precision candidate charges.',
        hard_seconds=1800,point_timeout_seconds=300,expected_seconds=180,threads=1,service_memory_gib=4,
        mm_limits=dict(max_steps=500,max_evaluations=750,point_worker_seconds=270,max_projected_atom_gradient_kcal_mol_angstrom=.001,torsion_error_degrees=.01),
        parent_choice='Last-row baseline has0.175A core heavy RMSD versus0.355A for first-row. Other errors remain; this is a provisional parent for one diagnostic, not proof of optimality or source-ambiguity resolution.',
        conformer_policy='Save every evaluated trial and accepted checkpoint. Audit final accepted geometry, all seven centers, covalent/nonbonded distances and full heavy-proper descriptor changes. Historical0.25A/20degree flags guide review, not minimum/basin certification. No multistarts or extra QM automatically.',
        comparison_policy='Relative energies against separately relaxed offset0 from its own QM seed. Retain all points; do not fit or score as a matched profile when actual conformer descriptors indicate drift.',
        completion_semantics='Five bounded constrained MM attempts, independent geometry/projected-force audit required; optimizer success or service completion is not minimum or basin certification.',
        full_precision_psf_export_pending=True,fit_admitted=False,fit_round_consumed=False,new_qm=0,heldout_accessed=False,
        minimum_certified=False,charge_transfer_validated=False,simulation_ready=False,cloud_spending_usd=0)
    save(ROOT/'plan.json',plan)
    save(ROOT/'preflight.json',dict(at=now(),passed=True,plan=pin(ROOT/'plan.json'),points=checks,
                                    exact_constraints_verified=True,full_heavy_torsions=len(torsions),
                                    unchanged_parameter_system=fixture['systems']['last'],new_mm_optimizations=0,new_qm=0))
    print(ROOT)


def worker(root,label):
    from ase import Atoms
    from ase.calculators.calculator import Calculator,all_changes
    from sella import Sella
    p,model=context(root);point=next(v for v in p['points'] if v['label']==label)
    folder=root/label;folder.mkdir();start=time.monotonic()
    with (folder/'started.json').open('x') as f:f.write(now()+'\n')
    x0=np.load(checked(point['geometry']))*BOHR
    assert audit_endpoint(x0/BOHR,model)['passed'];require_scan_angle(x0/BOHR,point['constraint'])
    engine=Evaluator(checked(p['system']));history=[];accepted=[];last_accepted=x0.copy();limits=p['mm_limits']
    def evaluate(x):
        if len(history)>=limits['max_evaluations'] or time.monotonic()-start>limits['point_worker_seconds']:
            raise RuntimeError('MM point allocation exhausted; audit before any continuation')
        energy,gradient,_=engine.evaluate(x)
        history.append(dict(x=x.copy(),energy=energy,gradient=gradient.copy()))
        return energy,gradient
    class CalculatorWithEvidence(Calculator):
        implemented_properties=['energy','forces']
        def calculate(self,atoms=None,properties=None,system_changes=all_changes):
            super().calculate(atoms,properties,system_changes)
            energy,gradient=evaluate(atoms.positions)
            self.results=dict(energy=energy/EV_KCAL,forces=-gradient/EV_KCAL)
    atoms=Atoms(model['elements'],positions=x0);atoms.calc=CalculatorWithEvidence()
    constraints,configuration=make_scan_constraints(atoms,point['constraint'],accepted_restart=True)
    save(folder/'constraint_configuration.json',configuration)
    class AuditedSella(Sella):
        def converged(self,forces=None):
            native=bool(super().converged(forces))
            gradient=-atoms.get_forces(apply_constraint=False)*EV_KCAL
            metrics=projected_metrics(atoms.positions,gradient,point['constraint']['indices'])
            return native and metrics['max_projected_atom_gradient_kcal_mol_angstrom']<limits['max_projected_atom_gradient_kcal_mol_angstrom']
    def checkpoint():
        nonlocal last_accepted
        x=atoms.positions.copy()
        matched=next((i for i in reversed(range(len(history))) if np.array_equal(history[i]['x'],x)),None)
        if matched is None:
            evaluate(x);matched=len(history)-1
        last_accepted=x;accepted.append(dict(x=x.copy(),evaluated_index=matched))
        np.save(folder/'last_accepted_angstrom.npy',x)
        save(folder/'progress.json',dict(at=now(),evaluations=len(history),accepted_states=len(accepted)))
    error=None;converged=False
    try:
        optimizer=AuditedSella(atoms,constraints=constraints,order=0,internal=True,eig=False,delta0=.1,
                              constraints_tol=1e-8,refine_initial_hessian=False,max_cpu_threads=1,
                              logfile=str(folder/'sella.log'),trajectory=str(folder/'sella.traj'))
        optimizer.attach(checkpoint,interval=1)
        converged=bool(optimizer.run(fmax=limits['max_projected_atom_gradient_kcal_mol_angstrom']/EV_KCAL,steps=limits['max_steps']))
    except Exception as exc:
        error=repr(exc);(folder/'failure_traceback.txt').write_text(traceback.format_exc())
    finally:
        np.savez_compressed(folder/'evaluations.npz',coordinates_angstrom=np.array([v['x'] for v in history]),
                            energies_kcal_mol=np.array([v['energy'] for v in history]),gradients_kcal_A=np.array([v['gradient'] for v in history]))
        np.savez_compressed(folder/'accepted.npz',coordinates_angstrom=np.array([v['x'] for v in accepted]),
                            evaluated_indices=np.array([v['evaluated_index'] for v in accepted],int))
    x=last_accepted;energy,gradient,parts=engine.evaluate(x,True)
    np.save(folder/'final_angstrom.npy',x);np.save(folder/'final_gradient_kcal_A.npy',gradient)
    identity=audit_endpoint(x/BOHR,model);projection=projected_metrics(x,gradient,point['constraint']['indices'])
    angle=torsion(x,point['constraint']['indices']);angle_error=abs(wrapped(angle-point['constraint']['target_degrees']))
    geometry=geometry_differences(x0,x,p['fixture'])
    match=descriptors(x0,x,p['fixture'],p['heavy_torsions'])
    passed=bool(error is None and converged and identity['passed'] and angle_error<.01 and
                projection['max_projected_atom_gradient_kcal_mol_angstrom']<.001)
    save(folder/'assessment.json',dict(at=now(),plan=pin(root/'plan.json'),label=label,point=point,
         error=error,optimizer_converged=converged,independent_stationarity_and_chemistry_passed=passed,
         final_geometry=pin(folder/'final_angstrom.npy'),final_gradient=pin(folder/'final_gradient_kcal_A.npy'),
         evaluations=pin(folder/'evaluations.npz'),accepted=pin(folder/'accepted.npz'),
         native_log=pin(folder/'sella.log') if (folder/'sella.log').exists() else None,
         native_trajectory=pin(folder/'sella.traj') if (folder/'sella.traj').exists() else None,
         evaluated_states=len(history),accepted_states=len(accepted),wall_seconds=time.monotonic()-start,
         energy_kcal_mol=energy,force_group_energies=parts,identity=identity,projection=projection,
         torsion_degrees=angle,torsion_error_degrees=angle_error,geometry_differences=geometry,
         conformer_descriptors=match,minimum_certified=False,basin_closure_certified=False,simulation_ready=False))
    engine.close()
    print(dict(label=label,stationarity_and_chemistry_passed=passed,descriptor_match=match['descriptor_match'],evaluations=len(history)),flush=True)
    return 1 if error else 0


def run(root):
    p,_=context(root);deadline=read(root/'launch_receipt.json')['deadline_epoch'];completed=[];error=None
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    try:
        for point in p['points']:
            context(root)
            if deadline-time.time()<p['point_timeout_seconds']+30:raise RuntimeError('Insufficient allocation for next point')
            with (root/(point['label']+'_runner.log')).open('x') as log:
                child=subprocess.run([str(PYTHON),str(checked(p['worker'])),'worker',str(root),'--label',point['label']],
                                     cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=p['point_timeout_seconds'])
            if child.returncode:raise RuntimeError(f"MM point {point['label']} failed with code{child.returncode}")
            completed.append(pin(root/point['label']/'assessment.json'));save(root/'progress.json',dict(at=now(),completed=completed))
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json',dict(at=now(),completed=completed,error=error,requires_completion_audit=True,
                                    minimum_certified=False,basin_closure_certified=False,simulation_ready=False))
    return 1 if error else 0


def launch(root):
    p,_=context(root);assert read(root/'preflight.json')['passed'] and read(root/'admission.json')['passed']
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line and '-watch' not in line for line in units.splitlines()):raise RuntimeError('Another CPD calculation active')
    available=int(next(v.split()[1] for v in Path('/proc/meminfo').read_text().splitlines() if v.startswith('MemAvailable:')))*1024
    if available<6*1024**3 or shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Insufficient resource headroom')
    service=CAMPAIGN/(root.name+'-service');service.mkdir()
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    start=time.time();unit='cpd-corrected-anti1-mm-endpoint-profile-v2'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),expected_seconds=p['expected_seconds'],review_deadline_epoch=start+1500,review_deadline_id='mm-endpoint-profile-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(PYTHON),str(checked(p['worker'])),'run',str(root)],cwd=str(root),runtime_hours=.5,memory_gib=4,omp_threads=1,plan=pin(root/'plan.json'),completion_semantics=p['completion_semantics']))
    save(root/'launch_receipt.json',dict(at=now(),deadline_epoch=start+1800,unit=unit,available_memory_gib=available/1024**3,execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=4G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=1785s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=100%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=1',f'--setenv=TMPDIR={root}/tmp',f'--setenv=PSI_SCRATCH={root}/tmp','/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','launch','run','worker'])
    parser.add_argument('root',nargs='?',type=Path,default=ROOT);parser.add_argument('--label')
    args=parser.parse_args();root=args.root.resolve()
    if args.action=='prepare':prepare()
    elif args.action=='worker':sys.exit(worker(root,args.label))
    elif args.action=='run':sys.exit(run(root))
    else:launch(root)
