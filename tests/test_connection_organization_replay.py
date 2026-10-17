"""Explicit organized connection replay follows native material, not stale hosts."""

import pytest

from backend.api.part_proof_commands import execute
from tests.test_connection_direct_replacement import direct_source as direct_source
from tests.test_part_connection_application_commands import application_prefix as application_prefix, FINITE_TYPES
from tests.test_part_pending_connection_versions import append, native_prefix as native_prefix, proof, authored
from tests.test_part_connection_direct import pending, params as direct_params
from tests.test_part_connection_inverse import apply_params
from tests.test_connection_organization_characterization import organize, backing
from tests.test_connection_disconnect import params as disconnect_params

CONTEXT = {'version': 1, 'removed_hosts': 'follow_material'}


def organized(values):
    return {**values, '_connection_organization': CONTEXT}


def application(source, family):
    if family in {'root-to-root', 'end-to-root'}:
        return {**direct_params(source), 'direct_application_version': 2, 'direct_owner_seeds': []}
    return {**apply_params(source, 'candidate'), 'connection_application_version': 4, 'direct_owner_seeds': []}


@pytest.mark.parametrize('family', ['root-to-root', 'end-to-root', *FINITE_TYPES, 'root-to-root-indirect', 'end-to-end-indirect'])
def test_all_native_families_preserve_groups_and_disconnect_from_recipe(direct_source, family):
    source = organize(pending(direct_source, family))
    before = source.model_dump_json()
    values = application(source, family)
    native = execute('overhang-bulk', source.copy_with(group_organization=None), values)
    if family in {'root-to-root-dsdna-linker', 'end-to-end-dsdna-linker'}:
        # ISSUE-126: native output has duplicate directional occupancy. Native
        # parity alone cannot qualify group ancestry; keep the explicit refusal.
        from backend.core.part_command_errors import CommandContractError
        from backend.core.part_group_lineage import _inventory, _Budget
        with pytest.raises(CommandContractError, match='Overlapping domains') as native_error:
            _inventory(native, _Budget())
        with pytest.raises(CommandContractError) as organized_error:
            execute('overhang-bulk', source, organized(values))
        assert organized_error.value.code == native_error.value.code == 'ambiguous_group_lineage'
        assert source.model_dump_json() == before
        return
    result = append(source, 'overhang-bulk', organized(values), 'apply-organized')
    assert authored(result.copy_with(group_organization=None)) == authored(native)
    for i, overhang in enumerate(source.overhangs[:2]):
        group = next(g for g in result.group_organization.groups if g.id == f'domain-{i}')
        sid, ordinal, _ = backing(result, overhang.id)
        assert [(r.strand_id, r.domain_index) for r in group.domain_ids] == [(sid, ordinal)]
        host = next(g for g in result.group_organization.groups if g.id == f'host-{i}')
        if overhang.helix_id not in {h.id for h in result.helices}:
            assert [(r.strand_id, r.domain_index) for r in host.domain_ids] == [(sid, ordinal)]
        else:
            assert host.helix_ids == [overhang.helix_id] and not host.domain_ids
    assert proof(result)['status'] == 'verified'
    restored = append(result, 'overhang-bulk', organized(disconnect_params(result)), 'disconnect-organized')
    assert not restored.overhang_connections and not restored.overhang_bindings and not restored.duplexes
    assert proof(restored)['status'] == 'verified'
    assert source.model_dump_json() == before


@pytest.mark.parametrize('family', ['direct', 'root-to-root-ssdna-linker', 'root-to-root-indirect'])
@pytest.mark.parametrize('combined', [False, True])
def test_replacement_chain_replays_through_restoration(direct_source, family, combined):
    from tests.test_connection_owner_selection import values_for
    source = organize(pending(direct_source))
    source = append(source, 'overhang-bulk', organized(application(source, 'root-to-root')), 'first')
    if not combined:
        # Metadata authoring uses the same explicit organization context.
        from tests.test_part_pending_connection_versions import creation
        values = creation(source, version_id='replacement', overhang_a_seq='ACGTACGTACGT', overhang_b_seq='TGCATGCA')
        values.update(connection_type='end-to-root' if family == 'direct' else family,
                      connection_version_contract=2, action='connection-version-create', _proof_version=1, affected_version_ids=[])
        source = append(source, 'overhang-bulk', organized(values), 'alternative')
    values = values_for(source, family, combined)
    result = append(source, 'overhang-bulk', organized(values), 'replacement')
    assert proof(result)['status'] == 'verified'
    restored = append(result, 'overhang-bulk', organized(disconnect_params(result)), 'disconnect')
    assert proof(restored)['status'] == 'verified'


@pytest.mark.parametrize('context', [None, {}, {'version': True, 'removed_hosts': 'follow_material'},
    {'version': 1, 'removed_hosts': 'drop'}, {**CONTEXT, 'unknown': True}])
def test_invalid_context_stays_closed(application_prefix, context):
    from backend.api.part_proof_commands import dependencies
    source = organize(pending(application_prefix))
    values = {**application(source, 'root-to-root'), '_connection_organization': context}
    assert not dependencies('overhang-bulk', values).known
    with pytest.raises(NotImplementedError, match='versioned proof contract'):
        execute('overhang-bulk', source, values)


def test_context_never_opens_live_publication(application_prefix):
    from backend.api.part_group_organization_gate import require_live_design
    from fastapi import HTTPException
    result = execute('overhang-bulk', organize(pending(application_prefix)),
                     organized(application(pending(application_prefix), 'root-to-root')))
    with pytest.raises(HTTPException) as error:
        require_live_design(result)
    assert error.value.detail['code'] == 'group_organization_not_enabled'


def test_unobserved_material_is_refused_and_trace_is_reset(application_prefix):
    from backend.api.part_connection_organization import execute as tracked
    from backend.core.part_command_errors import CommandContractError
    source = organize(pending(application_prefix))
    values = organized(application(source, 'root-to-root'))
    def unobserved(kind, design, params):
        return design.copy_with(strands=design.strands[1:])
    with pytest.raises(CommandContractError, match='directional material'):
        tracked('overhang-bulk', source, values, unobserved)
    assert execute('overhang-bulk', source, values).group_organization is not None


def test_mixed_host_group_converts_entire_selection(application_prefix):
    source = organize(pending(application_prefix))
    hosts = [o.helix_id for o in source.overhangs[:2]]
    source = append(source, 'group-create', {'_proof_version': 1, 'group': {
        'id': 'both', 'name': 'Both ends', 'helix_ids': hosts, 'color': '#123456'}}, 'both')
    original_refs = {(s.id, i) for s in source.strands for i, d in enumerate(s.domains) if d.helix_id in hosts}
    result = execute('overhang-bulk', source, organized(application(source, 'root-to-root')))
    group = next(g for g in result.group_organization.groups if g.id == 'both')
    assert {(r.strand_id, r.domain_index) for r in group.domain_ids} == original_refs
    assert group.name == 'Both ends' and group.color == '#123456'


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_named_deformation_after_transport_rebuilds_and_proves(application_prefix, kind):
    from tests.test_group_organization_consumers import operation, append_deformation
    from backend.api.part_recipe_edit import prepare_change
    from backend.core.part_verification_capture import capture
    from backend.api.part_verification_worker import VerificationWorker
    source = organize(pending(application_prefix))
    source = append(source, 'overhang-bulk', organized(application(source, 'root-to-root')), 'apply')
    source = append_deformation(source, operation('host-1', kind=kind))
    assert proof(source)['status'] == 'verified'
    index = next(i for i, e in enumerate(source.feature_log) if e.id == 'endpoint-2')
    changed, _ = prepare_change(source, capture(source, preserve_entry_types=True), index, lambda: None,
                               params={'length_bp': 16})
    assert proof(changed)['status'] == 'verified'
    worker = VerificationWorker(capture(changed))
    try:
        worker.start()
        assert worker.wait(5)
        assert worker.result()['status'] == 'verified'
    finally:
        worker.close()


def test_unorganized_commands_do_not_scan_lineage(application_prefix, monkeypatch):
    from backend.core.part_connection_lineage import ConnectionLineage
    def forbidden(*args, **kwargs):
        pytest.fail('Unorganized native operation entered lineage inventory')
    monkeypatch.setattr(ConnectionLineage, '__init__', forbidden)
    source = pending(application_prefix)
    assert execute('overhang-bulk', source, application(source, 'root-to-root')).duplexes
