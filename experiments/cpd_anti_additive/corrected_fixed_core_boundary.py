"""Separate sugar/cap relaxation from core-shape error in two acquired conformers."""
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
from experiments.cpd_anti_additive.corrected_bonded_baseline import Evaluator,BOHR,EH
from experiments.cpd_anti_additive.corrected_mm_endpoint_profile import torsion_jacobian,descriptors,EV_KCAL
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_anti_additive.endpoint_scan_constraints_v2 import make_scan_constraints
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion,wrapped

CAMPAIGN=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
ROOT=CAMPAIGN/'fixed-core-boundary-v1'
PYTHON=Path('/home/jojo/.cache/nadoc-qm/sella-runtime-v1/bin/python')


def free_projection(x,gradient,fixed,chi):
    g=np.array(gradient,float,copy=True);jac=torsion_jacobian(x,chi)
    if g.shape!=x.shape or not np.isfinite(g).all():raise ValueError('Invalid gradient')
    if len(set(fixed))!=len(fixed) or any(i<0 or i>=len(x) for i in fixed):raise ValueError('Invalid fixed indices')
    g[list(fixed)]=0.;jac[list(fixed)]=0.
    norm=np.sum(jac*jac)
    if norm<1e-12:raise ValueError('Chi has no independent free-atom motion')
    return g-jac*np.sum(g*jac)/norm


def constraints_for(atoms,point,fixed):
    constraints,configuration=make_scan_constraints(atoms,point['constraint'],accepted_restart=True)
    for i in fixed:constraints.fix_translation(index=int(i))
    jac=np.asarray(constraints.jacobian());rank=np.linalg.matrix_rank(jac,tol=1e-8)
    if rank!=3*len(fixed)+1:raise ValueError('Unexpected constraint rank')
    if np.max(abs(constraints.residual()))>max(1e-8,configuration['residual_limit_radians']):
        raise ValueError('Initial constraints exceed the audited restart tolerance')
    return constraints,dict(**configuration,fixed_atoms=len(fixed),constraint_rank=int(rank),free_dimensions=3*len(atoms)-int(rank))


def context(root):
    require_archive(root);p=read(root/'plan.json')
    if checked(p['worker'])!=Path(__file__).resolve():raise ValueError('Use frozen worker')
    for source in p['sources']:checked(source)
    auth=read(checked(p['authorization']))
    assert auth['user_authorized'] and auth['compute_policy']['cloud_spending_usd']==0
    assert p['hard_seconds']==900 and len(p['points'])==2 and len(p['fixed_indices'])==32
    if (CAMPAIGN/'pause.json').exists() and read(CAMPAIGN/'pause.json').get('paused'):raise RuntimeError('Campaign paused')
    for name,version in p['versions'].items():
        if metadata.version(name)!=version:raise ValueError(f'Runtime changed: {name}')
    if (root/'launch_receipt.json').exists():
        assert checked(read(checked(read(root/'launch_receipt.json')['execution_plan']))['plan'])==root/'plan.json'
    return p,read(checked(p['model']))


def prepare():
    from ase import Atoms
    require_archive(CAMPAIGN)
    fitroot=CAMPAIGN/'core-bonded-fit-v1';auditpath=fitroot/'completion_audit.json';audit=read(auditpath)
    assert audit['passed'] and audit['fixed_core_boundary_diagnostic_admitted'] and not audit['second_fit_admitted']
    fp=read(checked(audit['plan']));candidate=read(checked(audit['candidate']))
    priorpath=CAMPAIGN/'mm-endpoint-profile-v2/plan.json';prior=read(priorpath);fixture=prior['fixture'];model=read(checked(prior['model']))
    fixed=[i for i,k in enumerate(fixture['atom_keys']) if "'" not in k];free=[i for i in range(49) if i not in fixed]
    assert len(fixed)==32 and len(free)==17
    # The fitted terms involve fixed atoms only: they add a constant to each
    # conditioned problem, so refitting those terms cannot change its sugar forces.
    assert all(set(term['indices'])<=set(fixed) for group in fp['endpoint_groups'] for term in group['terms'])
    points=[point for point in prior['points'] if point['offset_degrees'] in (0,30)]
    ROOT.mkdir();(ROOT/'tmp').mkdir();shutil.copy2(Path(__file__),ROOT/'executed_source.py')
    engines=[Evaluator(checked(ref)) for ref in [prior['system'],candidate['endpoint']]];checks=[]
    for point in points:
        x=np.load(checked(point['geometry']))*BOHR
        assert audit_endpoint(x/BOHR,model)['passed']
        constraints,configuration=constraints_for(Atoms(model['elements'],positions=x),point,fixed)
        jac=np.asarray(constraints.jacobian());_,s,v=np.linalg.svd(jac,full_matrices=True);tangent=v[len(s):].T
        random=np.cos(np.arange(x.size)).reshape(x.shape)
        projected=free_projection(x,random,fixed,point['constraint']['indices'])
        error=float(np.max(abs(projected.ravel()-tangent@(tangent.T@random.ravel()))));assert error<1e-7
        values=[engine.evaluate(x) for engine in engines];constant=values[1][0]-values[0][0]
        max_gradient=float(np.max(abs(values[1][1][free]-values[0][1][free])));max_energy=0.
        for scale in (-.02,.02):
            perturbed=x.copy();perturbed[free]+=scale*np.sin(np.arange(len(free)*3)).reshape(-1,3)
            samples=[engine.evaluate(perturbed) for engine in engines]
            max_gradient=max(max_gradient,float(np.max(abs(samples[1][1][free]-samples[0][1][free]))))
            max_energy=max(max_energy,abs(samples[1][0]-samples[0][0]-constant))
        assert max_gradient<1e-10 and max_energy<1e-9
        qm=read(checked(point['qm_result']));qg=np.array(qm['gradient_hartree_bohr'])*EH/BOHR
        checks.append(dict(label=point['label'],configuration=configuration,independent_projection_error=error,
            parent_candidate_free_gradient_max_difference=max_gradient,constant_energy_difference_max_error=max_energy,
            qm_free_projected_max_atom_gradient_kcal_mol_A=float(np.linalg.norm(free_projection(x,qg,fixed,point['constraint']['indices']),axis=1).max())))
    for engine in engines:engine.close()
    sources=[pin(auditpath),pin(fitroot/'target_hessian_reconstruction_addendum_v2.json'),pin(fitroot/'plan.json'),pin(priorpath),
             prior['model'],prior['system'],candidate['endpoint'],pin(fitroot/'candidate_parameters.json')]
    for point in points:sources.extend([point['geometry'],point['qm_result'],point['prior_audit']])
    for name in ['corrected_core_stage1.py','corrected_coupled_ring.py','corrected_bonded_baseline.py',
                 'corrected_mm_endpoint_profile.py','prepare_corrected_endpoints.py','endpoint_scan_constraints_v2.py',
                 'endpoint_scan_constraints.py','endpoint_scan_geometry.py']:
        sources.append(pin(REPO/'experiments/cpd_anti_additive'/name))
    definitions=read(CAMPAIGN/'glycosidic-branch-profile-v1/completed_profile_review.json')['torsion_definitions']
    plan=dict(at=now(),worker=pin(ROOT/'executed_source.py'),sources=sources,authorization=fp['authorization'],
        fixture=fixture,model=prior['model'],system=candidate['endpoint'],parent_system=prior['system'],points=points,
        fixed_indices=fixed,free_indices=free,heavy_torsions=prior['heavy_torsions'],named_torsions=definitions,
        method='Sella order0/internal=True/eig=False/delta0=0.1/constraints_tol1e-8, OpenMM Reference.32 base/methyl atom positions fixed to each QM conformer; exact chi target retained;17 sugar/OH-cap atoms free (50 independent dimensions).',
        purpose='At offsets0 and+30, test sugar branch drift without core-shape relaxation. Base-only equilibrium corrections are exactly constant on this constrained domain; native free-force equivalence checked. Neither a full endpoint minimum nor a matched free-profile qualification.',
        limits=dict(max_steps=400,max_evaluations=600,worker_seconds=270,point_timeout_seconds=300,force_kcal_mol_A=.001,fixed_error_A=1e-7,chi_error_degrees=.01),
        hard_seconds=900,expected_seconds=180,threads=1,service_memory_gib=4,
        versions={n:metadata.version(n) for n in ['openmm','numpy','scipy','ase','sella','jax','jaxlib','rdkit']},
        decision_boundary='Audit actual free projected forces, fixed-coordinate drift, all seven stereocenters, cap/sugar torsions and contact geometry. If drift persists, core-only re-equilibration cannot fix this conditioned mismatch; identify boundary/nonbonded contributions before the remaining fit. If suppressed, re-evaluate coupled core shape. No automatic new fit or QM.',
        fit_round_consumed=False,new_qm=0,heldout_accessed=False,minimum_certified=False,basin_closure_certified=False,simulation_ready=False,cloud_spending_usd=0)
    save(ROOT/'plan.json',plan);save(ROOT/'preflight.json',dict(at=now(),passed=True,plan=pin(ROOT/'plan.json'),checks=checks,
        no_new_optimizations=True,new_qm=0,fit_performed=False))
    print(dict(root=str(ROOT),checks=checks))


def worker(root,label):
    from ase import Atoms
    from ase.calculators.calculator import Calculator,all_changes
    from sella import Sella
    p,model=context(root);point=next(v for v in p['points'] if v['label']==label);folder=root/label;folder.mkdir()
    x0=np.load(checked(point['geometry']))*BOHR;fixed=p['fixed_indices'];limits=p['limits'];engine=Evaluator(checked(p['system']))
    start=time.monotonic();history=[];accepted=[];last=x0.copy()
    def evaluate(x):
        if len(history)>=limits['max_evaluations'] or time.monotonic()-start>limits['worker_seconds']:
            raise RuntimeError('Bounded diagnostic allocation exhausted')
        e,g,_=engine.evaluate(x);history.append((x.copy(),e,g.copy()));return e,g
    class NativeCalculator(Calculator):
        implemented_properties=['energy','forces']
        def calculate(self,atoms=None,properties=None,system_changes=all_changes):
            super().calculate(atoms,properties,system_changes);e,g=evaluate(atoms.positions)
            self.results=dict(energy=e/EV_KCAL,forces=-g/EV_KCAL)
    atoms=Atoms(model['elements'],positions=x0);atoms.calc=NativeCalculator();constraints,configuration=constraints_for(atoms,point,fixed)
    save(folder/'constraint_configuration.json',configuration)
    class AuditedSella(Sella):
        def converged(self,forces=None):
            native=bool(super().converged(forces));g=-atoms.get_forces(apply_constraint=False)*EV_KCAL
            tangent=free_projection(atoms.positions,g,fixed,point['constraint']['indices'])
            return native and np.linalg.norm(tangent,axis=1).max()<limits['force_kcal_mol_A']
    def checkpoint():
        nonlocal last
        last=atoms.positions.copy();index=next((i for i in reversed(range(len(history))) if np.array_equal(history[i][0],last)),None)
        if index is None:evaluate(last);index=len(history)-1
        accepted.append((last.copy(),index));np.save(folder/'last_accepted_angstrom.npy',last)
    error=None;converged=False
    try:
        optimizer=AuditedSella(atoms,constraints=constraints,order=0,internal=True,eig=False,delta0=.1,constraints_tol=1e-8,
            refine_initial_hessian=False,max_cpu_threads=1,logfile=str(folder/'sella.log'),trajectory=str(folder/'sella.traj'))
        optimizer.attach(checkpoint,interval=1);converged=bool(optimizer.run(fmax=.001/EV_KCAL,steps=limits['max_steps']))
    except Exception as exc:
        error=repr(exc);(folder/'failure_traceback.txt').write_text(traceback.format_exc())
    finally:
        np.savez_compressed(folder/'evaluations.npz',coordinates_angstrom=np.array([v[0] for v in history]),energies_kcal_mol=np.array([v[1] for v in history]),gradients_kcal_A=np.array([v[2] for v in history]))
        np.savez_compressed(folder/'accepted.npz',coordinates_angstrom=np.array([v[0] for v in accepted]),evaluated_indices=np.array([v[1] for v in accepted],int))
    e,g,parts=engine.evaluate(last,True);e0,g0,parts0=engine.evaluate(x0,True)
    np.save(folder/'final_angstrom.npy',last);np.save(folder/'final_gradient_kcal_A.npy',g)
    tangent=free_projection(last,g,fixed,point['constraint']['indices']);force=float(np.linalg.norm(tangent,axis=1).max())
    drift=float(np.max(abs(last[fixed]-x0[fixed])));chi_error=abs(wrapped(torsion(last,point['constraint']['indices'])-point['constraint']['target_degrees']))
    identity=audit_endpoint(last/BOHR,model);passed=bool(error is None and converged and identity['passed'] and force<.001 and drift<1e-7 and chi_error<.01)
    if not passed and error is None:error='Constrained stationarity/geometry requirements not met within bounded attempt'
    named={}
    for name,keys in p['named_torsions'].items():
        ids=[p['fixture']['atom_keys'].index(k) for k in keys]
        named[name]=dict(reference_degrees=torsion(x0,ids),final_degrees=torsion(last,ids),change_degrees=wrapped(torsion(last,ids)-torsion(x0,ids)))
    save(folder/'assessment.json',dict(at=now(),plan=pin(root/'plan.json'),point=point,error=error,optimizer_converged=converged,
        independent_constrained_stationarity_and_chemistry_passed=passed,maximum_free_projected_atom_gradient_kcal_mol_A=force,
        max_fixed_coordinate_drift_A=drift,chi_error_degrees=chi_error,identity=identity,energy_kcal_mol=e,relaxation_energy_kcal_mol=e-e0,
        force_group_changes={k:parts[k]-parts0[k] for k in parts},named_torsions=named,
        conformer_descriptors=descriptors(x0,last,p['fixture'],p['heavy_torsions']),
        free_atom_rms_displacement_A=float(np.sqrt(np.mean(np.sum((last[p['free_indices']]-x0[p['free_indices']])**2,axis=1)))),
        final_geometry=pin(folder/'final_angstrom.npy'),final_gradient=pin(folder/'final_gradient_kcal_A.npy'),
        evaluations=pin(folder/'evaluations.npz'),accepted=pin(folder/'accepted.npz'),
        native_log=pin(folder/'sella.log'),native_trajectory=pin(folder/'sella.traj'),
        evaluated_states=len(history),accepted_states=len(accepted),wall_seconds=time.monotonic()-start,
        minimum_certified=False,basin_closure_certified=False,simulation_ready=False))
    engine.close();return 0 if passed else 1


def run(root):
    p,_=context(root);completed=[];error=None
    with (root/'started.json').open('x') as f:f.write(now()+'\n')
    try:
        for point in p['points']:
            context(root)
            if read(root/'launch_receipt.json')['deadline_epoch']-time.time()<330:raise RuntimeError('Insufficient allocation for next point')
            with (root/(point['label']+'_runner.log')).open('x') as log:
                child=subprocess.run([str(PYTHON),str(checked(p['worker'])),'worker',str(root),'--label',point['label']],cwd=root,stdout=log,stderr=subprocess.STDOUT,timeout=p['limits']['point_timeout_seconds'])
            if child.returncode:raise RuntimeError(f"Point {point['label']} failed; audit retained outputs before continuation")
            completed.append(pin(root/point['label']/'assessment.json'));save(root/'progress.json',dict(at=now(),completed=completed))
    except Exception as exc:
        error=repr(exc);(root/'failure_traceback.txt').write_text(traceback.format_exc())
    save(root/'assessment.json',dict(at=now(),completed=completed,error=error,requires_completion_audit=True,minimum_certified=False,simulation_ready=False))
    return 1 if error else 0


def launch(root):
    p,_=context(root);assert read(root/'preflight.json')['passed'] and read(root/'admission.json')['passed']
    units=subprocess.check_output(['systemctl','--user','list-units','--type=service','--state=running','--no-legend'],text=True)
    if any('cpd-' in line and '-watch' not in line for line in units.splitlines()):raise RuntimeError('Another CPD calculation active')
    available=int(next(v.split()[1] for v in Path('/proc/meminfo').read_text().splitlines() if v.startswith('MemAvailable:')))*1024
    if available<6*1024**3 or shutil.disk_usage(root).free<30*1024**3:raise RuntimeError('Insufficient headroom')
    service=CAMPAIGN/(root.name+'-service');service.mkdir()
    for old,new in [('launch.py','supervisor.py'),('watch.py','watcher.py')]:shutil.copy2(REPO/'experiments/cpd_anti_additive'/old,service/new)
    start=time.time();unit='cpd-corrected-anti1-fixed-core-boundary-v1'
    save(service/'watcher_config.json',dict(codex_executable=str(Path(shutil.which('codex')).resolve()),expected_seconds=180,review_deadline_epoch=start+720,review_deadline_id='fixed-core-boundary-audit',self_test=False))
    save(service/'execution_plan.json',dict(unit=unit,thread=os.environ['CODEX_THREAD_ID'],command=[str(PYTHON),str(checked(p['worker'])),'run',str(root)],cwd=str(root),runtime_hours=.25,memory_gib=4,omp_threads=1,plan=pin(root/'plan.json'),completion_semantics='Two fixed-core constrained MM attempts; independent audit required, no full-minimum or matched-profile certification.'))
    save(root/'launch_receipt.json',dict(at=now(),deadline_epoch=start+900,unit=unit,available_memory_gib=available/1024**3,execution_plan=pin(service/'execution_plan.json'),supervisor=pin(service/'supervisor.py'),watcher=pin(service/'watcher.py')))
    subprocess.run(['systemd-run','--user',f'--unit={unit}','--property=MemoryMax=4G','--property=MemorySwapMax=0','--property=RuntimeMaxSec=885s','--property=TimeoutStopSec=15s','--property=KillMode=control-group','--property=CPUQuota=100%',f'--setenv=PYTHONPATH={REPO}',f'--setenv=NADOC_REPO_ROOT={REPO}','--setenv=PYTHONDONTWRITEBYTECODE=1','--setenv=OPENBLAS_NUM_THREADS=1','--setenv=MKL_NUM_THREADS=1','--setenv=OMP_NUM_THREADS=1',f'--setenv=TMPDIR={root}/tmp',f'--setenv=PSI_SCRATCH={root}/tmp','/usr/bin/python3',str(service/'supervisor.py'),'--supervise',str(service)],check=True)
    print(service)


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('action',choices=['prepare','launch','run','worker'])
    parser.add_argument('root',nargs='?',type=Path,default=ROOT);parser.add_argument('--label');args=parser.parse_args();root=args.root.resolve()
    if args.action=='prepare':prepare()
    elif args.action=='launch':launch(root)
    elif args.action=='run':sys.exit(run(root))
    else:sys.exit(worker(root,args.label))
