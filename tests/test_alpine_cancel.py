import asyncio
from copy import deepcopy
import json
from unittest.mock import AsyncMock

import pytest

from backend.core import alpine_cancel, alpine_node_stop
from backend.core.cluster_ssh import RunResult
from backend.core.md_job import MdJob, MdStatus


def records():
    return [dict(pid=pid, pgid=10, start='1234', state='S', owned=True,
                 command=[b'/bin/bash', b'/var/spool/slurmd/job42/slurm_script'] if pid == 10 else [b'namd3'],
                 environment=[b'SLURM_JOB_ID=42'], cgroup='1:freezer:/slurm/uid_1/job_42/step_batch',
                 cwd='/scratch/run') for pid in [10, 11]]


@pytest.mark.parametrize('change', ['job', 'cwd', 'cgroup', 'group', 'missing_root', 'mixed_group', 'owner'])
def test_node_stop_rejects_ambiguous_or_mismatched_processes(change):
    rows = records()
    if change == 'job': rows[1]['environment'] = [b'SLURM_JOB_ID=99']
    elif change == 'cwd': rows[1]['cwd'] = '/scratch/other'
    elif change == 'cgroup': rows[1]['cgroup'] = '/job_99/'
    elif change == 'group': rows[1]['pgid'] = 99
    elif change == 'missing_root': rows = rows[1:]
    elif change == 'mixed_group': rows.append(dict(rows[1], pid=12, environment=[]))
    elif change == 'owner': rows[1]['owned'] = False
    with pytest.raises(RuntimeError):
        alpine_node_stop.verified_group(rows, '42', '/scratch/run')


def test_verified_node_stop_signals_only_validated_group_and_checks_exit(monkeypatch):
    samples = iter([records(), records(), []])
    monkeypatch.setattr(alpine_node_stop, 'snapshot', lambda *args: next(samples))
    monkeypatch.setattr(alpine_node_stop.time, 'sleep', lambda _: None)
    signals = []
    monkeypatch.setattr(alpine_node_stop.os, 'killpg', lambda *args: signals.append(args))
    result = alpine_node_stop.stop('42', '/scratch/run')
    assert signals == [(10, alpine_node_stop.signal.SIGTERM)]
    assert result['processes_stopped'] is True
    assert result['allocation_release_confirmed'] is False


def test_node_stop_excludes_ssh_helper_adopted_into_allocation_extern_step():
    rows = records()
    rows.append(dict(rows[1], pid=20, pgid=20, command=[b'python3'],
                     cgroup='1:freezer:/slurm/uid_1/job_42/step_extern', cwd='/home/user'))
    assert alpine_node_stop.verified_group(rows, '42', '/scratch/run', observer_pgid=20) == (10, [10, 11])
    # Another extern workload is not this diagnostic SSH helper: do not ignore it.
    with pytest.raises(RuntimeError, match='multiple process groups'):
        alpine_node_stop.verified_group(rows, '42', '/scratch/run', observer_pgid=21)


def test_node_stop_refuses_pid_reuse(monkeypatch):
    changed = deepcopy(records())
    changed[1]['start'] = '5678'
    samples = iter([records(), changed])
    monkeypatch.setattr(alpine_node_stop, 'snapshot', lambda *args: next(samples))
    monkeypatch.setattr(alpine_node_stop.os, 'killpg', lambda *args: pytest.fail('must not signal reused PID'))
    with pytest.raises(RuntimeError, match='identity changed'):
        alpine_node_stop.stop('42', '/scratch/run')


def test_node_stop_does_not_claim_success_if_process_remains(monkeypatch):
    monkeypatch.setattr(alpine_node_stop, 'snapshot', lambda *args: records())
    monkeypatch.setattr(alpine_node_stop.time, 'sleep', lambda _: None)
    monkeypatch.setattr(alpine_node_stop.os, 'killpg', lambda *args: None)
    with pytest.raises(RuntimeError, match='still exists'):
        alpine_node_stop.stop('42', '/scratch/run')


def job():
    return MdJob(job_id='j1', design_name='dna', protocol='production', created_at=0,
                 slurm_job_id='42', remote_scratch_dir='/scratch/run', status=MdStatus.running,
                 package_subdir='package', name_stem='dna')


def test_scheduler_timeout_uses_scoped_node_fallback_and_retains_evidence():
    target = job()
    target.slurm_state = 'RUNNING'
    evidence = dict(job_id='42', processes_stopped=True, allocation_release_confirmed=False)
    conn = AsyncMock()
    conn.run.side_effect = [RunResult(124, '', ''), RunResult(0, '42|RUNNING|node1\n', ''),
                            RunResult(0, json.dumps(evidence), '')]
    assert asyncio.run(alpine_cancel.cancel_job(target, conn=conn)) is True
    assert target.slurm_diagnostics['direct_stop']['node'] == 'node1'
    assert target.slurm_state is None
    assert target.slurm_diagnostics['direct_stop']['last_accounting_state'] == 'RUNNING'
    command = conn.run.call_args_list[-1].args[0]
    assert 'StrictHostKeyChecking=accept-new' in command
    assert '/scratch/run/.nadoc-node-known-hosts' in command
    assert 'node1' in command


def test_successful_scheduler_cancel_never_attempts_node_ssh():
    conn = AsyncMock()
    conn.run.return_value = RunResult(0, '', '')
    assert asyncio.run(alpine_cancel.cancel_job(job(), conn=conn)) is True
    assert conn.run.await_count == 1


@pytest.mark.parametrize('node', ['node[1-2]', '-proxy', 'node;false', 'Unknown'])
def test_fallback_refuses_ambiguous_or_unsafe_node_names(node):
    conn = AsyncMock()
    conn.run.side_effect = [RunResult(124, '', ''), RunResult(0, f'42|RUNNING|{node}\n', '')]
    with pytest.raises(alpine_cancel.SchedulerCancellationError):
        asyncio.run(alpine_cancel.cancel_job(job(), conn=conn))
    assert conn.run.await_count == 2
