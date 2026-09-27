"""Versioned coordinate-method revision after the retained local inversion failure.

Two bounded phases: feasible chirality constraints, then their complete removal.
Only coordinates move. No fit, dynamics, Hessian certificate, or app integration.
"""

import json
from pathlib import Path
import sys
import time

import numpy as np
import openmm as mm
from openmm import unit as u
from scipy.optimize import minimize, NonlinearConstraint, BFGS

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.validation_gate import read, source, checked
from experiments.cpd_anti_additive.prepare_engine_v2 import save
from experiments.cpd_anti_additive.relax_dna_placement_v2 import load, stereo_records, stereo_check, contact_check
from experiments.cpd_anti_additive.chiral_constraints import SignedVolumes, volumes_and_derivatives

ART = REPO / '.development-artifacts'
ROOT = ART / 'cpd-anti-source-conditioning-v1b'
PRIOR = ART / 'cpd-anti-local-placement-v2'


def inputs():
    d = load()
    diagnosis = read(PRIOR / 'source_geometry_diagnosis.json')
    previous = read(PRIOR / 'assessment.json')
    assert previous['error'] == "RuntimeError('Accepted optimizer step inverted stereo')"
    d['seed'] = np.loadtxt(checked(previous['coordinates']))
    remote = {(d['psf'].atom_list[i].system, d['psf'].atom_list[i].residue.idx)
              for bond in diagnosis['retained_bond_violations'] if not bond['mobile_touching']
              for i in bond['indices']}
    assert remote == {('D002', 26), ('D002', 27)}
    d['mobile'] = np.array(sorted(set(d['mobile']) | {a.idx for a in d['psf'].atom_list
        if any(a.system == seg and abs(a.residue.idx-res) <= 2 for seg, res in remote)}), dtype=int)
    records = stereo_records(d)
    mobile = set(d['mobile'])
    selected = [(r['neighbors'], np.sign(r['reference_volume_A3']), r['label'])
                for r in records if mobile.intersection(r['neighbors'])]
    ns = [[] for _ in d['seed']]
    for a, b in d['bonds']:
        ns[a].append(b); ns[b].append(a)
    for key in ('1:C5', '1:C6', '2:C5', '2:C6'):
        indices = ns[d['ids'][key]]
        assert len(indices) == 4
        value, _ = volumes_and_derivatives(d['seed'][indices])
        selected.append((indices, np.sign(value), key))
    constraint = SignedVolumes(d['seed'], d['mobile'], [r[0] for r in selected], [r[1] for r in selected])
    assert min(constraint.values(d['seed'][d['mobile']].ravel())) > .1
    return d, records, selected, constraint


def prepare():
    d, records, selected, constraint = inputs()
    ROOT.mkdir(exist_ok=False)
    (ROOT / 'executed_source.py').write_text(Path(__file__).read_text())
    assert stereo_check(d, d['seed'], records)['passed']
    contacts = contact_check(d, d['seed'])
    # Existing close contacts are preparation targets. Require zero at the end,
    # not before the coordinate repair being tested. Piercing is a different defect.
    assert not contacts['all_piercing_count']
    save(ROOT / 'starting_contact_review.json', contacts)
    np.savetxt(ROOT / 'starting_A.txt', d['seed'])
    save(ROOT / 'chirality_constraints.json', [dict(indices=ns, sign=float(s), label=label)
        for ns, s, label in selected])
    paths = [PRIOR / n for n in ('plan.json', 'assessment.json', 'independent_review.json',
             'source_geometry_diagnosis.json', 'candidate_A.txt')]
    paths += [d['dna'] / n for n in ('assessment.json', 'independent_review.json', 'coverage_system.xml', 'anti.psf')]
    paths += [Path(__file__), Path(__file__).with_name('chiral_constraints.py'),
              Path(__file__).with_name('relax_dna_placement_v2.py'),
              ROOT / 'starting_A.txt', ROOT / 'chirality_constraints.json', ROOT / 'starting_contact_review.json',
              ART / 'cpd-anti-source-conditioning-v1/preparation_failure.json']
    save(ROOT / 'plan.json', dict(version='source-conditioning-v1b',
        scope='Isolated coordinate method revision; earlier local attempt remains failed',
        authorization='Resumed campaign and necessary diagnostic candidate construction; no normal app promotion',
        rationale='Prior inversion at nearly planar neighboring C3-prime and four defective fixed backbone bonds; simple local L-BFGS cannot address these',
        sources=[source(p) for p in paths], mobile_indices=d['mobile'].tolist(),
        mobile_atoms=len(d['mobile']), fixed_atoms=len(d['seed'])-len(d['mobile']),
        additional_residues='D002:24-29, determined by the four independently identified fixed bond defects',
        model='Unchanged complete CHARMM vacuum system; all types, charges, graph and coefficients fixed',
        seed='Retained last valid iterate of failed local placement; not called a minimum',
        preparation_correction='v1 performed no calculations: preflight incorrectly required zero starting contacts in a geometry-repair task. Retain its two diagnosed remote contacts as repair targets; final zero-contact criterion unchanged.',
        phases=[dict(name='chirality_constrained', method='trust-constr', maxiter=500,
                     signed_volume_lower_bound_A3=.1, keep_feasible=True, analytic_sparse_jacobian=True,
                     objective_scale=1000, initial_trust_radius_A=.1, initial_barrier_parameter=.001,
                     gtol_scaled=1e-5, xtol=1e-10, barrier_tol=1e-8),
                dict(name='constraints_removed', method='L-BFGS-B', maxiter=1500,
                     gtol_kcal_A=.001, ftol=1e-13, maxls=30)],
        phase_transition='First phase must converge, preserve geometry, and have no signed volume within 0.0001 A^3 of its artificial bound',
        preparation_bound_not_acceptance='0.1 A^3 is a local feasibility margin preventing zero-volume chirality crossing; it is not a force-field parameter or literature accuracy certificate',
        max_iterations_total=2000, max_energy_evaluations=6000, hard_seconds=7200,
        expected_seconds=1200, max_attempts=1, max_continuations=0, max_parameter_changes=0,
        prior_native_minimization_steps=2000, prior_full_DNA_callbacks=24,
        native_plus_full_DNA_iteration_budget_upper_bound=4024,
        inherited_integrity=dict(severe_clash_ratio=.5, bond_equilibrium_ratio=[.7, 1.3],
                                max_mobile_force_kcal_A=.01, original_base_displacement_screen_A=3.5),
        checkpoints_every=25, stop_on_stereo_inversion=True, stop_on_checkpoint_piercing=True,
        references=['https://docs.scipy.org/doc/scipy/reference/generated/scipy.optimize.NonlinearConstraint.html',
                    'https://docs.scipy.org/doc/scipy/reference/optimize.minimize-trustconstr.html'],
        reference_scope='Optimizer semantics only; numerical construction budgets/margins are local choices',
        numerical_version=__import__('scipy').__version__, threads=2, platform='CPU',
        dynamics_authorized_in_this_job=False, minimum_certification=False, simulation_ready=False))
    print(json.dumps(dict(prepared=True, mobile_atoms=len(d['mobile']), constraints=len(selected),
                         min_seed_oriented_volume_A3=float(min(constraint.values(d['seed'][d['mobile']].ravel())))), indent=2))


def run():
    d, records, selected, constraint = inputs()
    plan = read(ROOT / 'plan.json')
    for ref in plan['sources']:
        checked(ref)
    assert plan['mobile_indices'] == d['mobile'].tolist()
    with (ROOT / 'started.json').open('x') as handle:
        json.dump(dict(started_at=time.time(), plan=source(ROOT / 'plan.json')), handle)
    system = mm.XmlSerializer.deserialize((d['dna'] / 'coverage_system.xml').read_text())
    integrator = mm.VerletIntegrator(.001)
    ctx = mm.Context(system, integrator, mm.Platform.getPlatformByName('CPU'), {'Threads': '2'})
    mobile = d['mobile']; fixed = np.setdiff1d(np.arange(len(d['seed'])), mobile)
    last = d['seed'].copy()
    start = time.monotonic(); evaluations = 0; total_iterations = 0
    phase_name = ''; phase_iteration = 0; phases = []; error = None

    def evaluate(flat):
        nonlocal evaluations
        if evaluations >= plan['max_energy_evaluations'] or time.monotonic()-start >= plan['hard_seconds']:
            raise RuntimeError('Registered evaluation/time budget exhausted')
        evaluations += 1
        xyz = constraint.positions(flat)
        ctx.setPositions(xyz*u.angstrom)
        state = ctx.getState(getEnergy=True, getForces=True)
        energy = state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole)
        gradient = -np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))[mobile].ravel()
        assert np.isfinite(energy) and np.isfinite(gradient).all()
        return energy, gradient

    def callback(flat, state=None):
        nonlocal total_iterations, phase_iteration, last
        total_iterations += 1; phase_iteration += 1
        xyz = constraint.positions(flat)
        stereo = stereo_check(d, xyz, records)
        if not stereo['passed']:
            np.savetxt(ROOT / f'{phase_name}-failed_stereo_A.txt', xyz)
            save(ROOT / f'{phase_name}-failed_stereo.json', stereo)
            raise RuntimeError('Stereochemical inversion; method revision stops')
        last = xyz.copy()
        if phase_iteration % plan['checkpoints_every'] == 0:
            folder = ROOT / f'{phase_name}-{phase_iteration:05d}'
            folder.mkdir()
            np.savetxt(folder / 'coordinates_A.txt', xyz)
            contacts = contact_check(d, xyz)
            save(folder / 'review.json', dict(stereo=stereo, contacts=contacts,
                evaluations=evaluations, elapsed_seconds=time.monotonic()-start,
                minimum_oriented_volume_A3=float(min(constraint.values(flat)))))
            save(ROOT / 'progress.json', dict(phase=phase_name, phase_iteration=phase_iteration,
                total_iterations=total_iterations, evaluations=evaluations, checkpoint=str(folder.resolve())))
            if contacts['all_piercing_count']:
                raise RuntimeError('Checkpoint ring piercing; method revision stops')
        if time.monotonic()-start >= plan['hard_seconds']:
            raise RuntimeError('Registered time budget exhausted')
        return False

    with (ROOT / 'evaluations.jsonl').open('x') as log:
        def objective(flat):
            e, g = evaluate(flat)
            log.write(json.dumps(dict(phase=phase_name, evaluation=evaluations, energy_kcal=e,
                max_mobile_force_kcal_A=float(abs(g).max()), elapsed_seconds=time.monotonic()-start))+'\n')
            log.flush()
            scale = 1000 if phase_name == 'chirality_constrained' else 1
            return e/scale, g/scale
        try:
            for stage in plan['phases']:
                phase_name = stage['name']; phase_iteration = 0
                if phase_name == 'chirality_constrained':
                    nlc = NonlinearConstraint(constraint.values, .1, np.inf,
                        jac=constraint.jacobian, hess=BFGS(), keep_feasible=True)
                    result = minimize(objective, last[mobile].ravel(), jac=True, method='trust-constr',
                        hess=BFGS(), constraints=[nlc], callback=callback,
                        options=dict(maxiter=stage['maxiter'], gtol=stage['gtol_scaled'], xtol=stage['xtol'],
                            barrier_tol=stage['barrier_tol'], initial_tr_radius=.1,
                            initial_barrier_parameter=.001, initial_barrier_tolerance=.001, sparse_jacobian=True))
                else:
                    result = minimize(objective, last[mobile].ravel(), jac=True, method='L-BFGS-B', callback=callback,
                        options=dict(maxiter=stage['maxiter'], gtol=stage['gtol_kcal_A'],
                            ftol=stage['ftol'], maxls=stage['maxls']))
                last = constraint.positions(result.x)
                np.savetxt(ROOT / f'{phase_name}-final_A.txt', last)
                phase_record = dict(name=phase_name, optimizer_success=bool(result.success),
                    message=str(result.message), iterations=int(result.nit),
                    minimum_oriented_volume_A3=float(min(constraint.values(result.x))),
                    coordinates=source(ROOT / f'{phase_name}-final_A.txt'))
                phases.append(phase_record); save(ROOT / 'phases.json', phases)
                if not result.success:
                    raise RuntimeError(f'{phase_name} did not converge; no extension or next phase')
                contacts = contact_check(d, last)
                if not stereo_check(d, last, records)['passed'] or contacts['all_piercing_count'] or contacts['severe_clash_count']:
                    raise RuntimeError('Phase-terminal geometry integrity failure')
                if phase_name == 'chirality_constrained' and min(constraint.values(result.x)) <= .1001:
                    raise RuntimeError('Construction depends on active artificial chirality bound; no release phase')
        except Exception as exc:
            error = repr(exc)
    ctx.setPositions(last*u.angstrom)
    state = ctx.getState(getEnergy=True, getForces=True)
    force = np.array(state.getForces(asNumpy=True).value_in_unit(u.kilocalorie_per_mole/u.angstrom))
    energy = float(state.getPotentialEnergy().value_in_unit(u.kilocalorie_per_mole))
    np.savetxt(ROOT / 'candidate_A.txt', last); np.savetxt(ROOT / 'forces_kcal_A.txt', force)
    stereo = stereo_check(d, last, records); contacts = contact_check(d, last)
    bond_set = {tuple(sorted(b)) for b in d['bonds']}; bond_rows = []
    for f in system.getForces():
        if not isinstance(f, mm.HarmonicBondForce):
            continue
        for i in range(f.getNumBonds()):
            a, b, eq, k = f.getBondParameters(i)
            if tuple(sorted((a, b))) not in bond_set:
                continue
            length = float(np.linalg.norm(last[a]-last[b])); reference = eq.value_in_unit(u.angstrom)
            bond_rows.append(dict(indices=[a, b], atoms=[d['labels'][a], d['labels'][b]],
                                  length_A=length, equilibrium_A=reference, ratio=length/reference))
    assert len(bond_rows) == len(bond_set)
    bonds_pass = all(.7 < r['ratio'] < 1.3 for r in bond_rows)
    unchanged = np.array_equal(last[fixed], d['x'][fixed])
    released = len(phases) == 2 and phases[-1]['optimizer_success']
    integrity = bool(error is None and released and bonds_pass and unchanged and stereo['passed']
                     and not contacts['severe_clash_count'] and not contacts['all_piercing_count'])
    base = [i for key, i in d['ids'].items() if "'" not in key and key in d['names']]
    max_base = float(np.linalg.norm(last[base]-d['x'][base], axis=1).max())
    result = dict(error=error, phases=phases, total_iterations=total_iterations, energy_evaluations=evaluations,
        coordinate_integrity_passed=integrity, chirality_constraints_removed=released,
        max_mobile_force_kcal_A=float(abs(force[mobile]).max()), potential_energy_kcal=energy,
        mobile_stationary=bool(abs(force[mobile]).max() <= .01), fixed_atoms_exactly_unchanged=unchanged,
        stereo=stereo, contacts=contacts, whole_model_bond_integrity=bonds_pass, bonds=bond_rows,
        max_base_displacement_A=max_base, inherited_base_displacement_screen_passed=max_base <= 3.5,
        minimum_certified=False, full_DNA_NAMD_tested=False, simulation_ready=False,
        preliminary_research_qualified=False, dynamics_performed=False, elapsed_seconds=time.monotonic()-start,
        plan=source(ROOT / 'plan.json'), coordinates=source(ROOT / 'candidate_A.txt'))
    save(ROOT / 'assessment.json', result)
    print(json.dumps({k: result[k] for k in ('error', 'coordinate_integrity_passed', 'chirality_constraints_removed',
        'max_mobile_force_kcal_A', 'mobile_stationary', 'whole_model_bond_integrity')}, indent=2))
    if not integrity:
        raise RuntimeError('Source-conditioning method revision failed; no automatic continuation')


if __name__ == '__main__':
    if sys.argv[1:] == ['prepare']:
        prepare()
    elif sys.argv[1:] == ['run']:
        run()
    else:
        raise ValueError('Expected prepare or run')
