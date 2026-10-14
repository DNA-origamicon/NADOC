"""Prepare the audited second alternate-sugar QM chunk without changing physics."""
from pathlib import Path
import importlib.util
import shutil
import sys
import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
from experiments.cpd_anti_additive.corrected_core_stage1 import read, save, pin, checked, now, BOHR


def prepare():
    from ase import Atoms
    campaign = (REPO / '.development-artifacts/cpd-corrected-cis-anti-i-refinement-v1').resolve()
    previous = campaign / 'alternate-sugar-qm-closure-v1'
    root = campaign / 'alternate-sugar-qm-closure-v2'
    auditpath = previous / 'completion_audit.json'
    audit = read(auditpath)
    assert audit['passed'] and audit['native_evidence_passed'] and audit['continuation_admitted']
    assert not audit['constrained_stationary'] and not audit['optimizer_converged']
    assert audit['new_gradients'] == 12 and audit['planned_boundary'] == 'New-gradient allocation exhausted'
    old = read(checked(audit['plan']))
    spec = importlib.util.spec_from_file_location('previous_frozen_closure', checked(old['worker']))
    worker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(worker)
    worker.context(previous)
    worker.require_archive(campaign)
    seedref = audit['last_accepted_result']
    seed = read(checked(seedref))
    saved = read(previous / 'restart_checkpoint.json')
    assert saved['evaluated_source'] == seedref and saved['geometry'] == seed['geometry']
    assert saved['gradient'] == seed['gradient_binary']
    model = read(checked(old['model']))
    x = np.load(checked(seed['geometry']))
    g = np.load(checked(seed['gradient_binary']))
    xr = np.load(checked(old['reference_geometry']))
    assert np.array_equal(g, np.array(seed['gradient_hartree_bohr']))
    checks = worker.geometry_constraints(x, xr, old['fixed_indices'], old['constraint'])
    identity = worker.audit_endpoint(x, model)
    assert identity['passed']
    atoms = Atoms(model['elements'], positions=x * BOHR)
    constraints, configuration = worker.constraints_for(atoms, xr, old['fixed_indices'], old['constraint'])
    _, singular, v = np.linalg.svd(np.array(constraints.jacobian()), full_matrices=True)
    assert np.count_nonzero(singular > 1e-8) == 97
    q = v[97:].T
    independent = worker.free_projection(x * BOHR, g, old['fixed_indices'], old['constraint']['indices'])
    projection_error = float(np.max(abs(independent.ravel() - q @ (q.T @ g.ravel()))))
    assert projection_error < 1e-9
    values = worker.stationarity(x, g, old['fixed_indices'], old['free_indices'], old['constraint'])
    assert not values['passed']
    root.mkdir()
    (root / 'tmp').mkdir()
    shutil.copy2(Path(__file__), root / 'preparation_source.py')
    archive = previous / 'executed_completion_audit.py'
    if not archive.exists():
        shutil.copy2(checked(audit['source']), archive)
    assert pin(archive)['sha256'] == audit['source']['sha256']
    source = checked(old['worker']).read_text()
    replacements = {
        "unit='cpd-corrected-anti1-alternate-sugar-qm-closure-v1'":
        "unit='cpd-corrected-anti1-alternate-sugar-qm-closure-v2'",
        'pilot_reused=any(row.get(\'reused\') for row in rows)':
        'seed_gradient_reused=any(row.get(\'reused\') for row in rows)',
    }
    for before, after in replacements.items():
        assert source.count(before) == 1
        source = source.replace(before, after)
    (root / 'executed_source.py').write_text(source)
    plan = dict(old)
    plan.update(at=now(), worker=pin(root / 'executed_source.py'), seed_result=seedref,
        sources=[*old['sources'], pin(auditpath), pin(archive), pin(root/'preparation_source.py'),
                 seedref, seed['native'], seed['input'], seed['geometry'], seed['gradient_binary'],
                 pin(previous/'restart_checkpoint.json')],
        continuation_audit=pin(auditpath), previous_plan=audit['plan'],
        expected_seconds=12*audit['mean_gradient_seconds']+120,
        seed_precision='Unchanged last accepted native geometry and full-precision gradient from closure-v1; reused once without QM recomputation or coordinate snapping. Fresh Sella optimizer history.',
        restart_policy='Use exact accepted geometry/gradient, keep the original reference targets for all32fixed atoms and the identical chi target. All evaluated trials and accepted checkpoints retained; optimizer Hessian/history not restorable.',
        completion_semantics='Convergence or planned12-gradient/time boundary; neither service completion nor stationarity is a minimum certificate. Re-audit progress, cost and necessity before another chunk.',
        continuation_worker_changes=replacements,
        worker_change_scope='Only unique systemd unit name and seed-reuse reporting key changed. Native evaluator, optimization algorithm, constraints and stationarity tolerances are byte-for-byte inherited.')
    save(root/'plan.json', plan)
    save(root/'preflight.json', dict(at=now(), passed=True, plan=pin(root/'plan.json'),
        continuation_audit=pin(auditpath), geometry=checks, identity=identity, constraints=configuration,
        independent_projection_error_au=projection_error, initial_stationarity=values,
        exact_accepted_seed=True, full_precision_gradient_reused=True, original_fixed_targets_preserved=True,
        new_qm_evaluations=0, expected_minutes=plan['expected_seconds']/60,
        inherited_focused_tests=pin(previous/'test_receipt.json')))
    save(root/'admission.json', dict(at=now(), passed=True, plan=pin(root/'plan.json'),
        preflight=pin(root/'preflight.json'), audit=pin(auditpath), authorization=plan['authorization'],
        decision='One additional12-gradient/one-hour chunk: previous maximum free force fell380.8fold overall and74.84% over the last5states. Both force criteria still fail; no stall or native-method failure. Reuse last accepted gradient, fresh Sella history.',
        max_new_gradients=12, hard_seconds=3600, task_timeout_seconds=600,
        new_fit_admitted=False, heldout_accessed=False, minimum_certified=False, cloud_spending_usd=0))
    print(dict(root=str(root), preflight_passed=True, initial_stationarity=values,
        geometry=checks, projection_error=projection_error, expected_minutes=plan['expected_seconds']/60))


if __name__ == '__main__':
    prepare()
