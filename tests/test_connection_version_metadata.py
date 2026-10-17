"""Applied candidate metadata remains replayable without implying disconnection."""

import pytest

from tests.test_part_connection_compose import document as document

from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import append, authored, creation, native_prefix as native_prefix, proof
from tests.test_part_connection_direct import pending, params as direct_params
from tests.test_part_connection_inverse import apply_params


def metadata(source, action, identity='candidate', **extra):
    from backend.api.part_connection_version_commands import affected_versions
    version = next(v for v in source.connection_versions if v.id == identity)
    values = {'_proof_version': 1, 'connection_version_contract': 2, 'action': action,
              'version_id': identity, 'overhang_a_id': version.overhang_a_id,
              'overhang_b_id': version.overhang_b_id, **extra}
    values['affected_version_ids'] = affected_versions(source, values)
    return values


def geometry(source):
    return {k: v for k, v in authored(source).items() if k != 'connection_versions'}


@pytest.mark.parametrize('family', ['direct', 'root-to-root-ssdna-linker', 'root-to-root-indirect'])
@pytest.mark.parametrize('operation', ['rename', 'parameters', 'flag', 'delete'])
def test_applied_metadata_preserves_geometry_and_replays(application_prefix, family, operation):
    source = pending(application_prefix, 'root-to-root' if family == 'direct' else family)
    values = direct_params(source) if family == 'direct' else apply_params(source, 'candidate')
    source = append(source, 'overhang-bulk', values, 'apply')
    before = source.model_dump_json()
    action = 'connection-version-delete' if operation == 'delete' else 'connection-version-patch'
    patches = {'rename': {'name': ' Saved choice '}, 'parameters': {'overhang_a_seq': ' gCa? ', 'bridge_length': 9,
               'connection_type': 'end-to-end-indirect'}, 'flag': {'applied': False}}
    values = metadata(source, action, **({'patch': patches[operation]} if operation != 'delete' else {}))
    changed = append(source, 'overhang-bulk', values, 'metadata')
    assert geometry(changed) == geometry(source)
    assert proof(changed)['status'] == 'verified'
    assert source.model_dump_json() == before
    if operation == 'delete':
        assert not changed.connection_versions
    elif operation == 'flag':
        assert not changed.connection_versions[0].applied
    elif operation == 'rename':
        assert changed.connection_versions[0].name == 'Saved choice'
    else:
        assert changed.connection_versions[0].overhang_a_seq == 'GCA'
        assert changed.connection_versions[0].bridge_length == 9


def test_applied_create_and_flag_mutex_have_exact_metadata_dependencies(application_prefix):
    from backend.api.part_connection_version_commands import affected_versions
    from backend.api.part_proof_commands import dependencies
    from backend.core.part_dependencies import Resource
    source = pending(application_prefix)
    values = {**creation(source, version_id='second', applied=True), 'action': 'connection-version-create',
              'connection_version_contract': 2}
    values['affected_version_ids'] = affected_versions(source, values)
    source = append(source, 'overhang-bulk', values, 'second')
    before = source.model_dump_json()
    values = metadata(source, 'connection-version-patch', patch={'applied': True})
    deps = dependencies('overhang-bulk', values)
    assert {Resource('connection_version', v.id) for v in source.connection_versions} <= deps.reads & deps.writes
    changed = append(source, 'overhang-bulk', values, 'activate')
    assert [v.applied for v in changed.connection_versions] == [True, False]
    assert geometry(changed) == geometry(source)
    assert proof(changed)['status'] == 'verified'
    assert source.model_dump_json() == before


def test_metadata_refuses_incomplete_mutex_set(application_prefix):
    from backend.api.part_connection_version_commands import build
    from backend.core.part_command_errors import ReferenceResolutionError
    source = pending(pending(application_prefix), identity='second')
    values = metadata(source, 'connection-version-patch', patch={'applied': True})
    values['affected_version_ids'] = ['candidate']
    with pytest.raises(ReferenceResolutionError):
        build(source, values)


@pytest.fixture
def applied_document(document, monkeypatch):
    from backend.api import part_connection_version_commands as commands
    monkeypatch.setattr(commands, 'APPLIED_METADATA_ENABLED', True)
    source = pending(document.source)
    source = append(source, 'overhang-bulk', direct_params(source), 'apply')
    document.source = source
    document.session.design = source
    return document


@pytest.mark.parametrize('operation', ['create', 'rename', 'flag', 'delete'])
def test_metadata_http_recording_is_one_undo_and_replay(applied_document, operation, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import state, routes_connection_versions as routes
    doc = applied_document
    before = doc.source.model_dump_json()
    app = FastAPI()
    app.include_router(routes.router)
    with monkeypatch.context() as guarded:
        def forbidden(*args, **kwargs):
            pytest.fail('metadata mutation attempted topology postprocessing')
        guarded.setattr(state, 'reconcile_cluster_membership', forbidden)
        guarded.setattr(state, '_retry_pending_ligations', forbidden)
        with TestClient(app) as client:
            if operation == 'create':
                body = {k: v for k, v in creation(doc.source, applied=True).items()
                        if k not in {'_proof_version', 'connection_version_contract', 'version_id', 'created_at'}}
                response = client.post('/design/connection-versions', json=body)
            elif operation == 'delete':
                response = client.delete('/design/connection-versions/candidate')
            else:
                response = client.patch('/design/connection-versions/candidate', json=(
                    {'name': 'Renamed'} if operation == 'rename' else {'applied': False}))
    assert response.status_code == (201 if operation == 'create' else 200), response.text
    result = doc.session.design
    assert result.feature_log[-1].params['connection_version_contract'] == 2
    assert geometry(result) == geometry(doc.source)
    assert len(doc.session.history) == 1 and doc.session.revision == 5
    assert proof(result)['status'] == 'verified'
    assert doc.source.model_dump_json() == before
    state.undo()
    assert authored(doc.session.design) == authored(doc.source)
    state.redo()
    assert authored(doc.session.design) == authored(result)


@pytest.mark.parametrize('operation', ['create', 'patch', 'delete'])
def test_metadata_failed_publication_preserves_held_source(applied_document, operation, monkeypatch):
    from backend.api import state, part_connection_version_commands as commands
    doc = applied_document
    before = doc.source.model_dump_json()
    doc.session.redo.append(doc.source.model_copy(deep=True))
    def fail(*args, **kwargs):
        raise RuntimeError('metadata publication failed')
    monkeypatch.setattr(state, 'validate_design', fail)
    choices = (creation(doc.source, applied=True) if operation == 'create' else {'applied': False} if operation == 'patch' else {})
    if operation == 'create':
        choices = {k: v for k, v in choices.items() if k not in {'_proof_version', 'connection_version_contract', 'version_id', 'created_at'}}
    with pytest.raises(RuntimeError, match='metadata publication failed'):
        commands.try_record('connection-version-' + operation, choices, version_id=None if operation == 'create' else 'candidate')
    assert doc.source.model_dump_json() == before
    assert doc.session.design.model_dump_json() == before
    assert not doc.session.history and len(doc.session.redo) == 1 and doc.session.revision == 4


@pytest.mark.parametrize('guard', ['cursor', 'loadout'])
def test_metadata_document_guard_preserves_source(applied_document, guard):
    from fastapi import HTTPException
    from backend.api import part_connection_version_commands as commands
    from backend.core.models import DesignLoadout
    doc = applied_document
    if guard == 'cursor':
        doc.source.feature_log_cursor = 0
    else:
        doc.source.loadouts = [DesignLoadout(id='locked', name='Locked', protected=True)]
        doc.source.active_loadout_id = 'locked'
    before = doc.source.model_dump_json()
    with pytest.raises(HTTPException):
        commands.try_record(commands.PATCH, {'name': 'Rejected'}, version_id='candidate')
    assert doc.session.design.model_dump_json() == before
    assert not doc.session.history


def test_applied_metadata_transport_and_independent_worker(application_prefix):
    from backend.api.part_verification_worker import VerificationWorker
    from backend.core.part_verification_capture import capture
    from backend.core.models import Design
    source = append(application_prefix, 'connection-version-create', creation(application_prefix,
        connection_type='root-to-root', overhang_a_seq='A' * 12, overhang_b_seq='T' * 12), 'candidate')
    source = append(source, 'overhang-bulk', direct_params(source), 'apply')
    source = append(source, 'overhang-bulk', metadata(source, 'connection-version-delete'), 'delete-metadata')
    transported = Design.model_validate_json(source.model_dump_json())
    worker = VerificationWorker(capture(transported))
    try:
        worker.start()
        assert worker.wait(5)
        assert worker.result()['status'] == 'verified'
    finally:
        worker.close()


def test_edited_applied_parameters_feed_next_native_apply(application_prefix):
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'apply')
    source = append(source, 'overhang-bulk', metadata(source, 'connection-version-patch', patch={
        'connection_type': 'root-to-root-ssdna-linker', 'bridge_length': 11, 'bridge_seq': 'A' * 11}), 'edit')
    result = append(source, 'overhang-bulk', apply_params(source, 'candidate'), 'reapply')
    assert not result.duplexes and not result.overhang_bindings
    assert result.connection_versions[0].bridge_length == 11
    assert proof(result)['status'] == 'verified'


@pytest.mark.parametrize('change', [
    {'connection_version_contract': True}, {'connection_version_contract': '2'},
    {'connection_version_contract': 3}, {'affected_version_ids': ['candidate', 'candidate']},
    {'affected_version_ids': None}, {'saved_design': {}}, {'patch': {'applied': 1}},
])
def test_malformed_metadata_cannot_skip_topology_processing(application_prefix, change):
    from backend.api.part_connection_version_commands import is_metadata_command
    from backend.api.part_proof_commands import dependencies
    source = pending(application_prefix)
    values = {**metadata(source, 'connection-version-patch', patch={'name': 'Name'}), **change}
    assert not is_metadata_command('overhang-bulk', values)
    assert not dependencies('overhang-bulk', values).known
