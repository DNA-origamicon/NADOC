"""Accepted residuals survive restart without weakening target or provenance checks."""
import copy
from types import SimpleNamespace

import numpy as np
import pytest

from experiments.cpd_anti_additive.corrected_core_stage1 import pin, save
from experiments.cpd_anti_additive.endpoint_scan_geometry import torsion
from experiments.cpd_anti_additive.endpoint_scan_restart import validate_scan_seed as legacy_seed
from experiments.cpd_anti_additive.endpoint_scan_restart_v2 import validate_scan_seed
from experiments.cpd_anti_additive.endpoint_scan_constraints_v2 import verify_constraint_configuration


def plan_for(tmp_path, error=2.2104963761648833e-6, tolerance=0.01):
    x = np.array([[0., 1., 0.], [0., 0., 0.], [1., 0., 0.], [1., 0., 1.]])
    g = np.ones_like(x)*1e-3
    np.save(tmp_path/'x.npy', x); np.save(tmp_path/'g.npy', g)
    spec = dict(indices=[0,1,2,3], target_degrees=torsion(x,[0,1,2,3])-error,
                tolerance_degrees=tolerance)
    task = dict(label='plus30', geometry=pin(tmp_path/'x.npy'), constraint=spec)
    save(tmp_path/'design.json', dict(training_tasks=[task]))
    base = dict(scan_design=pin(tmp_path/'design.json'), scan_label='plus30',
                starting_geometry=task['geometry'], constraint=spec, model={},
                elements=['C']*4, options={'method':'mp2'}, psi4_version='pinned',
                versions={}, optimizer={'constraints_tol':1e-8}, seed_result=None)
    save(tmp_path/'previous.json',base)
    save(tmp_path/'seed.json',dict(geometry=task['geometry'],
        gradient_binary=pin(tmp_path/'g.npy'),gradient_hartree_bohr=g.tolist()))
    save(tmp_path/'audit.json',dict(passed=True,constrained_stationary=False,
        optimizer_converged=False,plan=pin(tmp_path/'previous.json'),
        last_accepted_result=pin(tmp_path/'seed.json'),last_accepted_geometry=task['geometry']))
    return {**base,'seed_result':pin(tmp_path/'seed.json'),'continuation_audit':pin(tmp_path/'audit.json')}


def configured(spec, error):
    return SimpleNamespace(targets=np.radians([spec['target_degrees']]),
                           residual=lambda:np.radians([error]))


def test_exact_accepted_geometry_and_gradient_preserved(tmp_path):
    plan = plan_for(tmp_path)
    before = {p.name:p.read_bytes() for p in tmp_path.iterdir()}
    with pytest.raises(ValueError,match='off the fixed'):
        legacy_seed(plan)
    validate_scan_seed(plan)
    c = configured(plan['constraint'], 2.2104963761648833e-6)
    with pytest.raises(ValueError,match='residual'):
        verify_constraint_configuration(c,plan['constraint'])
    verify_constraint_configuration(c,plan['constraint'],accepted_restart=True)
    assert before == {p.name:p.read_bytes() for p in tmp_path.iterdir()}


@pytest.mark.parametrize('error,tolerance',[(0.02,0.01),(0.02,1.0),(0.002,0.001),(0.0,0.0)])
def test_outside_native_angle_gate_rejected(tmp_path,error,tolerance):
    plan = plan_for(tmp_path,error,tolerance)
    with pytest.raises(ValueError):
        validate_scan_seed(plan)
    with pytest.raises(ValueError):
        verify_constraint_configuration(configured(plan['constraint'],error),
                                        plan['constraint'],accepted_restart=True)


def test_double_conversion_still_rejected_for_restart(tmp_path):
    spec = plan_for(tmp_path)['constraint']
    c = configured(spec,0)
    c.targets = np.radians(c.targets)
    with pytest.raises(ValueError,match='degree target'):
        verify_constraint_configuration(c,spec,accepted_restart=True)


@pytest.mark.parametrize('field,value',[
    ('options',{'method':'different'}),('optimizer',{'constraints_tol':1e-4}),
    ('versions',{'sella':'changed'}),('seed_result',None)])
def test_method_or_restart_substitution_rejected(tmp_path,field,value):
    plan = copy.deepcopy(plan_for(tmp_path)); plan[field] = value
    with pytest.raises(ValueError):
        validate_scan_seed(plan)


def test_gradient_tampering_rejected(tmp_path):
    plan = plan_for(tmp_path)
    np.save(tmp_path/'g.npy',np.zeros((4,3)))
    with pytest.raises(ValueError,match='Changed source'):
        validate_scan_seed(plan)


def test_fresh_displaced_seed_cannot_reuse_gradient(tmp_path):
    plan = plan_for(tmp_path); plan.pop('continuation_audit')
    with pytest.raises(ValueError,match='cannot reuse'):
        validate_scan_seed(plan)
