"""Private staged revision display, distinct from historical feature controls."""
from multiprocessing.shared_memory import SharedMemory

from fastapi import HTTPException
import pytest

from backend.api import part_immutable_geometry_host as host
from backend.api import part_immutable_geometry_worker as worker
from backend.api import part_immutable_revision as revisions
from backend.api import state, part_publication_policy as policy
from backend.core.part_dna_comparison import project_for_deformation_preview
from tests.test_part_deformation_preview import native_source
from tests.test_part_immutable_geometry_host import document as document, immediate as immediate, saved, available


def stage(document, kind):
    _, session = document
    source = native_source(kind)
    session.design = revisions.prepare_geometry_revision(source)
    session.revision = 7
    session.redo.append(session.design)
    return host._stage('edit', len(source.feature_log) - 1, {'plane_b_bp': 30},
        expected_kind='deformation', expected_feature_id=source.feature_log[-1].id,
        expected_design_id=source.id, expected_revision=7)


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_real_projection_matches_native_display_and_keeps_source(document, immediate, monkeypatch, kind):
    staged = stage(document, kind)
    _, session = document
    before = saved(session)
    # Expected serialization uses the same independent native display boundary.
    expected = project_for_deformation_preview(revisions.materialize_revision(staged.prepared))
    monkeypatch.setattr(revisions, 'materialize_revision', lambda *a, **k: pytest.fail('API thread materialized'))
    monkeypatch.setattr(worker, '_decoded_exact', lambda *a, **k: pytest.fail('API thread decoded'))
    children = []
    original = worker.GeometryProjectionWorker
    def observed(*args):
        child = original(*args)
        children.append((child, child._input.name, child._output.name))
        return child
    monkeypatch.setattr(worker, 'GeometryProjectionWorker', observed)
    monkeypatch.setattr(host.publication, 'issue', lambda *a, **k: pytest.fail('Display issued permit'))
    packet = host._project_staged(staged)
    assert packet == {'stage': 'staged_revision', 'physical_validity': False,
        'design_id': staged.design_id, 'feature_id': staged.feature_id, 'component': expected}
    assert saved(session) == before
    assert len(children) == 1
    child, *names = children[0]
    assert child._closed and child._process_closed
    for name in names:
        with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('change', ['revision', 'source', 'session', 'policy', 'gate', 'cancel', 'deadline'])
def test_changed_staging_refuses_before_projection_spawn(document, immediate, monkeypatch, change):
    doc, session = document
    staged = stage(document, 'bend')
    if change == 'revision': session.revision += 1
    elif change == 'source': session.design = staged.prepared
    elif change == 'session': state.drop_doc(doc)
    elif change == 'policy': policy._install_configuration(policy.current_configuration())
    elif change == 'gate': monkeypatch.setattr(host.publication, 'ENABLED', False)
    elif change == 'cancel': staged.cancelled.set()
    else: monkeypatch.setattr(host, 'monotonic', lambda: float('inf'))
    monkeypatch.setattr(worker, 'GeometryProjectionWorker', lambda *a: pytest.fail('Stale projection spawned'))
    with pytest.raises(HTTPException): host._project_staged(staged)
    assert not session.history
    available()


def test_projection_output_budget_refuses_without_canonical_mutation(document, immediate, monkeypatch):
    from backend.api import part_deformation_preview_dto as display
    staged = stage(document, 'twist')
    before = saved(document[1])
    parts, _ = worker.encode_input(worker.reserve_input(staged.prepared), {
        'projection': 'staged_deformation_v1', 'feature_id': staged.feature_id, 'design_id': staged.design_id})
    monkeypatch.setattr(display, 'MAX_OUTPUT_BYTES', 10)
    result = worker.project_payload(b''.join(parts))['result']
    assert result['status'] != 'ready' and result['issues'][0]['code'] == 'preview_limit'
    assert saved(document[1]) == before


@pytest.mark.parametrize('change', ['revision', 'source', 'session', 'policy', 'gate', 'cancel', 'deadline'])
def test_projection_inflight_change_refuses_and_releases_worker(document, immediate, monkeypatch, change):
    doc, session = document
    staged = stage(document, 'bend')
    original = worker.GeometryProjectionWorker
    children = []

    class ChangedWorker(original):
        def start(self):
            super().start()
            if change == 'revision': session.revision += 1
            elif change == 'source': session.design = staged.prepared
            elif change == 'session': state.drop_doc(doc)
            elif change == 'policy': policy._install_configuration(policy.current_configuration())
            elif change == 'gate': monkeypatch.setattr(host.publication, 'ENABLED', False)
            elif change == 'cancel': staged.cancelled.set()
            else: monkeypatch.setattr(host, 'monotonic', lambda: float('inf'))

    def observed(*args):
        child = ChangedWorker(*args)
        children.append((child, child._input.name, child._output.name))
        return child

    monkeypatch.setattr(worker, 'GeometryProjectionWorker', observed)
    with pytest.raises(HTTPException): host._project_staged(staged)
    assert len(children) == 1 and not session.history
    child, *names = children[0]
    assert child._closed and child._process_closed
    for name in names:
        with pytest.raises(FileNotFoundError): SharedMemory(name=name)
    available()


@pytest.mark.parametrize('patch', [{'feature_id': 'missing'}, {'design_id': 'other'},
    {'projection': 'edit'}, {'verified': True}])
def test_projection_rejects_changed_or_authoritative_operation(document, immediate, patch):
    staged = stage(document, 'bend')
    operation = {'projection': 'staged_deformation_v1', 'feature_id': staged.feature_id,
                 'design_id': staged.design_id, **patch}
    parts, _ = worker.encode_input(worker.reserve_input(staged.prepared), operation)
    result = worker.project_payload(b''.join(parts))['result']
    assert result['status'] != 'ready'
    assert not document[1].history
