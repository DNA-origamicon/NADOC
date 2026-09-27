"""One fixed-candidate MM score per registered, independently accepted QM target.

Run `prepare` once, then `ready` after acquisition makes progress. Completed and
failed attempts are exclusive and never rerun. This does not fit parameters or
change the acquisition, candidate lock, reference identities, or acceptance gates.
"""
import argparse
import fcntl
import importlib.metadata as metadata
import os
from pathlib import Path
import re
import shutil
import sys
import time
import traceback
import warnings

import numpy as np

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, source, checked, geometry_match
from experiments.cpd_anti_additive.sella_pilot import BOHR, save, now, projected_metrics, geometry_audit, force_pass
from experiments.cpd_anti_additive.preliminary_protocol import STATE, POLICY, PAUSE
from experiments.cpd_anti_additive.conformational_fit_v2 import relax_point
from backend.parameterization.photoproduct_qm import _dihedral_degrees

ART = REPO/'.development-artifacts'
ROOT = ART/'cpd-anti-prospective-score-v2-r1'
QM = ART/'cpd-anti-prospective-qm-v2-r1'
FIT = ART/'cpd-anti-conformational-fit-v2-r1'
EH = 627.5094740631


def score_energy(qm_energy, mm_energy, reference):
    q = (qm_energy-reference['qm_energy_hartree'])*EH
    m = mm_energy-reference['mm_energy_kcal']
    if not np.isfinite([q, m]).all():
        raise ValueError('Nonfinite prospective score')
    return dict(reference_case_id=reference['case_id'], qm_relative_kcal=float(q),
                mm_relative_kcal=float(m), residual_kcal=float(m-q))


def aggregate(rows, ids):
    """A partial or failed set cannot pass by omitting its missing residuals."""
    if len({r['case_id'] for r in rows}) != len(rows) or set(r['case_id'] for r in rows)-set(ids):
        raise ValueError('Duplicate or unregistered target')
    indexed = {r['case_id']: r for r in rows}
    complete = all(k in indexed and indexed[k]['state'] == 'scored' for k in ids)
    metrics = dict(all_four_scored=complete, energy_passed=False, geometry_descriptors_passed=False)
    if complete:
        residuals = np.array([indexed[k]['energy']['residual_kcal'] for k in ids])
        if not np.isfinite(residuals).all():
            raise ValueError('Nonfinite prospective residual')
        rms, maximum = float(np.sqrt(np.mean(residuals**2))), float(abs(residuals).max())
        metrics.update(rmse_kcal=rms, max_abs_kcal=maximum, energy_passed=rms <= 1 and maximum <= 2,
                       geometry_descriptors_passed=all(indexed[k]['branch_descriptor_match'] for k in ids))
    return metrics


def validate():
    assert not read(PAUSE)['paused'] and read(STATE/'activation.json')['user_authorized_resume']
    registration = read(ROOT/'registration.json')
    for row in read(checked(registration['inputs_lock']))['files']:
        checked(row)
    plan = read(checked(registration['plan']))
    for row in plan['sources']:
        checked(row)
    acquisition = read(checked(plan['acquisition_plan']))
    for row in acquisition['sources']+acquisition['runtime_sources']+read(QM/'inputs_lock.json')['files']:
        checked(row)
    for name, version in plan['versions'].items():
        assert metadata.version(name) == version, name
    lock = read(checked(plan['candidate_lock']))
    assert lock['frozen_before_prospective_acquisition'] and lock['further_fitting_blocked']
    assert lock['candidate'] == plan['candidate'] and lock['validation_plan'] == plan['acquisition_plan']
    return plan, acquisition


def prepare():
    acquisition = read(QM/'plan.json')
    registration = read(QM/'registration.json')
    lock = read(checked(registration['candidate_lock']))
    fit_plan = read(ART/'cpd-anti-conformational-inputs-v2/receipt.json')
    assert lock['candidate'] == source(FIT/'candidate/comparator_last.prm')
    ROOT.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__), ROOT/'worker.py')
    paths = [POLICY, STATE/'activation.json', STATE/'conformational_rounds.json',
        QM/'registration.json', QM/'inputs_lock.json', FIT/'assessment.json', FIT/'independent_review.json',
        ART/'cpd-anti-conformational-inputs-v2/receipt.json', checked(fit_plan['inventory']), ROOT/'worker.py']
    paths += [REPO/'experiments/cpd_anti_additive'/name for name in
              ['conformational_fit_v2.py','sella_pilot.py','prepare_engine_v2.py','validation_gate.py','preliminary_protocol.py']]
    paths += [p for e in (1, 2) for p in sorted((FIT/f'candidate/endpoint-{e}').iterdir()) if p.is_file()]
    paths += [checked(r['mm_assessment']) for r in acquisition['references']]
    plan = dict(at=now(), candidate=lock['candidate'], candidate_lock=registration['candidate_lock'],
        acquisition_plan=source(QM/'plan.json'), references=acquisition['references'],
        case_ids=[t['case_id'] for t in acquisition['tasks']], sources=[source(p) for p in paths],
        versions=fit_plan['versions'], mm=fit_plan['mm'], parent=str((FIT/'candidate').resolve()),
        max_attempts_per_target=1, hard_scoring_seconds=7200, max_total_MM_evaluations=2400,
        fixed_acceptance=read(POLICY)['conformational'],
        rationale='Execution of the already registered downstream evaluation; candidate and scoring rules preceded QM acquisition. One fixed-potential MM relaxation per independently accepted target, from its own QM geometry.',
        acquisition_failures='Retain every target. Failed or missing QM cannot be substituted, pruned or scored as a stationary reference.',
        qualification='All seven exposed branch mismatches remain blocking; prospective scores alone cannot confer qualification.',
        no_parameter_fitting=True, minimum_certified=False, simulation_ready=False)
    save(ROOT/'plan.json', plan)
    save(ROOT/'inputs_lock.json', dict(at=now(), files=[source(p) for p in sorted(ROOT.rglob('*')) if p.is_file()]))
    save(ROOT/'registration.json', dict(at=now(), plan=source(ROOT/'plan.json'), inputs_lock=source(ROOT/'inputs_lock.json')))
    validate()
    print('Prepared fixed scoring; no QM, MM optimization, or parameter fit', flush=True)


def audit_qm(folder, plan, record):
    from ase.io import read as read_atoms
    from sella import Constraints
    assessment = read(checked(record['assessment']))
    prior = read(checked(record['independent_review']))
    assert record['passed'] and record['returncode'] == 0
    assert assessment['joint_optimizer_converged'] and prior['independent_stationarity_passed']
    rows = read(folder/'progress.json')['evaluations']
    assert len(rows) == assessment['evaluations'] == assessment['attempted_gradients'] <= 40
    frames = read_atoms(folder/'sella.traj', index=':')
    assert len(frames) == len(rows)
    graph = read(checked(plan['record']['model_graph']))
    records = []
    for i, (row, frame) in enumerate(zip(rows, frames), 1):
        result = read(checked(row['result']))
        x = np.load(checked(result['geometry'])); inp = read(checked(result['input']))
        assert np.array_equal(x, inp['geometry_bohr'])
        assert inp['elements'] == plan['elements'] == frame.get_chemical_symbols()
        assert inp['options'] == plan['options'] and inp['method'] == plan['method']
        assert np.max(abs(frame.positions/BOHR-x)) < 1e-10
        native = checked(result['native']).read_text()
        energies = re.findall(r'^\s*Total Energy\s*=\s*([-+\d.Ee]+)\s*\[Eh\]', native, re.M)
        assert energies and abs(float(energies[-1])-result['energy']) < 1e-10
        table = native.rsplit('-Total Gradient:', 1)[1].split('*** tstop()', 1)[0]
        parsed = re.findall(r'^\s*(\d+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s+([-+\d.Ee]+)\s*$', table, re.M)
        assert [int(p[0]) for p in parsed] == list(range(1, len(x)+1))
        printed = np.array([[float(v) for v in p[1:]] for p in parsed])
        assert np.max(abs(printed-np.asarray(result['gradient']))) < 6e-13
        response = [float(v) for v in re.findall(r'CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)', native)]
        assert response and max(response) <= plan['options']['solver_convergence']
        audit = geometry_audit(x, plan, graph); assert audit['chemistry_passed']
        records.append(dict(evaluation=i, result=row['result'], electronic_response_max=max(response)))
    final = read_atoms(folder/'optimized.xyz')
    assert final.get_chemical_symbols() == plan['elements'] and np.max(abs(final.positions/BOHR-x)) < 1e-10
    projections = [projected_metrics(x, printed, plan['record']['torsion_indices'], h) for h in (1e-4,1e-5,1e-6)]
    assert all(force_pass(m, plan['limits']) for m in projections) and audit['constraint_passed']
    cons = Constraints(final); cons.fix_dihedral(tuple(plan['record']['torsion_indices']))
    normal = cons.jacobian()[0].reshape(x.shape); gradient = np.asarray(result['gradient'])
    tangent = gradient-normal*np.sum(normal*gradient)/np.sum(normal**2)
    assert abs(np.linalg.norm(tangent,axis=1).max()-projections[1]['max_projected_atom_gradient']) < 1e-10
    last_check = read(folder/'convergence_checks.json')[-1]
    assert last_check['native_converged'] and last_check['independent_passed']
    report = dict(at=now(), passed=True, evaluations=records, assessment=record['assessment'],
        acquisition_review=record['independent_review'], final_result=rows[-1]['result'],
        trajectory=source(folder/'sella.traj'), optimized=source(folder/'optimized.xyz'),
        convergence_checks=source(folder/'convergence_checks.json'), projection_checks=projections,
        energy_hartree=result['energy'], minimum_certified=False)
    return report, x


def replay_mm(folder, point, plan):
    import openmm as mm
    from openmm import app, unit as u
    from experiments.cpd_anti_additive.prepare_engine_v2 import geometry_check
    result = read(folder/'assessment.json')
    raw = np.load(checked(result['raw_evaluations']))
    x = np.loadtxt(checked(result['final_geometry']))
    assert np.array_equal(x, raw['coordinates_A'][-1])
    with warnings.catch_warnings():
        warnings.simplefilter('ignore')
        params = app.CharmmParameterSet(str(checked(plan['candidate'])))
    psf = app.CharmmPsfFile(str(Path(plan['parent'])/f"endpoint-{point['endpoint']}"/'fragment.psf'))
    system = psf.createSystem(params, nonbondedMethod=app.NoCutoff, constraints=None, rigidWater=False)
    integ = mm.VerletIntegrator(.001); ctx = mm.Context(system,integ,mm.Platform.getPlatformByName('Reference'))
    ctx.setPositions(x*u.angstrom); state = ctx.getState(getEnergy=True,getForces=True)
    energy = state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
    gradient = -np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    de = abs(energy-result['energy_kcal']); dg = float(abs(gradient-raw['gradients_kcal_A'][-1]).max())
    assert de < 1e-5 and dg < 1e-4
    projections = [projected_metrics(x,gradient,point['record']['torsion_indices'],h) for h in (1e-4,1e-5,1e-6)]
    q = np.array(point['geometry_bohr'])*BOHR
    chemistry = geometry_check(psf,q,x)
    angle_error = abs((_dihedral_degrees(*x[point['record']['torsion_indices']])-point['actual_dihedral_deg']+180)%360-180)
    passed = bool(result['independent_stationarity_and_chemistry_passed'] and
        all(m['max_projected_atom_gradient'] < .001 for m in projections) and angle_error < .01 and
        chemistry['stereo_preserved'] and chemistry['graph_distances_passed'])
    shape = geometry_match(q,x,point['elements'],point['heavy_torsion_indices'])
    assert shape == result['branch_descriptors']
    audit = dict(at=now(), passed=passed, energy_kcal=energy, energy_replay_error=de,
        gradient_replay_error=dg, projection_checks=projections, torsion_error_deg=angle_error,
        chemistry=chemistry, branch_descriptors=shape, assessment=source(folder/'assessment.json'), minimum_certified=False)
    save(folder/'independent_review.json', audit)
    del ctx,integ
    return result,audit


def ready():
    import openmm as mm
    from openmm import app
    plan, acquisition = validate()
    lockfile = (ROOT/'scoring.lock').open('a')
    fcntl.flock(lockfile,fcntl.LOCK_EX|fcntl.LOCK_NB)
    master = read(QM/'progress.json') if (QM/'progress.json').exists() else dict(records=[])
    finished = {r['case']:r for r in master['records']}
    inventory = read(ART/'cpd-anti-conformational-inventory-v2b/inventory.json')['records']
    rows=[]
    used_seconds=sum(read(p)['elapsed_seconds'] for p in ROOT.glob('*/elapsed.json'))
    deadline=time.monotonic()+max(0,plan['hard_scoring_seconds']-used_seconds)
    for task in acquisition['tasks']:
        name=task['case_id']; out=ROOT/name
        if (out/'score.json').exists():
            saved=read(out/'score.json')
            for ref in saved.get('evidence',[]):checked(ref)
            rows.append(saved);continue
        if out.exists():
            rows.append(dict(case_id=name,state='incomplete_prior_attempt',no_automatic_retry=True));continue
        if name not in finished:
            rows.append(dict(case_id=name,state='awaiting_QM'));continue
        if not finished[name]['passed']:
            rows.append(dict(case_id=name,state='QM_failed',acquisition=finished[name]));continue
        if time.monotonic()>=deadline:
            rows.append(dict(case_id=name,state='scoring_wall_cap'));continue
        out.mkdir(exist_ok=False);start=time.monotonic()
        save(out/'started.json',dict(at=now(),candidate=plan['candidate'],acquisition=finished[name]))
        try:
            qp=read(checked(task['plan'])); native,x=audit_qm(Path(task['folder']),qp,finished[name])
            save(out/'qm_native_review.json',native)
            reference=next(r for r in acquisition['references'] if r['case_id']==qp['reference_case_id'])
            old=next(r for r in inventory if r['case_id']==reference['case_id'])
            assert old['endpoint']==qp['record']['endpoint'] and old['elements']==qp['elements']
            assert old['atom_map']==read(Path(plan['parent'])/f"endpoint-{old['endpoint']}"/'atom_map.json')
            point=dict(old,case_id=name,branch='prospective-reference-offset',geometry_bohr=x.tolist(),
                record=qp['record'],qm_energy_hartree=native['energy_hartree'],
                actual_dihedral_deg=_dihedral_degrees(*x[qp['record']['torsion_indices']]))
            save(out/'point.json',point)
            with warnings.catch_warnings():
                warnings.simplefilter('ignore')
                params=app.CharmmParameterSet(str(checked(plan['candidate'])))
            psf=app.CharmmPsfFile(str(Path(plan['parent'])/f"endpoint-{old['endpoint']}"/'fragment.psf'))
            system=psf.createSystem(params,nonbondedMethod=app.NoCutoff,constraints=None,rigidWater=False)
            relax_point(out/'MM',point,system,plan,deadline)
            result,audit=replay_mm(out/'MM',point,plan)
            scored=audit['passed']
            row=dict(case_id=name,state='scored' if scored else 'MM_failed',
                branch_descriptor_match=result['branch_descriptor_match'],branch_descriptors=result['branch_descriptors'],
                energy=score_energy(native['energy_hartree'],audit['energy_kcal'],reference) if scored else None,
                evidence=[source(out/p) for p in ['point.json','qm_native_review.json','MM/assessment.json','MM/independent_review.json']],
                minimum_certified=False)
        except Exception as exc:
            (out/'failure_traceback.txt').write_text(traceback.format_exc())
            row=dict(case_id=name,state='audit_or_scoring_failed',error=repr(exc),minimum_certified=False)
        finally:
            save(out/'elapsed.json',dict(elapsed_seconds=time.monotonic()-start))
        save(out/'score.json',row);rows.append(row)
        print(name,row['state'],row.get('energy'),flush=True)
    summary=dict(at=now(),registration=source(ROOT/'registration.json'),candidate=plan['candidate'],records=rows,
        **aggregate(rows,plan['case_ids']),development_parameter_passed=read(FIT/'assessment.json')['development_parameter_passed'],
        retained_exposed_geometry_mismatches=7,conformational_stage_passed=False,
        preliminary_research_qualified=False,minimum_certified=False,simulation_ready=False,
        fitting_performed=False,context_MD_authorized_by_this_result=False)
    save(ROOT/'progress.json',summary)
    if (QM/'assessment.json').exists() and all(r['state']!='awaiting_QM' for r in rows):
        if not (ROOT/'assessment.json').exists():save(ROOT/'assessment.json',summary)
    print({k:v for k,v in summary.items() if k not in ['records','registration','candidate']},flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','ready'])
    globals()[parser.parse_args().action]()
