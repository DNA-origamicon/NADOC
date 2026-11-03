"""Characterize heavy reconciliation reached by polling, without running that work.

These are the S34 admission blocker, not a permanent desired GET contract.
"""
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from backend.api import routes_jobs
from backend.api.part_strict_http import StrictPartDispatch
from backend.core import mrdna_runner, namd_runner
from backend.core.mrdna_job import MrdnaStatus, new_mrdna_job
from backend.core.md_job import MdJob, MdStatus, MdSegmentStatus
from backend.core.models import Design
from tests.test_part_strict_http import documents as documents, forbidden_app


class HeavyWorkReached(BaseException):
    """Escape the collector's broad Exception handler before any heavy work."""


def files(root):
    return {str(p.relative_to(root)): p.read_bytes() for p in root.rglob('*') if p.is_file()}


def test_activity_scan_enters_mrdna_output_finalization(tmp_path, monkeypatch):
    monkeypatch.setattr(routes_jobs, '_WORKSPACE_DIR', tmp_path)
    job = new_mrdna_job(design_name='Isolated observation boundary', design_source_path=None)
    job.status = MrdnaStatus.running
    job.fine_steps = 100
    job.save(tmp_path)
    monkeypatch.setattr(mrdna_runner.runtime, 'is_owned', lambda *a: False)
    monkeypatch.setattr(mrdna_runner, '_external_arbd_pid', lambda *a, **k: None)
    monkeypatch.setattr(mrdna_runner, 'is_running', lambda *a: False)
    monkeypatch.setattr(mrdna_runner, '_multiresolution_progress', lambda *a: (1.0,))
    monkeypatch.setattr(mrdna_runner, '_load_snapshot_design', lambda *a: Design())
    calls = []
    def finalizer(current, design, workspace):
        calls.append((current.job_id, workspace))
        raise HeavyWorkReached()
    monkeypatch.setattr(mrdna_runner, '_finalize_outputs', finalizer)
    before = files(tmp_path)
    with pytest.raises(HeavyWorkReached): routes_jobs._collect_active()
    assert calls == [(job.job_id, tmp_path)]
    after = files(tmp_path)
    assert all(after[path] == value for path, value in before.items())
    lock = str((job.job_dir(tmp_path) / '.runtime.lock').relative_to(tmp_path))
    assert {path: value for path, value in after.items() if path not in before} == {lock: b''}


@pytest.mark.parametrize('phase', ['finish', 'health'])
def test_activity_scan_enters_namd_finalization(tmp_path, monkeypatch, phase):
    monkeypatch.setattr(routes_jobs, '_WORKSPACE_DIR', tmp_path)
    job = MdJob(job_id='__status_boundary__', design_name='Isolated', protocol='test',
        status=MdStatus.running, created_at=0, package_subdir='package', name_stem='test')
    if phase == 'health':
        job.segments = [MdSegmentStatus(name='segment', stage='production', percent=100, steps=1)]
        job.package_dir(tmp_path).mkdir(parents=True)
        (job.package_dir(tmp_path) / 'manifest.json').write_text('{}')
    job.save(tmp_path)
    monkeypatch.setattr(namd_runner.runtime, 'is_owned', lambda *a: False)
    monkeypatch.setattr(namd_runner, 'is_running', lambda *a: False)
    monkeypatch.setattr(namd_runner, '_external_process_running', lambda *a: False)
    calls = []
    def heavy(*a, **k):
        calls.append(phase)
        raise HeavyWorkReached()
    if phase == 'finish': monkeypatch.setattr(namd_runner, '_finish_job', heavy)
    else:
        monkeypatch.setattr(namd_runner, '_segment_outputs_complete', lambda *a: True)
        monkeypatch.setattr(namd_runner, 'segments_from_manifest', lambda *a: (None, [
            SimpleNamespace(name='segment', min_c1_paired=0, min_wc_ref_relative=0)]))
        monkeypatch.setattr(namd_runner, '_jsonl_has_segment', lambda *a: False)
        monkeypatch.setattr(namd_runner, '_append_metrics_jsonl', lambda *a: calls.append('metrics'))
        monkeypatch.setattr(namd_runner, 'run_health_check', heavy)
    before = files(tmp_path)
    with pytest.raises(HeavyWorkReached): routes_jobs._collect_active()
    assert calls == (['finish'] if phase == 'finish' else ['metrics', 'health'])
    after = files(tmp_path)
    assert all(after[path] == value for path, value in before.items())
    lock = str((job.job_dir(tmp_path) / '.runtime.lock').relative_to(tmp_path))
    assert {path: value for path, value in after.items() if path not in before} == {lock: b''}


def test_strict_active_jobs_bypasses_legacy_collector(documents, tmp_path, monkeypatch):
    from backend.api import assembly
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    monkeypatch.setattr(routes_jobs, '_collect_active', lambda: pytest.fail('Unqualified collector entered'))
    with TestClient(StrictPartDispatch(forbidden_app), headers={'X-NADOC-Doc': documents[0]}) as client:
        result = client.get('/api/jobs/active')
        assert result.status_code == 200 and result.json() == {'jobs': [], 'count': 0, 'any_running': False}
