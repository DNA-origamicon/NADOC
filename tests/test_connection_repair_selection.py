"""Connection repairs select from the native prefix and rebuild the full suffix."""

import pytest

from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_repair_selection import prepare_selection, reference_slot
from backend.api.part_repair_input_metadata import describe_inputs
from backend.api.part_recipe_repair import prepare_repair
from backend.core.models import Design
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import native_prefix as native_prefix, append, proof
from tests.test_connection_recipe_recording import pending
from tests.test_connection_organization_replay import organize, organized, application, disconnect_params


def damage(source, feature_id, key):
    return source.copy_with(feature_log=[entry.model_copy(update={'params': {**entry.params, key: 'missing'}})
        if entry.id == feature_id else entry for entry in source.feature_log])


def selection(source, feature_id, key, **changes):
    return {'selection_version': 1, 'expected_design_id': source.id, 'expected_revision': 7,
            'feature_id': feature_id, 'parameter_path': [key], 'expected_old': 'missing', **changes}


def preview(source, feature_id, key, **changes):
    return prepare_selection(source, selection(source, feature_id, key, **changes), source_revision=7,
                             executor=execute, dependency_resolver=dependencies)


def repair(source, feature_id, key, value, **changes):
    request = {'repair_version': 1, 'expected_design_id': source.id, 'expected_revision': 7,
        'actions': [{'action': 'set_input', 'feature_id': feature_id, 'parameter_path': [key],
                     'expected_old': 'missing', 'value': value, **changes}]}
    return prepare_repair(source, request, source_revision=7, executor=execute, dependency_resolver=dependencies)


@pytest.mark.parametrize('grouped', [False, True])
@pytest.mark.parametrize('family', ['root-to-root', 'root-to-root-ssdna-linker', 'root-to-root-indirect'])
def test_version_repair_rebuilds_apply_and_downstream_disconnect(application_prefix, grouped, family):
    source = pending(application_prefix, family)
    if grouped:
        source = organize(source)
    context = organized if grouped else dict
    source = append(source, 'overhang-bulk', context(application(source, family)), 'apply')
    source = append(source, 'overhang-bulk', context(disconnect_params(source)), 'disconnect')
    broken = damage(source, 'apply', 'version_id')
    before = broken.model_dump_json()
    assert proof(broken)['status'] != 'verified'
    result = preview(broken, 'apply', 'version_id')
    assert result['status'] == 'preview', result
    assert [r['identity'] for r in result['selection']['candidates']] == ['candidate']
    assert result['selection']['not_evaluated'] == ['apply', 'disconnect']
    assert not result['selection']['whole_recipe_validated']
    repaired = repair(broken, 'apply', 'version_id', 'candidate')
    assert repaired['status'] == 'ready', repaired
    candidate = Design.model_validate(repaired['candidate'].model_dump(mode='json'))
    assert proof(candidate)['status'] == 'verified'
    assert not candidate.overhang_bindings and not candidate.overhang_connections and not candidate.duplexes
    assert broken.model_dump_json() == before


@pytest.mark.parametrize('key', ['overhang_a_id', 'overhang_b_id'])
def test_endpoint_repair_uses_prefix_and_excludes_other_end(application_prefix, key):
    source = pending(application_prefix)
    target = source.feature_log[-1]
    expected = target.params[key]
    broken = damage(source, target.id, key)
    result = preview(broken, target.id, key)
    assert result['status'] == 'preview', result
    assert [r['identity'] for r in result['selection']['candidates']] == [expected]
    candidate = repair(broken, target.id, key, expected)['candidate']
    assert proof(candidate)['status'] == 'verified'
    description = describe_inputs('overhang-bulk', broken.feature_log[-1].params)
    assert description['definition_supported']
    assert {tuple(f['parameter_path']) for f in description['fields']} == {('overhang_a_id',), ('overhang_b_id',)}


@pytest.mark.parametrize('path', [['history_seed'], ['connection_id'], ['conflict_duplex_ids', 0],
                                   ['_connection_organization'], ['direct_owner_seeds', 0]])
def test_output_identity_and_compound_ownership_slots_stay_closed(application_prefix, path):
    from backend.core.part_command_errors import CommandContractError
    source = organize(pending(application_prefix))
    with pytest.raises(CommandContractError) as error:
        reference_slot('overhang-bulk', organized(application(source, 'root-to-root')), path)
    assert error.value.code == 'unsupported_reference_slot'


def test_bad_expectation_does_not_offer_or_apply_candidates(application_prefix):
    source = pending(application_prefix)
    target = source.feature_log[-1]
    broken = damage(source, target.id, 'overhang_a_id')
    assert preview(broken, target.id, 'overhang_a_id', expected_old='stale')['status'] != 'preview'
    assert repair(broken, target.id, 'overhang_a_id', target.params['overhang_a_id'], expected_old='stale')['status'] != 'ready'


def test_candidates_exclude_wrong_pair_type_future_and_unlogged_versions(application_prefix):
    from tests.test_part_pending_connection_versions import creation
    source = pending(application_prefix)
    # Explicit metadata producers, all before the selected Apply except Future.
    for identity, family, reverse in [('alternative', 'root-to-root', False),
                                     ('wrong-type', 'root-to-root-indirect', False),
                                     ('reverse', 'root-to-root', True)]:
        params = creation(source, version_id=identity, connection_type=family,
                          overhang_a_seq='A' * 12, overhang_b_seq='T' * 12)
        if reverse:
            params['overhang_a_id'], params['overhang_b_id'] = params['overhang_b_id'], params['overhang_a_id']
        source = append(source, 'overhang-bulk', {**params, '_proof_version': 1,
            'connection_version_contract': 1, 'action': 'connection-version-create'}, identity)
    source = append(source, 'overhang-bulk', application(source, 'root-to-root'), 'apply')
    params = creation(source, version_id='future', connection_type='root-to-root')
    source = append(source, 'overhang-bulk', {**params, '_proof_version': 1,
        'connection_version_contract': 1, 'action': 'connection-version-create'}, 'future')
    source = damage(source, 'apply', 'version_id')
    source = source.copy_with(connection_versions=[*source.connection_versions,
        source.connection_versions[0].model_copy(update={'id': 'unlogged'})])
    result = preview(source, 'apply', 'version_id', limit=1)
    assert result['status'] == 'preview', result
    assert result['selection']['eligible_count'] == 2 and result['selection']['truncated']
    assert [r['identity'] for r in result['selection']['candidates']] == ['candidate']


def test_inspection_exposes_connection_reference_without_reading_geometry(application_prefix, monkeypatch):
    from backend.api import part_repair_input_metadata as metadata, state, doc_context
    from uuid import uuid4
    source = pending(application_prefix)
    target = source.feature_log[-1]
    source = damage(source, target.id, 'overhang_a_id')
    token = doc_context.set_current_doc('__connection_repair_inputs__' + str(uuid4()))
    doc = doc_context.get_current_doc()
    old = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    try:
        state.load_design(source)
        source.feature_log[-1].post_state_gz_b64 = object()
        source.helices = object()
        result = metadata.inspect_inputs({'expected_design_id': source.id, 'expected_revision': state.revision(),
                                          'feature_id': target.id})
        assert result['definition_supported'] and not result['references_checked']
        assert result['fields'][0]['expected_old'] == 'missing'
        assert result['fields'][0]['reference_selection']['resource_kind'] == 'overhang'
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(old[0])
        doc_context.set_request_feature_log_entry_id(old[1])


def test_organized_repair_job_publishes_once_and_undo_restores_broken_recipe(application_prefix, monkeypatch):
    from threading import Thread
    from uuid import uuid4
    from backend.api import state, doc_context, part_evaluation_jobs as jobs, part_group_organization_gate as gate
    source = organize(pending(application_prefix, 'root-to-root-ssdna-linker'))
    source = append(source, 'overhang-bulk', organized(application(source, 'root-to-root-ssdna-linker')), 'apply')
    source = append(source, 'overhang-bulk', organized(disconnect_params(source)), 'disconnect')
    source = damage(source, 'apply', 'version_id')
    before = source.model_dump_json()
    threads = []
    def submit(*args):
        thread = Thread(target=jobs._run, args=args, daemon=False)
        threads.append(thread)
        thread.start()
    monkeypatch.setattr(jobs, '_submit', submit)
    monkeypatch.setattr(gate, 'GROUP_ORGANIZATION_ENABLED', True)
    token = doc_context.set_current_doc('__connection_repair_job__' + str(uuid4()))
    doc = doc_context.get_current_doc()
    old = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    identity = None
    try:
        state.load_design(source)
        revision = state.revision()
        import gc
        gc.collect()  # Release fixture graphs outside capture; no latency claim.
        started = jobs.start({'operation': 'repair', 'repair': {
            'repair_version': 1, 'expected_design_id': source.id, 'expected_revision': revision,
            'actions': [{'action': 'set_input', 'feature_id': 'apply', 'parameter_path': ['version_id'],
                         'expected_old': 'missing', 'value': 'candidate'}]}})
        identity = started['job_id']
        threads[0].join(15)
        assert not threads[0].is_alive()
        result = jobs.inspect(identity)['result']
        assert result['status'] == 'ready', result
        assert state.get_or_404().model_dump_json() == before
        jobs.commit(identity)
        assert state.revision() == revision + 1 and state.undo_depth() == 1
        jobs.commit(identity)
        assert state.revision() == revision + 1 and state.undo_depth() == 1
        assert proof(Design.model_validate_json(state.get_or_404().model_dump_json()))['status'] == 'verified'
        state.undo()
        assert state.get_or_404().model_dump_json() == before
        assert proof(state.get_or_404())['status'] != 'verified'
        state.redo()
        assert proof(state.get_or_404())['status'] == 'verified'
    finally:
        with jobs._lock:
            job = jobs._jobs.get(identity)
            if job is not None:
                job.cancelled.set()
        for thread in threads:
            thread.join(5)
            assert not thread.is_alive()
        with jobs._lock:
            jobs._jobs.pop(identity, None)
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(old[0])
        doc_context.set_request_feature_log_entry_id(old[1])


@pytest.mark.parametrize('action', ['patch', 'delete', 'apply', 'unapply', 'disconnect_delete', 'create', 'connect'])
def test_metadata_exposes_only_reviewed_slots_for_each_native_action(application_prefix, action):
    from backend.api.part_connection_organized_routes import capture_inputs
    source = organize(pending(application_prefix))
    choices = {'overhang_a_id': source.overhangs[0].id, 'overhang_b_id': source.overhangs[1].id,
               'connection_type': 'root-to-root', 'name': 'Other'} if action in {'create', 'connect'} else {}
    params = capture_inputs(source, action, choices, 'candidate' if action not in {'create', 'connect'} else None)
    result = describe_inputs('overhang-bulk', params)
    assert result['definition_supported'], result
    expected = {('overhang_a_id',), ('overhang_b_id',)} if action in {'create', 'connect'} else {('version_id',)}
    assert {tuple(field['parameter_path']) for field in result['fields']} == expected


def test_broken_prefix_stops_before_candidate_scan(application_prefix):
    source = pending(application_prefix)
    target = source.feature_log[-1]
    source = damage(source, target.id, 'overhang_a_id')
    first = source.feature_log[0]
    source = source.copy_with(feature_log=[first.model_copy(update={'params': {'_proof_version': 99}}),
                                         *source.feature_log[1:]])
    result = preview(source, target.id, 'overhang_a_id')
    assert result['status'] != 'preview'
    assert not result['selection']['candidates']
    assert result['issues'][0]['feature_id'] == first.id


def test_candidate_inventory_refuses_duplicates_and_oversize_before_iteration(application_prefix, monkeypatch):
    from backend.api import part_connection_repair_selection as adapter
    from backend.api.part_repair_selection import SelectionRequest
    from backend.core.part_command_errors import CommandContractError
    source = pending(application_prefix)
    target = source.feature_log[-1]
    slot = adapter.reference_slot(target.params, ['overhang_a_id'])
    request = SelectionRequest.model_validate(selection(source, target.id, 'overhang_a_id'))
    duplicate = source.copy_with(overhangs=[source.overhangs[0], source.overhangs[0]])
    with pytest.raises(CommandContractError) as error:
        adapter.candidates(duplicate, slot, target.params, request, lambda: None)
    assert error.value.code == 'invalid_selection'
    class Unvisited(list):
        def __iter__(self):
            pytest.fail('Oversize candidate table was iterated')
    monkeypatch.setattr(adapter, 'MAX_OPERATION_NODES', 1)
    with pytest.raises(CommandContractError) as error:
        adapter.candidates(source.copy_with(overhangs=Unvisited(source.overhangs)), slot, target.params, request, lambda: None)
    assert error.value.code == 'connection_selection_limit'
