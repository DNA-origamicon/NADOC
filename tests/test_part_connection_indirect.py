"""Version-two native linkers preserve the zero-bridge ownership grammar."""
import pytest

from backend.api import part_connection_application_commands as application
from backend.api import part_connection_composition_commands as composition
from backend.api.part_proof_commands import dependencies
from backend.core.part_dependencies import Resource
from tests.test_connection_composition_contract import legacy_combined, version_from
from tests.test_part_connection_compose import params as compose_params
from tests.test_part_connection_application_commands import (
    _pending, _params, _legacy, application_prefix as application_prefix,
)
from tests.test_part_pending_connection_versions import (
    append, authored, native_prefix as native_prefix, proof,
)

INDIRECT = ['root-to-root-indirect', 'end-to-end-indirect']


def compose(source, kind=INDIRECT[0], **changes):
    return {**compose_params(source, kind), 'connection_composition_version': 2, **changes}


def apply(source, **changes):
    return {**_params(source), 'connection_application_version': 2, **changes}


@pytest.mark.parametrize('kind', INDIRECT)
@pytest.mark.parametrize('combined', [False, True])
def test_native_indirect_parity_and_actual_dependency_outputs(application_prefix, monkeypatch, kind, combined):
    source = application_prefix.model_copy(deep=True)
    if combined:
        values = compose(source, kind)
        expected, expected_report, _ = legacy_combined(source, version_from(values), monkeypatch)
        result, report = composition.build(source, values)
    else:
        source = _pending(source, kind)
        values = apply(source)
        expected, expected_report = _legacy(source, values, monkeypatch)
        result, report = application.build(source, values)
    assert authored(result) == authored(expected)
    assert report == expected_report
    contract = dependencies('overhang-bulk', values)
    prefix = f"__lnk__{values['connection_id']}"
    assert contract.known and contract.barrier
    assert Resource('strand', prefix + '__s') in contract.writes
    assert Resource('helix', prefix) not in contract.writes
    assert not any(h.id == prefix for h in result.helices)
    assert result.overhang_connections[0].length_value == 0


@pytest.mark.parametrize('kind', INDIRECT)
def test_version_one_still_refuses_indirect(application_prefix, kind):
    pending = _pending(application_prefix.model_copy(deep=True), kind)
    assert not dependencies('overhang-bulk', _params(pending)).known
    assert not dependencies('overhang-bulk', compose_params(application_prefix, kind)).known


@pytest.mark.parametrize('old_kind', [*INDIRECT, 'root-to-root-ssdna-linker', 'end-to-root-dsdna-linker'])
@pytest.mark.parametrize('new_kind', [INDIRECT[1], 'root-to-root-ssdna-linker'])
def test_cross_family_replacement_cold_replay(application_prefix, old_kind, new_kind):
    source = append(application_prefix, 'overhang-bulk', compose(application_prefix, old_kind), 'connect-one')
    before = source.model_dump_json()
    values = compose(source, new_kind, version_id='candidate-two', connection_id='replacement',
                     conflict_version_ids=['candidate'], conflict_connection_ids=['composed-output'])
    result = append(source, 'overhang-bulk', values, 'connect-two')
    assert source.model_dump_json() == before
    assert [v.applied for v in result.connection_versions] == [False, True]
    assert [c.id for c in result.overhang_connections] == ['replacement']
    assert not any(row.id.startswith('__lnk__composed-output') for row in [*result.strands, *result.helices])
    assert proof(result)['status'] == 'verified'


@pytest.mark.parametrize('corruption', ['domain_order', 'extra_domain', 'extra_owner'])
def test_indirect_removal_requires_complete_native_ownership(application_prefix, corruption):
    from backend.core.part_command_errors import ReferenceResolutionError
    source, _ = composition.build(application_prefix, compose(application_prefix))
    strand = source.find_strand('__lnk__composed-output__s')
    if corruption == 'domain_order':
        strand.domains = list(reversed(strand.domains))
    elif corruption == 'extra_domain':
        strand.domains.append(strand.domains[0].model_copy())
    else:
        source.strands.append(strand.model_copy(update={'id': strand.id + '-extra'}))
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError):
        composition.build(source, compose(source, version_id='next', connection_id='replacement',
            conflict_version_ids=['candidate'], conflict_connection_ids=['composed-output']))
    assert source.model_dump_json() == before


@pytest.fixture
def document(application_prefix, monkeypatch):
    from uuid import uuid4
    from types import SimpleNamespace
    from backend.api import state, doc_context, routes_connection_versions as routes
    source = application_prefix.model_copy(deep=True)
    session = state._DesignSession(design=source, revision=4)
    doc = f'__indirect__{uuid4()}'
    token = doc_context.set_current_doc(doc)
    prior = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    with state._lock:
        state._sessions[doc] = session
    monkeypatch.setattr(routes, 'NATIVE_LINKER_V2_ENABLED', True)
    try:
        yield SimpleNamespace(source=source, session=session)
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(prior[0])
        doc_context.set_request_feature_log_entry_id(prior[1])


@pytest.mark.parametrize('kind', INDIRECT)
def test_actual_http_connect_reapply_one_undo_and_replay(document, kind):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes, state
    from tests.test_part_connection_compose import choices
    body = choices(document.source).model_copy(update={'connection_type': kind})
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        first_response = client.post('/design/connection-versions/connect', json=body.model_dump())
        assert first_response.status_code == 201, first_response.text
        first = document.session.design
        version = first.connection_versions[0].id
        second_response = client.post(f'/design/connection-versions/{version}/apply')
    assert second_response.status_code == 200, second_response.text
    final = document.session.design
    assert len(document.session.history) == 2 and document.session.revision == 6
    assert final.feature_log[-1].params['connection_application_version'] == 2
    assert first.feature_log[-1].params['connection_composition_version'] == 2
    assert final.overhang_connections[0].id != first.overhang_connections[0].id
    assert proof(final)['status'] == 'verified'
    state.undo()
    assert authored(document.session.design) == authored(first)
    state.undo()
    assert authored(document.session.design) == authored(document.source)
    state.redo()
    assert authored(document.session.design) == authored(first)


def test_apply_http_source_change_before_dispatch_refuses(document, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes, state
    from backend.api import part_connection_composition_route as transport
    from tests.test_part_connection_compose import choices
    routes.create_and_apply_connection_version(choices(document.source).model_copy(update={'connection_type': INDIRECT[0]}))
    source = document.session.design
    before = source.model_dump_json()
    reader = transport._no_apply_inputs
    async def change(request, **kwargs):
        result = await reader(request, **kwargs)
        with state._lock:
            state._bump_revision(document.session)
        return result
    monkeypatch.setattr(transport, '_no_apply_inputs', change)
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post(f'/design/connection-versions/{source.connection_versions[0].id}/apply')
    assert response.status_code == 409 and response.json()['detail']['code'] == 'source_changed'
    assert document.session.design.model_dump_json() == before and len(document.session.history) == 1


@pytest.mark.parametrize('combined', [False, True])
def test_v2_edit_keeps_contract_and_output_identity(application_prefix, combined):
    from backend.core.part_edit_identity import preserve_proof_identity
    source = _pending(application_prefix, INDIRECT[0])
    values = compose(application_prefix) if combined else apply(source)
    marker = 'connection_composition_version' if combined else 'connection_application_version'
    updated = preserve_proof_identity(values, {**values, marker: 1,
        'connection_id': 'different', 'overhang_a_id': 'new-target'}, kind='overhang-bulk')
    assert updated[marker] == 2 and updated['connection_id'] == values['connection_id']
    assert updated['overhang_a_id'] == 'new-target'


@pytest.mark.parametrize('kind', INDIRECT)
def test_isolated_cold_worker_and_upstream_edit(application_prefix, kind):
    from backend.api.part_verification_worker import VerificationWorker
    from backend.core.part_verification_capture import capture
    from backend.api.part_recipe_edit import prepare_change
    source = append(application_prefix, 'overhang-bulk', compose(application_prefix, kind), 'connect')
    updated, _ = prepare_change(source, capture(source, preserve_entry_types=True),
                                1, lambda: None, params={'length_bp': 14})
    assert updated.overhang_connections[0].length_value == 0
    assert updated.connection_versions[0].id == 'candidate'
    assert updated.overhang_connections[0].id == 'composed-output'
    worker = VerificationWorker(capture(updated))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result['status'] == 'verified', result
    finally:
        worker.close()


@pytest.mark.parametrize('bad_version', [True, False, 2.0, '2', 3, None])
@pytest.mark.parametrize('combined', [False, True])
def test_v2_contract_version_is_an_exact_supported_integer(application_prefix, bad_version, combined):
    source = _pending(application_prefix, INDIRECT[0])
    values = compose(application_prefix) if combined else apply(source)
    marker = 'connection_composition_version' if combined else 'connection_application_version'
    assert not dependencies('overhang-bulk', {**values, marker: bad_version}).known


@pytest.mark.parametrize('body', [{'connection_type': INDIRECT[1]}, {}])
def test_version_apply_rejects_body_inputs(document, body):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes
    from tests.test_part_connection_compose import choices
    routes.create_and_apply_connection_version(choices(document.source).model_copy(update={'connection_type': INDIRECT[0]}))
    source = document.session.design
    before = source.model_dump_json()
    app = FastAPI()
    app.include_router(routes.router)
    with TestClient(app) as client:
        response = client.post(f'/design/connection-versions/{source.connection_versions[0].id}/apply', json=body)
    assert response.status_code == 400
    assert document.session.design.model_dump_json() == before and len(document.session.history) == 1


def test_zero_output_cannot_adopt_a_dangling_virtual_helix_reference(application_prefix, monkeypatch):
    from backend.core.models import NucleotideTransform
    from backend.core.part_command_errors import ReferenceResolutionError
    source = application_prefix.copy_with(nucleotide_transforms=[NucleotideTransform(
        id='dangling', kind='base', helix_id='__lnk__composed-output', bp_index=0, direction='FORWARD')])
    before = source.model_dump_json()
    monkeypatch.setattr(application, '_materialize', lambda *_: pytest.fail('built over dangling owner'))
    with pytest.raises(ReferenceResolutionError):
        composition.build(source, compose(source))
    assert source.model_dump_json() == before


@pytest.mark.parametrize('guard', ['history_cursor', 'protected_loadout'])
def test_v2_apply_guard_precedes_preparation(document, monkeypatch, guard):
    from fastapi import HTTPException
    from backend.api import routes_connection_versions as routes
    from backend.core.models import DesignLoadout
    source = _pending(document.source, INDIRECT[0])
    if guard == 'history_cursor':
        source.feature_log_cursor = 0
    else:
        source.loadouts = [DesignLoadout(id='simulation', name='Simulation', protected=True)]
        source.active_loadout_id = 'simulation'
    document.session.design = source
    before = source.model_dump_json()
    monkeypatch.setattr(application, '_source_index', lambda *_: pytest.fail('prepared before document guard'))
    with pytest.raises(HTTPException) as caught:
        routes.apply_connection_version('candidate')
    assert caught.value.status_code == 409
    assert document.session.design.model_dump_json() == before and not document.session.history
