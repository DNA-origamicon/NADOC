"""First-time direct Connect is one closed input recipe and one transaction."""

from uuid import UUID

import pytest

from tests.test_connection_direct_replacement import direct_source as direct_source
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import append, authored, creation, native_prefix as native_prefix, proof

ACTION = 'connection-version-connect-direct'


def params(source, connection_type='root-to-root', identity='composed-direct', seed=930):
    return {**creation(source, version_id=identity, connection_type=connection_type),
        'action': ACTION, 'direct_composition_version': 1, 'history_seed': str(UUID(int=seed)),
        'conflict_connection_ids': [], 'conflict_binding_ids': [], 'conflict_duplex_ids': [], 'conflict_version_ids': []}


@pytest.mark.parametrize('connection_type', ['root-to-root', 'end-to-root'])
def test_direct_connect_matches_pending_apply_and_replays(direct_source, connection_type):
    from backend.api import part_connection_version_commands as pending
    from tests.test_part_connection_direct import params as apply_params

    source = direct_source
    values = params(source, connection_type)
    definition = creation(source, version_id=values['version_id'], connection_type=connection_type)
    staged = append(source, pending.CREATE, definition, 'pending')
    expected = append(staged, 'overhang-bulk', apply_params(staged, values['version_id'], seed=930), 'apply')
    before = source.model_dump_json()
    actual = append(source, 'overhang-bulk', values, 'connect')
    assert authored(actual) == authored(expected)
    assert proof(actual)['status'] == 'verified'
    assert len(actual.feature_log) == len(source.feature_log) + 1
    assert source.model_dump_json() == before


def test_direct_compound_dependencies_do_not_read_their_new_version(application_prefix):
    from backend.api.part_proof_commands import dependencies
    from backend.core.part_dependencies import Resource

    values = params(application_prefix)
    result = dependencies('overhang-bulk', values)
    assert result.known and result.barrier
    output = Resource('connection_version', values['version_id'])
    assert output in result.writes and output not in result.reads
    assert not dependencies('overhang-bulk', {**values, '_generated_scope': {}}).known


def test_direct_compound_preserves_creator_identity_during_edits(application_prefix):
    from backend.core.part_edit_identity import preserve_proof_identity
    old = params(application_prefix)
    changes = {**old, 'version_id': 'new', 'history_seed': str(UUID(int=999)),
               'created_at': 42.0, 'direct_composition_version': 8, 'overhang_a_seq': 'TTTT'}
    actual = preserve_proof_identity(old, changes, kind='overhang-bulk')
    for field in ('action', 'version_id', 'history_seed', 'created_at', 'direct_composition_version'):
        assert actual[field] == old[field]
    assert actual['overhang_a_seq'] == 'TTTT'


@pytest.mark.parametrize('connection_type', ['root-to-root', 'end-to-root'])
def test_compound_direct_matches_actual_legacy_callback(direct_source, connection_type, monkeypatch):
    from backend.api import routes_connection_versions as routes
    from backend.api.part_connection_direct_composition import build
    from tests.test_connection_composition_contract import legacy_combined, version_from

    values = params(direct_source, connection_type)
    native = routes.materialize_direct

    def materialize(*args):
        return native(*args, history_seed=values['history_seed'], created_at=values['created_at'])

    monkeypatch.setattr(routes, 'materialize_direct', materialize)
    before = direct_source.model_dump_json()
    expected, report, _ = legacy_combined(direct_source, version_from(values), monkeypatch)
    actual, actual_report = build(direct_source, values)
    assert authored(actual) == authored(expected)
    assert report is actual_report is None
    assert direct_source.model_dump_json() == before


def test_direct_compound_replacement_uses_exact_prior_conflicts(direct_source):
    from backend.api.part_connection_direct_recording import conflict_values

    first = append(direct_source, 'overhang-bulk', params(direct_source), 'first')
    values = params(first, 'end-to-root', identity='replacement', seed=931)
    values.update(conflict_values(first, values['overhang_a_id'], values['overhang_b_id']))
    result = append(first, 'overhang-bulk', values, 'second')
    assert len(result.duplexes) == 1
    assert [v.applied for v in result.connection_versions] == [False, True]
    assert proof(result)['status'] == 'verified'


def test_direct_compound_only_postprocesses_once(application_prefix, monkeypatch):
    from backend.core import cluster_reconcile, lattice
    calls = []
    for owner, name in [(cluster_reconcile, 'reconcile_cluster_membership'), (lattice, 'retry_pending_ligations')]:
        original = getattr(owner, name)

        def counted(*args, _original=original, _name=name, **kwargs):
            calls.append(_name)
            return _original(*args, **kwargs)

        monkeypatch.setattr(owner, name, counted)
    append(application_prefix, 'overhang-bulk', params(application_prefix), 'connect')
    assert calls == ['reconcile_cluster_membership', 'retry_pending_ligations']


@pytest.mark.parametrize('changes', [
    {'direct_composition_version': True}, {'direct_composition_version': 2},
    {'history_seed': 'invalid'}, {'created_at': float('nan')}, {'applied': True},
    {'conflict_version_ids': ['composed-direct']}, {'conflict_binding_ids': ['x', 'x']},
    {'unexpected': []},
])
def test_invalid_compound_direct_schema_refuses_before_native_work(application_prefix, monkeypatch, changes):
    from backend.api import part_connection_direct_composition as composition
    monkeypatch.setattr(composition, 'prepare', lambda *_: pytest.fail('prepared malformed contract'))
    with pytest.raises(ValueError):
        composition.build(application_prefix, {**params(application_prefix), **changes})


def test_direct_compound_edit_and_isolated_worker(application_prefix):
    from backend.api.part_recipe_edit import prepare_change
    from backend.api.part_verification_worker import VerificationWorker
    from backend.core.part_verification_capture import capture

    source = append(application_prefix, 'overhang-bulk', params(application_prefix), 'connect')
    updated, _ = prepare_change(source, capture(source, preserve_entry_types=True),
                                len(source.feature_log) - 1, lambda: None,
                                params={'connection_type': 'end-to-root', 'overhang_a_seq': 'TTTT'})
    assert updated.connection_versions[0].id == source.connection_versions[0].id
    assert updated.duplexes[0].id == source.duplexes[0].id
    assert updated.connection_versions[0].overhang_a_seq == 'TTTTNNNNNNNN'
    worker = VerificationWorker(capture(updated))
    try:
        worker.start()
        assert worker.wait(5)
        assert worker.result()['status'] == 'verified'
    finally:
        worker.close()
