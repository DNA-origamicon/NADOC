"""Explicit pair disconnection restores native owners in one replayable action."""

import pytest

from tests.test_part_connection_compose import document as document

from tests.test_connection_direct_replacement import direct_source as direct_source
from tests.test_part_connection_application_commands import application_prefix as application_prefix, FINITE_TYPES
from tests.test_part_pending_connection_versions import append, authored, native_prefix as native_prefix, proof
from tests.test_part_connection_direct import pending, params as direct_params
from tests.test_part_connection_inverse import apply_params


def params(source, delete_version=False):
    from backend.api.part_connection_disconnect import capture_inputs
    return capture_inputs(source, source.connection_versions[0], delete_version=delete_version)


@pytest.mark.parametrize('family', ['root-to-root', 'end-to-root', *FINITE_TYPES, 'root-to-root-indirect', 'end-to-end-indirect'])
@pytest.mark.parametrize('delete_version', [False, True])
def test_native_disconnect_restores_all_families_and_replays(direct_source, family, delete_version):
    source = pending(direct_source, family)
    source = append(source, 'overhang-bulk', direct_params(source) if family in {'root-to-root', 'end-to-root'}
                    else apply_params(source, 'candidate'), 'apply')
    before = source.model_dump_json()
    result = append(source, 'overhang-bulk', params(source, delete_version), 'disconnect')
    assert not result.duplexes and not result.overhang_bindings and not result.overhang_connections
    assert not any(c.overhang_duplex_driver_id for c in result.cluster_transforms)
    assert not any(v.applied for v in result.connection_versions)
    assert bool(result.connection_versions) != delete_version
    assert proof(result)['status'] == 'verified'
    assert source.model_dump_json() == before


def test_disconnection_is_reapplicable_and_metadata_delete_stays_distinct(application_prefix):
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'apply')
    result = append(source, 'overhang-bulk', params(source), 'disconnect')
    result = append(result, 'overhang-bulk', direct_params(result, seed=999), 'reapply')
    assert result.duplexes and result.connection_versions[0].applied
    assert proof(result)['status'] == 'verified'


@pytest.mark.parametrize('damage', ['missing_binding', 'external_reference', 'missing_ligation'])
def test_disconnect_refuses_incomplete_ownership_without_mutation(application_prefix, damage):
    from backend.api.part_connection_disconnect import build
    from backend.core.part_command_errors import CommandContractError
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'apply')
    values = params(source)
    source = source.model_copy(deep=True)
    if damage == 'missing_binding':
        source.overhang_bindings = []
    elif damage == 'missing_ligation':
        source.forced_ligations = []
    else:
        child = next(c for c in source.cluster_transforms if c.overhang_duplex_driver_id)
        next(c for c in source.cluster_transforms if c.id != child.id).parent_cluster_id = child.id
    before = source.model_dump_json()
    with pytest.raises(CommandContractError):
        build(source, values)
    assert source.model_dump_json() == before


@pytest.fixture
def disconnected_document(document, monkeypatch):
    from backend.api import part_connection_disconnect as command
    monkeypatch.setattr(command, 'ENABLED', True)
    source = pending(document.source)
    source = append(source, 'overhang-bulk', direct_params(source), 'apply')
    document.source = source
    document.session.design = source
    return document


@pytest.mark.parametrize('delete_version', [False, True])
def test_disconnect_http_atomic_undo_and_replay(disconnected_document, delete_version):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import state, routes_connection_versions as routes
    doc = disconnected_document
    before = doc.source.model_dump_json()
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post('/design/connection-versions/candidate/' + ('disconnect-and-delete' if delete_version else 'unapply'))
    assert response.status_code == 200, response.text
    result = doc.session.design
    assert len(doc.session.history) == 1 and doc.session.revision == 5
    assert not result.duplexes and not result.overhang_bindings
    assert proof(result)['status'] == 'verified'
    assert doc.source.model_dump_json() == before
    state.undo()
    assert authored(doc.session.design) == authored(doc.source)
    state.redo()
    assert authored(doc.session.design) == authored(result)


@pytest.mark.parametrize('failure', ['publication', 'source_change'])
def test_disconnect_failure_preserves_original(disconnected_document, failure, monkeypatch):
    from fastapi import HTTPException
    from backend.api import state, part_connection_disconnect as command
    from backend.api import feature_recording
    doc = disconnected_document
    before = doc.source.model_dump_json()
    if failure == 'publication':
        def fail(*args, **kwargs):
            raise RuntimeError('disconnect publication failed')
        monkeypatch.setattr(state, 'validate_design', fail)
    else:
        native = feature_recording.record_feature
        def change(*args, **kwargs):
            doc.session.design = doc.source.model_copy(deep=True)
            return native(*args, **kwargs)
        monkeypatch.setattr(feature_recording, 'record_feature', change)
    with pytest.raises((RuntimeError, HTTPException)):
        command.record('candidate')
    assert doc.source.model_dump_json() == before
    assert doc.session.design.model_dump_json() == before
    assert not doc.session.history and doc.session.revision == 4


def test_disconnection_follows_upstream_branch_change(application_prefix):
    from backend.api.part_recipe_edit import prepare_change
    from backend.core.part_verification_capture import capture
    from backend.api.part_verification_worker import VerificationWorker
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'apply')
    source = append(source, 'overhang-bulk', params(source), 'disconnect')
    index = next(i for i, e in enumerate(source.feature_log) if e.id == 'endpoint-2')
    changed, _ = prepare_change(source, capture(source, preserve_entry_types=True), index, lambda: None, params={'length_bp': 16})
    from backend.core.models import Design
    changed = Design.model_validate_json(changed.model_dump_json())
    worker = VerificationWorker(capture(changed))
    try:
        worker.start()
        assert worker.wait(5)
        assert worker.result()['status'] == 'verified'
    finally:
        worker.close()


def test_exact_pair_disconnect_preserves_third_endpoint_connection(application_prefix):
    from uuid import UUID
    from tests.conftest import valid_overhang_sites
    from tests.test_part_pending_connection_versions import creation
    source = application_prefix
    site = next(iter(valid_overhang_sites(source)))
    source = append(source, 'overhang-extrude', {'_proof_version': 1, 'history_seed': str(UUID(int=123456)),
        **site, 'direction': site['direction'].value, 'length_bp': 12, 'reuse_existing_helix': False}, 'endpoint-3')
    source = pending(source)
    source = append(source, 'connection-version-create', creation(source, version_id='other',
        overhang_b_id=source.overhangs[-1].id, connection_type='root-to-root'), 'other')
    source = append(source, 'overhang-bulk', direct_params(source, 'other'), 'apply-other')
    before = authored(source)
    result = append(source, 'overhang-bulk', params(source), 'disconnect-original-pair')
    assert authored(result) == before
    assert result.connection_versions[1].applied
    assert proof(result)['status'] == 'verified'


@pytest.mark.parametrize('guard', ['body', 'source_change', 'cursor', 'loadout'])
def test_disconnect_http_guards_preserve_source(disconnected_document, guard, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import state, routes_connection_versions as routes
    from backend.api import part_connection_composition_route as transport
    from backend.core.models import DesignLoadout
    doc = disconnected_document
    if guard == 'cursor':
        doc.source.feature_log_cursor = 0
    elif guard == 'loadout':
        doc.source.loadouts = [DesignLoadout(id='locked', name='Locked', protected=True)]
        doc.source.active_loadout_id = 'locked'
    elif guard == 'source_change':
        original = transport._no_apply_inputs
        async def changed(request, **kwargs):
            result = await original(request, **kwargs)
            with state._lock:
                state._bump_revision(doc.session)
            return result
        monkeypatch.setattr(transport, '_no_apply_inputs', changed)
    before = doc.source.model_dump_json()
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post('/design/connection-versions/candidate/unapply', **({'json': {}} if guard == 'body' else {}))
    assert response.status_code >= 400
    assert doc.session.design.model_dump_json() == before
    assert not doc.session.history


def test_disconnect_protects_contract_and_declares_stable_dependencies(application_prefix):
    from backend.api.part_proof_commands import dependencies
    from backend.core.part_edit_identity import preserve_proof_identity
    from backend.core.part_dependencies import Resource
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'apply')
    values = params(source)
    dep = dependencies('overhang-bulk', values)
    assert dep.known and dep.barrier
    assert Resource('duplex', source.duplexes[0].id) in dep.reads & dep.writes
    assert not dependencies('overhang-bulk', {**values, '_generated_scope': {}}).known
    changed = preserve_proof_identity(values, {**values, 'connection_disconnect_version': 2}, kind='overhang-bulk')
    assert changed['connection_disconnect_version'] == 1


def test_legacy_literal_removal_cannot_leave_orphan_direct_cluster(application_prefix):
    from backend.api.part_connection_disconnect import build
    from backend.core.part_command_errors import CommandContractError
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'apply')
    # Simulate an unlogged legacy producer and a lost binding. No creator query
    # is available, so the retained native placement must independently refuse.
    source = source.copy_with(feature_log=[], overhang_bindings=[])
    before = source.model_dump_json()
    with pytest.raises(CommandContractError, match='Retained placement'):
        build(source, params(source))
    assert source.model_dump_json() == before
