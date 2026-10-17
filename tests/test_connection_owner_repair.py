"""Reviewed literal-owner migration preserves identity and survives branch edits."""

from copy import deepcopy

import pytest

from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_repair import prepare_repair
from backend.core.part_connection_owner_repair import upgrade_action
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import append, native_prefix as native_prefix, proof
from tests.test_part_connection_direct import pending, params as direct_params
from tests.test_part_connection_inverse import apply_params, compose_params
from tests.test_part_connection_direct_compose import params as connect_params


def history(source, family, combined):
    source = pending(source)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    if not combined:
        source = pending(source, 'end-to-root' if family == 'direct' else family, 'replacement')
    values = (connect_params(source, 'end-to-root', identity='replacement', seed=931) if combined else
              direct_params(source, 'replacement', seed=925)) if family == 'direct' else (
              compose_params(source, family) if combined else apply_params(source))
    from backend.api.part_connection_direct_recording import conflict_values
    values.update(conflict_values(source, values['overhang_a_id'], values['overhang_b_id']))
    source = append(source, 'overhang-bulk', values, 'consumer')
    return source


def request(source):
    row = source.feature_log[-1]
    return {'repair_version': 1, 'expected_design_id': source.id, 'expected_revision': 7,
            'actions': [upgrade_action(row.op_kind, row.params, row.id)]}


def run(source, body=None):
    return prepare_repair(source, body or request(source), source_revision=7,
                          executor=execute, dependency_resolver=dependencies)


@pytest.mark.parametrize('family', ['direct', 'root-to-root-ssdna-linker', 'root-to-root-indirect'])
@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('length', [8, 16])
def test_explicit_upgrade_repairs_both_conditional_branches(application_prefix, family, combined, length):
    from backend.api.part_recipe_edit import prepare_change
    from backend.core.part_verification_capture import capture
    source = history(application_prefix, family, combined)
    body = request(source)
    index = next(i for i, e in enumerate(source.feature_log) if e.id == 'endpoint-2')
    # A broken recipe may retain its last materialized state. Only inputs are
    # changed here; repair must rebuild independently, never certify that state.
    log = list(source.feature_log)
    log[index] = log[index].model_copy(update={'params': {**log[index].params, 'length_bp': length}})
    broken = source.copy_with(feature_log=log)
    before = broken.model_dump_json()
    assert proof(broken)['status'] != 'verified'
    result = run(broken, body)
    assert result['status'] == 'ready', result
    candidate = result['candidate']
    old, new = source.feature_log[-1].params, candidate.feature_log[-1].params
    changed_keys = {k for k in set(old) | set(new) if old.get(k) != new.get(k)}
    marker = ('direct_composition_version' if combined else 'direct_application_version') if family == 'direct' else (
        'connection_composition_version' if combined else 'connection_application_version')
    assert changed_keys == {marker, 'direct_owner_seeds', 'conflict_binding_ids', 'conflict_duplex_ids'}
    assert new['direct_owner_seeds'] == [next(e for e in source.feature_log if e.id == 'direct').params['history_seed']]
    assert proof(candidate)['status'] == 'verified'
    changed, _ = prepare_change(candidate, capture(candidate, preserve_entry_types=True), index, lambda: None,
                                params={'length_bp': 12})
    assert proof(changed)['status'] == 'verified'
    assert result['repair']['definition_upgrades'][0]['family'] == 'connection_owner_selection'
    assert broken.model_dump_json() == before


@pytest.mark.parametrize('fault', ['stale', 'overlap_before', 'overlap_after', 'duplicate'])
def test_exact_receipt_and_nonoverlap_are_required(application_prefix, fault):
    source = history(application_prefix, 'root-to-root-ssdna-linker', False)
    body = request(source)
    if fault == 'stale':
        body['actions'][0]['expected_definition_sha256'] = '0' * 64
    elif fault == 'duplicate':
        body['actions'].append(deepcopy(body['actions'][0]))
    else:
        row = source.feature_log[-1]
        edit = {'action': 'set_input', 'feature_id': row.id, 'parameter_path': ['version_id'],
                'expected_old': row.params['version_id'], 'value': row.params['version_id']}
        body['actions'].insert(0 if fault == 'overlap_before' else 1, edit)
    before = source.model_dump_json()
    result = run(source, body)
    assert result['status'] != 'ready'
    assert result['issues'][0]['code'] == ('repair_conflict' if fault == 'stale' else 'overlapping_repair_paths')
    assert source.model_dump_json() == before


@pytest.mark.parametrize('fault', ['future', 'duplicate', 'unknown_owner', 'unknown_producer'])
def test_only_unique_recognized_preceding_creators_can_migrate(application_prefix, fault):
    source = history(application_prefix, 'root-to-root-ssdna-linker', False)
    producer = next(e for e in source.feature_log if e.id == 'direct')
    if fault == 'future':
        source = source.copy_with(feature_log=[e for e in source.feature_log if e.id != 'direct'] + [producer])
        target = next(e for e in source.feature_log if e.id == 'consumer')
    else:
        target = source.feature_log[-1]
        if fault == 'duplicate':
            source = source.copy_with(feature_log=[*source.feature_log[:-1], producer.model_copy(update={'id': 'duplicate'}), target])
        elif fault == 'unknown_producer':
            source = source.copy_with(feature_log=[e.model_copy(update={'params': {**e.params, 'direct_application_version': 99}})
                if e.id == producer.id else e for e in source.feature_log])
        else:
            target = target.model_copy(update={'params': {**target.params, 'conflict_duplex_ids': ['unknown']}})
            source = source.copy_with(feature_log=[*source.feature_log[:-1], target])
    from backend.core.part_repair_inputs import UpgradeConnectionOwners
    from backend.core.part_connection_owner_repair import upgrade
    from backend.core.part_command_errors import CommandContractError
    action = UpgradeConnectionOwners.model_validate(upgrade_action(target.op_kind, target.params, target.id))
    with pytest.raises(CommandContractError) as error:
        upgrade(source, target, action, dependencies=dependencies)
    assert error.value.code == ('ambiguous_connection_creator' if fault == 'duplicate' else 'unsupported_connection_owner_upgrade')


def test_discovery_is_source_free_without_hashing_or_producer_scan(application_prefix, monkeypatch):
    from backend.core.part_repair_inputs import RepairRequest
    from backend.core.part_repair_proposal import proposed_inputs
    from backend.core import part_connection_owner_repair as migration
    source = history(application_prefix, 'root-to-root-ssdna-linker', False)
    actions = RepairRequest.model_validate(request(source)).actions
    monkeypatch.setattr(migration, 'definition_sha256', lambda *_: pytest.fail('Discovery hashed the definition'))
    monkeypatch.setattr(migration, 'owner_ids', lambda *_: pytest.fail('Discovery scanned producer identities'))
    proposed = proposed_inputs(source, actions, check_expectations=False)
    assert len(proposed) == 1 and proposed[0][1] == source.feature_log[-1].params


def test_descriptor_and_draft_roundtrip_preserve_exact_migration(application_prefix):
    from backend.api.part_repair_input_metadata import describe_inputs
    from backend.core.part_repair_inputs import RepairRequest
    from backend.core.part_repair_proposal import proposed_inputs
    source = history(application_prefix, 'root-to-root-ssdna-linker', False)
    row = source.feature_log[-1]
    descriptor = describe_inputs(row.op_kind, row.params, feature_id=row.id)
    assert descriptor['definition_supported']
    action = descriptor['upgrades'][0]['action']
    assert action == request(source)['actions'][0]
    parsed = RepairRequest.model_validate_json(RepairRequest.model_validate(request(source)).model_dump_json())
    proposed = proposed_inputs(source, parsed.actions, dependencies=dependencies)
    assert proposed[0][1]['connection_application_version'] == 4
    assert proposed[0][1]['direct_owner_seeds']
    assert row.params['connection_application_version'] == 3


def test_native_repair_job_migrates_commits_once_and_reloads(application_prefix, monkeypatch):
    from threading import Thread
    from uuid import uuid4
    from backend.api import state, doc_context, part_evaluation_jobs as jobs
    from backend.core.models import Design
    source = history(application_prefix, 'root-to-root-ssdna-linker', False)
    index = next(i for i, entry in enumerate(source.feature_log) if entry.id == 'endpoint-2')
    log = list(source.feature_log)
    log[index] = log[index].model_copy(update={'params': {**log[index].params, 'length_bp': 16}})
    source = source.copy_with(feature_log=log)
    before = source.model_dump_json()
    threads, identity = [], None
    def submit(*args):
        thread = Thread(target=jobs._run, args=args, daemon=False)
        threads.append(thread)
        thread.start()
    monkeypatch.setattr(jobs, '_submit', submit)
    doc = '__owner_migration__' + str(uuid4())
    token = doc_context.set_current_doc(doc)
    markers = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    try:
        state.load_design(source)
        revision = state.revision()
        body = request(source)
        body['expected_revision'] = revision
        import gc
        gc.collect()  # Fixture cleanup outside production capture; no latency claim.
        identity = jobs.start({'operation': 'repair', 'repair': body})['job_id']
        threads[0].join(15)
        assert not threads[0].is_alive()
        result = jobs.inspect(identity)['result']
        assert result['status'] == 'ready', result
        assert result['repair']['definition_upgrades'][0]['to_version'] == 4
        assert state.get_or_404().model_dump_json() == before
        jobs.commit(identity)
        jobs.commit(identity)
        assert state.revision() == revision + 1 and state.undo_depth() == 1
        candidate = Design.model_validate_json(state.get_or_404().model_dump_json())
        assert proof(candidate)['status'] == 'verified'
        state.undo()
        assert state.get_or_404().model_dump_json() == before
        state.redo()
        assert state.get_or_404().feature_log[-1].params['direct_owner_seeds']
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
        doc_context.set_request_revision(markers[0])
        doc_context.set_request_feature_log_entry_id(markers[1])



def test_inspected_receipt_preserves_generator_attribution(application_prefix):
    from backend.api.part_repair_input_metadata import describe_inputs
    source = history(application_prefix, 'root-to-root-ssdna-linker', False)
    target = source.feature_log[-1]
    target = target.model_copy(update={'params': {**target.params, '_generator': {'note': 'native attribution'}}})
    source = source.copy_with(feature_log=[*source.feature_log[:-1], target])
    descriptor = describe_inputs(target.op_kind, target.params, feature_id=target.id)
    body = request(source)
    assert descriptor['upgrades'][0]['action'] == body['actions'][0]
    result = run(source, body)
    assert result['status'] == 'ready', result
    assert result['candidate'].feature_log[-1].params['_generator'] == target.params['_generator']


def test_migration_does_not_hide_missing_current_native_ownership(application_prefix):
    source = history(application_prefix, 'root-to-root-ssdna-linker', False)
    # A checked creator definition is not enough: native resolution must still
    # find its complete live owners in the rebuilt prefix.
    def damaged_execute(kind, design, params):
        updated = execute(kind, design, params)
        if params.get('action') == 'connection-version-apply-direct':
            return updated.copy_with(overhang_bindings=[])
        return updated
    result = prepare_repair(source, request(source), source_revision=7,
                            executor=damaged_execute, dependency_resolver=dependencies)
    assert result['status'] != 'ready'
    assert result['issues'][0]['feature_id'] == 'consumer'
    assert 'candidate' not in result
