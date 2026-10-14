"""Freeze a provisional lower-conformer profile; prepare only its next QM point."""
from pathlib import Path
import importlib.util
import shutil
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import (
    BOHR, checked, metrics, now, pin, read, save, xyz,
)
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion, wrapped, rotate_sugar
from experiments.cpd_anti_additive.endpoint_scan_constraints import make_scan_constraints
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint


def prepare():
    from ase import Atoms

    campaign = (REPO / '.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    control = campaign / 'endpoint-1-glyco-branchzero-v1'
    minus = campaign / 'endpoint-1-glyco-minus15-v3'
    original = campaign / 'endpoint-1-optimization-v2'
    profile = campaign / 'glycosidic-branch-profile-v1'
    job = campaign / 'endpoint-1-glyco-branch-minus30-v1'
    review_path = control / 'matched_angle_review.json'
    if any(p.exists() for p in (profile, job, review_path)):
        raise FileExistsError('Preserve existing preparation and review')
    audit = read(control / 'completion_audit.json')
    minus_audit = read(minus / 'completion_audit.json')
    for value in (audit, minus_audit):
        if not all(value[k] for k in ('passed', 'native_evidence_passed', 'scan_target_passed',
                                     'constrained_stationary', 'optimizer_converged')):
            raise ValueError('Missing valid converged constrained response')
    old = read(checked(audit['plan']))
    minus_plan = read(checked(minus_audit['plan']))
    for key in ('options', 'model', 'elements', 'versions', 'psi4_version', 'optimizer'):
        if old[key] != minus_plan[key]:
            raise ValueError(f'Comparison methods differ: {key}')
    old_design = read(checked(old['scan_design']))
    original_audit = read(original / 'completion_audit.json')
    if not original_audit['passed'] or not original_audit['stationary']:
        raise ValueError('Original stationary reference lacks audit')
    original_plan = read(checked(original_audit['plan']))
    for key in ('options', 'model', 'elements', 'versions', 'psi4_version'):
        if old[key] != original_plan[key]:
            raise ValueError(f'Original comparison method differs: {key}')
    if old_design['original_reference'] != original_audit['last_accepted_result']:
        raise ValueError('Original reference identity changed')
    model = read(checked(old['model']))
    graph = read(checked(model['graph']))
    keys = model['atom_keys']
    indices = old['constraint']['indices']
    definitions = read(minus / 'converged_branch_review.json')['torsion_definitions']
    results = {}
    rows = {}
    for name, result_pin, audit_path in (
        ('original_zero', old_design['original_reference'], original / 'completion_audit.json'),
        ('branch_minus15', minus_audit['last_accepted_result'], minus / 'completion_audit.json'),
        ('branch_zero', audit['last_accepted_result'], control / 'completion_audit.json'),
    ):
        result = read(checked(result_pin))
        x = np.load(checked(result['geometry']))
        g = np.load(checked(result['gradient_binary']))
        if not np.array_equal(g, np.asarray(result['gradient_hartree_bohr'])):
            raise ValueError('Gradient binary differs from result')
        identity = audit_endpoint(x, model)
        if not identity['passed']:
            raise ValueError('Comparison identity failed')
        results[name] = result
        rows[name] = dict(result=result_pin, audit=pin(audit_path), geometry=result['geometry'],
            energy_hartree=result['energy_hartree'], glycosidic_degrees=torsion(x, indices),
            raw_gradient_metrics=metrics(g), identity=identity,
            conformer_torsions_degrees={name: torsion(x, [keys.index(k) for k in atoms])
                                       for name, atoms in definitions.items()})
    target = rows['original_zero']['glycosidic_degrees']
    if abs(wrapped(rows['branch_zero']['glycosidic_degrees'] - target)) > 1e-6:
        raise ValueError('Control and original reference angles differ')
    kcal = 627.509474
    comparisons = {}
    for left, right in [('branch_zero', 'original_zero'), ('branch_minus15', 'original_zero'),
                        ('branch_minus15', 'branch_zero')]:
        comparisons[f'{left}_minus_{right}'] = dict(
            energy_kcal_mol=kcal*(rows[left]['energy_hartree']-rows[right]['energy_hartree']),
            conformer_torsion_changes_degrees={name: wrapped(value-rows[right]['conformer_torsions_degrees'][name])
                for name, value in rows[left]['conformer_torsions_degrees'].items()})
    if comparisons['branch_zero_minus_original_zero']['energy_kcal_mol'] >= 0:
        raise ValueError('Reassess decision: matched control is not lower')
    save(review_path, dict(at=now(), source=pin(Path(__file__)), references=rows,
        torsion_definitions=definitions, comparisons=comparisons,
        control_projected_gradient=audit['last_gradient_metrics'],
        interpretation='A lower constrained conformation persists at the original angle, with different sugar/cap torsions. The earlier minus15-minus-original-zero energy mixes conformation and angle response.',
        decision='Stop the converged control. Freeze a separate provisional conformer profile at the original absolute angles; reuse exposed zero/minus15 data and acquire minus30 next from the nearest converged point.',
        family_status='Provisional path-connected conformations; basin closure and minimum identity are unproven.',
        full_endpoint_minimum_certified=False, fit_target_accepted=False, simulation_ready=False))

    profile.mkdir(); shutil.copy2(Path(__file__), profile / 'preparation_source.py')
    tasks = []
    for label, offset, source_name in [('minus30', -30, 'branch_minus15'),
                                        ('plus15', 15, 'branch_zero'), ('plus30', 30, 'branch_zero')]:
        folder = profile / label; folder.mkdir()
        source = results[source_name]
        x = np.load(checked(source['geometry']))
        absolute = wrapped(target + offset)
        y, moving = rotate_sugar(x, [v['indices'] for v in graph['bonds']], indices,
                                wrapped(absolute-torsion(x, indices)))
        identity = audit_endpoint(y, model)
        if len(moving) != 17 or not identity['passed']:
            raise ValueError('Profile seed chemistry failed')
        constraint = {**old['constraint'], 'target_degrees': absolute, 'offset_degrees': offset}
        _, config = make_scan_constraints(Atoms(model['elements'], positions=y*BOHR), constraint)
        changes = {name: wrapped(torsion(y, [keys.index(k) for k in atoms]) - torsion(x, [keys.index(k) for k in atoms]))
                   for name, atoms in definitions.items()}
        if max(abs(v) for v in changes.values()) > 1e-8:
            raise ValueError('Seed changed internal conformer torsions')
        np.save(folder / 'starting_geometry_bohr.npy', y)
        (folder / 'starting.xyz').write_text(xyz(model['elements'], y, 'Unoptimized branch-profile seed'))
        save(folder / 'seed_audit.json', dict(at=now(), passed=True, identity=identity,
            source_result=rows[source_name]['result'], configuration=config, moving_indices=moving,
            internal_torsion_changes_degrees=changes, bond_lengths_preserved=True, new_qm_evaluations=0))
        tasks.append(dict(label=label, partition='development_training', offset_degrees=offset,
            geometry=pin(folder / 'starting_geometry_bohr.npy'), constraint=constraint,
            source_result=rows[source_name]['result'], seed_audit=pin(folder / 'seed_audit.json'),
            seed_passed=True, fresh_gradient_required=True, fit_target_accepted=False))
    design = dict(at=now(), schema='nadoc.corrected-anti-conformer-profile.v1',
        original_reference_design=old['reference_design'], original_training_design=old_design['original_training_design'],
        original_reference=old_design['original_reference'], reference_torsion_degrees=target,
        profile_energy_reference=audit['last_accepted_result'], model=old['model'],
        branch_review=pin(review_path), training_offsets_degrees=[-30, -15, 0, 15, 30],
        existing_exposed_observations=[dict(offset_degrees=-15, **rows['branch_minus15']),
                                       dict(offset_degrees=0, **rows['branch_zero'])],
        training_tasks=tasks, acquisition_order=['minus30', 'plus15', 'plus30'],
        constraints='Only glycosidic angle is fixed; sugar/cap coordinates may relax. Preserve and review conformational changes rather than forcing a family label.',
        interpretation='Profile is provisionally anchored to the lower matched-angle conformation. Same absolute angle grid as original; no redefinition around an unobserved minimum.',
        existing_data_policy='Previously inspected zero and minus15 remain exposed development data, reused once; no independent sample or holdout relabeling.',
        original_family_policy='Preserve original zero and all original design/failures. Do not silently combine conformers into one fitted torsion profile or choose lowest energies without matched QM/MM geometries.',
        audit_policy='Audit native evidence, every angle, projected convergence, and cap/sugar/core torsions after each chunk. Review stalls, branch switching and necessity before further acquisition. Full conformer matching and any required closure checks precede fitting acceptance.',
        remaining_points_budget=dict(points=3, first_chunk_per_point_new_gradients=20,
            hard_seconds_per_chunk=5400, one_native_job_at_a_time=True,
            continuation='No automatic extension: progress, alternatives and resources require a new recorded audit.'),
        heldout_offsets_degrees=[-22.5, 22.5], heldout_acquisition=False,
        heldout_policy='No heldout coordinates, energies or gradients acquired before candidate parameters are hash-locked; retain same angle origin and intended family.',
        source=pin(profile / 'preparation_source.py'), full_endpoint_minimum_certified=False,
        fit_target_accepted=False, simulation_ready=False, cloud_spending_usd=0)
    save(profile / 'design.json', design)

    task = tasks[0]
    job.mkdir(); (job / 'tmp').mkdir()
    shutil.copy2(control / 'executed_source.py', job / 'executed_source.py')
    plan = {**old, 'at': now(), 'worker': pin(job / 'executed_source.py'), 'seed_result': None,
        'starting_geometry': task['geometry'], 'scan_design': pin(profile / 'design.json'),
        'scan_label': task['label'], 'constraint': task['constraint'],
        'unit': 'cpd-corrected-anti1-glyco-branch-minus30-v1',
        'sources': [*old['sources'], pin(control / 'completion_audit.json'), pin(review_path),
                    pin(profile / 'preparation_source.py'), pin(profile / 'design.json'),
                    *[t[k] for t in tasks for k in ('geometry', 'seed_audit')]],
        'expected_seconds': 20*audit['mean_gradient_seconds']+30,
        'completion_semantics': 'Constrained response in a provisional conformer profile. Service completion is not convergence, basin closure, fitting acceptance or minimum certification.'}
    save(job / 'plan.json', plan)
    spec = importlib.util.spec_from_file_location('branch_profile_worker', job / 'executed_source.py')
    worker = importlib.util.module_from_spec(spec); spec.loader.exec_module(worker); worker.context(job)
    if pin(job / 'executed_source.py')['sha256'] != pin(control / 'executed_source.py')['sha256']:
        raise ValueError('Unexpected native worker change')
    checked(read(control / 'test_receipt.json')['reused_regression_receipt'])
    save(job / 'preflight.json', dict(at=now(), passed=True, seed_audit=task['seed_audit'],
        frozen_context_verified=True, configured_target_and_seed_verified=True,
        fresh_gradient_required=True, unchanged_worker=pin(control / 'executed_source.py'),
        prior_regression_tests=pin(control / 'test_receipt.json'), new_qm_evaluations=0))
    save(job / 'admission.json', dict(at=now(), proceed=True, plan=pin(job / 'plan.json'),
        preceding_audit=pin(control / 'completion_audit.json'), branch_review=pin(review_path),
        preflight=pin(job / 'preflight.json'),
        necessity='Only zero and minus15 are available for the lower conformer. Minus30 extends the downhill side of the preregistered profile with a 15-degree seed rotation from the closest converged point.',
        alternatives='Reuse both converged points. No duplicate relaxation, endpoint exchange or full endpoint Hessian is needed to acquire this constrained response. No unconstrained release is needed to compare fixed-angle energies.',
        expected_minutes=plan['expected_seconds']/60, maximum_minutes=90,
        one_native_job_at_a_time=True, cloud_spending_usd=0, minimum_certified=False,
        fit_target_accepted=False, simulation_ready=False))
    print(job)


if __name__ == '__main__':
    prepare()
