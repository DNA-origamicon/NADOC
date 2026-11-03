"""Ordinary effect ownership and fallback behavior after activity decision extraction."""
import pytest

from backend.core import mrdna_runner as runner
from backend.core.mrdna_job import new_mrdna_job, MrdnaStatus
from backend.core.models import Design


@pytest.mark.parametrize('initial', [MrdnaStatus.running, MrdnaStatus.queued])
@pytest.mark.parametrize('outcome', ['complete', 'failure', 'missing-design'])
def test_raw_finalization_keeps_ordinary_success_and_fallback(tmp_path, monkeypatch, initial, outcome):
    job = new_mrdna_job(design_name='Assessment parity', design_source_path=None)
    job.status = initial;job.fine_steps = 100;job.save(tmp_path)
    monkeypatch.setattr(runner.runtime, 'is_owned', lambda *a: False)
    monkeypatch.setattr(runner, '_external_arbd_pid', lambda *a, **k: None)
    monkeypatch.setattr(runner, 'is_running', lambda *a: False)
    monkeypatch.setattr(runner, '_multiresolution_progress', lambda *a: (.99, 'done', 1.))
    monkeypatch.setattr(runner, '_load_snapshot_design', lambda *a: None if outcome == 'missing-design' else Design())
    calls = []
    def finalize(current, design, workspace):
        calls.append(current.job_id)
        if outcome == 'failure': raise RuntimeError('isolated finalization failure')
        current.status = MrdnaStatus.completed
        current.save(workspace)
    monkeypatch.setattr(runner, '_finalize_outputs', finalize)
    result = runner.reconcile_mrdna_status(job, tmp_path)
    expected = MrdnaStatus.completed if outcome == 'complete' else (
        MrdnaStatus.stopped if initial == MrdnaStatus.running else initial)
    assert result is job and job.status == expected
    assert calls == ([] if outcome == 'missing-design' else [job.job_id])
    assert not (job.job_dir(tmp_path) / 'display.json').exists()


def test_live_orphan_adoption_still_precedes_cached_output(tmp_path, monkeypatch):
    job = new_mrdna_job(design_name='Live parity', design_source_path=None)
    job.status = MrdnaStatus.queued;job.save(tmp_path)
    (job.job_dir(tmp_path) / 'display.json').write_text('{}')
    monkeypatch.setattr(runner.runtime, 'is_owned', lambda *a: False)
    monkeypatch.setattr(runner, '_external_arbd_pid', lambda *a, **k: 12345)
    monkeypatch.setattr(runner, 'is_running', lambda *a: False)
    monkeypatch.setattr(runner, '_multiresolution_progress', lambda *a: pytest.fail('Live job inspected outputs'))
    result = runner.reconcile_mrdna_status(job, tmp_path)
    assert result is job and job.status == MrdnaStatus.running and job.arbd_pid == 12345
