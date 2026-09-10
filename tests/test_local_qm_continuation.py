from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parents[1] / 'scripts/local_qm_fragment_campaign'


@pytest.fixture
def controller(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(HERE))
    spec = importlib.util.spec_from_file_location('test_continuation_module', HERE / 'continue_campaign.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    root = tmp_path
    (root / 'review').mkdir()
    (root / 'review_inputs').mkdir()
    (root / 'continuation_policy.json').write_text(json.dumps({'maximum_parallel_core_jobs': 3}))
    jobs = []
    for name, stage in [('core-1', 'A'), ('core-2', 'A'), ('boundary-1', 'B'), ('boundary-2', 'B')]:
        directory = root / name
        directory.mkdir()
        jobs.append({'id': name, 'stage': stage, 'job_dir': str(directory)})
    (root / 'continuation_authorization.json').write_text(json.dumps({
        'enabled': True, 'policy_sha256': module.digest(root / 'continuation_policy.json'),
        'geometry_order': [j['id'] for j in jobs]}))
    monkeypatch.setattr(module, 'inventory', lambda root: ({}, jobs))
    monkeypatch.setattr(module, 'preflight', lambda item: {})
    monkeypatch.setattr(module, 'active', lambda item: False)
    monkeypatch.setattr(module, 'assessment', lambda root, item, policy: {
        **item, 'decision': 'continue', 'run_sha256': 'hash', 'issues': []})
    launched = []
    monkeypatch.setattr(module, 'launch', lambda item, root: launched.append(item['id']))
    return module, root, jobs, launched


def complete(jobs):
    for item in jobs:
        (Path(item['job_dir']) / 'run_manifest.json').write_text('{}')


def test_independent_core_can_start_while_benchmark_runs(controller, monkeypatch):
    module, root, jobs, launched = controller
    monkeypatch.setattr(module, 'active', lambda item: item['id'] == 'core-1')
    assert module.tick(root)['status'] == 'launched'
    assert launched == ['core-2']


def test_failed_assessment_prevents_more_launches(controller, monkeypatch):
    module, root, jobs, launched = controller
    complete(jobs[:1])
    monkeypatch.setattr(module, 'assessment', lambda *args: {'decision': 'hold', 'issues': ['chirality failed']})
    assert module.tick(root)['status'] == 'hold'
    assert launched == []


def test_stage_boundary_requires_all_core_assessments(controller):
    module, root, jobs, launched = controller
    complete(jobs[:2])
    assert module.tick(root)['status'] == 'launched'
    assert launched == ['boundary-1']
    assert (root / 'review_inputs/automatic-stage-A.json').is_file()


def test_boundary_benchmark_remains_serial(controller, monkeypatch):
    module, root, jobs, launched = controller
    complete(jobs[:2])
    monkeypatch.setattr(module, 'active', lambda item: item['id'] == 'boundary-1')
    assert module.tick(root)['status'] == 'running'
    assert launched == []


def test_missing_response_fit_scope_never_launches_holdouts(controller):
    module, root, jobs, launched = controller
    complete(jobs)
    assert module.tick(root)['status'] == 'hold_for_response_and_fit_scope'
    assert launched == []


def test_policy_changes_invalidate_continuation(controller):
    module, root, jobs, launched = controller
    (root / 'continuation_policy.json').write_text('{}')
    with pytest.raises(ValueError, match='policy changed'):
        module.tick(root)
    assert launched == []


def test_active_local_execution_hold_prevents_launch(controller):
    module, root, jobs, launched = controller
    (root / 'local_execution_hold.json').write_text(json.dumps({
        'schema': 'nadoc.local-qm-execution-hold.v1',
        'status': 'active',
        'reason': 'offloaded to Alpine',
        'replacement': {'campaign': 'alpine-continuation'},
    }))
    report = module.tick(root)
    assert report['status'] == 'local_execution_held'
    assert report['reason'] == 'offloaded to Alpine'
    assert launched == []


def add_frequency_scope(controller, monkeypatch):
    module, root, jobs, launched = controller
    directory = root / 'frequency-benchmark'
    directory.mkdir()
    item = {'id': 'frequency-benchmark', 'stage': 'D', 'job_dir': str(directory)}
    jobs.append(item)
    scope = root / 'frequency_scope_v1.json'
    scope.write_text(json.dumps({'jobs': [item]}))
    authorization = json.loads((root / 'continuation_authorization.json').read_text())
    authorization.update(frequency_order=[item['id']], frequency_scope_sha256=module.digest(scope))
    (root / 'continuation_authorization.json').write_text(json.dumps(authorization))
    monkeypatch.setattr(module, 'preflight', lambda item: {'job_kind': 'frequency', 'parent_manifest': {'path': 'parent'}})
    return item


def test_scoped_frequency_starts_only_after_geometry_assessments(controller, monkeypatch):
    module, root, jobs, launched = controller
    complete(jobs)
    add_frequency_scope(controller, monkeypatch)
    assert module.tick(root)['status'] == 'launched'
    assert launched == ['frequency-benchmark']


def test_unfavorable_frequency_prevents_further_progression(controller, monkeypatch):
    module, root, jobs, launched = controller
    item = add_frequency_scope(controller, monkeypatch)
    complete(jobs)
    original = module.assessment
    monkeypatch.setattr(module, 'assessment', lambda root, job, policy:
                        {'decision': 'hold', 'issues': ['imaginary mode']} if job['id'] == item['id']
                        else original(root, job, policy))
    assert module.tick(root)['status'] == 'hold'
    assert launched == []


def test_frequency_scope_tampering_blocks_launch(controller, monkeypatch):
    module, root, jobs, launched = controller
    add_frequency_scope(controller, monkeypatch)
    (root / 'frequency_scope_v1.json').write_text('{}')
    with pytest.raises(ValueError, match='scope changed'):
        module.tick(root)
    assert launched == []


def test_favorable_frequency_cohort_still_requires_frozen_fit(controller, monkeypatch):
    module, root, jobs, launched = controller
    add_frequency_scope(controller, monkeypatch)
    complete(jobs)
    assert module.tick(root)['status'] == 'hold_for_primary_fit'
    assert launched == []
