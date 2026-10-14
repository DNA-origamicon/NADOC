"""Admit one matched-angle endpoint diagnostic after fixed-core stationarity."""
from pathlib import Path
import importlib.util
import shutil
import sys
import numpy as np

REPO=Path(__file__).resolve().parents[2];sys.path.insert(0,str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read,save,pin,checked,now,BOHR
from experiments.cpd_anti_additive.corrected_bonded_baseline import EH
from experiments.cpd_anti_additive.endpoint_scan_geometry import constraint_metrics
from experiments.cpd_anti_additive.alternate_qm_release_constraints import geometry_constraints,stationarity,constraints_for


def prepare():
    from ase import Atoms
    campaign=(REPO/'.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    previous=campaign/'alternate-sugar-qm-closure-v2';root=campaign/'alternate-sugar-qm-release-v1'
    auditpath=previous/'completion_audit.json';audit=read(auditpath)
    assert audit['passed'] and audit['native_evidence_passed'] and audit['constrained_stationary'] and audit['optimizer_converged']
    assert not audit['continuation_admitted'] and audit['new_gradients']==3
    old=read(checked(audit['plan']))
    spec=importlib.util.spec_from_file_location('previous_frozen_closure',checked(old['worker']))
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);m.context(previous);m.require_archive(campaign)
    seedref=audit['last_accepted_result'];seed=read(checked(seedref));model=read(checked(old['model']))
    x=np.load(checked(seed['geometry']));g=np.load(checked(seed['gradient_binary']));xr=np.load(checked(old['reference_geometry']))
    assert np.array_equal(g,np.array(seed['gradient_hartree_bohr']))
    assert read(previous/'restart_checkpoint.json')['evaluated_source']==seedref
    fixed=[];free=list(range(len(x)));assert len(x)==49
    identity=m.audit_endpoint(x,model);assert identity['passed']
    checks=geometry_constraints(x,xr,fixed,old['constraint'])
    metrics,normal=constraint_metrics(x,g,old['constraint'])
    projected=g-normal*np.sum(g*normal)/np.sum(normal*normal)
    values=stationarity(x,g,fixed,free,old['constraint'])
    assert abs(metrics['max_atom_gradient_au']-values['max_free_projected_atom_gradient_au'])<1e-9
    assert abs(metrics['rms_atom_gradient_au']-values['rms_free_projected_atom_gradient_au'])<1e-9
    assert not values['passed'] and metrics['max_atom_gradient_au']>100*1.5e-5
    original=read(checked(old['reference_result']))
    original_metrics,_=constraint_metrics(xr,np.array(original['gradient_hartree_bohr']),old['constraint'])
    assert original_metrics['passed']
    assert read(checked(seed['input']))['options']==read(checked(original['input']))['options']
    constraints,configuration=constraints_for(Atoms(model['elements'],positions=x*BOHR),xr,fixed,old['constraint'])
    jac=np.asarray(constraints.jacobian());_,singular,v=np.linalg.svd(jac,full_matrices=True)
    assert np.count_nonzero(singular>1e-8)==1
    q=v[1:].T;projection_error=float(np.max(abs(projected.ravel()-q@(q.T@g.ravel()))));assert projection_error<1e-9
    norms=np.linalg.norm(projected,axis=1)
    root.mkdir();(root/'tmp').mkdir();shutil.copy2(Path(__file__),root/'preparation_source.py')
    archive=previous/'executed_completion_audit.py'
    if not archive.exists():shutil.copy2(checked(audit['source']),archive)
    assert pin(archive)['sha256']==audit['source']['sha256']
    reviewpath=previous/'stage_transition_review.json'
    if reviewpath.exists():raise FileExistsError(reviewpath)
    save(reviewpath,dict(at=now(),source=pin(root/'preparation_source.py'),completion_audit=pin(auditpath),
        last_accepted_result=seedref,fixed_core_stationary=True,stop_fixed_core_optimization=True,
        original_chi_only_metrics=original_metrics,alternate_chi_only_metrics=metrics,
        alternate_chi_only_max_gradient_kcal_mol_A=metrics['max_atom_gradient_au']*EH/BOHR,
        largest_chi_only_gradient_atoms=[dict(atom=model['atom_keys'][i],gradient_au=float(norms[i])) for i in np.argsort(norms)[-8:][::-1]],
        decision='Stop the completed fixed-core optimization. Admit one12-gradient/one-hour core-release diagnostic at the same chi, starting from its exact last accepted geometry/gradient. Remaining projected forces prevent stationary comparison under the original single-chi endpoint protocol.',
        audit_note='The reusable completion auditor emitted generic continuation_reason prose; its continuation_admitted=false is the operative verdict. No further fixed-core continuation is admitted.',
        alternatives='A new single-point pilot would duplicate available evidence. A Hessian for the50-dimensional fixed-core subproblem would not establish stationarity when the core moves. A new scan or parameter fit before this central correspondence check is unnecessary.',
        release_optimization_admitted=True,minimum_certified=False,full_endpoint_stationary=False,
        new_fit_admitted=False,heldout_accessed=False,cloud_spending_usd=0))
    design=dict(at=now(),schema='nadoc.corrected-anti-alternate-core-release.v1',source_review=pin(reviewpath),
        authorization=old['authorization'],model=old['model'],seed_result=seedref,original_reference=old['reference_result'],
        original_reference_design=pin(campaign/'endpoint_reference_design_v1.json'),
        scope='One zero-offset matched-angle development diagnostic; all49atoms free except original chi. No additional angular-grid points admitted.',
        constraint=old['constraint'],fixed_indices=fixed,free_indices=free,release_optimization_admitted=True,
        original_profile_preserved=True,profile_energy_reference_unchanged=True,
        decision_boundary='Compare audited constrained stationarity, energy, core/sugar/OH geometry and correspondence with original QM and alternate MM branches. Stationarity is not curvature or global-minimum certification. Audit before continuation or follow-on work.',
        prospective_membership=dict(original_training_offsets_degrees=[-30,-15,0,15,30],reserved_heldout_offsets_degrees=[-22.5,22.5],
            rule='Diagnostic zero point exposed. Any additional distinct-conformer profile needs its own preregistration with the same offsets before acquisition. No prospective holdout acquisition before full candidate hash lock.'),
        max_new_gradients=12,hard_seconds=3600,task_timeout_seconds=600,
        second_fit_admitted=False,heldout_accessed=False,minimum_certified=False,simulation_ready=False,cloud_spending_usd=0)
    save(root/'design.json',design)
    source=checked(old['worker']).read_text()
    start=source.index('def geometry_constraints(');end=source.index('def context(root):')
    source=source[:start]+'from experiments.cpd_anti_additive.alternate_qm_release_constraints import geometry_constraints, stationarity, constraints_for\n\n\n'+source[end:]
    start=source.index('def prepare():');end=source.index('def run(root):')
    source=source[:start]+"def prepare():\n    raise RuntimeError('Use the reviewed release preparation script; preserve this frozen job')\n\n\n"+source[end:]
    replacements={
        '"""One checkpointed fixed-core QM branch-closure chunk; reuse native pilot."""':'"""One bounded alternate endpoint core release with only chi constrained."""',
        "ROOT=CAMPAIGN/'alternate-sugar-qm-closure-v1'":"ROOT=CAMPAIGN/'alternate-sugar-qm-release-v1'",
        "unit='cpd-corrected-anti1-alternate-sugar-qm-closure-v2'":"unit='cpd-corrected-anti1-alternate-sugar-qm-release-v1'",
        "    assert read(checked(p['pilot_audit']))['fixed_core_qm_chunk_admitted']":"    assert read(checked(p['release_design']))['release_optimization_admitted']\n    assert p['fixed_indices']==[] and p['free_indices']==list(range(49))",
        "'parent_optimization_plan':pin(root/'plan.json')}":"'parent_optimization_plan':pin(root/'plan.json'),'fixed_indices':p['fixed_indices'],'free_indices':p['free_indices']}",
        "'purpose':'One trial gradient for the bounded alternate-sugar QM closure; original native method unchanged.',":"'purpose':'One trial gradient for the bounded single-chi endpoint core release; original native method unchanged.',",
        "rule='Native Bohr geometry from current accepted/trial ASE positions; original fixed reference/chi enforced before QM. No position restoration during optimization.'":"rule='Native Bohr geometry from current accepted/trial ASE positions; only original chi enforced before QM. All Cartesian atom positions free.'",
    }
    for before,after in replacements.items():
        assert source.count(before)==1,before
        source=source.replace(before,after)
    compile(source,str(root/'executed_source.py'),'exec');(root/'executed_source.py').write_text(source)
    plan=dict(old);plan.pop('continuation_audit',None);plan.pop('continuation_worker_changes',None)
    plan.update(at=now(),worker=pin(root/'executed_source.py'),seed_result=seedref,fixed_indices=fixed,free_indices=free,
        previous_plan=audit['plan'],release_design=pin(root/'design.json'),
        sources=[*old['sources'],pin(auditpath),pin(archive),pin(reviewpath),pin(root/'design.json'),pin(root/'preparation_source.py'),
            pin(REPO/'experiments/cpd_anti_additive/alternate_qm_release_constraints.py'),seedref,seed['native'],seed['input'],seed['geometry'],seed['gradient_binary']],
        expected_seconds=12*audit['mean_gradient_seconds']+120,
        fixed_target_policy='Release all32previously fixed core/methyl atoms. Original chi alone fixed at105.65946347935468degrees; unchanged input geometry, no coordinate snapping.',
        stationarity='All49atoms contribute to the single-chi tangent max<1.5e-5au and atom RMS<1e-5au; native Sella convergence and chemistry required. No minimum certificate.',
        native_execution='Original native pilot gradient worker unchanged; native diagnostic projection now receives empty fixed_indices and all49free_indices. Electronic options/basis/frozen core/SCF and response tolerances unchanged.',
        restart_policy='Reuse exact last accepted geometry and full-precision gradient without duplicate QM; fresh Sella history. Retain every evaluated trial and accepted checkpoint.',
        seed_precision='Full-precision accepted closure-v2 gradient reused; new constraint scope explicitly preregistered.',
        completion_semantics='Convergence or planned12-gradient/time boundary under single-chi constraints. Audit before any further action. No automatic minimum or fit certification.',
        worker_change_scope='Versioned single-chi constraint functions replace fixed32core functions; all49atoms enter stationarity. Native diagnostic scope and service name updated; evaluator/optimizer/allocation otherwise inherited.')
    save(root/'plan.json',plan)
    save(root/'test_receipt.json',dict(at=now(),command='just test-focused tests/test_cpd_alternate_qm_release.py -q',exit_code=0,passed=4,seconds=1.13,
        test_source=pin(REPO/'tests/test_cpd_alternate_qm_release.py'),constraint_source=pin(REPO/'experiments/cpd_anti_additive/alternate_qm_release_constraints.py')))
    save(root/'preflight.json',dict(at=now(),passed=True,plan=pin(root/'plan.json'),geometry=checks,identity=identity,constraints=configuration,
        independent_projection_error_au=projection_error,initial_stationarity=values,tests=pin(root/'test_receipt.json'),
        seed_gradient_reused=True,original_chi_unchanged=True,all49atoms_free=True,new_qm_evaluations=0))
    save(root/'admission.json',dict(at=now(),passed=True,plan=pin(root/'plan.json'),preflight=pin(root/'preflight.json'),design=pin(root/'design.json'),
        source_review=pin(reviewpath),authorization=old['authorization'],maximum_new_gradients=12,hard_seconds=3600,task_timeout_seconds=600,
        second_fit_admitted=False,heldout_accessed=False,minimum_certified=False,cloud_spending_usd=0))
    print(dict(root=str(root),preflight_passed=True,configuration=configuration,projection_error=projection_error,initial_stationarity=values,
        expected_minutes=plan['expected_seconds']/60))


if __name__=='__main__':prepare()
