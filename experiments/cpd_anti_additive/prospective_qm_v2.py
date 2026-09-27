"""Register a fixed candidate, then acquire four prescribed prospective QM points.

No fitting or MM target scoring here. Existing Sella/Psi4 numerical conventions
are retained; candidate registration blocks further fitting before target exposure.
"""
import argparse
import importlib.metadata as metadata
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import traceback

import numpy as np

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.preliminary_protocol import require, POLICY, STATE, PAUSE
from experiments.cpd_anti_additive.sella_pilot import (
    BOHR, FORCE_FACTOR, HARTREE_EV, save, now, projected_metrics, geometry_audit,
    force_pass, xyz_text, review,
)
from backend.parameterization.photoproduct_qm import _dihedral_degrees

ART = REPO/'.development-artifacts'
ROOT = ART/'cpd-anti-prospective-qm-v2-r1'
FIT = ART/'cpd-anti-conformational-fit-v2-r1'
LOCK = STATE/'conformational_candidate_lock.json'
REFERENCES = ['endpoint-1-reference','endpoint-2-reference-lower-mm-basin']


def seed_at_offset(point, offset):
    """Rotate the graph-defined sugar component around the existing N1-C1 bond."""
    x = np.array(point['geometry_bohr'])
    graph = read(checked(point['record']['model_graph']))
    names = [a['key'] for a in graph['atoms']]
    endpoint = point['endpoint']
    c1, n1 = names.index(f"{endpoint}:C1'"), names.index(f'{endpoint}:N1')
    adjacent = {i:[] for i in range(len(x))}
    for b in graph['bonds']:
        a,c = b['indices']
        if {a,c} != {c1,n1}:
            adjacent[a].append(c); adjacent[c].append(a)
    move = {c1}; todo = [c1]
    while todo:
        i = todo.pop()
        for j in adjacent[i]:
            if j not in move:
                move.add(j); todo.append(j)
    expected = {i for i,n in enumerate(names) if n.startswith(f'{endpoint}:') and "'" in n}
    assert move == expected and len(move) == 17 and n1 not in move
    indices = point['record']['torsion_indices']
    reference = _dihedral_degrees(*x[indices])
    target = (reference+offset+180)%360-180
    axis = x[c1]-x[n1]; axis /= np.linalg.norm(axis); ids = sorted(move)
    candidates = []
    for theta in [np.radians(offset),-np.radians(offset)]:
        v = x[ids]-x[n1]; y = x.copy()
        y[ids] = x[n1]+v*np.cos(theta)+np.cross(axis,v)*np.sin(theta)+np.outer(v@axis,axis)*(1-np.cos(theta))
        error = abs((_dihedral_degrees(*y[indices])-target+180)%360-180)
        candidates.append((error,y))
    error,y = min(candidates,key=lambda v:v[0]); assert error < 1e-8
    assert np.array_equal(y[[i for i in range(len(x)) if i not in move]],x[[i for i in range(len(x)) if i not in move]])
    return y,target,ids


def prepare():
    from ase import Atoms
    from sella import Constraints
    import psi4
    require('conformational')
    assert not LOCK.exists()
    ROOT.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__),ROOT/'worker.py')
    pilot = read(ART/'cpd-anti-sella-fresh-v1/plan.json')
    for record in pilot['runtime_sources']:
        checked(record)
    for name,version in pilot['versions'].items():
        assert metadata.version(name) == version
    assert psi4.__version__ == pilot['psi4_version']
    inventory_path = ART/'cpd-anti-conformational-inventory-v2b/inventory.json'
    inventory = read(inventory_path)
    source_paths = [POLICY,STATE/'activation.json',STATE/'conformational_input_lock.json',
        STATE/'conformational_rounds.json',inventory_path,FIT/'assessment.json',FIT/'independent_review.json',
        FIT/'candidate/assessment.json',FIT/'candidate/comparator_last.prm',ROOT/'worker.py',
        ART/'cpd-anti-sella-fresh-v1/preflight.json',ART/'cpd-anti-sella-fresh-v1/completion_delivery_verified.json',
        ART/'cpd-anti-solvated-engine-v2e/independent_review.json',
        REPO/'experiments/cpd_anti_additive/sella_pilot.py']
    source_paths += [p for e in [1,2] for p in sorted((FIT/f'candidate/endpoint-{e}').iterdir()) if p.is_file()]
    tasks = []; refs = []; preflights = []
    for endpoint,label in enumerate(REFERENCES,1):
        point = next(r for r in inventory['records'] if r['case_id'] == label)
        graph = read(checked(point['record']['model_graph']))
        assert point['endpoint'] == endpoint and graph['formal_charge'] == 0
        assert {tuple(sorted(b['atoms'])) for b in graph['bonds'] if b['atoms'][0].split(':')[0]!=b['atoms'][1].split(':')[0]} == {('1:C5','2:C6'),('1:C6','2:C5')}
        reference_mm = FIT/'candidate_profiles'/label/'assessment.json'
        assert read(reference_mm)['independent_stationarity_and_chemistry_passed']
        source_paths.append(reference_mm)
        refs.append(dict(endpoint=endpoint,case_id=label,qm_energy_hartree=point['qm_energy_hartree'],
            mm_energy_kcal=read(reference_mm)['energy_kcal'],mm_assessment=source(reference_mm),
            reference_geometry=point['geometry_source'],reference_qm=point['qm_source']))
        for offset in [-22.5,22.5]:
            name = f'endpoint-{endpoint}-{offset:+g}-prospective-r1'
            folder = ROOT/name; folder.mkdir()
            y,target,rotated = seed_at_offset(point,offset)
            record = dict(endpoint=endpoint,label=name,model_graph=point['record']['model_graph'],
                scan_plan=point['record']['scan_plan'],torsion_indices=point['record']['torsion_indices'],target_degrees=target)
            plan = dict(record=record,elements=point['elements'],geometry_bohr=y.tolist(),
                method=pilot['method'],options=pilot['options'],psi4_version=pilot['psi4_version'],
                optimizer=pilot['optimizer'],limits=pilot['limits'],max_new_gradients=40,
                max_continuations=0,wall_seconds=21600,threads=4,memory_gib=6,
                scratch_dir=str(Path('/home/jojo/.cache/nadoc-qm')/ROOT.name/name),
                reference_case_id=label,offset_degrees=offset,reference_qm=point['qm_source'],
                reference_geometry=point['geometry_source'],rotated_atom_indices=rotated,
                minimum_certified=False,simulation_ready=False)
            audit = geometry_audit(y,plan,graph)
            # Also compare seed handedness with the independently acquired reference.
            original = geometry_audit(y,dict(plan,geometry_bohr=point['geometry_bohr']),graph)
            assert audit['chemistry_passed'] and audit['constraint_passed'] and original['chemistry_passed']
            atoms = Atoms(point['elements'],positions=y*BOHR)
            constraints = Constraints(atoms); constraints.fix_dihedral(tuple(record['torsion_indices']))
            angle = float(np.degrees(constraints.calc()[0]))
            assert abs((angle-target+180)%360-180) < 1e-8
            normal = constraints.jacobian()[0].reshape(y.shape)
            g = np.linspace(-1e-3,1e-3,y.size).reshape(y.shape)
            projected = g-normal*np.sum(normal*g)/np.sum(normal**2)
            independent = projected_metrics(y,g,record['torsion_indices'])
            assert abs(np.linalg.norm(projected,axis=1).max()-independent['max_projected_atom_gradient']) < 1e-10
            save(folder/'plan.json',plan); save(folder/'starting_audit.json',audit)
            (folder/'starting.xyz').write_text(xyz_text(point['elements'],y,'Prospective seed; no new QM or minimum claim'))
            tasks.append(dict(case_id=name,folder=str(folder.resolve()),plan=source(folder/'plan.json')))
            preflights.append(dict(case_id=name,target_degrees=target,original_reference_stereo_preserved=True,
                sella_angle_matches=True,independent_projection_matches=True,new_qm_evaluations=0))
    master = dict(at=now(),stage='conformational-prospective-validation',tasks=tasks,
        scope='Acquire exactly four prescribed independent QM targets for the first-round candidate; no fitting, MD or app integration',
        authorization='User-authorized campaign continuation under activated preliminary policy v2',
        sources=[source(p) for p in source_paths],runtime_sources=pilot['runtime_sources'],versions=pilot['versions'],
        runtime_python=sys.executable,psi4_version=pilot['psi4_version'],references=refs,
        max_new_gradients_per_case=40,max_total_new_gradients=160,hard_seconds=43200,
        per_case_hard_seconds=21600,expected_seconds=14400,max_continuations=0,
        workers_at_once=1,threads=4,memory_gib=6,service_memory_gib=10,
        budget_rationale='Reuse v2 40-gradient optimizer allowance for each of four prescribed validation targets; one sequential batch capped at12h. Budget exhaustion remains incomplete, never prunes a target.',
        downstream_evaluation='One locked-candidate MM relaxation per acquired QM target, seeded from that QM geometry; same existing MM 400-step/600-evaluation/.001-force/.01-degree limits. Use exact QM and MM reference identities and stored reference energies above, never separate minima/re-zeroing. Score four prospective energy residuals under original1kcal RMS/2kcal maximum; preserve all7 existing profile geometry flags and report new shape correspondence. No refit to these targets.',
        exposure='New targets registered before acquisition; all19 previous cases remain exposed development data. No claim of global or Hessian-certified minima.',
        existing_limitations=['Seven exposed profile geometry descriptors mismatched','Scientific/context qualification incomplete','Full-DNA engine pass does not waive prospective validation or product screens'],
        minimum_certified=False,simulation_ready=False)
    save(ROOT/'plan.json',master); save(ROOT/'preflight.json',dict(passed=True,cases=preflights,new_qm_evaluations=0))
    save(ROOT/'inputs_lock.json',dict(at=now(),files=[source(p) for p in sorted(ROOT.rglob('*')) if p.is_file()]))
    # Registration is new and exclusive; existing stage input locks are untouched.
    with LOCK.open('x') as f:
        json.dump(dict(at=now(),stage='conformational',candidate=source(FIT/'candidate/comparator_last.prm'),
            candidate_assessment=source(FIT/'candidate/assessment.json'),input_lock=source(STATE/'conformational_input_lock.json'),
            policy=source(POLICY),validation_plan=source(ROOT/'plan.json'),validation_inputs=source(ROOT/'inputs_lock.json'),
            frozen_before_prospective_acquisition=True,prospective_targets_used_for_fit=False,
            further_fitting_blocked=True,fit_rounds_used=1,minimum_certified=False,simulation_ready=False),f,indent=2)
    save(ROOT/'registration.json',dict(at=now(),candidate_lock=source(LOCK),preflight=source(ROOT/'preflight.json')))
    print('Registered candidate and four prospective targets; no new QM',ROOT,flush=True)


def validate():
    assert not read(PAUSE)['paused']
    registration = read(ROOT/'registration.json'); lock = read(checked(registration['candidate_lock']))
    assert lock['frozen_before_prospective_acquisition'] and not lock['prospective_targets_used_for_fit']
    checked(lock['candidate']); checked(lock['candidate_assessment']); checked(lock['input_lock']); checked(lock['policy'])
    plan = read(checked(lock['validation_plan']))
    for row in read(checked(lock['validation_inputs']))['files']+plan['sources']+plan['runtime_sources']:
        checked(row)
    assert read(STATE/'activation.json')['user_authorized_resume']
    assert source(POLICY) == read(STATE/'activation.json')['policy']
    assert plan['max_total_new_gradients'] == 160 and len(plan['tasks']) == 4 and plan['max_continuations'] == 0
    for name,version in plan['versions'].items():
        assert metadata.version(name) == version
    return plan


def run_case(folder):
    from ase import Atoms
    from ase.calculators.calculator import Calculator, all_changes
    from sella import Sella, Constraints
    import psi4
    master = validate(); plan = read(folder/'plan.json')
    assert any(checked(t['plan']) == (folder/'plan.json').resolve() for t in master['tasks'])
    assert psi4.__version__ == plan['psi4_version']
    with (folder/'started.json').open('x') as f:
        json.dump(dict(at=now(),plan=source(folder/'plan.json'),registration=source(ROOT/'registration.json')),f)
    os.chdir(folder)
    graph = read(checked(plan['record']['model_graph']))
    scratch = Path(plan['scratch_dir']); scratch.mkdir(parents=True,exist_ok=False)
    assert shutil.disk_usage(scratch).free > 15*1024**3
    psi4.set_num_threads(plan['threads']);psi4.set_memory('6 GiB')
    psi4.core.IOManager.shared_object().set_default_path(str(scratch));psi4.set_options(plan['options'])
    rows=[];convergence=[];attempts=0;started=time.monotonic()
    save(folder/'progress.json',dict(evaluations=rows,attempts=0,minimum_certified=False))
    class Psi4Calculator(Calculator):
        implemented_properties=['energy','forces']
        def calculate(self,atoms=None,properties=('energy','forces'),system_changes=all_changes):
            nonlocal attempts
            super().calculate(atoms,properties,system_changes)
            if attempts >= 40 or time.monotonic()-started >= plan['wall_seconds']:
                raise RuntimeError('Prospective point gradient/time cap reached; no continuation')
            x=self.atoms.positions/BOHR; audit=geometry_audit(x,plan,graph)
            if not audit['chemistry_passed']:
                save(folder/'rejected_trial.json',dict(geometry_bohr=x.tolist(),audit=audit))
                raise RuntimeError('Trial chemistry screen failed before QM')
            attempts+=1;out=folder/f'evaluation-{attempts:03d}';out.mkdir()
            np.save(out/'geometry_bohr.npy',x)
            save(out/'input.json',dict(elements=plan['elements'],geometry_bohr=x.tolist(),method=plan['method'],
                options=plan['options'],charge=0,multiplicity=1,attempt=attempts,started_at=now(),geometry_audit=audit))
            psi4.set_output_file(str(out/'output.dat'),False)
            text='\n'.join(el+' '+' '.join(f'{v:.15f}' for v in pos) for el,pos in zip(plan['elements'],x))
            molecule=psi4.geometry('0 1\n'+text+'\nunits bohr\nsymmetry c1\nno_com\nno_reorient')
            tick=time.monotonic(); gradient,wfn=psi4.gradient(plan['method'],molecule=molecule,return_wfn=True)
            energy=float(wfn.energy());gradient=np.array(gradient)
            assert np.max(abs(np.array(wfn.molecule().geometry())-x)) < 1e-10
            psi4.core.flush_outfile();psi4.core.clean()
            native=(out/'output.dat').read_text()
            residuals=[float(v) for v in re.findall(r'CGR\s+\d+\s+1\s+0\s+([\d.E+-]+)',native)]
            assert residuals and max(residuals) <= plan['options']['solver_convergence']
            assert gradient.shape == x.shape and np.isfinite(gradient).all() and np.isfinite(energy)
            metrics=projected_metrics(x,gradient,plan['record']['torsion_indices'])
            save(out/'result.json',dict(energy=energy,gradient=gradient.tolist(),input=source(out/'input.json'),
                geometry=source(out/'geometry_bohr.npy'),native=source(out/'output.dat'),reused=False,audit=audit,
                independent_projection=metrics,elapsed_seconds=time.monotonic()-tick))
            rows.append(dict(result=source(out/'result.json'),energy=energy,**metrics))
            save(folder/'progress.json',dict(evaluations=rows,attempts=attempts,elapsed_seconds=time.monotonic()-started,minimum_certified=False))
            (folder/'last_evaluated.xyz').write_text(xyz_text(plan['elements'],x,'Evaluated prospective target; not a certified minimum'))
            self.results=dict(energy=energy*HARTREE_EV,forces=-gradient*FORCE_FACTOR)
            print(json.dumps(dict(case=folder.name,evaluation=attempts,energy=energy,**metrics)),flush=True)
    atoms=Atoms(plan['elements'],positions=np.array(plan['geometry_bohr'])*BOHR);atoms.calc=Psi4Calculator()
    constraint=Constraints(atoms);constraint.fix_dihedral(tuple(plan['record']['torsion_indices']))
    class AuditedSella(Sella):
        def converged(self,forces=None):
            native=bool(super().converged(forces));x=atoms.positions/BOHR
            metrics=projected_metrics(x,-atoms.get_forces(apply_constraint=False)/FORCE_FACTOR,plan['record']['torsion_indices'])
            audit=geometry_audit(x,plan,graph)
            passed=force_pass(metrics,plan['limits']) and audit['constraint_passed'] and audit['chemistry_passed']
            convergence.append(dict(native_converged=native,independent_passed=passed,evaluations=attempts,
                **metrics,torsion_error_deg=audit['torsion_error_deg']))
            save(folder/'convergence_checks.json',convergence)
            return native and passed
    native=False;error=None
    try:
        optimizer=AuditedSella(atoms,constraints=constraint,logfile=str(folder/'sella.log'),trajectory=str(folder/'sella.traj'),**plan['optimizer'])
        native=bool(optimizer.run(fmax=plan['limits']['max_gradient']*FORCE_FACTOR,steps=40))
        if native:
            (folder/'optimized.xyz').write_text(xyz_text(plan['elements'],atoms.positions/BOHR,'Prospective constrained stationary candidate; no Hessian certification'))
        else:error='Sella step cap reached without joint convergence'
    except Exception as exc:
        error=repr(exc);(folder/'failure_traceback.txt').write_text(traceback.format_exc())
    finally:
        psi4.core.flush_outfile();psi4.core.clean()
        save(folder/'assessment.json',dict(joint_optimizer_converged=native,error=error,evaluations=len(rows),
            attempted_gradients=attempts,finished_at=now(),elapsed_seconds=time.monotonic()-started,minimum_certified=False,simulation_ready=False))
    independent=review(folder)
    if not native or not independent.get('independent_stationarity_passed'):
        raise RuntimeError(error or 'Independent stationarity review failed')


def run():
    plan=validate();start=time.monotonic();records=[]
    with (ROOT/'started.json').open('x') as f:
        json.dump(dict(at=now(),registration=source(ROOT/'registration.json')),f)
    for task in plan['tasks']:
        folder=Path(task['folder']);remaining=plan['hard_seconds']-(time.monotonic()-start)
        if remaining <= 0:
            records.append(dict(case=task['case_id'],state='not_started_total_time_cap',passed=False));continue
        try:
            with (folder/'worker.log').open('w') as log:
                p=subprocess.run([sys.executable,str(ROOT/'worker.py'),'case',str(folder)],cwd=REPO,stdout=log,
                    stderr=subprocess.STDOUT,timeout=min(plan['per_case_hard_seconds'],remaining))
            result=read(folder/'assessment.json') if (folder/'assessment.json').exists() else None
            audit=read(folder/'independent_review.json') if (folder/'independent_review.json').exists() else None
            passed=bool(p.returncode == 0 and result and result['joint_optimizer_converged'] and audit and audit.get('independent_stationarity_passed'))
            row=dict(case=task['case_id'],returncode=p.returncode,passed=passed,
                assessment=source(folder/'assessment.json') if result else None,
                independent_review=source(folder/'independent_review.json') if audit else None)
        except subprocess.TimeoutExpired:
            row=dict(case=task['case_id'],passed=False,error='Frozen wall-time cap reached; partial native outputs retained')
            save(folder/'timeout.json',dict(at=now(),**row))
        records.append(row);save(ROOT/'progress.json',dict(at=now(),records=records,total=4))
    passed=all(r['passed'] for r in records) and len(records)==4
    save(ROOT/'assessment.json',dict(at=now(),records=records,all_four_constrained_stationarity_passed=passed,
        candidate_lock=source(LOCK),elapsed_seconds=time.monotonic()-start,MM_prospective_validation_complete=False,
        minimum_certified=False,preliminary_research_qualified=False,simulation_ready=False))
    if not passed:raise RuntimeError('Prospective acquisition incomplete/failed; no continuation or target omission')


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','run','case']);parser.add_argument('folder',nargs='?',type=Path)
    args=parser.parse_args()
    if args.action == 'case':run_case(args.folder.resolve())
    else:globals()[args.action]()
