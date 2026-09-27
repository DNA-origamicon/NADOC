"""Prepared, explicitly authorized recovery of the interrupted second fit round.

Each uncached model runs in a fresh child process. Original outputs are read-only;
cached outer residuals and the interrupted Sella prefix reconstruct the same run.
The original absolute wall deadline, model count and per-case caps are retained.
"""
import argparse,contextlib,math,os,shutil,subprocess,sys,time,traceback
from pathlib import Path
import numpy as np
REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive import shape_fit_v2 as frozen
from experiments.cpd_anti_additive.shape_fit_protocol_v2 import require_fit_ready,STATE
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import save,now,BOHR

ART=REPO/'.development-artifacts'
PREP=ART/'cpd-anti-shape-recovery-preparation-v1b'
OUTPUT=ART/'cpd-anti-shape-fit-recovery-v1'
SERVICE=ART/'cpd-anti-shape-fit-service-v2-r2'


class RecoveryBoundary(RuntimeError):pass


def require_recovery_authorization(authorization,plan,current_time):
    if authorization.get('authorized') is not True or authorization.get('action')!='recover_interrupted_round_two':
        raise RuntimeError('Explicit recovery authorization required by the frozen no-restart contract')
    if not authorization.get('user_instruction') or authorization.get('recovery_plan_sha256')!=source(PREP/'recovery_plan.json')['sha256']:
        raise RuntimeError('Recovery authorization does not identify this plan')
    if current_time>=plan['original_absolute_fit_deadline_epoch']:
        raise RuntimeError('Original fitting wall deadline has passed; no automatic extension')


def validate(approval=False):
    _,oldplan=require_fit_ready();plan=read(PREP/'recovery_plan.json')
    for ref in plan['sources']:checked(ref)
    assert len(read(STATE/'conformational_rounds.json'))==2
    if approval:
        if not (PREP/'authorization.json').exists():
            raise RuntimeError('Explicit recovery authorization required by the frozen no-restart contract')
        require_recovery_authorization(read(PREP/'authorization.json'),plan,time.time())
    return plan,oldplan


def prepare():
    _,oldplan=require_fit_ready()
    audit=read(SERVICE/'completion_delivery_verified.json')
    assert audit['effective_state']=='failed_oom' and audit['completed_model_count']==33
    replay=read(SERVICE/'optimizer_replay_verified.json');assert replay['next_parameters_bitwise_match']
    native=read(PREP/'sella_replay_verified.json');assert native['interrupted_eight_step_prefix_reproduced']
    status=read(SERVICE/'status.json')
    files=[SERVICE/n for n in ['completion_delivery_verified.json','optimizer_replay_verified.json','termination_kernel.txt','status.json']]
    files += [PREP/'sella_replay_verified.json',frozen.INPUTS/'receipt.json',frozen.OUT/'progress.json',
        frozen.OUT/'model-034/progress.json',frozen.OUT/'model-034/started.json',frozen.OUT/'model-034/candidate.prm',
        STATE/'conformational_rounds.json']
    files += [REPO/'experiments/cpd_anti_additive'/n for n in
        ['shape_fit_isolated_recovery_v1.py','sella_cached_mm_replay_v1.py','replay_shape_optimizer_v2.py']]
    refs=[source(p) for p in files]
    for m in audit['models']:
        refs += [m['assessment'],m['residual']]
    for r in audit['partial_model']['complete_cases']:refs += [r['raw_evaluations'],r['final_geometry']]
    refs += [audit['partial_model']['incomplete_trajectory']]
    plan=dict(at=now(),sources=refs,output=str(OUTPUT.resolve()),original_worker=source(frozen.INPUTS/'worker.py'),
        original_absolute_fit_deadline_epoch=status['started_at']+7200,
        original_absolute_service_deadline_epoch=status['started_at']+8100,
        max_model_evaluations=360,max_nfev=12,fit_rounds_used=2,additional_fit_rounds=0,
        memory_gib=6,cpu_affinity=[4,5,6,7],original_completed_models=33,
        interrupted_model=34,reuse_completed_fragments=16,replay_partial_native_evaluations=8,
        parent_process='SciPy optimizer and saved residual cache only; no Sella optimizations',
        child_process='One fresh process for each uncached model. Exit releases process-owned caches/allocations.',
        physics_and_objective='Unchanged frozen shape-v2.2 receipt; same bounds, references, seeds, Sella settings, objective and gates.',
        resume='Replay 33 original outer residuals; assert bitwise model34 parameter identity; reuse its16 complete fragments; replay8 cached Sella evaluations before requesting new forces.',
        stop='No automatic repeat of this recovery; fail on cache divergence, child failure, expired original deadline or original model cap.',
        requires_explicit_recovery_authorization=True,authorization_received=False,minimum_certified=False,simulation_ready=False)
    p=PREP/'recovery_plan.json';assert not p.exists();save(p,plan)
    print('Recovery prepared; no authorization, launch, new energy or fit evaluation.',flush=True)


def assemble(folder,number,v,plan,results,coordinates,psfs):
    points=read(checked(plan['points']));reps=read(checked(plan['representatives']))
    assert len(results)==len(coordinates)==26
    errors=frozen.relative([r['energy_kcal'] for r in results[:23]],points)-np.array([p['qm_relative_kcal_mol'] for p in points])
    residual=list(errors/math.sqrt(23))
    for p,x in zip(points,coordinates):
        residual.extend(frozen.aligned_residual(np.array(p['geometry_bohr'])*BOHR,x,p['elements'])/(.25*math.sqrt(23)))
    residual.extend(r['branch_descriptors']['basin_max_torsion_deg']/(20*math.sqrt(23)) for r in results[:23])
    geom=[frozen.representative_geometry(psfs[p['endpoint']],p['atom_map'],np.array(p['geometry_bohr'])*BOHR,x) for p,x in zip(reps,coordinates[23:])]
    residual.extend(g['max_bond_A']/(.03*math.sqrt(3)) for g in geom)
    residual.extend(g['max_angle_deg']/(3*math.sqrt(3)) for g in geom)
    residual.extend(math.sqrt(.05/len(v))*v/3)
    residual.extend(0. if r['independent_stationarity_and_chemistry_passed'] else 1000. for r in results)
    residual=np.array(residual);assert np.isfinite(residual).all()
    valid=all(r['independent_stationarity_and_chemistry_passed'] for r in results)
    energy=dict(rmse_kcal=float(np.sqrt(np.mean(errors**2))),max_abs_kcal=float(abs(errors).max()))
    energy['passed']=energy['rmse_kcal']<=1 and energy['max_abs_kcal']<=2
    report=dict(at=now(),number=number,candidate=source(folder/'candidate.prm'),parameters=v.tolist(),
        objective=float(residual@residual),numerically_valid=valid,energy=energy,
        shape_failures=[r['case_id'] for r in results[:23] if not r['branch_descriptor_match']],
        representative_geometry=geom,results=results,
        development_parameter_passed=valid and energy['passed'] and all(r['branch_descriptor_match'] for r in results[:23]) and all(g['passed'] for g in geom),
        minimum_certified=False,simulation_ready=False)
    return report,residual


def child(request_path):
    import openmm as mm
    from openmm import app
    from ase.io import read as read_atoms
    from experiments.cpd_anti_additive.sella_cached_mm_replay_v1 import relax_point as cached_relax
    rp,plan=validate(approval=True);request=read(request_path);folder=request_path.parent
    assert folder.parent.resolve()==OUTPUT.resolve() and 34<=request['number']<=360
    v=np.array(request['parameters']);assert v.shape==(22,) and np.max(abs(v))<=5
    frozen.export_parameters(checked(plan['baseline_parameters']),folder/'candidate.prm',plan['variables'],v)
    par=frozen.parameters(folder/'candidate.prm');points=read(checked(plan['points']))+read(checked(plan['representatives']))
    psfs={p['endpoint']:app.CharmmPsfFile(str(Path(plan['parent'])/f"endpoint-{p['endpoint']}"/'fragment.psf')) for p in points}
    systems={e:p.createSystem(par,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False) for e,p in psfs.items()}
    prefix=read(frozen.OUT/'model-034/progress.json') if request['number']==34 else []
    if prefix:assert np.array_equal(v,read(frozen.OUT/'model-034/started.json')['parameters'])
    deadline=time.monotonic()+max(0,rp['original_absolute_fit_deadline_epoch']-time.time())
    results=[];coordinates=[]
    for i,p in enumerate(points):
        if time.monotonic()>=deadline:raise RecoveryBoundary('Original wall deadline reached')
        if i<len(prefix):
            r=prefix[i];assert r['case_id']==p['case_id'];checked(r['raw_evaluations']);x=np.loadtxt(checked(r['final_geometry']))
        elif request['number']==34 and i==len(prefix):
            path=frozen.OUT/'model-034'/p['case_id']/'sella.traj';frames=read_atoms(path,index=':');assert len(frames)==8
            r,x=cached_relax(folder/p['case_id'],p,systems[p['endpoint']],plan,deadline,replay_frames=frames)
            if r.get('error') and 'Cached Sella path diverged' in r['error']:
                raise RuntimeError(r['error'])
        else:r,x=frozen.relax_point(folder/p['case_id'],p,systems[p['endpoint']],plan,deadline)
        results.append(r);coordinates.append(x);save(folder/'progress.json',results)
    report,residual=assemble(folder,request['number'],v,plan,results,coordinates,psfs)
    np.save(folder/'residual.npy',residual);save(folder/'assessment.json',report)


def run():
    from scipy.optimize import least_squares
    rp,plan=validate(approval=True);OUTPUT.mkdir(exist_ok=False)
    save(OUTPUT/'execution.json',dict(at=now(),plan=source(PREP/'recovery_plan.json'),authorization=source(PREP/'authorization.json'),
        prior_failure=source(SERVICE/'completion_delivery_verified.json'),fit_rounds_used=2))
    cache={};records=[];requests=[]
    for row in read(frozen.OUT/'progress.json')['models']:
        if row['state']!='complete':continue
        r=read(checked(row['assessment']));residual=np.load(frozen.OUT/f"model-{row['number']:03d}"/'residual.npy')
        cache[np.array(r['parameters']).tobytes()]=residual
        records.append(dict(number=row['number'],assessment=row['assessment'],objective=r['objective'],numerically_valid=r['numerically_valid']))
    best=min((r for r in records if r['numerically_valid']),key=lambda r:r['objective']);termination=None
    def evaluate(v):
        nonlocal best
        key=np.asarray(v).tobytes()
        if key in cache:return cache[key].copy()
        if time.time()>=rp['original_absolute_fit_deadline_epoch'] or len(records)>=360:raise RecoveryBoundary('Original wall/model budget reached')
        number=len(records)+1
        if number==34:assert np.array_equal(v,read(frozen.OUT/'model-034/started.json')['parameters'])
        folder=OUTPUT/f'model-{number:03d}';folder.mkdir(exist_ok=False)
        request=folder/'request.json';save(request,dict(at=now(),number=number,parameters=v.tolist(),plan=source(PREP/'recovery_plan.json')))
        requests.append(source(request));save(OUTPUT/'progress.json',dict(at=now(),records=records,requests=requests,best=best))
        with (folder/'native.log').open('w') as log:
            try:
                result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'child',str(request)],cwd=REPO,
                    stdout=log,stderr=subprocess.STDOUT,timeout=max(.001,rp['original_absolute_fit_deadline_epoch']-time.time()))
            except subprocess.TimeoutExpired as exc:raise RecoveryBoundary('Child stopped at original fitting deadline') from exc
        if result.returncode:raise RecoveryBoundary(f'Child model {number} failed, exit {result.returncode}; no automatic retry')
        report=read(folder/'assessment.json');residual=np.load(folder/'residual.npy')
        row=dict(number=number,assessment=source(folder/'assessment.json'),objective=report['objective'],numerically_valid=report['numerically_valid'])
        records.append(row);cache[key]=residual
        if row['numerically_valid'] and row['objective']<best['objective']:best=row
        save(OUTPUT/'progress.json',dict(at=now(),records=records,requests=requests,best=best))
        print('MODEL',number,'loss',report['objective'],'shape failures',len(report['shape_failures']),flush=True)
        if report['development_parameter_passed']:
            best=row;raise RecoveryBoundary('First evaluated model passed all development gates')
        return residual.copy()
    def jac(v):
        base=evaluate(v);cols=[]
        for j in range(len(v)):
            trial=np.array(v);h=.02 if v[j]+.02<=5 else -.02;trial[j]+=h;cols.append((evaluate(trial)-base)/h)
        return np.array(cols).T
    try:
        r=least_squares(evaluate,np.clip(plan['initial_shifts'],-5+1e-8,5-1e-8),jac=jac,bounds=(-5.,5.),method='trf',
            max_nfev=12,ftol=.001,xtol=.001,gtol=.001,x_scale='jac')
        termination=dict(reason=str(r.message),solver_success=bool(r.success),nfev=r.nfev,njev=r.njev)
    except RecoveryBoundary as exc:termination=dict(reason=str(exc),solver_success=False)
    except Exception as exc:
        save(OUTPUT/'failure.json',dict(at=now(),error=repr(exc),traceback=traceback.format_exc()))
        termination=dict(reason=repr(exc),solver_success=False,unexpected_failure=True)
    chosen=read(checked(best['assessment']))
    save(OUTPUT/'assessment.json',dict(at=now(),selected=best,candidate=chosen['candidate'],termination=termination,
        completed_models=len(records),attempted_new_requests=len(requests),fit_rounds_used=2,
        energy=chosen['energy'],shape_failures=chosen['shape_failures'],representative_geometry=chosen['representative_geometry'],
        development_parameter_passed=chosen['development_parameter_passed'],prospective_validation_complete=False,
        minimum_certified=False,preliminary_research_qualified=False,simulation_ready=False,
        next='Independent audit only; no additional fit or automatic continuation.'))
    if termination.get('unexpected_failure') or 'failed, exit' in termination['reason']:
        raise RuntimeError(termination['reason'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run','child']);parser.add_argument('request',nargs='?',type=Path)
    args=parser.parse_args()
    if args.action=='child':child(args.request)
    else:globals()[args.action]()
