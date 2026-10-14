"""Prepare a matched-angle conformational control after the valid minus15 scan."""
from pathlib import Path
import importlib.util
import shutil
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read, save, pin, checked, now, BOHR, xyz
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion, wrapped, rotate_sugar
from experiments.cpd_anti_additive.endpoint_scan_constraints import make_scan_constraints
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint


def prepare():
    from ase import Atoms
    campaign = (REPO / '.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    prior = campaign / 'endpoint-1-glyco-minus15-v3'
    job = campaign / 'endpoint-1-glyco-branchzero-v1'
    audit = read(prior / 'completion_audit.json')
    if not all(audit[k] for k in ('passed', 'native_evidence_passed', 'scan_target_passed', 'constrained_stationary', 'optimizer_converged')):
        raise ValueError('No valid converged minus15 response')
    old = read(checked(audit['plan']))
    original_design = read(checked(old['scan_design']))
    result = read(checked(audit['last_accepted_result']))
    reference = read(checked(original_design['reference_result']))
    model = read(checked(old['model']))
    graph = read(checked(model['graph']))
    keys = model['atom_keys']; indices = old['constraint']['indices']
    x = np.load(checked(result['geometry']))
    ref_x = np.load(checked(reference['geometry']))
    target = torsion(ref_x, indices)
    if abs(wrapped(target-original_design['reference_torsion_degrees'])) > 1e-8:
        raise ValueError('Original reference target changed')

    # Record the actual converged conformation before acquiring this control.
    definitions = read(campaign / 'endpoint-1-glyco-minus15-v1/conformational_progress_review.json')['torsion_definitions']
    rows = []
    ref_angles = {name: torsion(ref_x, [keys.index(k) for k in atoms]) for name, atoms in definitions.items()}
    for record in audit['records']:
        coords = np.load(checked(record['geometry']))
        angles = {name: torsion(coords, [keys.index(k) for k in atoms]) for name, atoms in definitions.items()}
        rows.append(dict(result=record['source'], projected=record['scan_metrics'],
             energy_relative_to_original_reference_kcal_mol=627.509474*(record['energy_hartree']-reference['energy_hartree']),
             torsion_degrees=angles,
             torsion_change_from_reference_degrees={name: wrapped(value-ref_angles[name]) for name, value in angles.items()}))
    review_path = prior / 'converged_branch_review.json'
    if review_path.exists():
        raise FileExistsError(review_path)
    save(review_path, dict(at=now(), source=pin(Path(__file__)), completion_audit=pin(prior / 'completion_audit.json'),
         original_reference=original_design['reference_result'], torsion_definitions=definitions,
         original_reference_torsion_degrees=ref_angles, records=rows,
         constrained_stationary=True, unconstrained_stationary=audit['stationary'], minimum_certified=False,
         max_scan_angle_error_degrees=max(v['scan_metrics']['torsion_error_degrees'] for v in audit['records']),
         decision='Stop minus15 relaxation. Compare the relaxed conformation at the original zero-offset angle before admitting a conformer-specific torsion profile.',
         interpretation='Lower constrained energy accompanies cap/sugar rearrangement. It neither proves a distinct minimum nor isolates glycosidic torsion energy.',
         next_control='Rigidly rotate only the sugar fragment to the original reference angle, then relax all other coordinates with that angle fixed. This is a matched-angle diagnostic, not an unconstrained release.',
         fit_target_accepted=False, simulation_ready=False))

    job.mkdir(exist_ok=False); (job / 'tmp').mkdir()
    shutil.copy2(Path(__file__), job / 'preparation_source.py')
    y, moving = rotate_sugar(x, [v['indices'] for v in graph['bonds']], indices, wrapped(target-torsion(x, indices)))
    identity = audit_endpoint(y, model)
    if len(moving) != 17 or not identity['passed']:
        raise ValueError('Matched-angle seed identity failed')
    np.save(job / 'starting_geometry_bohr.npy', y)
    (job / 'starting.xyz').write_text(xyz(model['elements'], y, 'Matched original-angle branch control seed; not optimized'))
    constraint = {**old['constraint'], 'target_degrees': target, 'offset_degrees': 0}
    _, config = make_scan_constraints(Atoms(model['elements'], positions=y*BOHR), constraint)
    preserved = {name: wrapped(torsion(y, [keys.index(k) for k in atoms])-torsion(x, [keys.index(k) for k in atoms])) for name, atoms in definitions.items()}
    if max(abs(v) for v in preserved.values()) > 1e-8:
        raise ValueError('Seed rotation changed internal conformer torsions')
    save(job / 'seed_audit.json', dict(at=now(), passed=True, identity=identity,
         moving_indices=moving, configuration=config, internal_torsion_changes_degrees=preserved,
         bond_lengths_preserved=True, source_geometry=result['geometry'], new_qm_evaluations=0))
    task = dict(label='branchzero', partition='development_diagnostic', role='matched_angle_control',
                geometry=pin(job / 'starting_geometry_bohr.npy'), constraint=constraint,
                seed_audit=pin(job / 'seed_audit.json'), seed_passed=True, fit_target_accepted=False)
    save(job / 'design.json', dict(at=now(), schema='nadoc.corrected-anti-matched-angle-control.v1',
         original_training_design=old['scan_design'], reference_design=old['reference_design'],
         original_reference=original_design['reference_result'], reference_torsion_degrees=target,
         source_constrained_result=audit['last_accepted_result'], source_audit=pin(prior / 'completion_audit.json'),
         branch_review=pin(review_path), model=old['model'], training_tasks=[task],
         acquisition_scope='One development diagnostic using the existing acquisition-task manifest. No automatic fitting acceptance or holdout membership change.',
         hypothesis='Determine whether a lower-energy cap/sugar conformation persists at exactly the original zero-reference angle. Compare energy and conformer geometry after constrained convergence.',
         decision_rule='If the relaxed control stays distinct and lower at the same angle, preserve both references and preregister any additional conformer-specific profile before acquiring more points. If it returns to the original conformation, retain that result and review path dependence. An unfinished control is not a fitting target.',
         constraints='Only original O4-prime/C1-prime/N1/C2 angle fixed; remaining coordinates relax. Geometry/stereo checks do not freeze sugar pucker or OH conformers.',
         original_reference_preserved=True, heldout_acquisition=False, heldout_offsets_degrees=[-22.5, 22.5],
         full_endpoint_minimum_certified=False, fit_target_accepted=False, simulation_ready=False,
         sources=[pin(job / 'preparation_source.py')]))
    shutil.copy2(REPO / 'experiments/cpd_anti_additive/corrected_endpoint_optimization.py', job / 'executed_source.py')
    plan = {**old, 'at': now(), 'worker': pin(job / 'executed_source.py'), 'seed_result': None,
            'starting_geometry': task['geometry'], 'scan_design': pin(job / 'design.json'),
            'scan_label': task['label'], 'constraint': constraint,
            'sources': [*old['sources'], pin(prior / 'completion_audit.json'), pin(review_path),
                        result['input'], result['geometry'], result['native'],
                        pin(job / 'design.json'), pin(job / 'seed_audit.json'), pin(job / 'preparation_source.py')],
            'unit': 'cpd-corrected-anti1-glyco-branchzero-v1',
            'expected_seconds': 20*audit['mean_gradient_seconds']+30,
            'seed_precision': 'Full-precision rotated converged conformer. No gradient reuse at changed coordinates.',
            'completion_semantics': 'Matched-angle conformational control only. Constrained stationarity does not certify a minimum or automatically accept fitting data.'}
    for key in ('continuation_audit', 'failure_recovery', 'conformational_review'):
        plan.pop(key, None)
    save(job / 'plan.json', plan)
    spec = importlib.util.spec_from_file_location('branchzero_worker', job / 'executed_source.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); module.context(job)
    save(job / 'preflight.json', dict(at=now(), passed=True, seed_audit=pin(job / 'seed_audit.json'),
         frozen_context_verified=True, configured_target_and_seed_verified=True, fresh_gradient_required=True,
         unchanged_worker=pin(prior / 'executed_source.py'), prior_regression_tests=pin(prior / 'test_receipt.json'),
         new_qm_evaluations=0))
    save(job / 'admission.json', dict(at=now(), proceed=True, plan=pin(job / 'plan.json'),
         preceding_audit=pin(prior / 'completion_audit.json'), branch_review=pin(review_path),
         preflight=pin(job / 'preflight.json'),
         necessity='Converged minus15 energy is lower than the original stationary reference while cap/sugar conformation changed. Same-angle comparison is needed before fitting.',
         alternatives='No more relaxation at converged minus15. A matched fixed-angle control directly compares conformations without changing the reference angle; an unconstrained release would also move that angle. Full endpoint Hessian is not required for this diagnostic.',
         expected_minutes=plan['expected_seconds']/60, maximum_minutes=90,
         one_native_job_at_a_time=True, cloud_spending_usd=0, minimum_certified=False, fit_target_accepted=False, simulation_ready=False))
    print(job)


if __name__ == '__main__':
    prepare()
