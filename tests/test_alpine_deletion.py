import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncio

from backend.core import alpine_deletion as deletion


def test_reconnect_cancels_before_removing_remote_files(tmp_path):
    conn = SimpleNamespace(is_connected=lambda: True, host='alpine', user='user', run=AsyncMock(return_value=SimpleNamespace(rc=0)))
    job = SimpleNamespace(job_id='abc', slurm_job_id='123', remote_scratch_dir='/scratch/user/nadoc_jobs/abc')
    receipt = deletion.record(tmp_path, job, conn)
    asyncio.run(deletion.drain(tmp_path, conn))
    commands = [call.args[0] for call in conn.run.await_args_list]
    assert 'scancel' in commands[0]
    assert commands[1] == 'rm -rf -- /scratch/user/nadoc_jobs/abc'
    assert not receipt.exists()


def test_failed_cancel_preserves_receipt_and_files(tmp_path):
    conn = SimpleNamespace(is_connected=lambda: True, run=AsyncMock(side_effect=RuntimeError('offline')))
    job = SimpleNamespace(job_id='abc', slurm_job_id='123', remote_scratch_dir='/scratch/user/nadoc_jobs/abc')
    receipt = deletion.record(tmp_path, job, conn)
    asyncio.run(deletion.drain(tmp_path, conn))
    assert receipt.exists()
    assert not json.loads(receipt.read_text())['cancelled']
    assert conn.run.await_count == 1


def test_file_cleanup_retries_without_recancelling(tmp_path):
    conn = SimpleNamespace(is_connected=lambda: True, run=AsyncMock(side_effect=[SimpleNamespace(rc=0), SimpleNamespace(rc=1, stderr='busy')]))
    job = SimpleNamespace(job_id='abc', slurm_job_id='123', remote_scratch_dir='/scratch/user/nadoc_jobs/abc')
    receipt = deletion.record(tmp_path, job, conn)
    asyncio.run(deletion.drain(tmp_path, conn))
    assert json.loads(receipt.read_text())['cancelled']
    conn.run = AsyncMock(return_value=SimpleNamespace(rc=0))
    asyncio.run(deletion.drain(tmp_path, conn))
    assert conn.run.await_count == 1
    assert conn.run.await_args.args[0].startswith('rm -rf')
    assert not receipt.exists()


def test_different_account_cannot_process_receipt(tmp_path):
    conn = SimpleNamespace(is_connected=lambda: True, host='alpine', user='owner', run=AsyncMock())
    job = SimpleNamespace(job_id='abc', slurm_job_id='123', remote_scratch_dir='/scratch/user/nadoc_jobs/abc')
    receipt = deletion.record(tmp_path, job, conn)
    conn.user = 'other'
    asyncio.run(deletion.drain(tmp_path, conn))
    assert receipt.exists()
    conn.run.assert_not_awaited()


def test_already_finished_job_can_be_cleaned_up(tmp_path, monkeypatch):
    conn = SimpleNamespace(is_connected=lambda: True, run=AsyncMock(side_effect=[
        SimpleNamespace(rc=0, stdout='123|COMPLETED|\n'), SimpleNamespace(rc=0)]))
    monkeypatch.setattr(deletion, 'cancel_job', AsyncMock(side_effect=deletion.SchedulerCancellationError('gone')))
    job = SimpleNamespace(job_id='abc', slurm_job_id='123', remote_scratch_dir='/scratch/user/nadoc_jobs/abc')
    receipt = deletion.record(tmp_path, job, conn)
    asyncio.run(deletion.drain(tmp_path, conn))
    assert not receipt.exists()
    assert conn.run.await_args.args[0].startswith('rm -rf')


def test_unsafe_directory_is_never_removed(tmp_path):
    conn = SimpleNamespace(is_connected=lambda: True, run=AsyncMock())
    job = SimpleNamespace(job_id='abc', slurm_job_id='123', remote_scratch_dir='/scratch/user')
    receipt = deletion.record(tmp_path, job, conn)
    asyncio.run(deletion.drain(tmp_path, conn))
    assert receipt.exists()
    conn.run.assert_not_awaited()
