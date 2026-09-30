"""Finishing a remote run must accept its existing storage directory."""

import asyncio
from unittest.mock import AsyncMock, Mock

import pytest

from backend.api import routes_md
from backend.core import cluster_ssh, job_archive, md_executor
from backend.core.md_job import MdJob, MdStatus


@pytest.mark.parametrize('archived', [False, True])
def test_finish_download_in_existing_directory(tmp_path, monkeypatch, archived):
    job = MdJob(
        job_id='p1', design_name='small_plate', protocol='production',
        status=MdStatus.running, created_at=0, package_subdir='package',
        name_stem='small_plate', execution_target='alpine',
        archived=archived,
        archive_path=str(tmp_path / 'storage' / 'p1') if archived else None,
    )
    monkeypatch.setattr(routes_md, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes_md, '_load_job', lambda _: job)
    monkeypatch.setattr(job, 'save', Mock())
    stop = AsyncMock(return_value={})
    monkeypatch.setattr(routes_md, '_stop_md_job_impl', stop)
    monkeypatch.setattr(cluster_ssh, 'get_manager', lambda: Mock(is_connected=lambda: True))
    fetch = AsyncMock(return_value=True)
    monkeypatch.setattr(md_executor, 'fetch_outputs', fetch)
    archive = Mock()
    monkeypatch.setattr(job_archive, 'start_archive', archive)

    result = asyncio.run(routes_md.finish_and_download_md_job(
        job.job_id,
        routes_md.ArchiveRequest(dest_root=str(job.job_dir(tmp_path).parent)),
    ))

    stop.assert_awaited_once_with('p1', fetch_remote_output=False)
    fetch.assert_awaited_once()
    archive.assert_not_called()
    assert result['action'] == 'download'
    assert result['verified'] is True
    assert job.status == MdStatus.completed


@pytest.mark.parametrize('rc', [1, 124, 137])
def test_scheduler_failure_preserves_running_job_and_prevents_download(tmp_path, monkeypatch, rc):
    from fastapi import HTTPException

    job = MdJob(
        job_id='p1', design_name='plate', protocol='production',
        status=MdStatus.running, created_at=0, package_subdir='package',
        name_stem='plate', execution_target='alpine', slurm_job_id='42',
    )
    monkeypatch.setattr(routes_md, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes_md, '_load_job', lambda _: job)
    save = Mock()
    monkeypatch.setattr(job, 'save', save)
    run = AsyncMock(return_value=cluster_ssh.RunResult(rc=rc, stdout='', stderr='scheduler unavailable'))
    manager = Mock(is_connected=lambda: True, run=run)
    monkeypatch.setattr(cluster_ssh, 'get_manager', lambda: manager)
    fetch = AsyncMock()
    monkeypatch.setattr(md_executor, 'fetch_outputs', fetch)
    archive = Mock()
    monkeypatch.setattr(job_archive, 'start_archive', archive)

    with pytest.raises(HTTPException) as error:
        asyncio.run(routes_md.finish_and_download_md_job(
            'p1', routes_md.ArchiveRequest(dest_root=str(tmp_path)),
        ))

    assert error.value.status_code == 503
    assert 'may still be running' in error.value.detail
    run.assert_awaited_once_with('timeout --kill-after=2s 20s scancel --ctld --quiet 42', timeout=30)
    assert job.status == MdStatus.running
    # Preserve the user's stop intent (blocks automatic resume), but not a
    # terminal status: the scheduler has not acknowledged the cancellation.
    assert job.user_stopped
    save.assert_called_once_with(tmp_path)
    fetch.assert_not_awaited()
    archive.assert_not_called()


def test_cancel_transport_timeout_is_unconfirmed_scheduler_cancellation():
    job = Mock(slurm_job_id='42')
    manager = Mock(run=AsyncMock(side_effect=cluster_ssh.ClusterSSHError('timeout', kind='timeout')))
    with pytest.raises(md_executor.SchedulerCancellationError, match='did not confirm'):
        asyncio.run(md_executor.cancel_job(job, conn=manager))


def test_finish_download_accepts_verified_node_stop(tmp_path, monkeypatch):
    import json

    job = MdJob(
        job_id='p1', design_name='plate', protocol='production',
        status=MdStatus.running, created_at=0, package_subdir='package',
        name_stem='plate', execution_target='alpine', slurm_job_id='42',
        remote_scratch_dir='/scratch/run',
    )
    monkeypatch.setattr(routes_md, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes_md, '_load_job', lambda _: job)
    monkeypatch.setattr(job, 'save', Mock())
    evidence = dict(job_id='42', processes_stopped=True, allocation_release_confirmed=False)
    run = AsyncMock(side_effect=[cluster_ssh.RunResult(124, '', ''),
                                cluster_ssh.RunResult(0, '42|RUNNING|node1\n', ''),
                                cluster_ssh.RunResult(0, json.dumps(evidence), '')])
    monkeypatch.setattr(cluster_ssh, 'get_manager', lambda: Mock(is_connected=lambda: True, run=run))
    fetch = AsyncMock(return_value=True)
    monkeypatch.setattr(md_executor, 'fetch_outputs', fetch)
    result = asyncio.run(routes_md.finish_and_download_md_job(
        'p1', routes_md.ArchiveRequest(dest_root=str(job.job_dir(tmp_path).parent)),
    ))
    assert result['verified'] is True
    assert job.status == MdStatus.completed
    assert job.slurm_diagnostics['direct_stop']['processes_stopped'] is True
    assert job.slurm_diagnostics['direct_stop']['allocation_release_confirmed'] is False
    fetch.assert_awaited_once()
