"""Direct construction uses recorded identity/time without changing native output."""

from uuid import UUID

import pytest

from tests.test_connection_direct_replacement import (
    direct_source as direct_source, _topology, _version,
)
from tests.test_connection_composition_contract import legacy_combined
from tests.test_part_connection_application_commands import application_prefix as application_prefix
from tests.test_part_pending_connection_versions import authored, native_prefix as native_prefix


SEED = str(UUID(int=923))


def _build(source, connection_type):
    from backend.api.connection_version_direct import materialize_direct
    return materialize_direct(source, source.overhangs[0].id, source.overhangs[1].id,
        'root' if connection_type == 'root-to-root' else 'free_end', 'root', connection_type,
        history_seed=SEED, created_at=12.0)


@pytest.mark.parametrize('connection_type', ['root-to-root', 'end-to-root'])
def test_direct_native_identity_is_repeatable_complete_and_restorable(
    direct_source, connection_type, monkeypatch,
):
    from backend.api.connection_version_teardown import remove_conflicts

    source = direct_source
    before = source.model_dump_json()
    first = _build(source, connection_type)
    second = _build(source, connection_type)
    assert authored(first) == authored(second)
    legacy, _, _ = legacy_combined(source, _version(source, connection_type, 'candidate'), monkeypatch)
    # Only generated identities and creation timestamps may differ from the
    # ordinary path. Compare every authoring field, including restoration data.
    replacements = {}
    for field in ('overhang_bindings', 'duplexes', 'cluster_transforms', 'forced_ligations'):
        prior = {x.id for x in getattr(source, field)}
        actual = [x for x in getattr(first, field) if x.id not in prior]
        expected = [x for x in getattr(legacy, field) if x.id not in prior]
        assert len(actual) == len(expected)
        replacements.update((old.id, new.id) for old, new in zip(expected, actual, strict=True))

    def normalize(value):
        if isinstance(value, str):
            return replacements.get(value, value)
        if isinstance(value, list):
            return [normalize(x) for x in value]
        if isinstance(value, dict):
            out = {key: normalize(item) for key, item in value.items()}
            if value.get('id') in replacements and 'created_at' in out:
                out['created_at'] = 12.0
            return out
        return value

    expected = normalize(authored(legacy))
    expected['connection_versions'] = []
    assert authored(first) == expected
    assert _topology(remove_conflicts(first, [source.overhangs[0].id])) == _topology(source)
    assert source.model_dump_json() == before


@pytest.mark.parametrize('kwargs', [
    {'history_seed': SEED}, {'created_at': 12.0},
    {'history_seed': 'invalid', 'created_at': 12.0},
    {'history_seed': SEED, 'created_at': float('nan')},
    {'history_seed': SEED, 'created_at': -1},
    {'history_seed': SEED, 'created_at': True},
    {'history_seed': SEED, 'created_at': float('inf')},
])
def test_incomplete_or_invalid_direct_identity_is_rejected_before_build(application_prefix, kwargs):
    from backend.api.connection_version_direct import materialize_direct

    source = application_prefix
    before = source.model_dump_json()
    with pytest.raises(ValueError):
        materialize_direct(source, source.overhangs[0].id, source.overhangs[1].id,
                           'root', 'root', 'root-to-root', **kwargs)
    assert source.model_dump_json() == before


def test_direct_type_and_length_edits_preserve_common_output_identities(direct_source, application_prefix):
    original = _build(application_prefix, 'root-to-root')
    edited = _build(direct_source, 'end-to-root')
    for field in ('duplexes', 'cluster_transforms', 'forced_ligations'):
        old = {x.id for x in getattr(application_prefix, field)}
        new = {x.id for x in getattr(direct_source, field)}
        original_ids = {x.id for x in getattr(original, field)} - old
        edited_ids = {x.id for x in getattr(edited, field)} - new
        assert original_ids
        assert edited_ids == original_ids
    assert original.duplexes[0].created_at == edited.duplexes[0].created_at == 12.0


@pytest.mark.parametrize('connection_type', ['root-to-root', 'end-to-root'])
def test_direct_relocation_preserves_paired_bases_and_roundtrips(direct_source, connection_type):
    from backend.core.duplex import bp_to_offset, connect_register
    from backend.core.models import Design, _overhang_backing_domain

    source = direct_source
    a, b = source.overhangs[:2]
    before = connect_register(source, a.id, 'root' if connection_type == 'root-to-root' else 'free_end',
                              b.id, 'root')
    result = _build(source, connection_type)
    # Persistence must validate the actual native output, not only compare two
    # executions that can share the same stale-address defect (ISSUE-143).
    assert Design.model_validate_json(result.model_dump_json()) == result
    duplex = result.duplexes[0]
    for original, end in zip(before, (duplex.left, duplex.right), strict=True):
        old_domain = _overhang_backing_domain(source, original.overhang_id)[1]
        new_domain = _overhang_backing_domain(result, end.overhang_id)[1]
        assert end.overhang_id == original.overhang_id
        assert [bp_to_offset(new_domain, bp) for bp in (end.start_bp, end.end_bp)] == [
            bp_to_offset(old_domain, bp) for bp in (original.start_bp, original.end_bp)]
        assert abs(new_domain.end_bp - new_domain.start_bp) == abs(old_domain.end_bp - old_domain.start_bp)
    assert duplex.left.start_bp == duplex.right.end_bp
    assert duplex.left.end_bp == duplex.right.start_bp


@pytest.mark.parametrize('connection_type', ['root-to-root', 'end-to-root'])
def test_unequal_relocation_revert_restores_register_and_reapply(direct_source, connection_type):
    from backend.core.duplex import connect_register, relocate_duplex, revert_duplex_relocation
    from backend.core.models import Design

    result = _build(direct_source, connection_type)
    duplex = result.duplexes[0]
    if duplex.prior_driven_topology is None:
        return  # Equal-length restoration belongs to the binding.
    restored = revert_duplex_relocation(result, duplex)
    assert Design.model_validate_json(restored.model_dump_json()) == restored
    a, b = direct_source.overhangs[:2]
    ends = connect_register(direct_source, a.id,
        'root' if connection_type == 'root-to-root' else 'free_end', b.id, 'root')
    assert (restored.duplexes[0].left, restored.duplexes[0].right) == ends
    reapplied = relocate_duplex(restored, restored.duplexes[0], identity_seed=SEED)
    assert authored(reapplied) == authored(result)


@pytest.mark.parametrize('connection_type', ['root-to-root', 'end-to-root'])
def test_register_transport_preserves_native_geometry(direct_source, connection_type):
    from backend.api.crud import _geometry_for_design
    from backend.core.duplex import connect_register

    result = _build(direct_source, connection_type)
    if result.duplexes[0].prior_driven_topology is None:
        return
    a, b = direct_source.overhangs[:2]
    left, right = connect_register(direct_source, a.id,
        'root' if connection_type == 'root-to-root' else 'free_end', b.id, 'root')
    # Recreate precisely the old stale-register output while keeping every
    # native topology, sequence, pose and restoration field unchanged.
    stale = result.copy_with(duplexes=[result.duplexes[0].model_copy(update={'left': left, 'right': right})])
    native = _geometry_for_design(result)
    assert native
    assert native == _geometry_for_design(stale)
