"""Native behavior that the FH-25 compound/indirect contracts must preserve.

These characterize actual legacy callbacks and existing input-only builders;
passing does not register or enable a combined connection command. No mocked
molecular builders, coordinate edits, solver or application lifespan is used.
"""

import pytest

from backend.api import routes_connection_versions as routes
from backend.api import part_connection_version_commands as pending
from backend.api import part_connection_application_commands as application
from backend.core.models import ConnectionVersion
from backend.core.connection_versions import clean_sequence
from tests.test_part_connection_application_commands import (
    FINITE_TYPES, _params, application_prefix as application_prefix,
)
from tests.test_part_pending_connection_versions import (
    authored, creation, native_prefix as native_prefix,
)


def legacy_combined(source, version, monkeypatch):
    captured = []
    connection_model = routes.OverhangConnection

    def transaction(*, fn, **kwargs):
        result = fn(source)
        design, report = result if isinstance(result, tuple) else (result, None)
        captured.append((design, report, kwargs))
        return design, report, None

    with monkeypatch.context() as patch:
        patch.setattr(routes.design_state, 'get_or_404', lambda: source)
        patch.setattr(routes.design_state, 'mutate_with_feature_log', transaction)
        patch.setattr(routes, 'OverhangConnection', lambda **kwargs:
                      connection_model(id='composed-output', **kwargs))
        patch.setattr(routes, '_connection_apply_response', lambda *_: {})
        routes._apply_connection_version_legacy(version.id, new_version=version)
    assert len(captured) == 1
    return captured[0]


def definition(source, connection_type):
    return {'action': pending.CREATE, **creation(source,
        connection_type=connection_type, overhang_a_seq='acgtacgtacgtacgt',
        overhang_b_seq='tgca', bridge_seq='ggNN', bridge_length=7)}


def version_from(params):
    # Mirror the public Connect route's input normalization BEFORE the captured
    # legacy callback. Comparing an uncleaned model bypasses that real contract.
    values = {key: params[key] for key in ('name', 'created_at', 'overhang_a_id',
        'overhang_b_id', 'connection_type', 'overhang_a_seq', 'overhang_b_seq',
        'bridge_seq', 'bridge_length')}
    for key in ('overhang_a_seq', 'overhang_b_seq', 'bridge_seq'):
        values[key] = clean_sequence(values[key])
    return ConnectionVersion(id=params['version_id'], **values, applied=True)


@pytest.mark.parametrize('connection_type', FINITE_TYPES)
def test_fixed_pending_then_apply_composition_matches_actual_combined_callback(
    application_prefix, monkeypatch, connection_type,
):
    source = application_prefix.model_copy(deep=True)
    values = definition(source, connection_type)
    before = source.model_dump_json()
    expected, expected_report, receipt = legacy_combined(source, version_from(values), monkeypatch)
    staged = pending.build(source, values)
    actual, report = application.build(staged, _params(staged, connection_id='composed-output'))
    assert authored(actual) == authored(expected)
    assert report == expected_report
    assert source.model_dump_json() == before
    assert len(actual.connection_versions) == 1 and actual.connection_versions[0].applied
    assert actual.connection_versions[0].name == 'V1'
    # Legacy receipt omits construction inputs: this is parity evidence, NOT
    # evidence that the current combined command can regenerate from history.
    assert receipt['params'] == {'version_id': 'candidate', 'connection_type': connection_type}
    assert actual.connection_versions[0].overhang_a_seq == 'ACGTACGTACGT'
    assert actual.connection_versions[0].overhang_b_seq == 'TGCANNNNNNNN'


@pytest.mark.parametrize('connection_type', ['root-to-root-ssdna-linker', 'end-to-root-dsdna-linker'])
def test_composition_names_prior_blank_versions_without_mutating_source(
    application_prefix, monkeypatch, connection_type,
):
    source = application_prefix.model_copy(deep=True)
    values = definition(source, connection_type)
    prior = version_from(values).model_copy(update={'id': 'prior', 'created_at': 1.0, 'applied': False})
    source = source.copy_with(connection_versions=[prior])
    before = source.model_dump_json()
    expected, _, _ = legacy_combined(source, version_from(values), monkeypatch)
    assert source.model_dump_json() == before
    staged = pending.build(source, values)
    actual, _ = application.build(staged, _params(staged, connection_id='composed-output'))
    assert authored(actual) == authored(expected)
    assert [(v.name, v.applied) for v in actual.connection_versions] == [('V1', False), ('V2', True)]
    assert source.model_dump_json() == before


@pytest.mark.parametrize('connection_type', ['root-to-root-indirect', 'end-to-end-indirect'])
def test_indirect_native_output_has_no_virtual_helix_or_bridge_domain(
    application_prefix, monkeypatch, connection_type,
):
    source = application_prefix.model_copy(deep=True)
    values = definition(source, connection_type)
    before = source.model_dump_json()
    result, report, _ = legacy_combined(source, version_from(values), monkeypatch)
    assert source.model_dump_json() == before
    assert result.overhang_connections[0].length_value == 0
    assert [h.model_dump() for h in result.helices] == [h.model_dump() for h in source.helices]
    added = [s for s in result.strands if s.id not in {old.id for old in source.strands}]
    assert len(added) == 1 and added[0].id == '__lnk__composed-output__s'
    assert len(added[0].domains) == 2
    assert {d.binds_overhang_id for d in added[0].domains} == {values['overhang_a_id'], values['overhang_b_id']}
    assert all(d.helix_id != '__lnk__composed-output' for d in added[0].domains)
    # Existing callback reports a prospective helix even though none is emitted.
    # Future dependency writes must derive actual indirect output grammar.
    assert report.new_helix_origins == {'__lnk__composed-output': None}


def test_failed_combined_connect_cannot_rename_live_source_versions(application_prefix, monkeypatch):
    from uuid import uuid4
    from backend.api import state, doc_context

    source = application_prefix.model_copy(deep=True)
    values = definition(source, 'root-to-root-ssdna-linker')
    source = source.copy_with(connection_versions=[version_from(values).model_copy(
        update={'id': 'prior', 'name': '', 'created_at': 1.0, 'applied': False})])
    session = state._DesignSession(design=source, revision=7)
    session.redo.append(source.model_copy(deep=True))
    before = source.model_dump_json()
    redo_before = [d.model_dump_json() for d in session.redo]
    doc = f'__connection_composition__{uuid4()}'
    token = doc_context.set_current_doc(doc)
    revision = doc_context.current_request_revision()
    entry = doc_context.current_request_feature_log_entry_id()

    def fail(*_args, **_kwargs):
        raise RuntimeError('injected post-build validation failure')

    monkeypatch.setattr(state, 'validate_design', fail)
    try:
        with state._lock:
            state._sessions[doc] = session
        with pytest.raises(RuntimeError, match='post-build validation failure'):
            routes._apply_connection_version_legacy('candidate', new_version=version_from(values))
        assert session.design.model_dump_json() == before
        assert source.model_dump_json() == before
        assert session.revision == 7 and not session.history
        assert [d.model_dump_json() for d in session.redo] == redo_before
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(revision)
        doc_context.set_request_feature_log_entry_id(entry)
