"""Large visualization windows use shared binary tracks, not the legacy JSON point cap."""
import asyncio
import struct
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from backend.api import routes_md
from backend.core import md_ion_paths


@pytest.mark.parametrize('before,after', [(10, 200), (200, 200), (10000, 10000)])
def test_large_window_route_returns_binary(monkeypatch, tmp_path, before, after):
    job = SimpleNamespace(package_dir=lambda _: tmp_path)
    monkeypatch.setattr(routes_md, '_load_job', lambda _: job)
    monkeypatch.setattr(routes_md, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes_md, '_md_segment_dcds', lambda _: [('prod', 'production', 'test.dcd')])
    monkeypatch.setattr(routes_md, '_md_snapshot_design', lambda _: 'frozen design')
    def extract(pkg, dcds, b, a, design, *, compact):
        assert (pkg, dcds, b, a, design, compact) == (tmp_path, ['test.dcd'], before, after, 'frozen design', True)
        return {'paths': [], 'tracks': [], 'pore': {'radius_nm': 1}}
    monkeypatch.setattr(md_ion_paths, 'ion_paths', extract)
    response = asyncio.run(routes_md.md_ion_paths_route('P1', before, after))
    assert response.status_code == 200
    assert response.media_type == 'application/octet-stream'
    assert struct.unpack('<I', response.body[:4])[0] == 0x4e495054


def test_invalid_window_reports_input_error():
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes_md.md_ion_paths_route('P1', 0, 200))
    assert error.value.status_code == 422


def test_progress_reports_every_worker_stage_and_is_request_scoped(monkeypatch, tmp_path):
    job = SimpleNamespace(package_dir=lambda _: tmp_path)
    monkeypatch.setattr(routes_md, '_load_job', lambda _: job)
    monkeypatch.setattr(routes_md, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes_md, '_md_segment_dcds', lambda _: [])
    monkeypatch.setattr(routes_md, '_md_snapshot_design', lambda _: 'frozen')
    def extract(*args, progress, **kwargs):
        for name in ('topology', 'coordinates', 'rmsf', 'atomistic_average', 'surface'):
            progress(name, 5, 10)
            live = asyncio.run(routes_md.md_ion_paths_progress_route('P1', 'request-A'))
            assert live['state'] == 'running'
            assert live['stages'][-1]['done'] == 5
            progress(name, 10, 10)
        return {'paths': [], 'tracks': []}
    monkeypatch.setattr(md_ion_paths, 'ion_paths', extract)
    asyncio.run(routes_md.md_ion_paths_route('P1', 10, 200, 'request-A'))
    complete = asyncio.run(routes_md.md_ion_paths_progress_route('P1', 'request-A'))
    assert complete['state'] == 'done'
    assert complete['stages'][-1]['stage'] == 'serialize'
    assert asyncio.run(routes_md.md_ion_paths_progress_route('P1', 'request-B'))['state'] == 'pending'
