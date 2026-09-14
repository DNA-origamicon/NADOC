from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    'local_reassess', ROOT / 'scripts/local_qm_fragment_campaign/reassess.py'
)
monitor = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(monitor)


def write(path, data):
    path.write_text(json.dumps(data))
    return {'path': str(path), 'sha256': monitor.digest(path)}


@pytest.fixture
def campaign(tmp_path):
    root = tmp_path / 'campaign'
    root.mkdir()
    directory = root / 'job'
    directory.mkdir()
    (directory / 'input.dat').write_text('test input')
    xyz = write(directory / 'source.json', {'source': True})
    protocol = ROOT / 'backend/data/forcefield/photoproduct_qm_protocol_v1.7.0.json'
    job = {'input': {'sha256': monitor.digest(directory / 'input.dat')},
           'source_xyz': xyz, 'atom_map': ['C'], 'atom_count': 1,
           'product_id': 'test', 'model_id': 'test',
           'job_kind': 'geometry_optimization', 'protocol_version': '1.7.0',
           'protocol_sha256': monitor.digest(protocol)}
    record = write(directory / 'job_manifest.json', job)
    item = {'id': 'first', 'stage': 'A', 'job_dir': str(directory),
            'job_manifest': record, 'wall_hours': 3}
    manifest = write(root / 'campaign_manifest.json', {'campaign': 'test'})
    write(root / 'review_preparation.json', {'campaign': manifest, 'jobs': [item], 'benchmarks': ['first']})
    return root, directory, item


def completed(directory, status='completed_unreviewed'):
    return write(directory / 'run_manifest.json', {'status': status,
                 'job_manifest_sha256': monitor.digest(directory / 'job_manifest.json'),
                 'outputs': {}})


def test_preflight_detects_tampered_source_and_input(campaign):
    root, directory, item = campaign
    assert monitor.preflight(item)['model_id'] == 'test'
    (directory / 'source.json').write_text('changed')
    assert monitor.assess(root)['jobs'][0]['state'] == 'invalid_evidence'
    (directory / 'input.dat').write_text('changed')
    with pytest.raises(ValueError, match='input digest'):
        monitor.preflight(item)


def test_completion_triggers_benchmark_and_stage_but_never_accepts_minimum(campaign):
    root, directory, _ = campaign
    completed(directory)
    report = monitor.assess(root)
    assert report['jobs'][0]['state'] == 'completed_unreviewed'
    assert report['stages']['A']['execution_finished']
    assert report['stages']['A']['scientific_status'] == 'review_required'
    assert not report['stages']['D']['execution_finished']
    assert not report['simulation_ready']
    assert {'benchmark_review', 'stage_finished_review'} <= {e['kind'] for e in report['events']}
    assert monitor.persist(root, report)
    assert monitor.persist(root, monitor.assess(root)) == []


def test_failed_stage_still_triggers_review(campaign):
    root, directory, _ = campaign
    completed(directory, 'failed')
    report = monitor.assess(root)
    assert report['stages']['A']['execution_finished']
    assert 'execution_failed' in report['jobs'][0]['alerts']
    assert report['stages']['A']['scientific_status'] == 'review_required'


def test_identity_is_not_a_minimum_and_audit_tampering_invalidates(campaign):
    root, directory, _ = campaign
    run = completed(directory)
    xyz = write(directory / 'optimized.xyz', {'coordinates': True})
    write(directory / 'optimized_model_audit.json', {
        'status': 'passed_candidate_identity_and_chirality', 'effective_run_record': run,
        'optimized_xyz': xyz, 'product_id': 'test', 'model_id': 'test',
        'chirality_audit': {'passed': True}})
    assert monitor.assess(root)['jobs'][0]['state'] == 'identity_passed_minimum_unconfirmed'
    (directory / 'optimized.xyz').write_text('tampered')
    assert monitor.assess(root)['jobs'][0]['state'] == 'invalid_evidence'


def test_missing_receipt_detects_stall_overrun_and_dead_launcher(campaign):
    root, directory, _ = campaign
    write(directory / 'campaign_launch.json', {'started_epoch': 100, 'pid': 999999999, 'boot_id': 'old'})
    state = monitor.assess(root, now=100 + 4 * 3600)['jobs'][0]
    assert {'wall_budget_exceeded', 'launcher_gone_without_receipt', 'no_output_15min_after_launch'} <= set(state['alerts'])
    assert not monitor.assess(root)['stages']['A']['execution_finished']


def test_deferred_stage_registration_and_external_receipt_change(campaign):
    root, directory, item = campaign
    write(root / 'review_extensions.json', {'schema': 'nadoc.local-qm-review-extensions.v1',
                                          'jobs': [{**item, 'id': 'frequency', 'stage': 'D'}]})
    assert monitor.assess(root)['stages']['D']['registered_jobs'] == 1
    (root / 'review_inputs').mkdir()
    write(root / 'review_inputs/primary-fit-freeze.json', {'status': 'frozen'})
    report = monitor.assess(root)
    assert any(e['kind'] == 'review_receipt_changed' for e in report['events'])
