from pathlib import Path
from types import SimpleNamespace
import pytest

from experiments.cpd_anti_additive import deferred_endpoint_launch as runner
from experiments.cpd_anti_additive.corrected_core_stage1 import pin, read, save


@pytest.fixture
def queued(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'REPO', tmp_path)
    root = tmp_path/'deferred'; root.mkdir()
    job = tmp_path/'job'; job.mkdir()
    worker = job/'worker.py'; worker.write_text('# fixture only\n')
    save(job/'plan.json', dict(worker=pin(worker)))
    save(root/'plan.json', dict(source=pin(Path(runner.__file__)), native_plan=pin(job/'plan.json'),
         python='/test/python', thread='test-thread', codex_executable='/test/codex'))
    save(root/'completion_wake.json', dict(token='test-token', deliveries=[], state='timer_armed'))
    return root, job


def test_one_failed_attempt_sends_one_wake_without_retry(queued, monkeypatch):
    root, job = queued
    calls, messages = [], []
    def blocked(command, **kwargs):
        assert kwargs['env']['PATH'].split(':')[0] == '/test'
        assert kwargs['env']['CODEX_THREAD_ID'] == 'test-thread'
        calls.append(command)
        return SimpleNamespace(returncode=1, stdout='', stderr='Insufficient resource headroom')
    def notify(codex, thread, message, timeout):
        messages.append(message)
        return dict(returncode=0, stdout='queued', stderr='')
    monkeypatch.setattr(runner.subprocess, 'run', blocked)
    monkeypatch.setattr(runner, 'deliver', notify)
    runner.main(root)
    assert len(calls) == len(messages) == 1
    assert read(root/'status.json')['state'] == 'failed'
    assert read(root/'completion_wake.json')['state'] == 'queued'
    assert 'resource-admission' in messages[0]
    assert not (job/'launch_receipt.json').exists()


@pytest.mark.parametrize('condition,expected', [('paused', 'cancelled_paused'), ('launched', 'skipped_already_launched')])
def test_pause_or_existing_launch_cancels_timer_attempt(queued, monkeypatch, condition, expected):
    root, job = queued
    if condition == 'paused':
        save(job.parent/'pause.json', dict(paused=True))
    else:
        save(job/'launch_receipt.json', dict(already_launched=True))
    def forbidden(*args, **kwargs):
        raise AssertionError('Timer tried to launch or notify after cancellation')
    monkeypatch.setattr(runner.subprocess, 'run', forbidden)
    monkeypatch.setattr(runner, 'deliver', forbidden)
    runner.main(root)
    assert read(root/'status.json')['state'] == expected
    assert read(root/'completion_wake.json')['state'] == expected


def test_legacy_md_hold_does_not_pause_this_qm_campaign(queued, monkeypatch):
    root, job = queued
    legacy = runner.REPO/'.development-artifacts/cpd-anti-validation-v1/campaign_pause.json'
    legacy.parent.mkdir(parents=True)
    save(legacy, dict(paused=True, reason='Older MD physical-ensemble hold'))
    calls = []
    def blocked(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1, stdout='', stderr='Insufficient resource headroom')
    monkeypatch.setattr(runner.subprocess, 'run', blocked)
    monkeypatch.setattr(runner, 'deliver', lambda *args: dict(returncode=0, stdout='queued', stderr=''))
    runner.main(root)
    assert len(calls) == 1
    assert read(root/'status.json')['state'] == 'failed'
    assert read(legacy)['paused'] is True
