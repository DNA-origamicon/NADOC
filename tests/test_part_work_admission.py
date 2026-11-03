"""Deterministic shared-slot contention; real sealed annotation/preview workers."""
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from multiprocessing.shared_memory import SharedMemory
from threading import Event
from time import monotonic

from fastapi import HTTPException
import pytest

from backend.api import state, part_publication_policy as policy
from backend.api import part_immutable_display_reads as reads
from backend.api import part_immutable_deformation_preview as preview
from backend.api import part_deformation_preview_sessions as host
from backend.api.part_history_verification import _slot
from backend.api.part_work_admission import WorkAdmission
from tests.test_part_immutable_geometry_host import document as document, saved, available
from tests.test_part_immutable_deformation_preview import cleanup as cleanup, install
from tests.test_part_immutable_display_reads import context


def submit(pool, fn):
    return pool.submit(copy_context().run, fn)


def observe_wait(monkeypatch):
    waiting = Event()
    original = _slot.acquire_foreground
    def acquire(*, deadline, check):
        calls = 0
        def observed():
            nonlocal calls
            check()
            calls += 1
            if calls > 1:
                waiting.set()  # Reservation exists before its second check.
        return original(deadline=deadline, check=observed)
    monkeypatch.setattr(_slot, 'acquire_foreground', acquire)
    return waiting


@pytest.mark.parametrize('annotation', ['view-volumes', 'dimensions', 'readiness'])
@pytest.mark.parametrize('foreground', ['design', 'geometry', 'design-display', 'prepare'])
def test_foreground_waits_for_real_annotation_cleanup(document, monkeypatch, annotation, foreground):
    _, origin = install(document, 'bend')
    before = saved(document[1])
    captured = context(document)
    draining, release, closed = Event(), Event(), Event()
    children = []
    original = reads.DisplayReadWorker
    class Worker(original):
        def __init__(self, ticket, operation):
            self.background = operation['read'] == annotation
            if not self.background:
                assert closed.is_set()
            super().__init__(ticket, operation)
            children.append((self, self._input.name, self._output.name))
        def close(self):
            if self.background:
                draining.set()
                assert release.wait(3)
            super().close()
            if self.background:
                closed.set()
    monkeypatch.setattr(reads, 'DisplayReadWorker', Worker)
    original_preview = preview.PreviewWorker
    def preview_worker(*args):
        assert closed.is_set()
        child = original_preview(*args)
        children.append((child, child._input.name, child._output.name))
        return child
    monkeypatch.setattr(preview, 'PreviewWorker', preview_worker)
    waiting = observe_wait(monkeypatch)
    with ThreadPoolExecutor(2) as pool:
        background = submit(pool, lambda: reads.read(captured, annotation, Event()))
        try:
            assert draining.wait(2)
            start = monotonic()
            interactive = submit(pool, lambda: host.prepare(origin) if foreground == 'prepare'
                                 else reads.read(captured, foreground, Event()))
            reserved = waiting.wait(2)
            if interactive.done(): interactive.result()
            assert reserved
            assert not interactive.done() and not closed.is_set()
            # Neither another poll nor another foreground request may overtake it.
            with pytest.raises(HTTPException) as error:
                reads.read(captured, annotation, Event())
            assert error.value.status_code == 429
            with pytest.raises(HTTPException) as error:
                reads.read(captured, 'design', Event())
            assert error.value.status_code == 429
        finally:
            release.set()
        assert background.result(timeout=3).status_code == 200
        result = interactive.result(timeout=4)
        assert (result['preview_id'] == origin['preview_id'] if foreground == 'prepare'
                else result.status_code == 200)
        assert monotonic() - start < reads.TIME_BUDGET
    assert saved(document[1]) == before
    for child, *names in children:
        assert child._closed and child._process_closed
        for name in names:
            with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('foreground', ['design', 'prepare'])
@pytest.mark.parametrize('change', ['cancel', 'source', 'revision', 'session', 'policy', 'gate', 'deadline'])
def test_waiter_retires_without_allocating_or_releasing_background(document, monkeypatch, foreground, change):
    _, origin = install(document, 'bend')
    captured, cancelled = context(document), Event()
    waiting = observe_wait(monkeypatch)
    monkeypatch.setattr(reads, 'DisplayReadWorker', lambda *a: pytest.fail('Waiter allocated'))
    monkeypatch.setattr(preview, 'PreviewWorker', lambda *a: pytest.fail('Waiter allocated'))
    if change == 'deadline':
        monkeypatch.setattr(reads, 'TIME_BUDGET', .1)
        monkeypatch.setattr(preview, 'TIME_BUDGET', .1)
    assert _slot.acquire(blocking=False, background=True)
    try:
        with ThreadPoolExecutor(1) as pool:
            work = submit(pool, lambda: host.prepare(origin) if foreground == 'prepare'
                          else reads.read(captured, 'design', cancelled))
            assert waiting.wait(2)
            if change == 'cancel':
                if foreground == 'prepare': host.cancel(origin)
                else: cancelled.set()
            elif change == 'source': document[1].design = None
            elif change == 'revision': document[1].revision += 1
            elif change == 'session': state.drop_doc(document[0])
            elif change == 'policy': policy._install_configuration(policy.current_configuration())
            elif change == 'gate': monkeypatch.setattr(preview.authority, 'ENABLED', False)
            with pytest.raises(HTTPException) as error: work.result(timeout=2)
            expected = (408 if change == 'deadline' else
                        403 if foreground == 'prepare' and change in {'source', 'session'} else 409)
            assert error.value.status_code == expected
            assert not _slot.acquire(blocking=False)
            if foreground == 'prepare': assert document[0] not in host._entries
    finally:
        _slot.release()
    available()


def test_ordinary_admission_is_fail_fast_and_overrelease_refuses():
    slot = WorkAdmission()
    assert slot.acquire(blocking=False)
    assert not slot.acquire_foreground(deadline=monotonic() + 5, check=lambda: None)
    assert not slot.acquire(blocking=False, background=True)
    slot.release()
    with pytest.raises(ValueError): slot.release()
    assert slot.acquire(blocking=False)
    slot.release()


def test_waiting_time_is_charged_to_supervisor(document, monkeypatch):
    install(document, 'bend')
    captured = context(document)
    waiting = observe_wait(monkeypatch)
    assert _slot.acquire(blocking=False, background=True)
    def supervise(job, ticket, factory, seconds):
        try:
            assert 0 < seconds < reads.TIME_BUDGET - .03
            return {'status': 'ready', 'candidate': {}}
        finally:
            _slot.release()
    monkeypatch.setattr(reads, 'supervise', supervise)
    with ThreadPoolExecutor(1) as pool:
        work = submit(pool, lambda: reads.read(captured, 'design', Event()))
        try:
            assert waiting.wait(2)
            Event().wait(.04)
        finally:
            _slot.release()
        assert work.result(timeout=2).status_code == 200
    available()


@pytest.mark.parametrize('foreground', ['design', 'prepare'])
def test_activity_read_yields_its_slot_after_drain(document, monkeypatch, tmp_path, foreground):
    import asyncio
    from fastapi import Request
    from backend.api import assembly, part_strict_activity_reads as activity
    from backend.api.part_strict_reads import CONTEXT_KEY, StrictRequestContext
    from backend.core.activity_evidence_io import Evidence
    from tests.test_part_strict_http import scope
    _, origin = install(document, 'twist')
    captured = context(document)
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    proc = tmp_path / 'proc'; proc.mkdir()
    monkeypatch.setattr(activity, 'Evidence', lambda **kwargs: Evidence(proc, **kwargs))
    entered, release, closed = Event(), Event(), Event()
    original = activity._read
    def held(*args):
        result = original(*args)
        entered.set()
        assert release.wait(3)
        closed.set()
        return result
    monkeypatch.setattr(activity, '_read', held)
    waiting = observe_wait(monkeypatch)
    request_scope = scope(document[0], '/api/jobs/active', 'GET')
    request_scope[CONTEXT_KEY] = StrictRequestContext(document[0], captured.generation)
    async def receive():
        await asyncio.sleep(.01)
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    with ThreadPoolExecutor(2) as pool:
        background = submit(pool, lambda: asyncio.run(activity.active_jobs(Request(request_scope, receive))))
        try:
            assert entered.wait(2)
            work = submit(pool, lambda: host.prepare(origin) if foreground == 'prepare'
                          else reads.read(captured, 'design', Event()))
            assert waiting.wait(2) and not work.done() and not closed.is_set()
            assert not _slot.acquire(blocking=False, background=True)
        finally:
            release.set()
        assert background.result(timeout=3).status_code == 200
        result = work.result(timeout=3)
        assert (result['preview_id'] == origin['preview_id'] if foreground == 'prepare'
                else result.status_code == 200)
    available()


def test_async_waiter_cancellation_drains_before_return(document, monkeypatch):
    import asyncio
    from backend.api.part_async_work import thread_call
    install(document, 'bend')
    captured, cancelled = context(document), Event()
    waiting = observe_wait(monkeypatch)
    monkeypatch.setattr(reads, 'DisplayReadWorker', lambda *a: pytest.fail('Cancelled waiter allocated'))
    assert _slot.acquire(blocking=False, background=True)
    async def exercise():
        task = asyncio.create_task(thread_call(reads.read, captured, 'design', cancelled, cancelled=cancelled))
        try:
            assert await asyncio.to_thread(waiting.wait, 2)
            task.cancel()
            with pytest.raises(asyncio.CancelledError): await task
            assert cancelled.is_set()
            assert not _slot.acquire(blocking=False)
        finally:
            if not task.done():
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
    try:
        asyncio.run(exercise())
    finally:
        _slot.release()
    available()
