"""Slow status scans must leave the shared HTTP event loop available to part loads."""
import asyncio
import importlib
import threading

import httpx
import pytest

from backend.api.main import app
from backend.api.doc_context import get_current_doc


@pytest.mark.parametrize('engine,model', [
    ('md', 'MdJob'), ('mrdna', 'MrdnaJob'), ('oxdna', 'OxdnaJob'),
    ('cando', 'CandoJob'), ('snupi', 'SnupiJob'), ('blade', 'BladeJob'),
    ('lammps', 'LammpsJob'),
])
def test_health_responds_while_job_list_is_reading_disk(monkeypatch, engine, model):
    route = importlib.import_module(f'backend.api.routes_{engine}')
    started, release = threading.Event(), threading.Event()
    seen_docs = []

    def slow_list(*args):
        seen_docs.append(get_current_doc())
        started.set()
        release.wait(2)
        return []

    monkeypatch.setattr(getattr(route, model), 'list_jobs', slow_list)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            listing = asyncio.create_task(client.get(f'/api/{engine}/jobs', headers={'X-NADOC-Doc': '__e2e__poll_context'}))
            try:
                assert await asyncio.to_thread(started.wait, 1)
                health = await asyncio.wait_for(client.get('/api/health'), 0.5)
                assert health.status_code == 200
                assert not listing.done(), 'status scan blocked health until the scan finished'
            finally:
                release.set()
                result = await listing
            assert result.status_code == 200, result.text
            assert result.json() == []
    asyncio.run(run())
    assert seen_docs == ['__e2e__poll_context']


def test_md_manifest_decoration_also_leaves_event_loop_free(monkeypatch):
    from backend.api import routes_md
    started, release = threading.Event(), threading.Event()
    monkeypatch.setattr(routes_md.MdJob, 'list_jobs', lambda *_: [])

    def slow_rows(*args):
        started.set()
        release.wait(2)
        return [], []

    monkeypatch.setattr(routes_md, '_md_job_list_rows', slow_rows)

    async def run():
        listing = asyncio.create_task(routes_md.list_md_jobs())
        try:
            assert await asyncio.to_thread(started.wait, 1)
            await asyncio.sleep(0)
            assert not listing.done(), 'manifest processing occupied the event loop'
        finally:
            release.set()
            await listing
    asyncio.run(run())


@pytest.mark.parametrize('path', ['/api/md/queue', '/api/simulate/jobs'])
def test_other_polled_catalogs_do_not_block_health(monkeypatch, path, tmp_path):
    from backend.api import assembly, routes_md_queue
    from backend.core.oxdna_job import OxdnaJob

    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    monkeypatch.setattr(routes_md_queue, '_WORKSPACE_DIR', tmp_path)
    started, release = threading.Event(), threading.Event()

    def slow_list(*args):
        started.set()
        release.wait(2)
        return []

    model = routes_md_queue.MdJob if path.endswith('/queue') else OxdnaJob
    monkeypatch.setattr(model, 'list_jobs', slow_list)

    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            listing = asyncio.create_task(client.get(path))
            try:
                assert await asyncio.to_thread(started.wait, 1)
                health = await asyncio.wait_for(client.get('/api/health'), 0.5)
                assert health.status_code == 200
                assert not listing.done()
            finally:
                release.set()
                result = await listing
            assert result.status_code == 200, result.text
    asyncio.run(run())
