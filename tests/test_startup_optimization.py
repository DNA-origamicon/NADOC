"""Startup work stays off the loop, shares reads, and isolates document state."""
import asyncio
import threading

from backend.api.startup_cache import coalesce_job_reads


def test_engine_probe_runs_off_loop_and_is_cached(monkeypatch):
    from backend.api import routes_engines as routes
    started, release = threading.Event(), threading.Event()
    calls = []

    def probe():
        calls.append(threading.get_ident())
        started.set()
        assert release.wait(5)
        return {"ready": True}

    monkeypatch.setattr(routes, "engines_status", probe)

    async def scenario():
        a = asyncio.create_task(routes.get_engines_status())
        try:
            assert await asyncio.to_thread(started.wait, 5)
            b = asyncio.create_task(routes.get_engines_status())
            await asyncio.sleep(0)
            assert not a.done()  # loop is responsive while the probe is blocked
        finally:
            release.set()
        assert await a == await b == {"ready": True}
        assert await routes.get_engines_status() == {"ready": True}
        assert len(calls) == 1
        assert calls[0] != threading.get_ident()
        await routes.get_engines_status(refresh=True)
        assert len(calls) == 2

    asyncio.run(scenario())


def test_job_reads_share_work_but_not_results_or_documents(monkeypatch, tmp_path):
    from backend.api import assembly, state
    from backend.api.doc_context import get_current_doc, set_current_doc, reset_current_doc
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(state, "revision", lambda: 1)

    async def scenario():
        release = asyncio.Event()
        calls = []

        @coalesce_job_reads
        async def read():
            calls.append(get_current_doc())
            await release.wait()
            return [{"doc": get_current_doc()}]

        a = asyncio.create_task(read())
        b = asyncio.create_task(read())
        token = set_current_doc("other-tab")
        c = asyncio.create_task(read())
        reset_current_doc(token)
        for _ in range(100):
            if len(calls) == 2:
                break
            await asyncio.sleep(.001)
        assert len(calls) == 2
        release.set()
        first, second, other = await asyncio.gather(a, b, c)
        assert first == second and first != other
        first[0]["doc"] = "changed"
        assert first != second
        await read()  # no stale result survives a completed read
        assert len(calls) == 3

    asyncio.run(scenario())


def test_unified_list_uses_engine_reads_and_tolerates_one_failure(monkeypatch, tmp_path):
    from backend.api import assembly, routes_simulate as routes
    from backend.api import routes_oxdna, routes_lammps, routes_mrdna, routes_cando, routes_snupi, routes_blade, routes_md
    from backend.core import sim_jobs
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes, "_finish_simulate_nodes", lambda nodes, *_: nodes)
    calls = []
    for engine, module in [('oxdna', routes_oxdna), ('lammps', routes_lammps), ('mrdna', routes_mrdna), ('cando', routes_cando), ('snupi', routes_snupi), ('blade', routes_blade), ('md', routes_md)]:
        async def read(engine=engine):
            calls.append(engine)
            if engine == 'blade':
                raise RuntimeError('unavailable')
            return [{"engine": engine, "size_bytes": None}]
        monkeypatch.setattr(module, f'list_{engine}_jobs', read)
        monkeypatch.setattr(sim_jobs, f'normalize_{engine}_job', lambda row: row)
    rows = asyncio.run(routes.list_simulate_jobs())
    assert len(calls) == 7 and len(rows) == 6
    assert all(row['size_bytes'] is None for row in rows)


def test_active_summary_does_not_reconcile_stopped_archived_jobs(monkeypatch, tmp_path):
    from backend.api import routes_jobs
    from backend.core import oxdna_runner
    from backend.core.oxdna_job import OxdnaJob, OxdnaStatus
    from types import SimpleNamespace
    monkeypatch.setattr(routes_jobs, '_WORKSPACE_DIR', tmp_path)
    monkeypatch.setattr(OxdnaJob, 'list_jobs', lambda *_: [SimpleNamespace(status=OxdnaStatus.stopped)])
    def unexpected(*_):
        raise AssertionError('inactive jobs must not read trajectory outputs')
    calls = []
    def reconcile(*args):
        calls.append(args)
        return unexpected(*args)
    monkeypatch.setattr(oxdna_runner, 'reconcile_oxdna_status', reconcile)
    assert routes_jobs._collect_active() == []
    assert calls == []


def test_cancelled_caller_does_not_cancel_shared_read(monkeypatch, tmp_path):
    from backend.api import assembly, state
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    monkeypatch.setattr(state, 'revision', lambda: 1)

    async def scenario():
        started, release = asyncio.Event(), asyncio.Event()
        calls = []
        @coalesce_job_reads
        async def read():
            calls.append(1)
            started.set()
            await release.wait()
            return [1]
        first = asyncio.create_task(read())
        await started.wait()
        second = asyncio.create_task(read())
        # Let second caller acquire its document revision and join the task.
        await asyncio.sleep(.02)
        first.cancel()
        try:
            await first
        except asyncio.CancelledError:
            pass
        release.set()
        assert await second == [1]
        assert len(calls) == 1
    asyncio.run(scenario())


def test_background_size_queue_deduplicates_and_serializes(monkeypatch, tmp_path):
    from backend.core import design_disk_usage as sizes
    started, release, complete = threading.Event(), threading.Event(), threading.Event()
    paths = [tmp_path / 'one', tmp_path / 'two']
    calls = []
    def walk(path):
        calls.append(path)
        if path == paths[0]:
            started.set()
            assert release.wait(5)
        else:
            complete.set()
        return 123
    monkeypatch.setattr(sizes, 'dir_size_bytes', walk)
    sizes.schedule_dir_size_warm([paths[0]])
    try:
        assert started.wait(5)
        for _ in range(10):
            sizes.schedule_dir_size_warm(paths)
        assert calls == [paths[0]]
    finally:
        release.set()
    assert complete.wait(5)
    # Wait until cache publication, not merely entry into the worker.
    import time
    for _ in range(100):
        if sizes.dir_size_bytes_cached_only(paths[1]) == 123:
            break
        time.sleep(.001)
    assert calls == paths
    assert sizes.dir_size_bytes_cached_only(paths[1]) == 123
