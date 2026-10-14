import copy

import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_core_stage1 import pin, save
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion
from experiments.cpd_anti_additive.endpoint_scan_restart import validate_scan_seed


@pytest.fixture
def restart_plan(tmp_path):
    x = np.array([[0., 1., 0.], [0., 0., 0.], [1., 0., 0.], [1., 0., 1.]])
    g = np.ones_like(x) * 1e-3
    np.save(tmp_path / 'x.npy', x)
    np.save(tmp_path / 'g.npy', g)
    constraint = dict(indices=[0, 1, 2, 3], target_degrees=torsion(x, [0, 1, 2, 3]))
    task = dict(label='minus15', geometry=pin(tmp_path / 'x.npy'), constraint=constraint)
    save(tmp_path / 'design.json', dict(training_tasks=[task]))
    base = dict(scan_design=pin(tmp_path / 'design.json'), scan_label='minus15',
                starting_geometry=task['geometry'], constraint=constraint, model={},
                elements=['C']*4, options={'method': 'mp2'}, psi4_version='pinned',
                versions={}, optimizer={'constraints_tol': 1e-8}, seed_result=None)
    save(tmp_path / 'previous_plan.json', base)
    save(tmp_path / 'seed.json', dict(geometry=task['geometry'], gradient_binary=pin(tmp_path / 'g.npy'),
                                    gradient_hartree_bohr=g.tolist()))
    save(tmp_path / 'audit.json', dict(passed=True, constrained_stationary=False, optimizer_converged=False,
                                     plan=pin(tmp_path / 'previous_plan.json'),
                                     last_accepted_result=pin(tmp_path / 'seed.json'),
                                     last_accepted_geometry=task['geometry']))
    return {**base, 'seed_result': pin(tmp_path / 'seed.json'), 'continuation_audit': pin(tmp_path / 'audit.json')}


def test_audited_same_target_can_reuse_exact_gradient(restart_plan):
    validate_scan_seed(restart_plan)


def test_initial_displaced_scan_cannot_reuse_gradient(restart_plan):
    plan = copy.deepcopy(restart_plan)
    plan.pop('continuation_audit')
    with pytest.raises(ValueError, match='cannot reuse'):
        validate_scan_seed(plan)


@pytest.mark.parametrize('field,value', [('options', {'method': 'different'}),
                                       ('optimizer', {'constraints_tol': 1e-4})])
def test_changed_method_or_optimizer_is_rejected(restart_plan, field, value):
    plan = copy.deepcopy(restart_plan)
    plan[field] = value
    with pytest.raises(ValueError, match=f'changed {field}'):
        validate_scan_seed(plan)


def test_changed_constraint_is_rejected(restart_plan):
    plan = copy.deepcopy(restart_plan)
    plan['constraint']['target_degrees'] += 1
    with pytest.raises(ValueError, match='frozen training design'):
        validate_scan_seed(plan)


def test_replaced_gradient_is_rejected(restart_plan):
    from experiments.cpd_anti_additive.corrected_core_stage1 import read
    seed = read(restart_plan['seed_result']['path'])
    np.save(seed['gradient_binary']['path'], np.zeros((4, 3)))
    with pytest.raises(ValueError, match='Changed source'):
        validate_scan_seed(restart_plan)
