"""Sealed read contract, real native HTTP refresh and ownership refusals."""
import json
from multiprocessing.shared_memory import SharedMemory
from threading import Event

from fastapi import HTTPException
import pytest

from backend.api import state, part_publication_policy as policy
from backend.api import part_immutable_display_reads as reads
from backend.api import part_immutable_revision as revisions
from backend.api import part_strict_geometry_http as geometry
from backend.api import crud
from backend.core.validator import validate_design
from tests.test_part_immutable_geometry_host import document as document, saved, available
from tests.test_part_immutable_deformation_preview import cleanup as cleanup, install
from tests.test_part_strict_deformation_preview_http import client as client, enabled as enabled, PREFIX
from tests.test_part_deformation_preview_sessions import update, cancellation
from tests.test_part_deformation_preview import patch


def context(document):
    return geometry.capture_context(document[0], policy.resolve(document[0]).generation, recovering=False)


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_real_sealed_refresh_sequence(document, client, kind):
    _, origin = install(document, kind)
    opened = client.post(PREFIX, json=origin).json()
    applied = client.post(PREFIX + '/apply', json=update(opened, params=patch(kind)))
    assert applied.status_code == 200, applied.text
    receipt = applied.json()
    before = saved(document[1])
    body = cancellation(opened)
    assert client.post(PREFIX + '/status', json=body).json()['revision'] == receipt['revision']
    design = client.get('/api/design')
    assert design.status_code == 200, design.text
    projected = client.get('/api/design/geometry')
    assert projected.status_code == 200, projected.text
    revision = client.get('/api/design/revision').json()
    assert revision['has_design'] and revision['revision'] == receipt['revision']
    assert client.post(PREFIX + '/status', json=body).json()['revision'] == receipt['revision']
    assert design.json()['revision'] == projected.json()['revision'] == receipt['revision']
    assert design.json()['design']['id'] == projected.json()['design_id'] == receipt['design_id']
    private = revisions.materialize_revision(document[1].design)
    expected = crud._design_response(private, validate_design(private), full_feature_log=True,
                                    normalize_legacy=False, revision=receipt['revision'])
    assert design.json() == json.loads(crud.ORJSONResponse(expected).body)
    assert 'feature_log_payloads_partial' not in design.json()
    assert isinstance(projected.json()['nucleotides'], list)
    assert isinstance(projected.json()['helix_axes'], list)
    assert saved(document[1]) == before
    available()


@pytest.mark.parametrize('kind', ['design', 'geometry'])
@pytest.mark.parametrize('family', ['bend', 'twist'])
def test_native_read_parity_parent_ownership_and_cleanup(document, monkeypatch, kind, family):
    # Keep native current deformation geometry here (refresh fixture has a later suffix).
    from tests.test_part_deformation_preview import native_source
    private = native_source(family)
    document[1].design = revisions.prepare_geometry_revision(private)
    document[1].revision = 7
    before = saved(document[1])
    if kind == 'design':
        expected = crud._design_response(private, validate_design(private), full_feature_log=True,
                                        normalize_legacy=False, revision=7)
    else:
        monkeypatch.setattr(crud.design_state, 'get_or_404', lambda: private)
        expected = json.loads(crud.get_geometry(True, None, True).body)
        expected.update(design_id=private.id, revision=7)
    monkeypatch.setattr(reads, '_decoded_exact', lambda *a: pytest.fail('Parent decoded source'))
    monkeypatch.setattr(revisions, 'materialize_revision', lambda *a: pytest.fail('Parent materialized'))
    monkeypatch.setattr(geometry.publication, 'issue', lambda *a, **k: pytest.fail('Read issued authority'))
    children = []
    original = reads.DisplayReadWorker
    def observe(*args):
        child = original(*args)
        children.append((child, child._input.name, child._output.name))
        return child
    monkeypatch.setattr(reads, 'DisplayReadWorker', observe)
    actual = json.loads(reads.read(context(document), kind, Event()).body)
    assert actual == json.loads(crud.ORJSONResponse(expected).body) and saved(document[1]) == before
    child, *names = children[0]
    assert child._closed and child._process_closed
    for name in names:
        with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('change', ['source', 'revision', 'session', 'policy', 'gate', 'cancel'])
def test_stale_capture_never_spawns(document, monkeypatch, change):
    install(document, 'bend')
    captured = context(document)
    cancelled = Event()
    if change == 'source': document[1].design = None
    elif change == 'revision': document[1].revision += 1
    elif change == 'session': state.drop_doc(document[0])
    elif change == 'policy': policy._install_configuration(policy.current_configuration())
    elif change == 'gate': monkeypatch.setattr(geometry.publication, 'ENABLED', False)
    else: cancelled.set()
    monkeypatch.setattr(reads, 'DisplayReadWorker', lambda *a: pytest.fail('Stale read spawned'))
    with pytest.raises(HTTPException): reads.read(captured, 'design', cancelled)
    available()


@pytest.mark.parametrize('change', ['revision', 'session', 'policy', 'gate', 'cancel'])
def test_inflight_read_refuses_and_cleans_up(document, monkeypatch, change):
    install(document, 'twist')
    cancelled = Event()
    children = []
    original = reads.DisplayReadWorker
    class Changed(original):
        def start(self):
            super().start()
            if change == 'revision': document[1].revision += 1
            elif change == 'session': state.drop_doc(document[0])
            elif change == 'policy': policy._install_configuration(policy.current_configuration())
            elif change == 'gate': monkeypatch.setattr(geometry.publication, 'ENABLED', False)
            else: cancelled.set()
    def observe(*args):
        child = Changed(*args)
        children.append((child, child._input.name, child._output.name))
        return child
    monkeypatch.setattr(reads, 'DisplayReadWorker', observe)
    with pytest.raises(HTTPException): reads.read(context(document), 'geometry', cancelled)
    child, *names = children[0]
    assert child._closed and child._process_closed
    for name in names:
        with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('path', ['/api/design', '/api/design/geometry'])
def test_read_gate_queries_and_no_compatibility_fallback(document, client, monkeypatch, path):
    install(document, 'bend')
    monkeypatch.setattr(reads, 'DisplayReadWorker', lambda *a: pytest.fail('Refused read spawned'))
    assert client.get(path + '?apply_deformations=false').status_code == 422
    monkeypatch.setattr(geometry.publication, 'ENABLED', False)
    assert client.get(path).status_code == 409


def test_combined_output_budget_refuses_and_preserves_source(document, monkeypatch):
    from backend.api import part_deformation_preview_dto as display
    source, _ = install(document, 'bend')
    before = saved(document[1])
    parts, _ = reads.worker.encode_input(reads.worker.reserve_input(document[1].design),
        {'read': 'design', 'design_id': source.id, 'revision': 7})
    monkeypatch.setattr(display, 'MAX_OUTPUT_BYTES', 10)
    result = reads.project_payload(b''.join(parts))['result']
    assert result['status'] != 'ready' and result['issues'][0]['code'] == 'preview_limit'
    assert saved(document[1]) == before


@pytest.mark.parametrize('mutation', [lambda op: op.update(read='full-authority'),
    lambda op: op.update(revision=True), lambda op: op.update(verified=True),
    lambda op: op.update(design_id='another')])
def test_closed_worker_operation(document, mutation):
    source, _ = install(document, 'bend')
    operation = {'read': 'design', 'design_id': source.id, 'revision': 7}
    mutation(operation)
    parts, _ = reads.worker.encode_input(reads.worker.reserve_input(document[1].design), operation)
    result = reads.project_payload(b''.join(parts))['result']
    assert result['status'] != 'ready' and result['issues'][0]['code'] == 'display_read_input'


def test_http_disconnect_cancels_and_drains_real_read(document, monkeypatch):
    import asyncio
    from fastapi import Request
    from backend.api.part_strict_reads import CONTEXT_KEY, StrictRequestContext
    from tests.test_part_strict_http import scope
    install(document, 'bend')
    before = saved(document[1])
    started = Event()
    cancellation_events, children = [], []
    original_read, original_worker = reads.read, reads.DisplayReadWorker
    def observed(context, kind, cancelled):
        cancellation_events.append(cancelled)
        return original_read(context, kind, cancelled)
    class Held(original_worker):
        def start(self):
            super().start()
            started.set()
            assert cancellation_events[0].wait(2)
    def observed_worker(*args):
        child = Held(*args)
        children.append((child, child._input.name, child._output.name))
        return child
    monkeypatch.setattr(reads, 'read', observed)
    monkeypatch.setattr(reads, 'DisplayReadWorker', observed_worker)
    request_scope = scope(document[0], '/api/design', 'GET')
    captured = context(document)
    request_scope[CONTEXT_KEY] = StrictRequestContext(document[0], captured.generation)
    request_scope[geometry.CONTEXT_KEY] = captured
    async def receive():
        return {'type': 'http.disconnect'} if started.is_set() else {
            'type': 'http.request', 'body': b'', 'more_body': False}
    async def exercise():
        with pytest.raises(HTTPException) as error:
            await reads.design(Request(request_scope, receive))
        assert error.value.detail['code'] == 'cancelled'
    asyncio.run(exercise())
    assert saved(document[1]) == before
    child, *names = children[0]
    assert child._closed and child._process_closed
    for name in names:
        with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('family', ['bend', 'twist'])
def test_combined_native_display_parity_and_one_worker(document, monkeypatch, client, family):
    install(document, family)
    before = saved(document[1])
    design = client.get('/api/design').json()
    native_geometry = client.get('/api/design/geometry').json()
    children = []
    original = reads.DisplayReadWorker
    def observed(*args):
        child = original(*args);children.append((child, child._input.name, child._output.name));return child
    monkeypatch.setattr(reads, 'DisplayReadWorker', observed)
    monkeypatch.setattr(reads, '_decoded_exact', lambda *a: pytest.fail('Parent decoded'))
    combined = client.get('/api/design?include_geometry=true')
    assert combined.status_code == 200, combined.text
    assert combined.json() == {**design, **native_geometry}
    assert saved(document[1]) == before and len(children) == 1
    for child, *names in children:
        assert child._closed and child._process_closed
        for name in names:
            with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('query', ['include_geometry=false', 'include_geometry=1',
    'include_geometry=true&include_geometry=true'])
def test_combined_query_is_closed(document, client, query):
    install(document, 'bend')
    assert client.get('/api/design?' + query).status_code == 422
    assert client.get('/api/design/geometry?include_geometry=true').status_code == 422


def test_combined_output_is_one_budget_not_two(document, monkeypatch):
    from backend.api import part_deformation_preview_dto as display
    source, _ = install(document, 'bend')
    def project(kind):
        parts, _ = reads.worker.encode_input(reads.worker.reserve_input(document[1].design),
            {'read': kind, 'design_id': source.id, 'revision': 7})
        return reads.project_payload(b''.join(parts))['result']
    design, geometry_packet = project('design')['candidate'], project('geometry')['candidate']
    def size(value):
        budget = display.GraphBudget(max_nodes=200_000, max_bytes=2_000_000, seconds=None, clock=lambda: 0)
        budget.charge(value)
        return max(2_000_000 - budget.remaining[1], len(json.dumps(value, separators=(',', ':')).encode()))
    limit = max(size(design), size(geometry_packet)) + 100
    assert size({**design, **geometry_packet}) > limit
    monkeypatch.setattr(display, 'MAX_OUTPUT_BYTES', limit)
    assert project('design')['status'] == project('geometry')['status'] == 'ready'
    result = project('design-display')
    assert result['status'] != 'ready' and result['issues'][0]['code'] == 'preview_limit'


@pytest.mark.parametrize('change', ['revision', 'policy', 'cancel'])
def test_combined_inflight_stale_result_never_returns(document, monkeypatch, change):
    install(document, 'twist')
    cancelled = Event()
    children = []
    original = reads.DisplayReadWorker
    class Changed(original):
        def start(self):
            super().start()
            if change == 'revision': document[1].revision += 1
            elif change == 'policy': policy._install_configuration(policy.current_configuration())
            else: cancelled.set()
    def observed(*args):
        child = Changed(*args);children.append((child, child._input.name, child._output.name));return child
    monkeypatch.setattr(reads, 'DisplayReadWorker', observed)
    with pytest.raises(HTTPException): reads.read(context(document), 'design-display', cancelled)
    assert len(children) == 1
    for child, *names in children:
        assert child._closed and child._process_closed
        for name in names:
            with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()
