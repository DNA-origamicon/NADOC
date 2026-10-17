"""Native direct Apply must regenerate from inputs and validate replacement owners."""

from copy import deepcopy
from uuid import UUID

import pytest

from tests.test_connection_direct_replacement import direct_source as direct_source
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import (
    CREATE, append, authored, creation, native_prefix as native_prefix, proof,
)

ACTION = 'connection-version-apply-direct'


def pending(source, connection_type='root-to-root', identity='candidate'):
    return append(source, CREATE, creation(source, version_id=identity,
        connection_type=connection_type, overhang_a_seq='ACGTACGTACGT', overhang_b_seq='TGCATGCA'), identity)


def params(source, identity='candidate', seed=924):
    version = next(v for v in source.connection_versions if v.id == identity)
    pair = {version.overhang_a_id, version.overhang_b_id}
    return {'_proof_version': 1, 'direct_application_version': 1, 'action': ACTION,
        'version_id': identity, 'overhang_a_id': version.overhang_a_id,
        'overhang_b_id': version.overhang_b_id, 'connection_type': version.connection_type,
        'history_seed': str(UUID(int=seed)), 'created_at': 12.0,
        **{field: [item.id for item in getattr(source, collection)
                  if pair.intersection((item.overhang_a_id, item.overhang_b_id))]
           for field, collection in [('conflict_connection_ids', 'overhang_connections'),
                ('conflict_binding_ids', 'overhang_bindings'), ('conflict_version_ids', 'connection_versions')]},
        'conflict_duplex_ids': [item.id for item in source.duplexes
            if pair.intersection((item.left.overhang_id, item.right.overhang_id))]}


def build(source, values):
    from backend.api.part_connection_direct_commands import build
    return build(source, values)


@pytest.mark.parametrize('connection_type', ['root-to-root', 'end-to-root'])
def test_direct_apply_is_registered_and_cold_replayable(direct_source, connection_type):
    source = pending(direct_source, connection_type)
    before = source.model_dump_json()
    values = params(source)
    actual, report = build(source, values)
    assert report is None
    recorded = append(source, 'overhang-bulk', values, 'direct-apply')
    from backend.core.cluster_reconcile import reconcile_cluster_membership
    from backend.core.lattice import retry_pending_ligations
    canonical = retry_pending_ligations(source, reconcile_cluster_membership(source, actual, report))
    assert authored(recorded) == authored(canonical)
    assert proof(recorded)['status'] == 'verified'
    assert actual.connection_versions[0].applied
    assert len(actual.duplexes) == 1
    assert source.model_dump_json() == before


@pytest.mark.parametrize('connection_type', ['root-to-root', 'end-to-root'])
def test_direct_replacement_replays_both_owners(direct_source, connection_type):
    source = pending(direct_source, connection_type)
    source = append(source, 'overhang-bulk', params(source), 'first-apply')
    source = pending(source, 'end-to-root' if connection_type == 'root-to-root' else 'root-to-root', 'replacement')
    before = source.model_dump_json()
    values = params(source, 'replacement', seed=925)
    actual = append(source, 'overhang-bulk', values, 'second-apply')
    assert proof(actual)['status'] == 'verified'
    assert len(actual.duplexes) == 1
    assert [v.applied for v in actual.connection_versions] == [False, True]
    assert source.model_dump_json() == before


@pytest.mark.parametrize('field', ['conflict_binding_ids', 'conflict_duplex_ids', 'conflict_version_ids'])
def test_direct_stale_conflict_selection_fails_without_mutation(application_prefix, field):
    from backend.core.part_command_errors import ReferenceResolutionError

    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', params(source), 'first')
    values = params(source, seed=926)
    values[field] = []
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError):
        build(source, values)
    assert source.model_dump_json() == before


def test_direct_refuses_corrupt_restoration_before_native_teardown(application_prefix):
    from backend.core.part_command_errors import CommandContractError

    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', params(source), 'first')
    source = source.model_copy(deep=True)
    source.overhang_bindings[0].prior_driven_topology['strand_id'] = 'missing'
    before = source.model_dump_json()
    with pytest.raises(CommandContractError):
        build(source, params(source, seed=927))
    assert source.model_dump_json() == before


def test_direct_identity_collision_cannot_adopt_an_existing_owner(application_prefix):
    from backend.core.part_command_errors import ReferenceResolutionError

    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', params(source), 'first')
    before = source.model_dump_json()
    with pytest.raises(ReferenceResolutionError):
        build(source, params(source))
    assert source.model_dump_json() == before


@pytest.mark.parametrize('changes', [{'direct_application_version': True},
    {'direct_application_version': 2}, {'history_seed': 'invalid'}, {'created_at': float('nan')},
    {'unexpected': []}])
def test_direct_schema_rejects_malformed_contract(application_prefix, changes):
    source = pending(application_prefix)
    values = {**params(source), **changes}
    before = source.model_dump_json()
    with pytest.raises(ValueError):
        build(source, values)
    assert source.model_dump_json() == before


def test_direct_edit_retains_output_namespace(application_prefix):
    from backend.core.part_edit_identity import preserve_proof_identity
    source = pending(application_prefix)
    old = params(source)
    new = deepcopy(old)
    new.update(history_seed=str(UUID(int=999)), created_at=42.0, direct_application_version=8)
    result = preserve_proof_identity(old, new, kind='overhang-bulk')
    for field in ('history_seed', 'created_at', 'direct_application_version', 'action'):
        assert result[field] == old[field]


@pytest.mark.parametrize('connection_type', ['root-to-root', 'end-to-root'])
def test_direct_command_matches_native_ordinary_callback(direct_source, connection_type, monkeypatch):
    from backend.api import routes_connection_versions as routes
    from tests.test_part_connection_application_commands import _legacy

    source = pending(direct_source, connection_type)
    values = params(source)
    native = routes.materialize_direct

    def recorded_identity(*args):
        return native(*args, history_seed=values['history_seed'], created_at=values['created_at'])

    monkeypatch.setattr(routes, 'materialize_direct', recorded_identity)
    expected, report = _legacy(source, {**values, 'connection_id': 'unused'}, monkeypatch)
    actual, actual_report = build(source, values)
    assert authored(actual) == authored(expected)
    assert report is actual_report is None


def test_direct_registration_declares_dependencies_and_refuses_generated_scope(application_prefix):
    from backend.api.part_proof_commands import dependencies, PART_TOPOLOGY
    from backend.api.part_connection_direct_commands import output_slots, parse_command
    from backend.core.part_dependencies import Resource

    source = pending(application_prefix)
    values = params(source)
    result = dependencies('overhang-bulk', values)
    assert result.known and result.barrier
    assert Resource('connection_version', 'candidate') in result.reads
    assert PART_TOPOLOGY in result.reads and PART_TOPOLOGY in result.writes
    assert {Resource(*slot) for slot in output_slots(parse_command(values))} <= result.writes
    assert not dependencies('overhang-bulk', {**values, '_generated_scope': {}}).known


def test_direct_registered_execution_postprocesses_once(application_prefix, monkeypatch):
    from backend.core import cluster_reconcile, lattice

    source = pending(application_prefix)
    calls = []
    for owner, name in [(cluster_reconcile, 'reconcile_cluster_membership'), (lattice, 'retry_pending_ligations')]:
        original = getattr(owner, name)

        def counted(*args, _original=original, _name=name, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(owner, name, counted)
    append(source, 'overhang-bulk', params(source), 'direct')
    assert calls == ['reconcile_cluster_membership', 'retry_pending_ligations']


@pytest.mark.parametrize('corruption', ['missing_ligation', 'edited_ligation', 'cluster_membership',
                                       'incoming_cluster', 'driver', 'driven_length'])
def test_direct_replacement_cannot_destroy_retained_or_missing_owners(application_prefix, corruption):
    from backend.core.part_command_errors import CommandContractError

    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', params(source), 'first').model_copy(deep=True)
    binding = source.overhang_bindings[0]
    ligation = binding.prior_driven_topology['forced_ligation']['id']
    cluster = next(c for c in source.cluster_transforms if c.overhang_duplex_driver_id)
    if corruption == 'missing_ligation':
        source.forced_ligations = [x for x in source.forced_ligations if x.id != ligation]
    elif corruption == 'edited_ligation':
        next(x for x in source.forced_ligations if x.id == ligation).five_prime_bp += 1
    elif corruption == 'cluster_membership':
        cluster.domain_ids = []
    elif corruption == 'driver':
        binding.driver_oh_id = binding.driven_oh_id
    elif corruption == 'driven_length':
        snapshot = binding.prior_driven_topology
        strand = next(s for s in source.strands if s.id == snapshot['strand_id'])
        strand.domains[snapshot['domain_index']].end_bp += 1
    else:
        retained = next(c for c in source.cluster_transforms if c.id != cluster.id)
        retained.parent_cluster_id = cluster.id
    before = source.model_dump_json()
    with pytest.raises(CommandContractError):
        build(source, params(source, seed=928))
    assert source.model_dump_json() == before


def test_upstream_length_edit_switches_driver_and_verifies_in_real_worker(application_prefix):
    from backend.api.part_recipe_edit import prepare_change
    from backend.api.part_verification_worker import VerificationWorker
    from backend.core.part_verification_capture import capture

    source = pending(application_prefix)
    source = append(source, 'overhang-bulk', params(source), 'direct')
    index = next(i for i, e in enumerate(source.feature_log) if e.id == 'endpoint-2')
    updated, _ = prepare_change(source, capture(source, preserve_entry_types=True),
        index, lambda: None, params={'length_bp': 16})
    assert updated.duplexes[0].id == source.duplexes[0].id
    assert not updated.overhang_bindings
    assert updated.duplexes[0].driver == 'right'
    worker = VerificationWorker(capture(updated))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result['status'] == 'verified', result
    finally:
        worker.close()


@pytest.mark.parametrize('connection_type', ['root-to-root-ssdna-linker', 'root-to-root-indirect'])
def test_direct_can_replace_native_finite_and_indirect_recipe(application_prefix, connection_type):
    from tests.test_part_connection_application_commands import _params

    source = pending(application_prefix, connection_type, 'linker')
    values = _params(source, version_id='linker')
    values['connection_application_version'] = 2
    source = append(source, 'overhang-bulk', values, 'linker-apply')
    source = pending(source, identity='direct')
    result = append(source, 'overhang-bulk', params(source, 'direct'), 'direct-apply')
    assert not result.overhang_connections
    assert len(result.duplexes) == 1
    assert proof(result)['status'] == 'verified'


@pytest.mark.parametrize('field', ['overhang_a_id', 'overhang_b_id'])
def test_missing_direct_endpoint_has_repairable_parameter_path(application_prefix, field):
    from backend.core.part_command_errors import ReferenceResolutionError

    source = pending(application_prefix)
    values = params(source)
    source = source.copy_with(overhangs=[item for item in source.overhangs if item.id != values[field]])
    with pytest.raises(ReferenceResolutionError) as caught:
        build(source, values)
    assert caught.value.code == 'missing_reference'
    assert caught.value.references[0]['parameter_path'] == [field]


def test_direct_work_budget_precedes_geometry(application_prefix, monkeypatch):
    from backend.api import connection_version_direct
    from backend.core.part_command_errors import CommandContractError

    source = pending(application_prefix).model_copy(deep=True)
    source.helices[0].length_bp = 5000
    monkeypatch.setattr(connection_version_direct, 'materialize_direct', lambda *_args, **_kw: pytest.fail('built oversized input'))
    with pytest.raises(CommandContractError, match='allowance'):
        build(source, params(source))
