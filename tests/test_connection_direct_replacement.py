"""Direct replacement must restore native topology before creating a new owner.

Inputs are real bundle/extrusion recipes, including unequal lengths. These
exercise the actual legacy transaction without replacing molecular builders.
"""

from copy import deepcopy

import pytest

from backend.core.part_history_contract import create_empty_part
from tests.test_connection_composition_contract import definition, legacy_combined, version_from
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import (
    append, authored, native_prefix as native_prefix, proof,
)


@pytest.fixture(params=[12, 8], ids=['equal', 'unequal'])
def direct_source(application_prefix, request):
    source = create_empty_part('Direct replacement', 'HONEYCOMB')
    for entry in application_prefix.feature_log:
        params = deepcopy(entry.params)
        if entry.id == 'endpoint-2':
            params['length_bp'] = request.param
        source = append(source, entry.op_kind, params, entry.id)
    assert proof(source)['status'] == 'verified'
    return source


def _version(source, connection_type, identity):
    values = definition(source, connection_type)
    values.update(version_id=identity, overhang_a_seq='', overhang_b_seq='')
    return version_from(values)


def _topology(design):
    values = authored(design)
    values.pop('connection_versions')
    # Restoration may append the original helix; record order is immaterial.
    for key, value in values.items():
        if isinstance(value, list) and value and all(isinstance(x, dict) and 'id' in x for x in value):
            values[key] = sorted(value, key=lambda x: x['id'])
    return values


@pytest.mark.parametrize('direct_type', ['root-to-root', 'end-to-root'])
@pytest.mark.parametrize('sequence', ['', 'ACGTACGTACGTACGT'])
@pytest.mark.parametrize('replacement_type', ['root-to-root-indirect', 'root-to-root-ssdna-linker'])
def test_direct_to_linker_restores_original_topology_and_removes_all_direct_owners(
    direct_source, direct_type, replacement_type, sequence, monkeypatch,
):
    source = direct_source
    before = source.model_dump_json()
    connected, _, _ = legacy_combined(source, _version(source, direct_type, 'direct'), monkeypatch)
    assert len(connected.duplexes) == 1
    assert len(connected.overhang_bindings) == int(
        source.overhangs[0].sub_domains[0].length_bp == source.overhangs[1].sub_domains[0].length_bp)
    connected_before = connected.model_dump_json()
    replacement = _version(source, replacement_type, 'replacement').model_copy(update={
        'overhang_a_seq': sequence, 'overhang_b_seq': sequence,
    })
    expected, _, _ = legacy_combined(source, replacement, monkeypatch)
    actual, _, _ = legacy_combined(connected, replacement, monkeypatch)
    assert not actual.duplexes
    assert not actual.overhang_bindings
    assert _topology(actual) == _topology(expected)
    assert [(v.id, v.applied) for v in actual.connection_versions] == [
        ('direct', False), ('replacement', True)]
    assert source.model_dump_json() == before
    assert connected.model_dump_json() == connected_before


@pytest.mark.parametrize('direct_type', ['root-to-root', 'end-to-root'])
def test_direct_reapply_replaces_display_and_retains_restorable_native_owner(
    direct_source, direct_type, monkeypatch,
):
    from backend.api.connection_version_teardown import remove_conflicts

    source = direct_source
    first, _, _ = legacy_combined(source, _version(source, direct_type, 'first'), monkeypatch)
    replacement_type = 'end-to-root' if direct_type == 'root-to-root' else 'root-to-root'
    actual, _, _ = legacy_combined(first, _version(source, replacement_type, 'second'), monkeypatch)
    assert len(actual.duplexes) == 1
    assert actual.duplexes[0].connection_type == replacement_type
    assert actual.duplexes[0].id != first.duplexes[0].id
    assert len(actual.overhang_bindings) == len(first.overhang_bindings)
    restored = remove_conflicts(actual, [source.overhangs[0].id])
    assert not restored.duplexes and not restored.overhang_bindings
    assert _topology(restored) == _topology(source)
