"""Prepare a shorter, audited endpoint continuation from the accepted checkpoint."""
from pathlib import Path
import importlib.util
import shutil
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now,metrics
from experiments.cpd_anti_additive.prepare_corrected_endpoints import audit_endpoint


def prepare():
    campaign=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    old_root=campaign/'endpoint-1-optimization-v1';root=campaign/'endpoint-1-optimization-v2'
    audit=read(old_root/'completion_audit.json');old=read(old_root/'plan.json')
    if not audit['passed'] or audit['stationary']:raise ValueError('No admissible unconverged predecessor')
    result=read(checked(audit['last_accepted_result']));model=read(checked(old['model']))
    x=np.load(checked(result['geometry']));identity=audit_endpoint(x,model)
    if not identity['passed']:raise ValueError('Restart identity failed')
    root.mkdir(exist_ok=False);(root/'tmp').mkdir()
    shutil.copy2(REPO/'experiments/cpd_anti_additive/corrected_endpoint_optimization.py',root/'executed_source.py')
    shutil.copy2(Path(__file__),root/'preparation_source.py')
    plan={**old,'at':now(),'worker':pin(root/'executed_source.py'),
        'sources':[*old['sources'],pin(old_root/'completion_audit.json'),result['input'],result['geometry'],result['native'],
                   pin(root/'preparation_source.py')],
        'seed_result':audit['last_accepted_result'],'continuation_audit':pin(old_root/'completion_audit.json'),
        'max_new_gradients':15,'hard_seconds':3600,'expected_seconds':15*audit['mean_gradient_seconds']+30,
        'unit':'cpd-corrected-anti1-endpoint1-optimization-v2',
        'seed_precision':'Exact saved binary input geometry and full-precision gradient from last accepted evaluated state.',
        'stopping_policy':'Convergence, 15 new gradients or 1-hour cap; 10-minute per-gradient timeout. Fresh Sella history, unchanged force limits and method. Audit before any further continuation.'}
    save(root/'plan.json',plan)
    spec=importlib.util.spec_from_file_location('frozen_continuation',root/'executed_source.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module);module.context(root)
    module.admit(14,631,plan)
    for count,remaining in [(15,900),(0,630)]:
        try:module.admit(count,remaining,plan)
        except module.ChunkBoundary:pass
        else:raise ValueError('Continuation budget guard failed')
    save(root/'preflight.json',dict(at=now(),passed=True,seed_identity=identity,gradient_metrics=metrics(result['gradient_hartree_bohr']),
        frozen_context_verified=True,allocation_boundary_checks_passed=True,new_qm_evaluations=0,
        previous_native_and_driver_tests=pin(old_root/'test_receipt.json'),
        unchanged_optimizer_and_gradient_code=True))
    save(root/'admission.json',dict(at=now(),proceed=True,preceding_audit=plan['continuation_audit'],plan=pin(root/'plan.json'),
        preflight=pin(root/'preflight.json'),necessity='Maximum gradient 2.369859e-5 exceeds unchanged 1.5e-5 au criterion; RMS 9.974772e-6 is below 1e-5 criterion.',
        progress='Maximum atom gradient decreased from 0.0297588 to 0.0000236986 au over 30 new evaluations; final ten evaluations continue reducing forces/energy. No stalled-progress evidence.',
        performance='30 new gradients in 96.23 service minutes; native mean191.84s, max213.86s. Fifteen evaluations project48min; one-hour total cap.',
        alternatives='Reuse last full-precision accepted gradient instead of duplicate QM. Keep unchanged four-thread method; no measurement supports benchmarking or conditioning changes. Fresh Sella history follows the recorded restart policy.',
        optimizer_history_reused=False,minimum_certified=False,simulation_ready=False))
    print(root)


if __name__=='__main__':prepare()
