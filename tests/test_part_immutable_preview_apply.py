"""Sealed historical Apply uses full proof, one commit and recoverable receipt."""
from multiprocessing.shared_memory import SharedMemory

from fastapi import HTTPException
import pytest

from backend.api import state, part_publication_policy as policy
from backend.api import part_deformation_preview_sessions as host
from backend.api import part_immutable_geometry_host as geometry
from backend.api import part_immutable_geometry_worker as worker
from backend.api import part_immutable_revision as revisions
from tests.test_part_immutable_deformation_preview import cleanup as cleanup, install
from tests.test_part_immutable_geometry_host import document as document, immediate as immediate, saved, available
from tests.test_part_deformation_preview_sessions import update, cancellation
from tests.test_part_deformation_preview import patch
from tests.test_group_organization_history import _verified


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_real_apply_receipt_undo_redo_full_suffix_and_cleanup(document, monkeypatch, kind):
    source, origin = install(document, kind)
    opened = host.prepare(origin)
    _, session = document
    before = session.design
    children = []
    original = worker.GeometryEvaluationWorker
    def observed(*args):
        child = original(*args);children.append((child, child._input.name, child._output.name));return child
    monkeypatch.setattr(worker, 'GeometryEvaluationWorker', observed)
    receipt = host.apply(update(opened, params=patch(kind)))
    after = session.design
    assert after is not before and session.revision == 8
    assert list(session.history) == [before] and not session.redo
    model = revisions.materialize_revision(after)
    assert model.feature_log[1].op_snapshot.plane_b_bp == 30
    assert model.feature_log[-1].id == source.feature_log[-1].id == 'suffix'
    assert {h.id for h in model.helices} == {'h_XY_6_6'}
    _verified(model)
    # Discarding the Apply response does not republish: Status recovers receipt.
    assert {k: host.status(cancellation(opened))[k] for k in receipt} == receipt
    assert host.cancel(cancellation(opened)) == receipt
    with pytest.raises(HTTPException): host.apply(update(opened, sequence=2, params=patch(kind)))
    assert session.design is after and session.revision == 8 and len(session.history) == 1
    geometry.history('undo', expected_design_id=source.id, expected_revision=8)
    assert session.design is before
    geometry.history('redo', expected_design_id=source.id, expected_revision=9)
    assert session.design is after
    assert len(children) == 1
    for child, *names in children:
        assert child._closed and child._process_closed
        for name in names:
            with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('change', ['revision', 'source', 'session', 'policy', 'gate', 'cancel', 'expiry', 'sequence'])
def test_apply_staging_gap_cannot_publish(document, immediate, monkeypatch, change):
    source, origin = install(document, 'bend')
    opened = host.prepare(origin)
    doc, session = document
    original = geometry._stage
    def stage(*args, **kwargs):
        staged = original(*args, **kwargs)
        if change == 'revision': session.revision += 1
        elif change == 'source': session.design = revisions.prepare_geometry_revision(source)
        elif change == 'session': state.drop_doc(doc)
        elif change == 'policy': policy._install_configuration(policy.current_configuration())
        elif change == 'gate': monkeypatch.setattr(geometry.publication, 'ENABLED', False)
        elif change == 'cancel': host.cancel(cancellation(opened))
        elif change == 'expiry': host._entries[doc].expires = 0;host._expire(host._entries[doc])
        else: host._entries[doc].sequence += 1
        return staged
    monkeypatch.setattr(geometry, '_stage', stage)
    monkeypatch.setattr(host, 'publish_replacement', lambda *a, **k: pytest.fail('Stale Apply published'))
    with pytest.raises(HTTPException): host.apply(update(opened))
    assert not session.history
    available()


def test_cancel_during_commit_recovers_scalar_receipt(document, immediate, monkeypatch):
    _, origin = install(document, 'twist')
    opened = host.prepare(origin)
    original = host.publish_replacement
    def publish(*args, **kwargs):
        assert host.cancel(cancellation(opened))['status'] == 'commit_in_progress'
        return original(*args, **kwargs)
    monkeypatch.setattr(host, 'publish_replacement', publish)
    receipt = host.apply(update(opened, params=patch('twist')))
    assert host.cancel(cancellation(opened)) == receipt
    assert host._entries[document[0]].prepared is None
    assert len(document[1].history) == 1


def test_revision_failure_rolls_back_and_keeps_lease_ready(document, immediate, monkeypatch):
    _, origin = install(document, 'bend')
    opened = host.prepare(origin)
    before = saved(document[1])
    original = state._bump_revision
    def fail(session):
        original(session)
        raise RuntimeError('injected assignment failure')
    monkeypatch.setattr(state, '_bump_revision', fail)
    with pytest.raises(RuntimeError, match='injected'): host.apply(update(opened))
    assert saved(document[1]) == before
    assert host.status(cancellation(opened))['status'] == 'ready'
    available()


@pytest.mark.parametrize('fault', ['cached_index', 'source_mismatch', 'invalid_patch'])
def test_preview_or_cached_selection_never_substitutes_for_apply_proof(document, immediate, fault):
    from dataclasses import replace
    source, origin = install(document, 'bend')
    if fault == 'source_mismatch':
        source.helices[0].length_bp += 1
        document[1].design = revisions.prepare_geometry_revision(source)
    opened = host.prepare(origin)
    before = saved(document[1])
    if fault == 'cached_index':
        entry = host._entries[document[0]]
        entry.prepared = replace(entry.prepared, feature_index=0)
    params = {'params': {'kind': 'twist', 'total_degrees': 10}} if fault == 'invalid_patch' else patch('bend')
    with pytest.raises(HTTPException): host.apply(update(opened, params=params))
    assert saved(document[1]) == before
    assert host.status(cancellation(opened))['status'] == 'ready'
    available()


def test_expiry_during_commit_cannot_outlive_lease_permit(document, immediate, monkeypatch):
    from backend.api import part_publication_permit as permits
    _, origin = install(document, 'bend')
    opened = host.prepare(origin)
    before = saved(document[1])
    original = host.publish_replacement
    def expired(*args, **kwargs):
        monkeypatch.setattr(permits, 'monotonic', lambda: float('inf'))
        return original(*args, **kwargs)
    monkeypatch.setattr(host, 'publish_replacement', expired)
    with pytest.raises(HTTPException): host.apply(update(opened))
    assert saved(document[1]) == before
    available()


@pytest.mark.parametrize('kind', ['bend', 'twist'])
@pytest.mark.parametrize('background', ['view-volumes', 'dimensions', 'activity', 'readiness'])
def test_apply_waits_for_background_and_publishes_once(document, monkeypatch, tmp_path, kind, background):
    import asyncio
    from concurrent.futures import ThreadPoolExecutor
    from threading import Event
    from fastapi import Request
    from backend.api import assembly, part_immutable_display_reads as reads, part_strict_activity_reads as activity
    from backend.api.part_strict_reads import CONTEXT_KEY, StrictRequestContext
    from backend.core.activity_evidence_io import Evidence
    from tests.test_part_immutable_display_reads import context
    from tests.test_part_work_admission import submit, observe_wait
    from tests.test_part_strict_http import scope
    _, origin = install(document, kind)
    opened = host.prepare(origin)
    before = document[1].design
    captured = context(document)
    draining, release, closed = Event(), Event(), Event()
    children = []
    original = reads.DisplayReadWorker
    class Held(original):
        def close(self):
            draining.set()
            assert release.wait(3)
            super().close()
            closed.set()
    def read_worker(*args):
        child = Held(*args);children.append((child, child._input.name, child._output.name));return child
    monkeypatch.setattr(reads, 'DisplayReadWorker', read_worker)
    native = worker.GeometryEvaluationWorker
    def apply_worker(*args):
        assert closed.is_set()
        child = native(*args);children.append((child, child._input.name, child._output.name));return child
    monkeypatch.setattr(worker, 'GeometryEvaluationWorker', apply_worker)
    monkeypatch.setattr(assembly, '_WORKSPACE_DIR', tmp_path)
    proc = tmp_path / 'proc';proc.mkdir()
    monkeypatch.setattr(activity, 'Evidence', lambda **kw: Evidence(proc, **kw))
    original_activity = activity._read
    def held_activity(*args):
        result = original_activity(*args)
        draining.set()
        assert release.wait(3)
        closed.set()
        return result
    monkeypatch.setattr(activity, '_read', held_activity)
    request_scope = scope(document[0], '/api/jobs/active', 'GET')
    request_scope[CONTEXT_KEY] = StrictRequestContext(document[0], captured.generation)
    async def receive():
        await asyncio.sleep(.01)
        return {'type': 'http.request', 'body': b'', 'more_body': False}
    waiting = observe_wait(monkeypatch)
    with ThreadPoolExecutor(2) as pool:
        background_work = submit(pool, lambda: asyncio.run(activity.active_jobs(Request(request_scope, receive)))
            if background == 'activity' else reads.read(captured, background, Event()))
        try:
            assert draining.wait(2)
            work = submit(pool, lambda: host.apply(update(opened, params=patch(kind))))
            assert waiting.wait(2) and not work.done()
            assert document[1].design is before and not document[1].history
            assert not geometry._slot.acquire(blocking=False, background=True)
        finally:
            release.set()
        assert background_work.result(timeout=3).status_code == 200
        receipt = work.result(timeout=4)
    session = document[1]
    assert session.revision == 8 and list(session.history) == [before] and not session.redo
    assert {k: host.status(cancellation(opened))[k] for k in receipt} == receipt
    assert host.cancel(cancellation(opened)) == receipt
    _verified(revisions.materialize_revision(session.design))
    for child, *names in children:
        assert child._closed and child._process_closed
        for name in names:
            with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('change', ['cancel', 'source', 'revision', 'session', 'policy', 'gate', 'sequence', 'expiry', 'deadline'])
def test_waiting_apply_retires_without_publication(document, monkeypatch, change):
    from concurrent.futures import ThreadPoolExecutor
    from time import monotonic
    from tests.test_part_work_admission import submit, observe_wait
    _, origin = install(document, 'bend')
    opened = host.prepare(origin)
    before = saved(document[1])
    entry = host._entries[document[0]]
    if change == 'expiry': entry.expires = monotonic() + .1
    if change == 'deadline': monkeypatch.setattr(geometry, 'TIME_BUDGET', .1)
    monkeypatch.setattr(worker, 'GeometryEvaluationWorker', lambda *a: pytest.fail('Waiting Apply allocated'))
    monkeypatch.setattr(host, 'publish_replacement', lambda *a, **k: pytest.fail('Stale Apply published'))
    waiting = observe_wait(monkeypatch)
    assert geometry._slot.acquire(blocking=False, background=True)
    try:
        with ThreadPoolExecutor(1) as pool:
            work = submit(pool, lambda: host.apply(update(opened)))
            assert waiting.wait(2)
            if change == 'cancel': host.cancel(cancellation(opened))
            elif change == 'source': document[1].design = None
            elif change == 'revision': document[1].revision += 1
            elif change == 'session': state.drop_doc(document[0])
            elif change == 'policy': policy._install_configuration(policy.current_configuration())
            elif change == 'gate': monkeypatch.setattr(geometry.publication, 'ENABLED', False)
            elif change == 'sequence': entry.sequence += 1
            with pytest.raises(HTTPException): work.result(timeout=2)
            assert not geometry._slot.acquire(blocking=False)
            assert list(document[1].history) == before[2] and list(document[1].redo) == before[3]
    finally:
        geometry._slot.release()
    available()


@pytest.mark.parametrize('change', ['cancel', 'policy', 'deadline'])
def test_inflight_sealed_apply_drains_before_releasing(document, monkeypatch, change):
    _, origin = install(document, 'bend')
    opened = host.prepare(origin)
    before = saved(document[1])
    children = []
    original = worker.GeometryEvaluationWorker
    class Changed(original):
        def start(self):
            super().start()
            if change == 'cancel': host.cancel(cancellation(opened))
            elif change == 'policy': policy._install_configuration(policy.current_configuration())
            else:
                from backend.api import part_verification_jobs as jobs
                monkeypatch.setattr(jobs, 'monotonic', lambda: float('inf'))
        def close(self):
            assert not geometry._slot.acquire(blocking=False)
            super().close()
    def observed(*args):
        child = Changed(*args);children.append((child, child._input.name, child._output.name));return child
    monkeypatch.setattr(worker, 'GeometryEvaluationWorker', observed)
    with pytest.raises(HTTPException): host.apply(update(opened, params=patch('bend')))
    assert saved(document[1]) == before
    assert len(children) == 1
    for child, *names in children:
        assert child._closed and child._process_closed
        for name in names:
            with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()
