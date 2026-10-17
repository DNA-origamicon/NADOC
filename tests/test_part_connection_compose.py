"""Closed combined Connect: declared inputs, one native postprocessing pass."""
from importlib import import_module

import pytest

from backend.api.part_proof_commands import dependencies, execute
from backend.core.part_dependencies import Resource
from backend.core.part_edit_identity import preserve_proof_identity
from tests.test_connection_composition_contract import definition, legacy_combined, version_from
from tests.test_part_connection_application_commands import (
    FINITE_TYPES, application_prefix as application_prefix,
)
from tests.test_part_pending_connection_versions import (
    append, authored, native_prefix as native_prefix, proof,
)

ACTION = 'connection-version-connect-linker'


def params(source, connection_type='root-to-root-ssdna-linker'):
    return {**definition(source, connection_type), 'action': ACTION,
        'connection_composition_version': 1, 'connection_id': 'composed-output',
        'conflict_connection_ids': [], 'conflict_version_ids': []}


def commands():
    return import_module('backend.api.part_connection_composition_commands')


@pytest.mark.parametrize('connection_type', FINITE_TYPES)
def test_complete_native_output_matches_combined_legacy(application_prefix, monkeypatch, connection_type):
    source = application_prefix.model_copy(deep=True)
    values = params(source, connection_type)
    before = source.model_dump_json()
    expected, report, _ = legacy_combined(source, version_from(values), monkeypatch)
    actual, actual_report = commands().build(source, values)
    assert authored(actual) == authored(expected)
    assert actual_report == report
    assert source.model_dump_json() == before


@pytest.mark.parametrize('producer', ['connect', 'endpoint-1'])
@pytest.mark.parametrize('connection_type', ['root-to-root-ssdna-linker', 'end-to-root-dsdna-linker'])
def test_cold_recipe_and_upstream_edit_preserve_both_output_ids(application_prefix, connection_type, producer):
    from backend.api.part_recipe_edit import prepare_change
    from backend.core.part_verification_capture import capture
    from backend.core.models import Design
    source = append(application_prefix.model_copy(deep=True), 'overhang-bulk',
                    params(application_prefix, connection_type), 'connect')
    transported = Design.model_validate_json(source.model_dump_json())
    assert proof(transported)['status'] == 'verified'
    index = next(i for i, row in enumerate(transported.feature_log) if row.id == producer)
    changes = {'bridge_length': 11} if producer == 'connect' else {'length_bp': 14}
    updated, _ = prepare_change(transported, capture(transported, preserve_entry_types=True),
                                index, lambda: None, params=changes)
    assert [v.id for v in updated.connection_versions] == ['candidate']
    assert [c.id for c in updated.overhang_connections] == ['composed-output']
    assert updated.overhang_connections[0].length_value == (11 if producer == 'connect' else 7)
    if producer == 'endpoint-1':
        assert len(updated.connection_versions[0].overhang_a_seq) == 14
    assert proof(updated)['status'] == 'verified'


def test_dependency_contract_creates_version_instead_of_reading_it(application_prefix):
    result = dependencies('overhang-bulk', params(application_prefix))
    assert result.known and result.barrier
    assert Resource('connection_version', 'candidate') in result.writes
    assert Resource('connection_version', 'candidate') not in result.reads
    assert Resource('overhang_connection', 'composed-output') in result.writes
    assert Resource('helix', '__lnk__composed-output') in result.writes


@pytest.mark.parametrize('change', [
    {'connection_composition_version': True}, {'connection_composition_version': 4},
    {'applied': True}, {'_generated_scope': {}}, {'unregistered_input': {}},
    {'connection_type': 'root-to-root-indirect'}, {'conflict_version_ids': ['candidate']},
])
def test_malformed_or_unsupported_composition_is_not_registered(application_prefix, change):
    assert not dependencies('overhang-bulk', {**params(application_prefix), **change}).known


def test_edit_protects_definition_and_output_slots_but_not_inputs(application_prefix):
    before = params(application_prefix)
    changes = {**before, 'action': 'other', 'version_id': 'other-version',
        'connection_id': 'other-output', 'created_at': 40.0,
        'connection_composition_version': 9, 'bridge_length': 19, 'overhang_a_id': 'other-target'}
    result = preserve_proof_identity(before, changes, kind='overhang-bulk')
    for key in ('action', 'version_id', 'connection_id', 'created_at', 'connection_composition_version'):
        assert result[key] == before[key]
    assert result['bridge_length'] == 19 and result['overhang_a_id'] == 'other-target'


def test_only_one_reconcile_and_retry_for_whole_compound(application_prefix, monkeypatch):
    from backend.core import cluster_reconcile, lattice
    calls = []
    for owner, name in [(cluster_reconcile, 'reconcile_cluster_membership'), (lattice, 'retry_pending_ligations')]:
        native = getattr(owner, name)
        def observe(*args, _native=native, _name=name, **kwargs):
            calls.append(_name)
            return _native(*args, **kwargs)
        monkeypatch.setattr(owner, name, observe)
    result = execute('overhang-bulk', application_prefix, params(application_prefix))
    assert result.connection_versions[0].applied
    assert calls == ['reconcile_cluster_membership', 'retry_pending_ligations']


@pytest.fixture
def document(application_prefix, monkeypatch):
    from types import SimpleNamespace
    from uuid import uuid4
    from backend.api import state, doc_context, routes_connection_versions as routes
    source = application_prefix.model_copy(deep=True)
    session = state._DesignSession(design=source, revision=4)
    doc = f'__compose__{uuid4()}'
    token = doc_context.set_current_doc(doc)
    prior = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    monkeypatch.setattr(routes, 'OWNED_COMBINED_CONNECTION_APPLY_ENABLED', True)
    with state._lock:
        state._sessions[doc] = session
    try:
        yield SimpleNamespace(source=source, session=session, doc=doc)
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(prior[0])
        doc_context.set_request_feature_log_entry_id(prior[1])


def choices(source):
    from backend.api.routes_connection_versions import ConnectionVersionCreateRequest
    values = params(source)
    return ConnectionVersionCreateRequest(**{key: values[key] for key in
        ('name', 'connection_type', 'overhang_a_id', 'overhang_b_id',
         'overhang_a_seq', 'overhang_b_seq', 'bridge_length', 'bridge_seq')})


def test_ordinary_connect_is_one_feature_one_undo_and_replay(document):
    from backend.api import routes_connection_versions as routes, state
    before = document.source.model_dump_json()
    response = routes.create_and_apply_connection_version(choices(document.source))
    current = document.session.design
    assert current.feature_log[-1].params['action'] == ACTION
    assert len(current.feature_log) == len(document.source.feature_log) + 1
    assert document.session.revision == 5 and len(document.session.history) == 1
    assert len(response['design']['connection_versions']) == 1
    assert proof(current)['status'] == 'verified'
    assert document.source.model_dump_json() == before
    state.undo()
    assert authored(document.session.design) == authored(document.source)
    assert not document.session.design.connection_versions
    state.redo()
    assert authored(document.session.design) == authored(current)


@pytest.mark.parametrize('failure', ['materialize', 'validate'])
def test_failed_connect_retains_source_undo_redo_and_revision(document, monkeypatch, failure):
    from backend.api import state, routes_connection_versions as routes
    document.session.redo.append(document.source.model_copy(deep=True))
    before = document.source.model_dump_json()
    def fail(*_args, **_kwargs):
        raise RuntimeError('injected Connect failure')
    monkeypatch.setattr(commands() if failure == 'materialize' else state,
                        'materialize' if failure == 'materialize' else 'validate_design', fail)
    monkeypatch.setattr(routes, '_apply_connection_version_legacy', lambda *_a, **_k: pytest.fail('legacy retry'))
    with pytest.raises(RuntimeError, match='injected Connect failure'):
        routes.create_and_apply_connection_version(choices(document.source))
    assert document.session.design.model_dump_json() == before
    assert document.source.model_dump_json() == before
    assert not document.session.history and len(document.session.redo) == 1
    assert document.session.revision == 4


def test_actual_http_connect_records_native_recipe(document):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post('/design/connection-versions/connect', json=choices(document.source).model_dump())
    assert response.status_code == 201, response.text
    assert document.session.design.feature_log[-1].params['action'] == ACTION
    assert proof(document.session.design)['status'] == 'verified'


@pytest.mark.parametrize('change', [
    {'overhang_a_id': 'missing'}, {'conflict_connection_ids': ['missing']},
    {'conflict_version_ids': ['missing']},
])
def test_missing_inputs_refuse_before_materialization(application_prefix, monkeypatch, change):
    from backend.core.part_command_errors import ReferenceResolutionError
    from backend.api import part_connection_application_commands as application
    before = application_prefix.model_dump_json()
    monkeypatch.setattr(application, '_materialize', lambda *_: pytest.fail('native work before admission'))
    with pytest.raises(ReferenceResolutionError):
        commands().build(application_prefix, {**params(application_prefix), **change})
    assert application_prefix.model_dump_json() == before


def test_created_version_collision_refuses_without_renaming_old_source(application_prefix):
    from backend.api import part_connection_version_commands as pending
    from backend.core.part_command_errors import ReferenceResolutionError
    source = pending.build(application_prefix, definition(application_prefix, 'root-to-root-ssdna-linker'))
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError):
        commands().build(source, params(source))
    assert source.model_dump_json() == before


def test_http_source_revision_changed_during_body_read_refuses(document, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes, state
    from backend.api import part_connection_composition_route as transport
    read = transport.read_operation_json
    async def changed(request, **kwargs):
        result = await read(request, **kwargs)
        with state._lock:
            state._bump_revision(document.session)
        return result
    monkeypatch.setattr(transport, 'read_operation_json', changed)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post('/design/connection-versions/connect', json=choices(document.source).model_dump())
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'source_changed'
    assert document.session.design is document.source and not document.session.history
    assert not document.source.connection_versions


def test_one_source_inventory_and_materialization_on_ordinary_connect(document, monkeypatch):
    from backend.api import part_connection_application_commands as application
    from backend.api import routes_connection_versions as routes, state
    counts = {}
    for owner, name in [(application, '_source_index'), (application, '_materialize'),
                        (state, '_snapshot_copy'), (state, 'encode_design_snapshot')]:
        native = getattr(owner, name)
        counts[name] = 0
        def observe(*args, _name=name, _native=native, **kwargs):
            counts[_name] += 1
            return _native(*args, **kwargs)
        monkeypatch.setattr(owner, name, observe)
    routes.create_and_apply_connection_version(choices(document.source))
    assert counts == {'_source_index': 1, '_materialize': 1, '_snapshot_copy': 1, 'encode_design_snapshot': 2}


def test_http_compatibility_fallback_cannot_rebind_after_capture(document, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes, state
    def unsupported_after_revision_change(_choices, *, contract_version):
        assert contract_version == 1
        with state._lock:
            state._bump_revision(document.session)
        return None
    monkeypatch.setattr(commands(), 'try_record', unsupported_after_revision_change)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post('/design/connection-versions/connect', json=choices(document.source).model_dump())
    assert response.status_code == 409
    assert response.json()['detail']['code'] == 'source_changed'
    assert not document.session.design.connection_versions and not document.session.history


def test_compound_replacement_preserves_old_definition_and_replays(document):
    from backend.api import routes_connection_versions as routes, state
    routes.create_and_apply_connection_version(choices(document.source))
    first = document.session.design
    first_id = first.overhang_connections[0].id
    source_before = first.model_dump_json()
    routes.create_and_apply_connection_version(choices(first))
    final = document.session.design
    assert len(final.connection_versions) == 2
    assert [v.applied for v in final.connection_versions] == [False, True]
    assert final.feature_log[-1].params['conflict_connection_ids'] == [first_id]
    assert final.feature_log[-1].params['conflict_version_ids'] == [first.connection_versions[0].id]
    assert final.overhang_connections[0].id != first_id
    assert first.model_dump_json() == source_before
    assert proof(final)['status'] == 'verified'
    state.undo()
    assert authored(document.session.design) == authored(first)


def test_compound_survives_actual_isolated_verification_worker(application_prefix):
    from backend.api.part_verification_worker import VerificationWorker
    from backend.core.part_verification_capture import capture
    source = append(application_prefix, 'overhang-bulk', params(application_prefix), 'connect')
    worker = VerificationWorker(capture(source))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result['status'] == 'verified', result
        assert result['checked_commands'] == 4
    finally:
        worker.close()


@pytest.mark.parametrize('guard', ['history_cursor', 'protected_loadout'])
def test_document_guard_precedes_output_allocation(document, monkeypatch, guard):
    from fastapi import HTTPException
    from backend.api import routes_connection_versions as routes
    from backend.core.models import DesignLoadout
    if guard == 'history_cursor':
        document.source.feature_log_cursor = 0
    else:
        document.source.loadouts = [DesignLoadout(id='simulation', name='Simulation', protected=True)]
        document.source.active_loadout_id = 'simulation'
    before = document.source.model_dump_json()
    monkeypatch.setattr(commands(), 'uuid4', lambda: pytest.fail('allocated before document admission'))
    with pytest.raises(HTTPException) as caught:
        routes.create_and_apply_connection_version(choices(document.source))
    assert caught.value.status_code == 409
    assert document.session.design.model_dump_json() == before
    assert not document.session.history and document.session.revision == 4
