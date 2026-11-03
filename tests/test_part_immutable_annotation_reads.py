"""Sealed annotation reads with populated persisted display state."""
from multiprocessing.shared_memory import SharedMemory
from threading import Event

from fastapi import HTTPException
import pytest

from backend.api import state, part_publication_policy as policy
from backend.api import part_immutable_display_reads as reads
from backend.api import part_immutable_revision as revisions
from backend.api import part_strict_geometry_http as geometry
from backend.api import routes_dimensions, routes_display_metadata
from backend.core.dimensions import Dimension
from tests.deformation_history_app import fixture
from tests.test_part_view_volume_preservation import volumes
from tests.test_part_immutable_geometry_host import document as document, saved, available
from tests.test_part_strict_deformation_preview_http import client as client
from tests.test_part_immutable_display_reads import context

KINDS = ['view-volumes', 'dimensions']


def install(document, family='bend', populated=False):
    design = fixture(family)
    if populated:
        design.view_volumes = volumes()
        design.dimensions = [Dimension(id='measure-1', name='Hidden measurement',
            a=(1, 2, 3), b=(4, 6, 9), visible=False)]
    document[1].design = revisions.prepare_geometry_revision(design)
    document[1].revision = 7
    document[1].redo.append(document[1].design)
    return design


@pytest.mark.parametrize('family', ['bend', 'twist'])
@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('populated', [False, True])
def test_native_http_parity_and_sealed_ownership(document, client, monkeypatch, family, kind, populated):
    design = install(document, family, populated)
    before = saved(document[1])
    monkeypatch.setattr(state, 'get_or_404', lambda: design)
    monkeypatch.setattr(state, 'revision', lambda: 7)
    expected = (routes_dimensions.get_dimensions('design', design.id) if kind == 'dimensions'
                else routes_display_metadata.get_view_volumes(design.id))
    monkeypatch.setattr(state, 'get_or_404', lambda: pytest.fail('Compatibility fallback'))
    monkeypatch.setattr(reads, '_decoded_exact', lambda *a: pytest.fail('Parent decoded'))
    monkeypatch.setattr(revisions, 'materialize_revision', lambda *a: pytest.fail('Parent materialized'))
    monkeypatch.setattr(geometry.publication, 'issue', lambda *a, **k: pytest.fail('Read issued authority'))
    result = client.get('/api/design/' + kind, params={'document_id': design.id})
    assert result.status_code == 200, result.text
    assert result.json() == expected and saved(document[1]) == before
    available()


def test_optional_view_identity_and_required_dimension_identity(document, client, monkeypatch):
    install(document)
    assert client.get('/api/design/view-volumes').json() == {'view_volumes': [], 'revision': 7}
    monkeypatch.setattr(reads, 'DisplayReadWorker', lambda *a: pytest.fail('Missing identity spawned'))
    assert client.get('/api/design/dimensions').status_code == 422


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('query,status', [('document_id=wrong', 409), ('document_id=', 409),
    ('document_id=a&document_id=b', 422), ('assembly=true', 422), ('verified=true', 422)])
def test_invalid_selection_never_spawns(document, client, monkeypatch, kind, query, status):
    install(document)
    monkeypatch.setattr(reads, 'DisplayReadWorker', lambda *a: pytest.fail('Invalid selection spawned'))
    assert client.get('/api/design/' + kind + '?' + query).status_code == status


@pytest.mark.parametrize('kind', KINDS)
def test_gate_and_mutation_paths_stay_closed(document, client, monkeypatch, kind):
    design = install(document)
    monkeypatch.setattr(reads, 'DisplayReadWorker', lambda *a: pytest.fail('Refusal spawned'))
    for method in ('patch', 'put', 'post', 'delete'):
        assert getattr(client, method)('/api/design/' + kind).status_code == 403
    monkeypatch.setattr(geometry.publication, 'ENABLED', False)
    assert client.get('/api/design/' + kind, params={'document_id': design.id}).status_code == 409


@pytest.mark.parametrize('kind', KINDS)
@pytest.mark.parametrize('change', ['source', 'session', 'revision', 'policy', 'gate', 'cancel'])
def test_inflight_change_refuses_and_reaps(document, monkeypatch, kind, change):
    install(document, populated=True)
    cancelled, children = Event(), []
    original = reads.DisplayReadWorker
    class Changed(original):
        def start(self):
            super().start()
            if change == 'source': document[1].design = None
            elif change == 'session': state.drop_doc(document[0])
            elif change == 'revision': document[1].revision += 1
            elif change == 'policy': policy._install_configuration(policy.current_configuration())
            elif change == 'gate': monkeypatch.setattr(geometry.publication, 'ENABLED', False)
            else: cancelled.set()
    def observe(*args):
        child = Changed(*args)
        children.append((child, child._input.name, child._output.name))
        return child
    monkeypatch.setattr(reads, 'DisplayReadWorker', observe)
    with pytest.raises(HTTPException):
        reads.read(context(document), kind, cancelled)
    child, *names = children[0]
    assert child._closed and child._process_closed
    for name in names:
        with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('kind', KINDS)
def test_output_budget_refuses(document, monkeypatch, kind):
    from backend.api import part_deformation_preview_dto as display
    design = install(document, populated=True)
    before = saved(document[1])
    parts, _ = reads.worker.encode_input(reads.worker.reserve_input(document[1].design),
        {'read': kind, 'design_id': design.id, 'revision': 7})
    monkeypatch.setattr(display, 'MAX_OUTPUT_BYTES', 10)
    result = reads.project_payload(b''.join(parts))['result']
    assert result['status'] != 'ready' and result['issues'][0]['code'] == 'preview_limit'
    assert saved(document[1]) == before

