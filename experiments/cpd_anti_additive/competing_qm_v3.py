"""Bounded Sella/Psi4 comparison of exposed cis-anti conformations.

This is diagnostic reference acquisition, not a fit or prospective validation.
Historical ledgers and source geometries remain immutable.
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
from experiments.cpd_anti_additive.sella_pilot import (
    BOHR, FORCE_FACTOR, HARTREE_EV, save, now, projected_metrics,
    geometry_audit, force_pass, xyz_text, review,
)

ART = REPO / '.development-artifacts'
ROOT = ART / 'cpd-anti-competing-qm-v3-20261003'
CAMPAIGN = ART / 'cpd-anti-readiness-v3-20261003'


def validate():
    registration = read(ROOT / 'registration.json')
    master = read(checked(registration['plan']))
    for item in read(checked(registration['inputs']))['files']:
        checked(item)
    for item in master['sources'] + master['runtime_sources']:
        checked(item)
    for name, version in master['versions'].items():
        if metadata.version(name) != version:
            raise RuntimeError(f'Runtime changed: {name}')
    if master['max_total_new_gradients'] != 160 or len(master['tasks']) != 4:
        raise RuntimeError('Unexpected diagnostic budget')
    if time.time() >= read(checked(master['campaign']))['deadline_epoch']:
        raise RuntimeError('Campaign compute deadline reached')
    return master


def prepare():
    from ase import Atoms
    from sella import Constraints
    import psi4
    receipt_path = ART / 'cpd-anti-shape-inputs-v2-r2/receipt.json'
    receipt = read(receipt_path)
    points_path = checked(receipt['points'])
    points = {p['case_id']: p for p in read(points_path)}
    pilot_path = ART / 'cpd-anti-sella-fresh-v1/plan.json'
    pilot = read(pilot_path)
    for item in pilot['runtime_sources']:
        checked(item)
    for name, version in pilot['versions'].items():
        if metadata.version(name) != version:
            raise RuntimeError(f'Runtime changed: {name}')
    assert psi4.__version__ == pilot['psi4_version']
    assert pilot['optimizer']['order'] == 0 and pilot['optimizer']['internal']
    ROOT.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__), ROOT / 'worker.py')
    sources = [source(p) for p in [receipt_path, points_path, pilot_path,
        REPO/'experiments/cpd_anti_additive/sella_pilot.py',
        REPO/'experiments/cpd_anti_additive/validation_gate.py',
        REPO/'backend/parameterization/photoproduct_qm.py',
        ART/'cpd-anti-shape-gate-refinement-v1/assessment.json',
        ART/'cpd-anti-shape-state-v2-r2/conformational_rounds.json',
        ART/'cpd-anti-preliminary-v2/conformational_candidate_lock.json'] if p.exists()]
    tasks = []; preflights = []
    specifications = [
        ('plus30-qm-reference', 'endpoint-1-+30', None),
        ('plus30-mm-trial1', 'endpoint-1-+30', ART/'cpd-anti-shape-gate-refinement-v1/model-001'),
        ('plus30-mm-trial7', 'endpoint-1-+30', ART/'cpd-anti-shape-gate-refinement-v1/model-007'),
        ('minus22p5-mm-model61', 'endpoint-1--22.5-prospective-r1', ART/'cpd-anti-shape-fit-recovery-v1/model-061'),
    ]
    for label, case_id, model in specifications:
        point = points[case_id]
        graph = read(checked(point['record']['model_graph']))
        assert [a['key'] for a in graph['atoms']] == point['atom_map']
        assert [a['element'] for a in graph['atoms']] == point['elements']
        assert graph['formal_charge'] == 0
        assert {tuple(sorted(b['atoms'])) for b in graph['bonds'] if b['atoms'][0].split(':')[0] != b['atoms'][1].split(':')[0]} == {('1:C5','2:C6'),('1:C6','2:C5')}
        x = np.array(point['geometry_bohr'])
        seeds = [source(points_path)]
        if model is not None:
            assessment = read(model/'assessment.json')
            result = next(r for r in assessment['results'] if r['case_id'] == case_id)
            assert result['independent_stationarity_and_chemistry_passed'] and result['constraint_applied']
            seeds = [source(model/'assessment.json'), source(model/case_id/'final_A.txt')]
            x = np.loadtxt(checked(seeds[1])) / BOHR
        # The old prospective point inherited parent source fields. Resolve the
        # actual Sella result directly instead of propagating those fields.
        if 'prospective' in case_id:
            actual = ART/'cpd-anti-prospective-qm-v2-r1'/case_id
            last = read(actual/'progress.json')['evaluations'][-1]['result']
            native = read(checked(last))
            assert np.array_equal(np.load(checked(native['geometry'])), point['geometry_bohr'])
            assert native['energy'] == point['qm_energy_hartree']
            reference_sources = [last, native['geometry'], native['native'], source(actual/'plan.json')]
        else:
            reference_sources = [point['geometry_source'], point['qm_source']]
        folder = ROOT/label; folder.mkdir()
        plan = dict(record=dict(point['record'], label=label), elements=point['elements'],
            atom_map=point['atom_map'], geometry_bohr=x.tolist(), method=pilot['method'],
            options=pilot['options'], psi4_version=pilot['psi4_version'], optimizer=pilot['optimizer'],
            limits=pilot['limits'], max_new_gradients=40, max_continuations=0,
            wall_seconds=21600, threads=4, memory_gib=6,
            scratch_dir=str(Path('/home/jojo/.cache/nadoc-qm')/ROOT.name/label),
            exposed_case_id=case_id, seed_sources=seeds, reference_sources=reference_sources,
            reference_geometry_bohr=point['geometry_bohr'],
            reference_qm_energy_hartree=point['qm_energy_hartree'],
            constrained=True, scope='Exposed competing-conformer diagnostic; not prospective validation',
            minimum_certified=False, simulation_ready=False)
        audit = geometry_audit(x, dict(plan, geometry_bohr=point['geometry_bohr']), graph)
        assert audit['chemistry_passed'] and audit['constraint_passed']
        atoms = Atoms(plan['elements'], positions=x*BOHR)
        constraint = Constraints(atoms); constraint.fix_dihedral(tuple(plan['record']['torsion_indices']))
        angle = float(np.degrees(constraint.calc()[0]))
        assert abs((angle-plan['record']['target_degrees']+180)%360-180) < plan['limits']['torsion_error_deg']
        normal = constraint.jacobian()[0].reshape(x.shape)
        gradient = np.linspace(-1e-3,1e-3,x.size).reshape(x.shape)
        projected = gradient-normal*np.sum(normal*gradient)/np.sum(normal**2)
        independent = projected_metrics(x, gradient, plan['record']['torsion_indices'])
        assert abs(np.linalg.norm(projected,axis=1).max()-independent['max_projected_atom_gradient']) < 1e-10
        save(folder/'plan.json', plan); save(folder/'starting_audit.json', audit)
        (folder/'starting.xyz').write_text(xyz_text(plan['elements'],x,'Diagnostic seed, not a minimum'))
        tasks.append(dict(case_id=label, folder=str(folder.resolve()), plan=source(folder/'plan.json')))
        preflights.append(dict(case_id=label, chemistry_passed=True, constraint_passed=True,
            atom_mapping_verified=True, analytic_projection_matches=True, new_qm_evaluations=0))
        sources += seeds + reference_sources + [point['record']['model_graph'], point['record']['scan_plan']]
    master = dict(at=now(), stage='competing-conformation-diagnostic-v3', tasks=tasks,
        campaign=source(CAMPAIGN/'contract.json'), sources=sources,
        runtime_sources=pilot['runtime_sources'], versions=pilot['versions'],
        runtime_python=sys.executable, psi4_version=psi4.__version__,
        max_total_new_gradients=160, max_new_gradients_per_case=40,
        hard_seconds=43200, per_case_hard_seconds=21600, expected_seconds=14400,
        max_continuations=0, workers_at_once=1, threads=4, memory_gib=6, service_memory_gib=10,
        hypothesis='Compare stationary QM basins reached from the old QM and competing MM shapes at the same constrained torsion, electronic model, atom mapping and stereo.',
        interpretation='Use energy, projected gradients and aligned geometry. Different stationary basins require targeted local stability evidence before choosing reference changes. Same basin supports retained correspondence target. No automatic fit or data replacement.',
        preserved='Old fit contracts, candidates, locks, failures and all23 exposed points remain unchanged.',
        simulation_ready=False, minimum_certified=False)
    save(ROOT/'plan.json', master)
    save(ROOT/'preflight.json', dict(passed=True,cases=preflights,new_qm_evaluations=0))
    save(ROOT/'inputs_lock.json',dict(files=[source(p) for p in sorted(ROOT.rglob('*')) if p.is_file()]))
    save(ROOT/'registration.json',dict(at=now(),plan=source(ROOT/'plan.json'),inputs=source(ROOT/'inputs_lock.json')))
    validate()
    print(json.dumps(dict(root=str(ROOT),preflight_passed=True,cases=4,new_qm_evaluations=0)))


def run():
    master = validate(); start = time.monotonic(); records = []
    with (ROOT/'started.json').open('x') as f:
        json.dump(dict(at=now(),registration=source(ROOT/'registration.json')),f)
    for task in master['tasks']:
        folder = Path(task['folder'])
        remaining = min(master['hard_seconds']-(time.monotonic()-start),
            read(checked(master['campaign']))['deadline_epoch']-time.time())
        if remaining <= 0:
            records.append(dict(case=task['case_id'],passed=False,error='Total compute cap reached'))
            continue
        try:
            with (folder/'worker.log').open('w') as log:
                p = subprocess.run([sys.executable,str(ROOT/'worker.py'),'case',str(folder)],
                    cwd=REPO, stdout=log, stderr=subprocess.STDOUT,
                    timeout=min(master['per_case_hard_seconds'],remaining))
            assessment = read(folder/'assessment.json') if (folder/'assessment.json').exists() else {}
            audit = read(folder/'independent_review.json') if (folder/'independent_review.json').exists() else {}
            passed = bool(p.returncode == 0 and assessment.get('joint_optimizer_converged') and audit.get('independent_stationarity_passed'))
            row = dict(case=task['case_id'],returncode=p.returncode,passed=passed,
                assessment=source(folder/'assessment.json') if assessment else None,
                independent_review=source(folder/'independent_review.json') if audit else None)
        except subprocess.TimeoutExpired:
            row = dict(case=task['case_id'],passed=False,error='Frozen wall-time cap reached; partial outputs retained')
            save(folder/'timeout.json',dict(at=now(),**row))
        records.append(row);save(ROOT/'progress.json',dict(at=now(),records=records,total=4))
    passed = len(records)==4 and all(r['passed'] for r in records)
    save(ROOT/'assessment.json',dict(at=now(),records=records,
        all_four_constrained_stationarity_passed=passed,elapsed_seconds=time.monotonic()-start,
        requires_native_evidence_and_basin_review=True,minimum_certified=False,
        preliminary_research_qualified=False,simulation_ready=False))
    if not passed:
        raise RuntimeError('Diagnostic acquisition incomplete/failed; preserve results and review before further work')


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
                raise RuntimeError('Diagnostic gradient/time cap reached; no continuation')
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
            (folder/'last_evaluated.xyz').write_text(xyz_text(plan['elements'],x,'Evaluated diagnostic target; not a certified minimum'))
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
            (folder/'optimized.xyz').write_text(xyz_text(plan['elements'],atoms.positions/BOHR,'Diagnostic constrained stationary candidate; no Hessian certification'))
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

if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('action',choices=['prepare','run','case','validate'])
    parser.add_argument('folder',nargs='?',type=Path)
    args=parser.parse_args()
    if args.action == 'case':
        run_case(args.folder.resolve())
    else:
        globals()[args.action]()
