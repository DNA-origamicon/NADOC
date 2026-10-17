"""Owned organized connection publication uses source proof and one undo."""

import pytest

from backend.api import state
from backend.api import part_connection_recipe_recording as host
from tests.test_part_pattern_recording import document as document, worker as worker, saved, unchanged
from tests.test_part_connection_application_commands import application_prefix as application_prefix, FINITE_TYPES
from tests.test_connection_direct_replacement import direct_source as direct_source
from tests.test_part_pending_connection_versions import native_prefix as native_prefix, proof
from tests.test_connection_organization_replay import organize, organized, application, disconnect_params


def pending(source, family='root-to-root'):
    from tests.test_part_pending_connection_versions import append, creation
    return append(source, 'overhang-bulk', {**creation(source, version_id='candidate', connection_type=family,
        overhang_a_seq='A' * 12, overhang_b_seq='T' * 12), '_proof_version': 1,
        'connection_version_contract': 1, 'action': 'connection-version-create'}, 'candidate')


def install(document, source):
    state.load_design(source)
    # Functional isolation only: release graphs from earlier fixture/worker
    # setup outside the production lock. Capture deadlines remain unchanged.
    import gc
    gc.collect()
    return document


def create(document, values):
    return host.create(values, expected_design_id=document.design.id, expected_revision=document.revision)


@pytest.mark.parametrize('family', ['root-to-root', 'end-to-root', *FINITE_TYPES, 'root-to-root-indirect', 'end-to-end-indirect'])
def test_owned_apply_disconnect_one_undo_and_replay(document, worker, direct_source, family):
    install(document, organize(pending(direct_source, family)))
    before = saved(document)
    if family in {'root-to-root-dsdna-linker', 'end-to-end-dsdna-linker'}:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as error:
            create(document, organized(application(document.design, family)))
        assert error.value.detail['code'] == 'ambiguous_group_lineage'
        unchanged(document, before)
        return
    lengths = [o.sub_domains[0].length_bp for o in document.design.overhangs[:2]]
    if family in {'root-to-root', 'end-to-root'} and lengths[0] != lengths[1]:
        # ISSUE-143: native relocation leaves the Duplex register at the old
        # address. Prove the unorganized oracle fails too; never certify parity.
        from backend.api.part_proof_commands import execute
        from backend.core.models import Design
        from pydantic import ValidationError
        from fastapi import HTTPException
        native = execute('overhang-bulk', document.design.copy_with(group_organization=None),
                         application(document.design, family))
        with pytest.raises(ValidationError, match='outside overhang'):
            Design.model_validate(native.model_dump(mode='json'))
        with pytest.raises(HTTPException) as error:
            create(document, organized(application(document.design, family)))
        assert error.value.detail['code'] == 'invalid_connection_output'
        unchanged(document, before)
        return
    result, report, entry, _ = create(document, organized(application(document.design, family)))
    assert result is document.design and entry is result.feature_log[-1]
    assert document.revision == before[2] + 1 and len(document.history) == len(before[3]) + 1
    assert proof(result)['status'] == 'verified'
    assert before[0].model_dump_json() == before[1]
    result, _, _, _ = create(document, organized(disconnect_params(result)))
    assert not result.duplexes and not result.overhang_connections and not result.overhang_bindings
    assert proof(result)['status'] == 'verified'
    assert len(document.history) == len(before[3]) + 2
    assert all(w.closed for w in worker.instances)


def test_native_worker_transport(document, application_prefix):
    install(document, organize(pending(application_prefix)))
    result, _, _, _ = create(document, organized(application(document.design, 'root-to-root')))
    assert proof(result)['status'] == 'verified'


@pytest.mark.parametrize('fault', ['revision', 'policy', 'cancel'])
def test_no_publication_after_source_or_policy_change(document, worker, application_prefix, fault):
    from threading import Event
    from backend.api import part_publication_policy as policy
    from fastapi import HTTPException
    install(document, organize(pending(application_prefix)))
    cancelled = Event()
    before = saved(document)
    def change(_worker):
        if fault == 'revision':
            document.revision += 1
        elif fault == 'policy':
            config, generation = policy._configuration
            policy._configuration = config, generation + 1
        else:
            cancelled.set()
    worker.on_result = change
    with pytest.raises(HTTPException):
        host.create(organized(application(document.design, 'root-to-root')),
            expected_design_id=document.design.id, expected_revision=document.revision, cancelled=cancelled)
    if fault == 'revision':
        document.revision -= 1
    unchanged(document, before)
    assert all(w.closed for w in worker.instances)


def test_generic_append_cannot_supply_missing_host_context(application_prefix):
    from backend.api.part_evaluation import evaluate
    source = organize(pending(application_prefix))
    result = evaluate(source, {'request': {'operation': 'append', 'kind': 'overhang-bulk',
        'params': organized(application(source, 'root-to-root')), 'expected_revision': 0},
        'header': {'identity': 'untrusted', 'timestamp': 'now'}})
    assert result['status'] != 'ready'
    assert result['issues'][0]['code'] == 'invalid_capture_context'


@pytest.mark.parametrize('family', ['root-to-root', 'end-to-root', 'root-to-root-ssdna-linker', 'root-to-root-indirect'])
def test_http_lifecycle_and_metadata_history_edit(document, worker, application_prefix, monkeypatch, family):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from backend.api import routes_connection_versions as routes, part_connection_organized_routes as organized_routes, crud
    monkeypatch.setattr(organized_routes, 'ENABLED', True)
    install(document, organize(application_prefix))
    before = saved(document)
    def forbidden_normalization(*args, **kwargs):
        pytest.fail('Owned response inferred compatibility membership')
    monkeypatch.setattr(crud, '_ensure_default_cluster', forbidden_normalization)
    app = FastAPI()
    app.include_router(routes.router)
    app.include_router(crud.router)
    # Release test/import graphs before the functional HTTP workflow. This is
    # not latency qualification: production GC overlap remains measured debt.
    import gc
    gc.collect()
    choices = {'overhang_a_id': document.design.overhangs[0].id, 'overhang_b_id': document.design.overhangs[1].id,
               'connection_type': family, 'overhang_a_seq': 'A' * 12, 'overhang_b_seq': 'T' * 12,
               'bridge_length': 7, 'name': 'First'}
    with TestClient(app) as client:
        response = client.post('/design/connection-versions', json=choices)
        assert response.status_code == 201, response.text
        identity = document.design.connection_versions[0].id
        creation_index = len(document.design.feature_log) - 1
        base = '/design/connection-versions/' + identity
        for method, path, body in [('patch', base, {'name': 'Renamed'}), ('post', base + '/apply', None),
                                   ('post', base + '/unapply', None), ('post', base + '/apply', None)]:
            response = getattr(client, method)(path, **({'json': body} if body is not None else {}))
            assert response.status_code == 200, response.text
        response = client.post(f'/design/features/{creation_index}/edit', json={
            'params': {'name': 'Edited creation'},
            'expected_feature_id': document.design.feature_log[creation_index].id,
            'expected_design_id': document.design.id, 'expected_revision': document.revision})
        assert response.status_code == 200, response.text
        result = document.design
        assert proof(result)['status'] == 'verified'
        assert result.connection_versions[0].name == 'Renamed'  # Later explicit edit wins.
        response = client.post(base + '/disconnect-and-delete')
        assert response.status_code == 200, response.text
        assert not document.design.connection_versions
        response = client.post('/design/connection-versions/connect', json=choices)
        assert response.status_code == 201, response.text
        identity = document.design.connection_versions[0].id
        assert document.design.connection_versions[0].applied
        response = client.delete('/design/connection-versions/' + identity)
        assert response.status_code == 200, response.text
    assert not document.design.connection_versions
    assert document.design.overhang_connections or document.design.duplexes  # Metadata delete isn't Unapply.
    assert proof(document.design)['status'] == 'verified'
    assert len(document.history) == len(before[3]) + 9
    final = document.design
    state.undo()
    assert document.design.connection_versions
    state.redo()
    assert document.design.model_dump(mode='json', exclude={'feature_log'}) == final.model_dump(mode='json', exclude={'feature_log'})


def test_closed_routes_never_fall_back(document, worker, application_prefix, monkeypatch):
    from backend.api import routes_connection_versions as routes, part_connection_organized_routes as organized_routes
    from fastapi import HTTPException
    install(document, organize(pending(application_prefix)))
    before = saved(document)
    def forbidden(*args, **kwargs):
        pytest.fail('Organized failure reached compatibility builder')
    monkeypatch.setattr(routes, '_apply_connection_version_legacy', forbidden)
    with pytest.raises(HTTPException) as error:
        routes.apply_connection_version('candidate')
    assert error.value.detail['code'] == 'organized_connections_not_enabled'
    monkeypatch.setattr(organized_routes, 'ENABLED', True)
    with pytest.raises(HTTPException):
        routes.apply_connection_version('missing')
    unchanged(document, before)


def test_noncomplementary_native_output_cannot_publish(document, worker, application_prefix):
    from tests.test_part_connection_direct import pending as incompatible
    from fastapi import HTTPException
    install(document, organize(incompatible(application_prefix)))
    before = saved(document)
    with pytest.raises(HTTPException, match='complementary'):
        create(document, organized(application(document.design, 'root-to-root')))
    unchanged(document, before)


@pytest.mark.parametrize('changes', [{'action': 'connection-version-delete'}, {'history_seed': 'other'},
    {'_connection_organization': None}, {'version_id': 'other'}, {'saved_design': {}}, {'_generated_scope': {}}])
def test_edit_cannot_change_contract_or_output_identity(document, worker, application_prefix, changes):
    from fastapi import HTTPException
    install(document, organize(pending(application_prefix)))
    result, _, entry, _ = create(document, organized(application(document.design, 'root-to-root')))
    before = saved(document)
    with pytest.raises(HTTPException):
        host.edit(len(result.feature_log) - 1, changes, expected_feature_id=entry.id,
            expected_design_id=result.id, expected_revision=document.revision)
    unchanged(document, before)


def test_closed_publication_scope_never_grants_generic_writes(document, worker, application_prefix):
    from backend.api.part_group_organization_gate import require_live_design
    from fastapi import HTTPException
    install(document, organize(pending(application_prefix)))
    result, _, _, _ = create(document, organized(application(document.design, 'root-to-root')))
    with pytest.raises(HTTPException):
        require_live_design(result)


@pytest.mark.parametrize('family', ['root-to-root-ssdna-linker', 'root-to-root-indirect'])
def test_connect_parameter_edit_preserves_identity_and_rebuilds(document, worker, application_prefix, family):
    from backend.api.part_connection_organized_routes import capture_inputs
    install(document, organize(application_prefix))
    choices = {'overhang_a_id': document.design.overhangs[0].id, 'overhang_b_id': document.design.overhangs[1].id,
               'connection_type': family, 'overhang_a_seq': 'A' * 12, 'overhang_b_seq': 'T' * 12,
               'bridge_length': 7}
    result, _, entry, _ = create(document, capture_inputs(document.design, 'connect', choices))
    output_id = entry.params['connection_id']
    result, _, edited, _ = host.edit(len(result.feature_log) - 1, {'bridge_length': 11},
        expected_feature_id=entry.id, expected_design_id=result.id, expected_revision=document.revision)
    assert edited.id == entry.id and edited.params['connection_id'] == output_id
    assert result.connection_versions[0].bridge_length == 11
    assert proof(result)['status'] == 'verified'



def test_capture_deadline_refusal_is_atomic(document, worker, application_prefix, monkeypatch):
    from backend.api import part_ordinary_recipe_recording as recording
    from backend.core.part_verification_capture import CaptureLimit
    from fastapi import HTTPException
    install(document, organize(pending(application_prefix)))
    before = saved(document)
    def expired(*args, **kwargs):
        raise CaptureLimit('Part verification capture budget exceeded')
    monkeypatch.setattr(recording, 'capture', expired)
    with pytest.raises(HTTPException) as error:
        create(document, organized(application(document.design, 'root-to-root')))
    assert error.value.status_code == 413
    assert error.value.detail['code'] == 'connection_capture_limit'
    unchanged(document, before)
    assert not worker.instances
