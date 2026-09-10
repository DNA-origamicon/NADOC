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
