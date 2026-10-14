"""Finish the existing alternate target with the audited two-hour allocation."""
from pathlib import Path
import importlib.util
import shutil
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now,BOHR
from experiments.cpd_anti_additive.alternate_qm_release_constraints import geometry_constraints,stationarity,constraints_for


def prepare():
    from ase import Atoms
    c=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    previous=c/'alternate-sugar-qm-release-v1';root=c/'alternate-sugar-qm-release-v2'
    auditpath=previous/'completion_audit.json';reviewpath=previous/'consolidated_candidate_review.json'
    a=read(auditpath);review=read(reviewpath)
    assert a['passed'] and a['native_evidence_passed'] and not a['constrained_stationary']
    assert review['passed'] and review['continuation_admitted'] and review['completion_audit']==pin(auditpath)
    assert (review['continuation_max_new_gradients'],review['continuation_hard_seconds'],review['task_timeout_seconds'])==(30,7200,600)
    p=read(checked(a['plan']));seed=read(checked(a['last_accepted_result']));model=read(checked(p['model']))
    assert read(previous/'restart_checkpoint.json')['evaluated_source']==a['last_accepted_result']
    spec=importlib.util.spec_from_file_location('prior_frozen_release',checked(p['worker']))
    old=importlib.util.module_from_spec(spec);spec.loader.exec_module(old);old.context(previous);old.require_archive(c)
    x=np.load(checked(seed['geometry']));g=np.load(checked(seed['gradient_binary']));xr=np.load(checked(p['reference_geometry']))
    assert np.array_equal(g,np.array(seed['gradient_hartree_bohr'])) and old.audit_endpoint(x,model)['passed']
    checks=geometry_constraints(x,xr,p['fixed_indices'],p['constraint'])
    constraints,configuration=constraints_for(Atoms(model['elements'],positions=x*BOHR),xr,[],p['constraint'])
    jac=np.asarray(constraints.jacobian());_,s,v=np.linalg.svd(jac,full_matrices=True);assert np.count_nonzero(s>1e-8)==1
    q=v[1:].T;projected=old.free_projection(x*BOHR,g,[],p['constraint']['indices'])
    error=float(np.max(abs(projected.ravel()-q@(q.T@g.ravel()))));assert error<1e-9
    values=stationarity(x,g,[],list(range(49)),p['constraint']);assert not values['passed']
    root.mkdir();(root/'tmp').mkdir();shutil.copy2(Path(__file__),root/'preparation_source.py')
    for report,filename in [(a,'executed_completion_audit.py'),(review,'executed_candidate_review.py')]:
        dest=previous/filename
        if not dest.exists():shutil.copy2(checked(report['source']),dest)
        assert pin(dest)['sha256']==report['source']['sha256']
    design=read(checked(p['release_design']))
    design.update(at=now(),schema='nadoc.corrected-anti-alternate-core-release.v2',parent_design=p['release_design'],
        source_review=pin(reviewpath),seed_result=a['last_accepted_result'],max_new_gradients=30,hard_seconds=7200,
        scope='Continuation of the same zero-offset alternate endpoint. No additional target or constraint/method change.',
        stopping_rule='Convergence ends computation immediately.30newgradients/twohours are upper bounds; audit at boundary before any additional action.')
    save(root/'design.json',design)
    source=checked(p['worker']).read_text()
    replacements={
        "ROOT=CAMPAIGN/'alternate-sugar-qm-release-v1'":"ROOT=CAMPAIGN/'alternate-sugar-qm-release-v2'",
        "unit='cpd-corrected-anti1-alternate-sugar-qm-release-v1'":"unit='cpd-corrected-anti1-alternate-sugar-qm-release-v2'",
        "==(12,3600,600)":"==(30,7200,600)",
        'steps=24':'steps=60',
        'review_deadline_epoch=start+3000':'review_deadline_epoch=start+6900',
        'runtime_hours=1.':'runtime_hours=2.',
        'deadline_epoch=start+3600':'deadline_epoch=start+7200',
        '--property=RuntimeMaxSec=3585s':'--property=RuntimeMaxSec=7185s',
    }
    for before,after in replacements.items():
        assert source.count(before)==1,before
        source=source.replace(before,after)
    # Validate that all immutable scientific settings remain inherited.
    compile(source,str(root/'executed_source.py'),'exec');(root/'executed_source.py').write_text(source)
    plan=dict(p)
    plan.update(at=now(),worker=pin(root/'executed_source.py'),seed_result=a['last_accepted_result'],release_design=pin(root/'design.json'),
        previous_plan=a['plan'],continuation_audit=pin(auditpath),consolidated_review=pin(reviewpath),
        sources=[*p['sources'],pin(auditpath),pin(reviewpath),pin(previous/'executed_completion_audit.py'),pin(previous/'executed_candidate_review.py'),
            pin(root/'preparation_source.py'),pin(root/'design.json'),a['last_accepted_result'],seed['geometry'],seed['gradient_binary'],seed['native'],seed['input']],
        max_new_gradients=30,hard_seconds=7200,task_timeout_seconds=600,expected_seconds=30*a['mean_gradient_seconds']+120,
        completion_semantics='Convergence or planned30-gradient/twohour boundary. Same target; no automatic Hessian, additional grid or parameter fit. Audit accepted evidence before any next action.',
        seed_precision='Exact last accepted release-v1 coordinates and full-precision gradient reused; fresh Sella history. No snapping or repeated seed gradient.',
        worker_changes=replacements,worker_change_scope='Only service identity and allocation/step/time ceilings changed; native evaluator, constraints, gradient gates and Sella algorithm unchanged.')
    save(root/'plan.json',plan)
    newspec=importlib.util.spec_from_file_location('new_frozen_release',root/'executed_source.py')
    new=importlib.util.module_from_spec(newspec);newspec.loader.exec_module(new);new.context(root)
    new.admit(29,631,plan)
    for attempts,remaining in [(30,7000),(0,630)]:
        try:new.admit(attempts,remaining,plan)
        except new.ChunkBoundary:pass
        else:raise AssertionError('Acquisition guard failed')
    assert plan['optimizer']==p['optimizer'] and plan['native_worker']==p['native_worker'] and plan['constraint']==p['constraint']
    save(root/'preflight.json',dict(at=now(),passed=True,plan=pin(root/'plan.json'),geometry=checks,identity=old.audit_endpoint(x,model),
        constraints=configuration,independent_projection_error_au=error,initial_stationarity=values,
        exact_seed_and_gradient_reused=True,scientific_settings_unchanged=True,budget_guards_passed=True,
        new_qm_evaluations=0,expected_minutes=plan['expected_seconds']/60,inherited_constraint_tests=pin(previous/'test_receipt.json')))
    save(root/'admission.json',dict(at=now(),passed=True,plan=pin(root/'plan.json'),preflight=pin(root/'preflight.json'),design=pin(root/'design.json'),
        completion_audit=pin(auditpath),consolidated_review=pin(reviewpath),authorization=p['authorization'],
        maximum_new_gradients=30,hard_seconds=7200,task_timeout_seconds=600,
        necessity='Finish the already acquired single-chi alternate QM target; strong force reduction continues and only2.85x/1.68x thresholds remain. Geometry comparison improves while7.15kcal/mol MM conformer-energy discrepancy persists; no second fit before this reference is stationary.',
        minimum_certified=False,second_fit_admitted=False,heldout_accessed=False,cloud_spending_usd=0))
    print(dict(root=str(root),passed=True,projection_error=error,expected_minutes=plan['expected_seconds']/60,
        maximum_new_gradients=30,hard_seconds=7200,initial_stationarity=values))


if __name__=='__main__':prepare()
