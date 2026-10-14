"""Repair the angle-unit failure and restart from the last valid v1 scan state."""
from pathlib import Path
import importlib.util
import shutil
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read, save, pin, checked, now
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint
from experiments.cpd_anti_additive.endpoint_scan_geometry import constraint_metrics


def prepare():
    campaign = (REPO / '.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    previous = campaign / 'endpoint-1-glyco-minus15-v1'
    root = campaign / 'endpoint-1-glyco-minus15-v3'
    failed = campaign / 'endpoint-1-glyco-minus15-v2'
    failure = read(failed / 'scientific_failure.json')
    if failure['scientific_scan_passed'] or failure['new_evaluations_outside_target'] != 20:
        raise ValueError('Wrong failure recovery scope')
    audit = read(previous / 'completion_audit.json')
    review = read(previous / 'conformational_progress_review.json')
    if not audit['passed'] or audit['constrained_stationary'] or not review['proceed_with_one_constrained_continuation']:
        raise ValueError('No admissible continuation')
    if checked(review['completion_audit']) != previous / 'completion_audit.json':
        raise ValueError('Branch review does not cover predecessor')
    if audit['last_accepted_result'] != failure['valid_restart']:
        raise ValueError('Recovery must use the preserved valid v1 checkpoint')
    old = read(checked(audit['plan']))
    seed = read(checked(audit['last_accepted_result']))
    model = read(checked(old['model']))
    x = np.load(checked(seed['geometry']))
    identity = audit_endpoint(x, model)
    if not identity['passed']:
        raise ValueError('Restart identity failed')
    root.mkdir(exist_ok=False); (root / 'tmp').mkdir()
    shutil.copy2(REPO / 'experiments/cpd_anti_additive/corrected_endpoint_optimization.py', root / 'executed_source.py')
    shutil.copy2(Path(__file__), root / 'preparation_source.py')
    plan = {**old, 'at': now(), 'worker': pin(root / 'executed_source.py'),
            'seed_result': audit['last_accepted_result'],
            'continuation_audit': pin(previous / 'completion_audit.json'),
            'conformational_review': pin(previous / 'conformational_progress_review.json'),
            'failure_recovery': pin(failed / 'scientific_failure.json'),
            'sources': [*old['sources'], pin(previous / 'completion_audit.json'),
                        pin(previous / 'conformational_progress_review.json'),
                        seed['input'], seed['geometry'], seed['native'], seed['gradient_binary'],
                        pin(root / 'preparation_source.py'),
                        pin(REPO / 'experiments/cpd_anti_additive/endpoint_scan_restart.py'),
                        pin(REPO / 'experiments/cpd_anti_additive/endpoint_scan_constraints.py'),
                        pin(failed / 'scientific_failure.json')],
            'unit': 'cpd-corrected-anti1-glyco-minus15-v3',
            'max_new_gradients': 20, 'hard_seconds': 5400,
            'expected_seconds': 20*audit['mean_gradient_seconds']+30,
            'seed_precision': 'Exact valid v1 accepted geometry and full-precision binary gradient. No new v2 data reused. Correct degree API target; fresh optimizer history.',
            'completion_semantics': 'Conformational diagnostic continuation of the same training-design angle. Chunk completion is not constrained convergence; no minimum or fit-target acceptance implied.'}
    save(root / 'plan.json', plan)
    spec = importlib.util.spec_from_file_location('frozen_scan_continuation', root / 'executed_source.py')
    module = importlib.util.module_from_spec(spec); spec.loader.exec_module(module)
    module.context(root)
    module.admit(19, 631, plan)
    for attempts, remaining in [(20, 900), (0, 630)]:
        try:
            module.admit(attempts, remaining, plan)
        except module.ChunkBoundary:
            pass
        else:
            raise ValueError('Allocation guard failed')
    projected, _ = constraint_metrics(x, np.asarray(seed['gradient_hartree_bohr']), plan['constraint'])
    save(root / 'preflight.json', dict(at=now(), passed=True, frozen_context_verified=True,
         seed_identity=identity, constraint_metrics=projected, same_target_full_precision_restart_verified=True,
         allocation_guards_passed=True, new_qm_evaluations=0))
    save(root / 'admission.json', dict(at=now(), proceed=True, preceding_audit=plan['continuation_audit'],
         conformational_review=plan['conformational_review'], plan=pin(root / 'plan.json'), preflight=pin(root / 'preflight.json'),
         necessity=review['necessity'], alternatives=review['alternatives'], fit_scope=review['fit_scope'],
         failure_recovery=plan['failure_recovery'], recovery_reason='v2 followed a wrong target due to double angle conversion. Preserve and exclude its 20 new gradients; repair configured-target and before-QM angle checks, then restart valid v1 branch.',
         performance=dict(mean_native_seconds=audit['mean_gradient_seconds'], max_native_seconds=audit['max_gradient_seconds'],
                          estimated_minutes=plan['expected_seconds']/60, hard_minutes=90, prior_memory_peak_systemd='6.5G; no swap'),
         optimizer_history_reused=False, full_precision_seed_gradient_reused=True,
         one_native_job_at_a_time=True, cloud_spending_usd=0, minimum_certified=False, simulation_ready=False))
    print(root)


if __name__ == '__main__':
    prepare()
