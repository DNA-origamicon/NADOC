"""Versioned inverse replacement must restore direct owners before linker replay."""

import pytest

from tests.test_connection_direct_replacement import direct_source as direct_source
from tests.test_part_connection_application_commands import (
    FINITE_TYPES, _params, application_prefix as application_prefix,
)
from tests.test_part_pending_connection_versions import append, authored, native_prefix as native_prefix, proof
from tests.test_part_connection_direct import pending, params as direct_params
from tests.test_part_connection_direct_compose import params as connect_params

TYPES = [*FINITE_TYPES, 'root-to-root-indirect', 'end-to-end-indirect']


def apply_params(source, identity='replacement'):
    from backend.api.part_connection_direct_recording import conflict_values
    values = _params(source, version_id=identity, connection_id='inverse-linker')
    values['connection_application_version'] = 3
    values.update(conflict_values(source, values['overhang_a_id'], values['overhang_b_id']))
    return values


def compose_params(source, connection_type):
    from backend.api.part_connection_direct_recording import conflict_values
    values = connect_params(source, connection_type, identity='replacement')
    values.pop('history_seed')
    values.pop('direct_composition_version')
    values.update(action='connection-version-connect-linker', connection_composition_version=3,
                  connection_id='inverse-linker')
    values.update(conflict_values(source, values['overhang_a_id'], values['overhang_b_id']))
    return values


@pytest.mark.parametrize('direct_type', ['root-to-root', 'end-to-root'])
@pytest.mark.parametrize('connection_type', TYPES)
@pytest.mark.parametrize('combined', [False, True])
def test_all_native_linker_types_replace_direct_and_replay(direct_source, direct_type, connection_type, combined, monkeypatch):
    from backend.api import part_connection_application_commands as application
    from backend.api import part_connection_composition_commands as composition
    from tests.test_part_connection_application_commands import _legacy
    from tests.test_part_connection_application_commands import parallel_bridge, assert_parallel_bridge_refused
    source = pending(direct_source, direct_type)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    if parallel_bridge(source, connection_type):
        if combined:
            values = compose_params(source, connection_type)
            staged = composition._stage(source, composition.parse_command(values))
            assert_parallel_bridge_refused(lambda: _legacy(staged, apply_params(staged), monkeypatch),
                                           lambda: composition.build(source, values))
        else:
            source = pending(source, connection_type, 'replacement')
            values = apply_params(source)
            assert_parallel_bridge_refused(lambda: _legacy(source, values, monkeypatch),
                                           lambda: application.build(source, values))
        return
    if combined:
        values = compose_params(source, connection_type)
    else:
        source = pending(source, connection_type, 'replacement')
        values = apply_params(source)
    before = source.model_dump_json()
    staged = composition._stage(source, composition.parse_command(values)) if combined else source
    expected, expected_report = _legacy(staged, apply_params(staged), monkeypatch)
    actual, report = (composition if combined else application).build(source, values)
    assert authored(actual) == authored(expected)
    assert report == expected_report
    result = append(source, 'overhang-bulk', values, 'inverse')
    assert not result.duplexes and not result.overhang_bindings
    assert not any(c.overhang_duplex_driver_id for c in result.cluster_transforms)
    assert len(result.overhang_connections) == 1
    assert result.overhang_connections[0].id == 'inverse-linker'
    assert [v.applied for v in result.connection_versions] == [False, True]
    assert proof(result)['status'] == 'verified'
    assert source.model_dump_json() == before


@pytest.mark.parametrize('version', [1, 2])
def test_saved_linker_contracts_do_not_acquire_direct_replacement_semantics(application_prefix, version):
    from backend.api.part_connection_application_commands import build
    from backend.core.part_command_errors import CommandContractError
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    source = pending(source, TYPES[0], 'replacement')
    values = _params(source, version_id='replacement')
    values['connection_application_version'] = version
    before = source.model_dump_json()
    with pytest.raises(CommandContractError):
        build(source, values)
    assert source.model_dump_json() == before


@pytest.mark.parametrize('field', ['conflict_binding_ids', 'conflict_duplex_ids'])
def test_inverse_requires_exact_direct_owner_selection(application_prefix, field):
    from backend.api.part_connection_application_commands import build
    from backend.core.part_command_errors import ReferenceResolutionError
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    source = pending(source, TYPES[0], 'replacement')
    values = apply_params(source)
    values[field] = []
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError):
        build(source, values)
    assert source.model_dump_json() == before


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('marker', [True, 3.0, '3', 4, None, []])
def test_v3_requires_exact_version_and_complete_conflict_fields(application_prefix, combined, marker):
    from backend.api.part_proof_commands import dependencies
    source = pending(application_prefix, TYPES[0], 'replacement')
    values = compose_params(application_prefix, TYPES[0]) if combined else apply_params(source)
    key = 'connection_composition_version' if combined else 'connection_application_version'
    assert not dependencies('overhang-bulk', {**values, key: marker}).known


@pytest.mark.parametrize('corruption', ['restoration', 'ligation', 'placement', 'incoming'])
def test_inverse_refuses_corrupt_or_referenced_direct_ownership(application_prefix, corruption):
    from backend.api.part_connection_application_commands import build
    from backend.core.part_command_errors import CommandContractError
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    source = pending(source, TYPES[0], 'replacement').model_copy(deep=True)
    binding = source.overhang_bindings[0]
    child = next(c for c in source.cluster_transforms if c.overhang_duplex_driver_id)
    if corruption == 'restoration':
        binding.prior_driven_topology['strand_id'] = 'missing'
    elif corruption == 'ligation':
        identity = binding.prior_driven_topology['forced_ligation']['id']
        source.forced_ligations = [f for f in source.forced_ligations if f.id != identity]
    elif corruption == 'placement':
        child.domain_ids = []
    else:
        next(c for c in source.cluster_transforms if c.id != child.id).parent_cluster_id = child.id
    before = source.model_dump_json()
    with pytest.raises(CommandContractError):
        build(source, apply_params(source))
    assert source.model_dump_json() == before


@pytest.mark.parametrize('combined', [False, True])
@pytest.mark.parametrize('field', ['conflict_binding_ids', 'conflict_duplex_ids'])
def test_v3_cannot_omit_direct_owner_fields(application_prefix, combined, field):
    from backend.api.part_proof_commands import dependencies
    source = pending(application_prefix, TYPES[0], 'replacement')
    values = compose_params(application_prefix, TYPES[0]) if combined else apply_params(source)
    values.pop(field)
    assert not dependencies('overhang-bulk', values).known


def test_inverse_reads_direct_owners_and_preserves_version_three_identity(application_prefix):
    from backend.api.part_proof_commands import dependencies
    from backend.core.part_dependencies import Resource
    from backend.core.part_edit_identity import preserve_proof_identity
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    source = pending(source, TYPES[0], 'replacement')
    values = apply_params(source)
    deps = dependencies('overhang-bulk', values)
    assert Resource('overhang_binding', source.overhang_bindings[0].id) in deps.reads
    assert Resource('duplex', source.duplexes[0].id) in deps.reads
    changed = preserve_proof_identity(values, {**values, 'connection_application_version': 2,
        'connection_id': 'different'}, kind='overhang-bulk')
    assert changed['connection_application_version'] == 3
    assert changed['connection_id'] == values['connection_id']


def test_branch_changing_edit_flags_stale_owner_then_explicit_recipe_repair_replays(application_prefix):
    from fastapi import HTTPException
    from backend.api.part_recipe_edit import prepare_change, regenerate
    from backend.api.part_verification_worker import VerificationWorker
    from backend.core.part_verification_capture import capture
    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', direct_params(source), 'direct')
    source = pending(source, 'root-to-root-indirect', 'replacement')
    source = append(source, 'overhang-bulk', apply_params(source), 'inverse')
    before = source.model_dump_json()
    index = next(i for i, entry in enumerate(source.feature_log) if entry.id == 'endpoint-2')
    with pytest.raises(HTTPException) as caught:
        prepare_change(source, capture(source, preserve_entry_types=True), index, lambda: None,
                       params={'length_bp': 16})
    assert caught.value.status_code == 409
    assert caught.value.detail['feature_id'] == 'inverse'
    assert caught.value.detail['code'] == 'missing_reference'
    assert caught.value.detail['references'][0]['parameter_path'] == ['conflict_binding_ids']
    # Explicit isolated recipe correction, not automatic retargeting or a UI
    # qualification claim: unequal construction has only the stable Duplex owner.
    entries = list(source.feature_log)
    entries[index] = entries[index].model_copy(update={'params': {**entries[index].params, 'length_bp': 16}})
    entries[-1] = entries[-1].model_copy(update={'params': {**entries[-1].params, 'conflict_binding_ids': []}})
    repaired = regenerate(source, entries, lambda: None)
    assert repaired.overhang_connections[0].id == source.overhang_connections[0].id
    worker = VerificationWorker(capture(repaired))
    try:
        worker.start()
        assert worker.wait(5)
        assert worker.result()['status'] == 'verified'
    finally:
        worker.close()
    assert source.model_dump_json() == before
