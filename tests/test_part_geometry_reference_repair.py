"""Priority geometry features repair authored source references at their prefix."""
from copy import deepcopy

import pytest

from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_repair import prepare_repair
from backend.api.part_repair_input_metadata import describe_inputs
from backend.api.part_repair_selection import prepare_selection
from backend.core.part_history_contract import assess_part_history, create_empty_part
from tests.test_part_deformation_preview import _append
from tests.test_part_extrusion_edit_routes import recipe
from tests.test_part_sweep_preview import source_recipe

CASES = [('sweep', 'source_helix_id', 'helices'),
         ('extrude-continuation', 'source_frame_id', 'lattice_frames'),
         ('extrude-frame', 'source_frame_id', 'lattice_frames'),
         ('extrude-deformed-continuation', 'ref_helix_id', 'helices'),
         ('overhang-extrude', 'helix_id', 'helices')]


def fixture(kind, field):
    if kind == 'sweep':
        original = source_recipe(attached=True)
    else:
        original, _ = recipe(kind, False)
    prefix = create_empty_part(original.recipe_root.initial_name, original.lattice_type).copy_with(id=original.id)
    prefix = _append(prefix, original.feature_log[0])
    entry = original.feature_log[1]
    params = deepcopy(entry.params)
    if field == 'source_frame_id':
        params[field] = prefix.lattice_frames[0].id
        if kind == 'extrude-continuation':
            from backend.api.part_extrusion_edit_inputs import bind_prefix
            from backend.core.constants import BDNA_RISE_PER_BP
            params['cells'] = [[0, 0]]
            params['offset_nm'] = 21 * BDNA_RISE_PER_BP
            params = bind_prefix(kind, params, prefix)
    elif field == 'ref_helix_id':
        params.update(ref_helix_id=prefix.helices[0].id, source_bp=20)
    original = _append(prefix, entry.model_copy(update={'params': params}))
    # A real later feature must survive repair.
    from uuid import uuid4
    from backend.core.models import SnapshotLogEntry
    original = _append(original, SnapshotLogEntry(id='later', op_kind='extrude-segment',
        label='Later extrusion', params={'cells': [[8, 8]], 'length_bp': 5, 'plane': 'XY',
        'history_seed': str(uuid4()), '_proof_version': 1}))
    broken = original.model_copy(deep=True)
    broken.feature_log[1].params[field] = 'missing-source'
    if kind == 'extrude-continuation':
        broken.feature_log[1].params['_source_helix_ids'] = ['missing-derived-source']
    return original, broken, prefix, params[field]


def requests(source, field, replacement):
    selected = source.feature_log[1]
    guards = {'expected_design_id': source.id, 'expected_revision': 7}
    selection = {**guards, 'selection_version': 1, 'feature_id': selected.id,
        'parameter_path': [field], 'expected_old': 'missing-source'}
    repair = {**guards, 'repair_version': 1, 'actions': [{'action': 'set_input',
        'feature_id': selected.id, 'parameter_path': [field], 'expected_old': 'missing-source',
        'value': replacement}]}
    return selection, repair


@pytest.mark.parametrize('kind,field,collection', CASES)
def test_repair_uses_prefix_choices_and_rebuilds_without_changing_output_ids(kind, field, collection):
    original, broken, prefix, replacement = fixture(kind, field)
    selected = broken.feature_log[1]
    before = broken.model_dump_json()
    metadata = describe_inputs(kind, selected.params, feature_id=selected.id)
    assert metadata['definition_supported'], metadata
    assert any(item['parameter_path'] == [field] and item['input_type'] == 'reference'
               for item in metadata['fields'])
    selection, repair = requests(broken, field, replacement)
    choices = prepare_selection(broken, selection, source_revision=7,
        executor=execute, dependency_resolver=dependencies)
    assert choices['status'] == 'preview', choices
    identities = {item['identity'] for item in choices['selection']['candidates']}
    assert replacement in identities
    assert identities <= {item.id for item in getattr(prefix, collection)}
    repaired = prepare_repair(broken, repair, source_revision=7,
        executor=execute, dependency_resolver=dependencies)
    assert repaired['status'] == 'ready', repaired
    candidate = repaired['candidate']
    proof = assess_part_history(candidate, execute=execute, dependencies=dependencies)
    expected = assess_part_history(original, execute=execute, dependencies=dependencies)
    assert proof['status'] == expected['status'] == 'verified'
    assert proof['authoring_fingerprint'] == expected['authoring_fingerprint']
    assert [row.id for row in candidate.feature_log] == [row.id for row in original.feature_log]
    assert candidate.feature_log[1].params[field] == replacement
    assert broken.model_dump_json() == before


@pytest.mark.parametrize('kind,field,collection', CASES)
def test_invalid_replacement_refuses_without_mutating_source(kind, field, collection):
    _, broken, _, _ = fixture(kind, field)
    before = broken.model_dump_json()
    _, repair = requests(broken, field, 'still-missing')
    result = prepare_repair(broken, repair, source_revision=7,
        executor=execute, dependency_resolver=dependencies)
    assert result['status'] == 'failed', result
    assert 'candidate' not in result
    assert result['issues'][0]['feature_id'] == broken.feature_log[1].id
    assert broken.model_dump_json() == before


def test_repeated_reference_selection_and_repair_do_not_skip_prefix_accounting(monkeypatch):
    from backend.core import part_replay_cache as cache
    monkeypatch.setattr(cache, 'MIN_CACHE_SECONDS', 0)
    cache.clear()
    try:
        _, broken, _, replacement = fixture('sweep', 'source_helix_id')
        selection, repair = requests(broken, 'source_helix_id', replacement)
        for _ in range(2):
            choices = prepare_selection(broken, selection, source_revision=7,
                executor=execute, dependency_resolver=dependencies)
            assert choices['status'] == 'preview', choices
            assert choices['selection']['completed_prefix'] == [broken.feature_log[0].id]
            result = prepare_repair(broken, repair, source_revision=7,
                executor=execute, dependency_resolver=dependencies)
            assert result['status'] == 'ready', result
            assert result['repair']['completed_prefix'] == [row.id for row in broken.feature_log]
    finally:
        cache.clear()


def test_reference_repair_preserves_suppression_until_explicit_unsuppress():
    from backend.api.part_history_suppression import prepare_suppression
    original, _, _, replacement = fixture('sweep', 'source_helix_id')
    source, _ = prepare_suppression(original, 1, True, executor=execute, dependency_resolver=dependencies)
    source.feature_log[1].params['source_helix_id'] = 'missing-source'
    _, repair = requests(source, 'source_helix_id', replacement)
    result = prepare_repair(source, repair, source_revision=7,
        executor=execute, dependency_resolver=dependencies)
    assert result['status'] == 'ready', result
    candidate = result['candidate']
    assert candidate.feature_log[1].suppressed
    assert candidate.helices == source.helices and candidate.deformations == source.deformations
    restored, _ = prepare_suppression(candidate, 1, False, executor=execute, dependency_resolver=dependencies)
    a = assess_part_history(restored, execute=execute, dependencies=dependencies)
    b = assess_part_history(original, execute=execute, dependencies=dependencies)
    assert a['status'] == 'verified' and a['authoring_fingerprint'] == b['authoring_fingerprint']
