"""Review a planning-only Psi4 Hessian preview and propose bounded local batches."""
from pathlib import Path
import importlib.util
import sys

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import checked, now, pin, read, save


def review(root):
    target=root/'hessian_stage2_proposal.json'
    if target.exists():
        raise FileExistsError('Preserve the existing proposal')
    audit=read(root/'stage1_completion_audit.json')
    if not audit['passed']:
        raise ValueError('Stage-one audit must pass first')
    plan=read(checked(audit['plan']))
    preview=root/'hessian-preview-v1'
    fd=read(preview/'preview.json')
    if fd['task_count'] != 211 or fd['authorized'] or fd['new_qm_evaluations'] != 0:
        raise ValueError('Unexpected preview scope')
    spec=importlib.util.spec_from_file_location('frozen',checked(audit['frozen_worker']))
    worker=importlib.util.module_from_spec(spec);spec.loader.exec_module(worker)
    x=np.load(checked(audit['final_binary_geometry']))
    first=read(checked(fd['tasks'][0]['input']))
    reference=np.array(first['molecule']['geometry']).reshape(-1,3)
    difference=float(np.max(abs(reference-x)))
    if difference>=1e-12:
        raise ValueError('Reference is not the audited stationary geometry')
    baseline={k:v for k,v in first['specification']['keywords'].items() if k!='function_kwargs'}
    coordinates=[]
    for i,task in enumerate(fd['tasks']):
        data=read(checked(task['input']));mol=data['molecule']
        q=np.array(mol['geometry']).reshape(-1,3)
        if (mol['symbols']!=plan['elements'] or mol['molecular_charge']!=0 or
                mol['molecular_multiplicity']!=1 or
                data['specification']['model']!={'method':'mp2','basis':'6-31g(d)'}):
            raise ValueError('Task identity or QM model changed')
        keywords=data['specification']['keywords']
        if {k:v for k,v in keywords.items() if k!='function_kwargs'} != baseline:
            raise ValueError('Physical QM options changed')
        if keywords['function_kwargs'] != ({} if i==0 else {'write_orbitals':False}):
            raise ValueError('Unexpected task function controls')
        if not worker.geometry_audit(q,plan)['passed']:
            raise ValueError('Displaced structure fails corrected identity')
        coordinates.append(q)
    midpoint_error=0.
    for i in range(1,len(coordinates),2):
        if fd['tasks'][i]['label'].split(':')[0]!=fd['tasks'][i+1]['label'].split(':')[0]:
            raise ValueError('Displacement pairing changed')
        midpoint_error=max(midpoint_error,float(np.max(abs(.5*(coordinates[i]+coordinates[i+1])-reference))))
    if midpoint_error>=1e-12:
        raise ValueError('Paired displacements do not share the exact reference')
    mean=audit['gradient_seconds']['mean'];slow=audit['gradient_seconds']['maximum']
    schedule=dict(schema='nadoc.corrected-core-hessian-approval-plan.v1',at=now(),
        status='proposed_for_user_review',execution_authorized=False,gate_effect='none',
        product_id='tt-cpd-cis-anti-i',
        purpose='Determine whether the corrected stationary core is a local harmonic minimum at the pinned MP2 method.',
        source_stationarity_audit=pin(root/'stage1_completion_audit.json'),
        stationary_geometry=audit['final_binary_geometry'],preview=pin(preview/'preview.json'),
        preview_reviewer=pin(Path(__file__)),source_optimizer_plan=audit['plan'],
        task_count=211,reference_tasks=1,displaced_gradient_pairs=105,
        geometry_preflight=dict(reference_max_difference_bohr=difference,
             all_211_identities_passed=True,paired_midpoint_max_error_bohr=midpoint_error),
        option_preflight='All physical keywords identical; Psi4 disables orbital output for displaced tasks only.',
        preserved_preflight_failure=pin(preview/'validation_attempt_1.json'),
        finite_difference=fd['finite_difference'],
        method='MP2/6-31G(d), density fitted, frozen core, neutral singlet; same Psi4 1.11, basis data, SCF E/D 1e-12 and response 1e-10 as optimization.',
        total_expected_gradient_hours=211*mean/3600,
        conservative_expected_hours=211*slow*1.5/3600,
        total_reserved_wall_hours=6,concurrency=1,threads_per_job=4,
        psi4_memory_GiB=4,service_memory_max_GiB=8,service_swap_max_bytes=0,
        available_memory_admission_GiB=12,
        scratch='Existing per-task Archive directories established before Psi4 import; all native logs/checkpoints there.',
        batches=[dict(id='batch-1',task_indices=list(range(105)),task_count=105,
                  description='Reference plus 52 complete +/- displacement pairs',
                  expected_gradient_hours=105*mean/3600,wall_cap_hours=3),
                 dict(id='batch-2',task_indices=list(range(105,211)),task_count=106,
                  description='53 remaining complete +/- displacement pairs',
                  expected_gradient_hours=106*mean/3600,wall_cap_hours=3)],
        audit_before_continuation=[
            'Verify native convergence and input/output hashes for every completed task.',
            'Recheck corrected identity, atom order, fixed geometry and source-coordinate provenance.',
            'Compare reference energy/gradient with the optimized result using declared numerical tolerances before accepting the displaced series.',
            'Review actual runtime, peak memory, scratch, necessity and whether the single-worker method remains appropriate.',
            'Admit batch two only after batch one passes; do not enlarge caps or retry failed tasks automatically.'],
        implementation_before_launch=[
            'Pin a bounded single-worker runner; do not use old 18-GiB or multiworker launchers.',
            'Reconstruct the exact finite-difference plan and byte-compare task inputs before executing or assembling.',
            'Verify checkpoint/timeout behavior, existing scratch paths, resources and a fresh completion watcher.'],
        restart='Completed immutable gradient tasks are reusable only with identical input/method hashes. Preserve interrupted task directories; failed tasks are incomplete.',
        assembly='After all tasks pass, assemble using the exact Psi4 plan. Audit Hessian symmetry, mass weighting, rigid-body modes, the expected 102 internal modes and imaginary/numerically ambiguous modes. Do not clip negative modes or equate assembly with a pass.',
        assembly_budget='Include assembly/audit grace inside batch two; stop with saved tasks if insufficient time remains.',
        claim_if_passed='Local harmonic minimum of this capped core at the stated QM method; no global-minimum, DNA-boundary, parameter-fit or production-readiness claim.',
        scope_excluded=['Reference data/fitting','DNA boundary QM','MD','Automatic registry approval','Cloud spending'],
        minimum_certified=False,new_qm_evaluations_in_preview=0,
        authorization_note='Only stage one was approved. This Hessian allocation needs approval; no new computation has been queued.')
    if schedule['conservative_expected_hours']>=6:
        raise ValueError('Conservative estimate does not fit reservation')
    save(target,schedule)
    save(REPO/'docs/audits/cpd_corrected_cis_anti_i_stage1_completion_20261010.json',
         dict(schema='nadoc.corrected-core-stage1-handoff.v1',at=now(),
              status='stage1_passed_stationary_candidate',gate_effect='none',
              completion_audit=pin(root/'stage1_completion_audit.json'),next_stage_proposal=pin(target),
              native_new_gradients=30,optimizer_service_seconds=audit['optimizer_service_seconds'],
              final_metrics=audit['final_metrics'],minimum_certified=False,later_compute_authorized=False))
    return schedule


if __name__=='__main__':
    result=review(Path(sys.argv[1]).resolve())
    print({k:result[k] for k in ['task_count','geometry_preflight','total_expected_gradient_hours',
                                'conservative_expected_hours','total_reserved_wall_hours']})
