"""Prepare one reviewed successor from the frozen conformer-profile inventory."""
from pathlib import Path
import argparse
import importlib.util
import shutil
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import BOHR, checked, metrics, now, pin, read, save
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion, wrapped
from experiments.cpd_anti_additive.endpoint_scan_constraints import make_scan_constraints
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint


def prepare(previous, label):
    from ase import Atoms

    archive = Path('/media/jojo/Archive')
    campaign = (REPO / '.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    previous = previous.resolve()
    if previous.parent != campaign:
        raise ValueError('Predecessor outside current campaign')
    if not archive.is_mount() or campaign.stat().st_dev != archive.stat().st_dev or archive.stat().st_dev == Path('/').stat().st_dev:
        raise RuntimeError('Mounted Archive required before any bulk preparation')
    audit = read(previous / 'completion_audit.json')
    if not all(audit[k] for k in ('passed', 'native_evidence_passed', 'scan_target_passed',
                                 'constrained_stationary', 'optimizer_converged')):
        raise ValueError('Predecessor needs audit/convergence review, not advancement')
    old = read(checked(audit['plan']))
    design = read(checked(old['scan_design']))
    order = design['acquisition_order']
    index = order.index(label)
    if index == 0 or order[index-1] != old['scan_label']:
        raise ValueError('Successor is not next in the preregistered order')
    task = next(t for t in design['training_tasks'] if t['label'] == label)
    job = campaign / f'endpoint-1-glyco-branch-{label}-v1'
    review_path = previous / 'profile_point_review.json'
    if job.exists() or review_path.exists():
        raise FileExistsError('Preserve existing preparation and review')
    model = read(checked(old['model']))
    keys = model['atom_keys']
    definitions = read(checked(design['branch_review']))['torsion_definitions']
    reference = read(checked(design['profile_energy_reference']))
    predecessor_task = next(t for t in design['training_tasks'] if t['label'] == old['scan_label'])
    source = read(checked(predecessor_task['source_result']))
    source_x = np.load(checked(source['geometry']))
    source_angles = {n: torsion(source_x, [keys.index(k) for k in atoms]) for n, atoms in definitions.items()}
    rows = []
    for record in audit['records']:
        x = np.load(checked(record['geometry']))
        angles = {n: torsion(x, [keys.index(k) for k in atoms]) for n, atoms in definitions.items()}
        rows.append(dict(result=record['source'], energy_hartree=record['energy_hartree'],
            relative_to_branch_zero_kcal_mol=627.509474*(record['energy_hartree']-reference['energy_hartree']),
            projected_metrics=record['scan_metrics'], raw_metrics=record['gradient_metrics'],
            torsions_degrees=angles,
            torsion_changes_from_source_degrees={n: wrapped(v-source_angles[n]) for n,v in angles.items()}))
    last = read(checked(audit['last_accepted_result']))
    final = next(row for row in rows if row['result'] == audit['last_accepted_result'])
    job.mkdir(); (job/'tmp').mkdir()
    shutil.copy2(Path(__file__), job/'preparation_source.py')
    save(review_path, dict(at=now(), source=pin(job/'preparation_source.py'),
        audit=pin(previous/'completion_audit.json'), design=old['scan_design'],
        constraint=old['constraint'], source_conformer=predecessor_task['source_result'],
        torsion_definitions=definitions, source_torsions_degrees=source_angles, records=rows,
        final_accepted=final,
        final_energy_relative_to_source_kcal_mol=627.509474*(last['energy_hartree']-source['energy_hartree']),
        largest_adjacent_torsion_changes_degrees={n:max(abs(wrapped(b['torsions_degrees'][n]-a['torsions_degrees'][n]))
            for a,b in zip(rows,rows[1:])) for n in definitions},
        maximum_evaluated_angle_error_degrees=max(v['scan_metrics']['torsion_error_degrees'] for v in audit['records']),
        decision=f'Stop this converged target; prepare only the preregistered {label} point. Review recorded conformation changes before launch. No automatic chain or repeated relaxation.',
        interpretation='Constrained convergence and continuous optimization history support acquisition of the next profile point. They do not certify a full minimum, basin closure, global ordering or fitting acceptance.',
        minimum_certified=False, fit_target_accepted=False, simulation_ready=False))
    x = np.load(checked(task['geometry']))
    identity = audit_endpoint(x, model)
    if not task['seed_passed'] or not read(checked(task['seed_audit']))['passed'] or not identity['passed']:
        raise ValueError('Frozen next-point seed failed identity audit')
    _, configuration = make_scan_constraints(Atoms(model['elements'],positions=x*BOHR),task['constraint'])
    shutil.copy2(previous/'executed_source.py', job/'executed_source.py')
    plan = {**old, 'at':now(), 'worker':pin(job/'executed_source.py'),
        'seed_result':None, 'starting_geometry':task['geometry'], 'scan_label':label,
        'constraint':task['constraint'], 'unit':f'cpd-corrected-anti1-glyco-branch-{label}-v1',
        'expected_seconds':20*audit['mean_gradient_seconds']+30,
        'sources':[*old['sources'],pin(previous/'completion_audit.json'),pin(review_path),
                   pin(job/'preparation_source.py'),audit['last_accepted_result'],
                   last['native'],last['geometry'],last['input']]}
    for key in ('continuation_audit','failure_recovery','conformational_review'):
        plan.pop(key,None)
    save(job/'plan.json',plan)
    spec = importlib.util.spec_from_file_location('next_profile_point',job/'executed_source.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module); module.context(job)
    if pin(job/'executed_source.py')['sha256'] != pin(previous/'executed_source.py')['sha256']:
        raise ValueError('Scientific worker changed')
    save(job/'preflight.json',dict(at=now(),passed=True,identity=identity,configuration=configuration,
        seed_audit=task['seed_audit'],frozen_context_verified=True,fresh_gradient_required=True,
        prior_regression_tests=pin(previous/'test_receipt.json'),new_qm_evaluations=0,
        archive_mount=str(archive),archive_device=archive.stat().st_dev,
        output_directory=str(job),scratch_directory=str(job/'tmp'),system_disk_fallback=False))
    save(job/'admission.json',dict(at=now(),proceed=True,plan=pin(job/'plan.json'),
        preceding_audit=pin(previous/'completion_audit.json'),profile_review=pin(review_path),
        preflight=pin(job/'preflight.json'),
        necessity=f'Acquire missing {label} side of the frozen constrained profile; completed targets are reused.',
        alternatives='No further relaxation at converged targets, duplicate endpoint mapping, full endpoint Hessian or new unconstrained reference is required for this fixed-angle acquisition.',
        expected_minutes=plan['expected_seconds']/60,maximum_minutes=90,
        one_native_job_at_a_time=True,cloud_spending_usd=0,minimum_certified=False,
        fit_target_accepted=False,simulation_ready=False))
    print(job)


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('previous',type=Path)
    parser.add_argument('label',choices=('plus15','plus30'))
    args=parser.parse_args();prepare(args.previous,args.label)
