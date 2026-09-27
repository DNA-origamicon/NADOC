"""One remaining, bounded fit round with relaxed energy and geometry in its objective."""
import argparse
import contextlib
import importlib.metadata as metadata
import math
import os
from pathlib import Path
import shutil
import sys
import time
import traceback
import warnings
import numpy as np

REPO=Path(os.environ.get('NADOC_REPO_ROOT',Path(__file__).resolve().parents[2]))
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.validation_gate import read,source,checked
from experiments.cpd_anti_additive.sella_pilot import BOHR,save,now
from experiments.cpd_anti_additive.conformational_fit_v2 import export_parameters,relax_point,relative
from experiments.cpd_anti_additive.shape_fit_protocol_v2 import STATE,require_fit_ready,begin_round
from experiments.cpd_anti_additive import preliminary_protocol as old
from experiments.cpd_published_comparator.local_benchmarks import angle

ART=REPO/'.development-artifacts'
INPUTS=ART/'cpd-anti-shape-inputs-v2-r2'
OUT=ART/'cpd-anti-shape-fit-v2-r2'
FIRST=ART/'cpd-anti-conformational-fit-v2-r1'
BASE=ART/'cpd-anti-engine-candidate-v2g'
SCORES=ART/'cpd-anti-prospective-score-v2-r1'
EH=627.5094740631


class BudgetReached(RuntimeError):pass
class FitSatisfied(RuntimeError):pass


def aligned_residual(q,x,elements):
    ids=[i for i,e in enumerate(elements) if e!='H']
    a=q[ids]-q[ids].mean(0);b=x[ids]-x[ids].mean(0)
    u,_,vt=np.linalg.svd(b.T@a);d=np.eye(3);d[2,2]=np.linalg.det(u@vt)
    return (b@(u@d@vt)-a).ravel()/math.sqrt(len(ids))


def representative_geometry(psf,names,q,x):
    def lesion(ids):
        roles=[names[i].split(':')[1] for i in ids]
        return any("'" not in s and s not in ('CM','HCM1','HCM2','HCM3') for s in roles)
    bonds=[(t.atom1.idx,t.atom2.idx) for t in psf.bond_list]
    angles=[(t.atom1.idx,t.atom2.idx,t.atom3.idx) for t in psf.angle_list]
    be=[abs(np.linalg.norm(x[a]-x[b])-np.linalg.norm(q[a]-q[b])) for a,b in bonds if lesion((a,b))]
    ae=[abs(angle(x,ids)-angle(q,ids)) for ids in angles if lesion(ids)]
    b=float(max(be,default=0));a=float(max(ae,default=0))
    return dict(max_bond_A=b,max_angle_deg=a,passed=b<=.03 and a<=3)


def build_variables():
    from openmm import app
    variables=[{k:v[k] for k in ('endpoint','names','periodicity','types')} for v in read(FIRST/'fit.json')['coefficients']]
    psf=app.CharmmPsfFile(str(BASE/'endpoint-1/fragment.psf'));names=read(BASE/'endpoint-1/atom_map.json')
    for e in (1,2):
        for roles,ns in [([f'{e}:C2',f'{e}:N1',f'{e}:C6',f'{3-e}:C5'],[3,6]),
                         ([f'{e}:N3',f'{e}:C2',f'{e}:N1',f'{e}:C6'],[2,4]),
                         ([f'{e}:N1',f'{e}:C2',f'{e}:N3',f'{e}:C4'],[2])]:
            types=tuple(psf.atom_list[names.index(n)].attype for n in roles)
            for n in ns:variables.append(dict(endpoint=e,names=roles,periodicity=n,types=list(min(types,types[::-1]))))
    assert len(variables)==22 and len({(tuple(v['types']),v['periodicity']) for v in variables})==22
    return variables


def parameters(path):
    from openmm import app
    with warnings.catch_warnings():
        warnings.simplefilter('ignore');return app.CharmmParameterSet(str(path))


def export_check(parent,destination,variables,shifts,fixtures):
    """Check every typed occurrence against an independently added cosine force."""
    import openmm as mm
    from openmm import app,unit as u
    basepar=parameters(parent);newpar=parameters(destination);rows=[]
    for label,folder in fixtures.items():
        psf=app.CharmmPsfFile(str(folder/'fragment.psf'))
        base=psf.createSystem(basepar,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
        check=mm.CustomTorsionForce('delta*cos(n*theta)+offset')
        for n in ('delta','n','offset'):check.addPerTorsionParameter(n)
        occurrences=[]
        for v,d in zip(variables,shifts):
            key=tuple(v['types']);n=v['periodicity']
            signed={t.per:t.phi_k*math.cos(math.radians(t.phase)) for t in basepar.dihedral_types[key]}.get(n,0.)
            count=0
            for t in psf.dihedral_list:
                atoms=[t.atom1,t.atom2,t.atom3,t.atom4];types=tuple(a.attype for a in atoms)
                if min(types,types[::-1])==key:
                    check.addTorsion(*[a.idx for a in atoms],[float(d)*4.184,n,(abs(signed+d)-abs(signed))*4.184]);count+=1
            occurrences.append(count)
        base.addForce(check)
        other=app.CharmmPsfFile(str(folder/'fragment.psf')).createSystem(newpar,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
        x=np.loadtxt(folder/'starting_A.txt');values=[]
        for system in (base,other):
            integ=mm.VerletIntegrator(.001);ctx=mm.Context(system,integ,mm.Platform.getPlatformByName('Reference'))
            ctx.setPositions(x*u.angstrom);s=ctx.getState(getEnergy=True,getForces=True)
            values.append((s.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole),
                np.array(s.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))))
            del ctx,integ
        de=abs(values[0][0]-values[1][0]);df=float(abs(values[0][1]-values[1][1]).max())
        assert de<1e-5 and df<1e-4,(label,de,df)
        rows.append(dict(fixture=label,energy_error_kcal=de,force_error_kcal_A=df,typed_occurrences=occurrences))
    return rows


def prepare():
    from openmm import app
    from experiments.cpd_anti_additive.score_prospective_v2 import validate
    validate()
    closepath=ART/'cpd-anti-prospective-closeout-v2-r1/assessment.json';close=read(closepath)
    assert close['fit_rounds_used']==1 and not close['conformational_stage_passed']
    assert not (old.STATE/'conformational_successor.json').exists()
    INPUTS.mkdir(exist_ok=False)
    vars=build_variables();points=read(ART/'cpd-anti-conformational-inventory-v2b/inventory.json')['records']
    references=read(ART/'cpd-anti-prospective-qm-v2-r1/plan.json')['references']
    files=[source(closepath),source(FIRST/'fit.json'),source(FIRST/'assessment.json'),source(BASE/'comparator_last.prm'),
        source(ART/'cpd-anti-shape-model-diagnosis-v1c/assessment.json'),source(SCORES/'assessment.json'),
        source(ART/'cpd-anti-conformational-inventory-v2b/inventory.json'),source(old.POLICY)]
    for row in read(SCORES/'assessment.json')['records']:
        for ref in row['evidence']:checked(ref);files.append(ref)
        p=read(SCORES/row['case_id']/'point.json')
        ref=next(r for r in references if r['case_id']==p['reference_case_id'])
        p['qm_relative_kcal_mol']=(p['qm_energy_hartree']-ref['qm_energy_hartree'])*EH
        points.append(p)
    assert [p['case_id'] for p in points]==close['exposed_case_ids']
    for p in points:
        for k in ('geometry_source','qm_source','native'):
            if p.get(k):checked(p[k]);files.append(p[k])
    fixtures={label:BASE/label for label in ('endpoint-1','endpoint-2','core','endpoint-2-remote','two-nucleosides')}
    rep=[];top=INPUTS/'topologies';top.mkdir()
    for label,folder in fixtures.items():
        for name in ('fragment.psf','atom_map.json','starting_A.txt'):files.append(source(folder/name))
        if label=='two-nucleosides':continue
        dest=top/(label if label in ('endpoint-1','endpoint-2') else 'endpoint-'+label)
        dest.mkdir();shutil.copyfile(folder/'fragment.psf',dest/'fragment.psf')
        shutil.copyfile(folder/'atom_map.json',dest/'atom_map.json')
        if label not in ('core','endpoint-2-remote'):continue
    for label in ('core','endpoint-1','endpoint-2-remote'):
        folder=fixtures[label];psf=app.CharmmPsfFile(str(folder/'fragment.psf'));names=read(folder/'atom_map.json')
        elements=[a.element.symbol for a in psf.topology.atoms()]
        q=np.loadtxt(folder/'starting_A.txt')
        heavy=[[t.atom1.idx,t.atom2.idx,t.atom3.idx,t.atom4.idx] for t in psf.dihedral_list
               if all(elements[a.idx]!='H' for a in (t.atom1,t.atom2,t.atom3,t.atom4))]
        endpoint='rep-'+label;dest=top/f'endpoint-{endpoint}';dest.mkdir()
        shutil.copyfile(folder/'fragment.psf',dest/'fragment.psf');shutil.copyfile(folder/'atom_map.json',dest/'atom_map.json')
        rep.append(dict(case_id='representative-'+label,representative=label,endpoint=endpoint,branch='remote-unconstrained',
            elements=elements,atom_map=names,geometry_bohr=(q/BOHR).tolist(),heavy_torsion_indices=heavy,
            record=dict(torsion_indices=heavy[0]),actual_dihedral_deg=0.))
    save(INPUTS/'points.json',points);save(INPUTS/'representatives.json',rep)
    x0=np.array([r['shift_kcal'] for r in read(FIRST/'fit.json')['coefficients']]+[0.]*10)
    # Static export verification only; no optimizer or objective evaluation before registration.
    export_parameters(BASE/'comparator_last.prm',INPUTS/'export_start.prm',vars,x0)
    probe=x0+np.array([-.1 if v>=0 else .1 for v in x0])
    export_parameters(BASE/'comparator_last.prm',INPUTS/'export_probe.prm',vars,probe)
    checks=dict(initial=export_check(BASE/'comparator_last.prm',INPUTS/'export_start.prm',vars,x0,fixtures),
                original_round_one=export_check(BASE/'comparator_last.prm',FIRST/'candidate/comparator_last.prm',vars,x0,fixtures),
                probe=export_check(BASE/'comparator_last.prm',INPUTS/'export_probe.prm',vars,probe,fixtures))
    save(INPUTS/'preflight.json',dict(at=now(),checks=checks,no_geometry_optimization=True,no_fit=True))
    shutil.copyfile(Path(__file__),INPUTS/'worker.py')
    for name in ('shape_fit_protocol_v2.py','conformational_fit_v2.py','sella_pilot.py','preliminary_protocol.py','validation_gate.py','prepare_engine_v2.py'):
        files.append(source(REPO/'experiments/cpd_anti_additive'/name))
    files += [source(p) for p in sorted(INPUTS.rglob('*')) if p.is_file()]
    policy=read(old.POLICY)
    plan=dict(at=now(),stage='conformational',revision='shape-v2.2',ready=True,case_ids=[p['case_id'] for p in points],
        artifacts=list({r['path']:r for r in files}.values()),max_campaign_rounds=2,
        original_candidate_lock=source(old.STATE/'conformational_candidate_lock.json'),
        parent=str(top.resolve()),baseline_parameters=source(BASE/'comparator_last.prm'),
        points=source(INPUTS/'points.json'),representatives=source(INPUTS/'representatives.json'),
        variables=vars,initial_shifts=x0.tolist(),bounds=[-5.,5.],bound_reference='Total signed coefficient changes from v2g, including consumed first-round changes; no +/-5 reset.',
        mm=read(ART/'cpd-anti-conformational-inputs-v2/receipt.json')['mm'],
        versions={n:metadata.version(n) for n in ('sella','ase','openmm','scipy','numpy')},
        limits=dict(hard_seconds=7200,max_model_evaluations=360,max_optimizer_nfev=12,MM_points_per_model=26,max_fit_rounds_remaining=1,automatic_continuations=0),
        optimizer=dict(name='scipy.optimize.least_squares',method='trf',absolute_jacobian_step_kcal=.02,ftol=.001,xtol=.001,gtol=.001),
        objective='Sum of five equally weighted mean-square blocks: 23 relative-energy errors/1kcal, 23 aligned heavy-coordinate RMSD/.25A, 23 maximum heavy-proper errors/20deg, 3 representative maximum lesion bond errors/.03A, 3 representative maximum lesion angle errors/3deg; plus .05*mean((total coefficient shift/3kcal)^2). Numerical failures add 1000 residual per failed case; never omit a case.',
        stopping='Stop at the first model passing all development gates, otherwise on solver/budget termination. Keep the lowest-objective numerically valid evaluated model; no new fit round or automatic restart.',
        fixed='Charges, LJ, bond/angle/improper and nonselected proper terms, including parent sugar/phosphate. Six ring-proper families add ten existing-multiplicity coefficients to the original twelve.',
        acceptance=policy['conformational'],branch_limits=dict(heavy_rmsd_A=.25,max_heavy_torsion_deg=20.),
        prospective_validation=dict(reference_case_ids=[r['case_id'] for r in references],offsets_deg=[-18.75,18.75],
            cases=4,method='Same four-case Sella/Psi4 acquisition and independent stationarity protocol; register revised candidate before acquisition.',
            gate='Before acquisition, audit historical evaluated-angle identities for overlap. If any target has already been exposed, stop for an explicit new version; no substitution or reuse as blind.',
            max_gradients_per_case=40,hard_hours=12,automatic_continuations=0),
        rationale='User requested continuation to scientific quality. Completed first-candidate validation found one prospective and seven exposed shape failures, including a fit-induced +15-degree regression; add mapped ring coordinates and relaxed geometry to the objective without changing qualification limits.',
        minimum_certified=False,simulation_ready=False)
    save(INPUTS/'receipt.json',plan)
    STATE.mkdir(exist_ok=False)
    activation=dict(read(old.STATE/'activation.json'),parent_activation=source(old.STATE/'activation.json'),
        revision='shape-v2.2',user_continuation_instruction='Proceed with getting cis-anti to scientific quality.',at=now())
    save(STATE/'activation.json',activation)
    save(STATE/'conformational_rounds.json',read(old.STATE/'conformational_rounds.json'))
    save(STATE/'conformational_second_round_review.json',dict(prior_result=source(closepath),authorized=True,rationale=plan['rationale']))
    old.lock_inputs('conformational',INPUTS/'receipt.json',STATE)
    claim=dict(at=now(),state=str(STATE.resolve()),input_lock=source(STATE/'conformational_input_lock.json'),max_campaign_rounds=2)
    with (old.STATE/'conformational_successor.json').open('x') as h:
        import json;json.dump(claim,h,indent=2);h.write('\n')
    save(STATE/'lineage.json',dict(parent_state=str(old.STATE.resolve()),successor_claim=source(old.STATE/'conformational_successor.json'),
        parent_candidate_lock=source(old.STATE/'conformational_candidate_lock.json'),parent_rounds=source(old.STATE/'conformational_rounds.json'),
        parent_closeout=source(closepath),parent_activation=source(old.STATE/'activation.json'),output=str(OUT.resolve())))
    save(STATE/'registration.json',dict(at=now(),files=[source(STATE/name) for name in
        ['lineage.json','activation.json','conformational_input_lock.json','conformational_second_round_review.json']]))
    require_fit_ready()
    print('Prepared shape-v2.2: 23 exposed + 3 representative structures, 22 coefficients, one remaining round; no fit yet.',flush=True)


def run():
    import openmm as mm
    from openmm import app
    from scipy.optimize import least_squares
    _,plan=require_fit_ready()
    for n,v in plan['versions'].items():assert metadata.version(n)==v
    _,_,number=begin_round(OUT);assert number==2
    OUT.mkdir(exist_ok=False)
    save(OUT/'plan.json',dict(at=now(),receipt=source(INPUTS/'receipt.json'),registration=source(STATE/'registration.json'),
        round=2,worker=source(Path(__file__))))
    points=read(checked(plan['points']));reps=read(checked(plan['representatives']));allpoints=points+reps
    deadline=time.monotonic()+plan['limits']['hard_seconds'];cache={};history=[];best=None
    psfs={p['endpoint']:app.CharmmPsfFile(str(Path(plan['parent'])/f"endpoint-{p['endpoint']}"/'fragment.psf')) for p in allpoints}
    target=np.array([p['qm_relative_kcal_mol'] for p in points])
    def evaluate(v):
        nonlocal best
        v=np.asarray(v);key=v.tobytes()
        if key in cache:return cache[key]['residual']
        if time.monotonic()>deadline or len(history)>=plan['limits']['max_model_evaluations']:raise BudgetReached('Declared wall/model cap')
        number=len(history)+1;folder=OUT/f'model-{number:03d}';folder.mkdir()
        entry=dict(number=number,parameters=v.tolist(),state='started',at=now());history.append(entry)
        save(folder/'started.json',entry);save(OUT/'progress.json',dict(at=now(),models=history,best=best))
        prm=folder/'candidate.prm';coeff=export_parameters(checked(plan['baseline_parameters']),prm,plan['variables'],v)
        par=parameters(prm);systems={e:p.createSystem(par,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False) for e,p in psfs.items()}
        results=[];coordinates=[]
        with (folder/'native_summary.log').open('w') as log,contextlib.redirect_stdout(log):
            for p in allpoints:
                if time.monotonic()>deadline:raise BudgetReached('Declared wall cap during model')
                r,x=relax_point(folder/p['case_id'],p,systems[p['endpoint']],plan,deadline)
                results.append(r);coordinates.append(x);save(folder/'progress.json',results)
        energies=np.array([r['energy_kcal'] for r in results[:23]])
        errors=relative(energies,points)-target
        residual=list(errors/math.sqrt(23))
        for p,x in zip(points,coordinates):
            residual.extend(aligned_residual(np.array(p['geometry_bohr'])*BOHR,x,p['elements'])/(.25*math.sqrt(23)))
        residual.extend(r['branch_descriptors']['basin_max_torsion_deg']/(20*math.sqrt(23)) for r in results[:23])
        geom=[representative_geometry(psfs[p['endpoint']],p['atom_map'],np.array(p['geometry_bohr'])*BOHR,x) for p,x in zip(reps,coordinates[23:])]
        residual.extend(g['max_bond_A']/(.03*math.sqrt(3)) for g in geom)
        residual.extend(g['max_angle_deg']/(3*math.sqrt(3)) for g in geom)
        residual.extend(math.sqrt(.05/len(v))*v/3)
        residual.extend(0. if r['independent_stationarity_and_chemistry_passed'] else 1000. for r in results)
        residual=np.array(residual);assert np.isfinite(residual).all()
        valid=all(r['independent_stationarity_and_chemistry_passed'] for r in results)
        energy=dict(rmse_kcal=float(np.sqrt(np.mean(errors**2))),max_abs_kcal=float(abs(errors).max()))
        energy['passed']=energy['rmse_kcal']<=1 and energy['max_abs_kcal']<=2
        development=valid and energy['passed'] and all(r['branch_descriptor_match'] for r in results[:23]) and all(g['passed'] for g in geom)
        objective=float(residual@residual)
        report=dict(at=now(),number=number,candidate=source(prm),parameters=v.tolist(),coefficients=coeff,objective=objective,
            numerically_valid=valid,energy=energy,shape_failures=[r['case_id'] for r in results[:23] if not r['branch_descriptor_match']],
            representative_geometry=geom,development_parameter_passed=development,results=results,minimum_certified=False,simulation_ready=False)
        save(folder/'assessment.json',report);np.save(folder/'residual.npy',residual)
        entry.update(state='complete',objective=objective,numerically_valid=valid,development_parameter_passed=development,
            shape_failures=len(report['shape_failures']),energy=energy,assessment=source(folder/'assessment.json'))
        if valid and (best is None or objective<best['objective']):best=dict(number=number,objective=objective,assessment=source(folder/'assessment.json'))
        cache[key]=dict(residual=residual,report=report)
        save(OUT/'progress.json',dict(at=now(),models=history,best=best))
        print('MODEL',number,'loss',objective,'shapes',len(report['shape_failures']),'energy',energy,'valid',valid,flush=True)
        if development:
            best=dict(number=number,objective=objective,assessment=source(folder/'assessment.json'))
            raise FitSatisfied('First evaluated model passed all development gates')
        return residual
    def jac(v):
        base=evaluate(v);cols=[]
        for j in range(len(v)):
            trial=np.array(v);h=.02 if v[j]+.02<=5 else -.02;trial[j]+=h
            cols.append((evaluate(trial)-base)/h)
        return np.array(cols).T
    termination=None;failure=None
    try:
        start=np.clip(plan['initial_shifts'],-5+1e-8,5-1e-8)
        result=least_squares(evaluate,start,jac=jac,bounds=(-5.,5.),method='trf',max_nfev=12,ftol=.001,xtol=.001,gtol=.001,x_scale='jac')
        termination=dict(reason=str(result.message),solver_success=bool(result.success),nfev=result.nfev,njev=result.njev)
    except (BudgetReached,FitSatisfied) as exc:termination=dict(reason=str(exc),solver_success=False,bounded_stop=True)
    except Exception as exc:
        failure=dict(at=now(),error=repr(exc),traceback=traceback.format_exc());save(OUT/'failure.json',failure)
        termination=dict(reason='Unexpected failure; partial evidence retained',solver_success=False)
    for entry in history:
        if entry['state']=='started':entry.update(state='incomplete',termination=termination)
    save(OUT/'progress.json',dict(at=now(),models=history,best=best,termination=termination))
    if best is None:raise RuntimeError('No numerically valid model; inspect retained failure/evaluations')
    chosen=read(checked(best['assessment']));candidate=OUT/'candidate';candidate.mkdir()
    shutil.copyfile(checked(chosen['candidate']),candidate/'comparator_last.prm')
    fixtures={label:BASE/label for label in ('endpoint-1','endpoint-2','core','endpoint-2-remote','two-nucleosides')}
    check=export_check(checked(plan['baseline_parameters']),candidate/'comparator_last.prm',plan['variables'],chosen['parameters'],fixtures)
    save(OUT/'export_checks.json',dict(at=now(),checks=check))
    report=dict(at=now(),round=2,fit_round_budget_exhausted=True,termination=termination,unexpected_failure=failure,
        selected=best,candidate=source(candidate/'comparator_last.prm'),export_checks=source(OUT/'export_checks.json'),
        evaluated_models=len(history),energy=chosen['energy'],shape_failures=chosen['shape_failures'],representative_geometry=chosen['representative_geometry'],
        development_parameter_passed=chosen['development_parameter_passed'] and failure is None,
        prospective_validation_complete=False,conformational_stage_passed=False,minimum_certified=False,
        preliminary_research_qualified=False,simulation_ready=False,
        next='Independent audit. Fresh registered validation and engine checks only if development gates pass; no additional fit or automatic continuation.')
    save(OUT/'assessment.json',report);print('ASSESSMENT',report,flush=True)
    if failure is not None:raise RuntimeError(failure['error'])


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run'])
    globals()[parser.parse_args().action]()
