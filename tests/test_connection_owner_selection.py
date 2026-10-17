"""Creator selections survive conditional direct ownership without hiding damage."""

import pytest

from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import append, native_prefix as native_prefix, proof
from tests.test_part_connection_direct import pending, params as direct_params
from tests.test_part_connection_direct_compose import params as connect_params
from tests.test_part_connection_inverse import apply_params, compose_params


def values_for(source, family, combined):
    from backend.api.part_connection_owner_selection import capture_selection
    if family == 'direct':
        values = connect_params(source, 'end-to-root', identity='replacement', seed=931) if combined else direct_params(source, 'replacement', seed=925)
        values['direct_composition_version' if combined else 'direct_application_version'] = 2
    else:
        values = compose_params(source, family) if combined else apply_params(source)
        values['connection_composition_version' if combined else 'connection_application_version'] = 4
    from backend.api.part_connection_direct_recording import conflict_values
    values.update(conflict_values(source, values["overhang_a_id"], values["overhang_b_id"]))
    values.update(capture_selection(source, values))
    return values


@pytest.mark.parametrize('family', ['direct', 'root-to-root-ssdna-linker', 'root-to-root-indirect'])
@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('length', [8, 16])
@pytest.mark.parametrize('direct_type', ['root-to-root', 'end-to-root'])
def test_creator_selection_survives_both_branches_and_returns_to_equal(application_prefix, family, combined, length, direct_type):
    from backend.api.part_recipe_edit import prepare_change
    from backend.core.part_verification_capture import capture
    source = pending(application_prefix, direct_type)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    if not combined:
        source = pending(source, 'end-to-root' if family == 'direct' else family, 'replacement')
    values = values_for(source, family, combined)
    assert len(values['direct_owner_seeds']) == 1
    assert values['conflict_binding_ids'] == values['conflict_duplex_ids'] == []
    source = append(source, 'overhang-bulk', values, 'consumer')
    before = source.model_dump_json()
    index = next(i for i, e in enumerate(source.feature_log) if e.id == 'endpoint-2')
    changed, _ = prepare_change(source, capture(source, preserve_entry_types=True), index, lambda: None,
                             params={'length_bp': length})
    assert proof(changed)['status'] == 'verified'
    restored, _ = prepare_change(changed, capture(changed, preserve_entry_types=True), index, lambda: None,
                              params={'length_bp': 12})
    assert proof(restored)['status'] == 'verified'
    assert source.model_dump_json() == before


@pytest.mark.parametrize('damage', ['missing_binding', 'missing_duplex', 'overlap', 'unknown_seed'])
def test_creator_selection_does_not_hide_missing_or_ambiguous_owner(application_prefix, damage):
    from backend.api.part_connection_application_commands import build
    from backend.core.part_command_errors import CommandContractError
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    source = pending(source, 'root-to-root-indirect', 'replacement')
    values = values_for(source, 'root-to-root-indirect', False)
    if damage == 'missing_binding':
        source = source.copy_with(overhang_bindings=[])
    elif damage == 'missing_duplex':
        source = source.copy_with(duplexes=[])
    elif damage == 'overlap':
        values['conflict_duplex_ids'] = [source.duplexes[0].id]
    else:
        values['direct_owner_seeds'] = ['00000000-0000-0000-0000-000000000001']
    before = source.model_dump_json()
    with pytest.raises(CommandContractError):
        build(source, values)
    assert source.model_dump_json() == before


def test_creator_dependency_and_independent_worker_after_edit(application_prefix):
    from backend.api.part_proof_commands import dependencies
    from backend.api.part_recipe_edit import prepare_change
    from backend.api.part_verification_worker import VerificationWorker
    from backend.core.part_dependencies import Resource
    from backend.core.part_verification_capture import capture
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    source = pending(source, 'root-to-root-indirect', 'replacement')
    values = values_for(source, 'root-to-root-indirect', False)
    deps = dependencies('overhang-bulk', values)
    assert Resource('duplex', source.duplexes[0].id) in deps.reads
    assert not any(ref.kind == 'overhang_binding' for ref in deps.reads)
    source = append(source, 'overhang-bulk', values, 'inverse')
    index = next(i for i, e in enumerate(source.feature_log) if e.id == 'endpoint-2')
    changed, _ = prepare_change(source, capture(source, preserve_entry_types=True), index, lambda: None,
                                params={'length_bp': 16})
    worker = VerificationWorker(capture(changed))
    try:
        worker.start()
        assert worker.wait(5)
        assert worker.result()['status'] == 'verified'
    finally:
        worker.close()


@pytest.mark.parametrize('seeds', [None, [], ['bad'], ['00000000-0000-0000-0000-000000000001'] * 2,
                                  ['00000000-0000-0000-0000-00000000000A']])
def test_selector_schema_and_exact_remainder(application_prefix, seeds):
    from backend.api.part_connection_application_commands import build
    from backend.core.part_command_errors import CommandContractError
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    source = pending(source, 'root-to-root-indirect', 'replacement')
    values = values_for(source, 'root-to-root-indirect', False)
    values['direct_owner_seeds'] = seeds
    with pytest.raises((ValueError, CommandContractError)):
        build(source, values)


def test_capture_is_bounded_and_refuses_duplicate_producers(application_prefix, monkeypatch):
    from backend.api import part_connection_owner_selection as selection
    from backend.core.part_command_errors import CommandContractError
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    source = pending(source, 'root-to-root-indirect', 'replacement')
    values = apply_params(source)
    duplicate = source.copy_with(feature_log=[*source.feature_log, source.feature_log[-2]])
    with pytest.raises(CommandContractError, match='multiple producers'):
        selection.capture_selection(duplicate, values)
    monkeypatch.setattr(selection, 'MAX_PRODUCERS', 1)
    with pytest.raises(CommandContractError, match='producer allowance'):
        selection.capture_selection(source, values)


@pytest.mark.parametrize('family', ['direct', 'root-to-root-indirect'])
@pytest.mark.parametrize('combined', [False, True])
def test_new_contract_identity_and_connect_producer_capture(application_prefix, family, combined):
    from backend.core.part_edit_identity import preserve_proof_identity
    source = append(application_prefix, 'overhang-bulk', connect_params(application_prefix, 'root-to-root'), 'direct')
    if not combined:
        source = pending(source, 'end-to-root' if family == 'direct' else family, 'replacement')
    values = values_for(source, family, combined)
    assert len(values['direct_owner_seeds']) == 1
    marker = ('direct_' if family == 'direct' else 'connection_') + ('composition_version' if combined else 'application_version')
    changed = preserve_proof_identity(values, {**values, marker: 1}, kind='overhang-bulk')
    assert changed[marker] == values[marker]
    assert proof(append(source, 'overhang-bulk', values, 'consumer'))['status'] == 'verified'
