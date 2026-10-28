"""Native core repair uses authored definitions and the exact preceding topology."""
from copy import deepcopy
from uuid import uuid4

import pytest

from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_repair import prepare_repair
from backend.api.part_repair_input_metadata import describe_inputs
from backend.api.part_repair_selection import prepare_selection
from backend.core.models import ClusterCreateLogEntry, ClusterRigidTransform
from backend.core.part_history_contract import assess_part_history
from backend.core.part_overlay_commands import command_input
from backend.core.part_repair_capture import capture_draft_inputs
from backend.core.part_repair_inputs import SetInput
from tests.test_part_deformation_preview import _append, native_source
from tests.test_part_transform_preview import source_recipe


def at(values, path):
    for token in path:
        values = values[token]
    return values


def changed(values, path, value):
    result = deepcopy(values)
    at(result, path[:-1])[path[-1]] = value
    return result


def guards(source):
    return {'expected_design_id': source.id, 'expected_revision': 7}


def request(source, entry, path, value, child=None):
    params = command_input(child or entry)[1]
    return {**guards(source), 'repair_version': 1, 'actions': [{'action': 'set_input',
        'feature_id': entry.id, 'child_id': None if child is None else child.id,
        'parameter_path': path, 'expected_old': at(params, path), 'value': value}]}


def evaluate(source, proposal):
    return prepare_repair(source, proposal, source_revision=7, executor=execute,
                          dependency_resolver=dependencies)


def verified(source):
    proof = assess_part_history(source, execute=execute, dependencies=dependencies)
    assert proof['status'] == 'verified', proof


def core_fixture(kind):
    if kind in {'bend', 'twist'}:
        source = native_source(kind)
        entry = source.feature_log[-1]
        path = ['affected_helix_ids', 0]
    elif kind == 'cluster_create':
        # Use only the real native bundle before making a separate identity owner.
        from backend.api.part_recipe_edit import regenerate
        original = native_source()
        source = regenerate(original, original.feature_log[:1], lambda: None, executor=execute, use_cache=False)
        cluster = ClusterRigidTransform(id=str(uuid4()), helix_ids=[source.helices[0].id], name='Repair owner')
        entry = ClusterCreateLogEntry(id='created-owner', cluster_id=cluster.id, cluster_snapshot=cluster,
                                      helix_ids=cluster.helix_ids, name=cluster.name, proof_version=3)
        source = _append(source, entry)
        path = ['cluster', 'helix_ids', 0]
    else:
        source = source_recipe(kind)
        entry = next(row for row in source.feature_log if row.id == 'selected-transform')
        path = ['cluster_id'] if kind == 'cluster_op' else ['helix_id']
    params = command_input(entry)[1]
    value = at(params, path)
    from backend.api.part_core_repair_inputs import replacement
    broken = source.model_copy(deep=True)
    broken.feature_log = [replacement(row, changed(params, path, 'missing-core-target'))
                          if row.id == entry.id else row for row in broken.feature_log]
    return source, broken, path, value, entry.id


@pytest.mark.parametrize('kind', ['bend', 'twist', 'cluster_create', 'cluster_op', 'nucleotide-transform'])
def test_missing_core_reference_repair_preserves_ids_source_and_cold_replay(kind):
    original, broken, path, value, identity = core_fixture(kind)
    row = next(row for row in broken.feature_log if row.id == identity)
    input_kind, params = command_input(row)
    before = broken.model_dump_json()
    metadata = describe_inputs(input_kind, row if input_kind in {'deformation', 'cluster_create', 'cluster_op'} else params)
    assert metadata['definition_supported'], metadata
    assert any(field['parameter_path'] == path and field['input_type'] == 'reference' for field in metadata['fields'])
    selected = prepare_selection(broken, {**guards(broken), 'selection_version': 1,
        'feature_id': row.id, 'parameter_path': path, 'expected_old': 'missing-core-target'},
        source_revision=7, executor=execute, dependency_resolver=dependencies)
    assert selected['status'] == 'preview', selected
    assert value in {item['identity'] for item in selected['selection']['candidates']}
    result = evaluate(broken, request(broken, row, path, value))
    assert result['status'] == 'ready', result
    candidate = result['candidate']
    assert [row.id for row in candidate.feature_log] == [row.id for row in original.feature_log]
    assert candidate.model_dump(mode='json', include={'helices', 'strands', 'cluster_transforms', 'deformations', 'nucleotide_transforms'}) == original.model_dump(mode='json', include={'helices', 'strands', 'cluster_transforms', 'deformations', 'nucleotide_transforms'})
    verified(candidate)
    assert broken.model_dump_json() == before


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_scalar_repair_and_cluster_retarget_recompute_only_authored_selection(kind):
    source = native_source(kind, grouped=True)
    row = source.feature_log[-1]
    replacement_id = next(owner.id for owner in source.cluster_transforms if owner.id not in row.op_snapshot.cluster_ids)
    proposal = request(source, row, ['cluster_ids', 0], replacement_id)
    result = evaluate(source, proposal)
    assert result['status'] == 'ready', result
    op = result['candidate'].deformations[-1]
    owner = next(c for c in source.cluster_transforms if c.id == replacement_id)
    assert op.affected_helix_ids == owner.helix_ids
    verified(result['candidate'])
    parameter = 'curvature_deg_per_bp' if kind == 'bend' else 'total_degrees'
    scalar = evaluate(source, request(source, row, ['params', parameter], .15 if kind == 'bend' else 12.0))
    assert scalar['status'] == 'ready', scalar
    assert scalar['candidate'].deformations[-1].affected_helix_ids == row.op_snapshot.affected_helix_ids
    verified(scalar['candidate'])


def test_overlay_discovery_never_serializes_or_hashes(monkeypatch):
    source = native_source()
    row = source.feature_log[-1]
    action = SetInput.model_validate(request(source, row, ['plane_b_bp'], 30)['actions'][0])
    monkeypatch.setattr('backend.core.part_repair_planning.same_input', lambda *_: pytest.fail('Hash under capture'))
    monkeypatch.setattr('backend.core.part_repair_planning.command_input', lambda *_: pytest.fail('Serialize under capture'))
    captured = capture_draft_inputs(source, source_revision=7, proposed_actions=[action])
    assert captured.feature_log[-1].op_snapshot == row.op_snapshot


@pytest.mark.parametrize('path,value', [(['id'], 'replacement'), (['target_ranges'], []), (['_proof_version'], 2)])
def test_deformation_receipts_cannot_be_repaired_as_authored_inputs(path, value):
    source = native_source()
    result = evaluate(source, request(source, source.feature_log[-1], path, value))
    assert result['status'] != 'ready'
    assert result['issues'][0]['code'] in {'protected_recipe_identity', 'invalid_parameter_path', 'missing_proof_contract'}


from tests.test_part_routing_edit_native_matrix import KINDS, prepared_case, parent, with_suffix

@pytest.mark.parametrize('kind', KINDS)
def test_each_routing_family_replaces_a_missing_pre_child_reference(kind):
    prefix, params, _ = prepared_case(kind, False)
    from backend.api.part_core_repair_inputs import fields
    references = [path for path, input_type, _, _ in fields(kind, params) if input_type == 'reference']
    assert references
    path = references[0]
    original = with_suffix(parent(prefix, [(kind, params, 'repair-child')]))
    broken = original.model_copy(deep=True)
    row = next(row for row in broken.feature_log if row.id == 'selected-parent')
    child = row.children[0]
    value = at(params, path)
    child.params = changed(params, path, 'missing-core-target')
    result = evaluate(broken, request(broken, row, path, value, child))
    assert result['status'] == 'ready', result
    verified(result['candidate'])
    assert [row.id for row in result['candidate'].feature_log] == [row.id for row in original.feature_log]


@pytest.mark.parametrize('kind', ['strand-end-resize', 'domain-shift', 'forced-ligation-create',
    'crossover-move', 'crossover-move-batch', 'crossover-delete', 'crossover-delete-batch',
    'crossover-extra-bases', 'crossover-extra-bases-batch'])
def test_positional_routing_repair_binds_actual_pre_child_occupants(kind):
    from backend.core.positional_refs import to_positional
    from backend.api.part_core_repair_inputs import fields
    prefix, literal, _ = prepared_case(kind, False)
    params = to_positional(kind, literal, prefix)
    path = next(path for path, input_type, _, _ in fields(kind, params) if input_type == 'reference')
    source = parent(prefix, [(kind, params, 'positional-child')])
    row, child = source.feature_log[-1], source.feature_log[-1].children[0]
    value = at(params, path)
    child.params = changed(params, path, 'missing-core-target')
    result = evaluate(source, request(source, row, path, value, child))
    assert result['status'] == 'ready', result
    assert result['candidate'].feature_log[-1].children[0].params['_proof_version'] == 2
    verified(result['candidate'])


@pytest.mark.parametrize('kind', ['bend', 'twist'])
def test_explicit_domain_repair_rebinds_frozen_scope_from_prefix(kind):
    source = native_source(kind, scoped=True)
    row = source.feature_log[-1]
    old = row.op_snapshot.targets[0]['strand_id']
    row.op_snapshot.targets[0]['strand_id'] = 'missing-strand'
    result = evaluate(source, request(source, row, ['targets', 0, 'strand_id'], old))
    assert result['status'] == 'ready', result
    verified(result['candidate'])


def test_routing_batch_outputs_and_deformation_receipts_never_appear_in_catalog():
    from backend.api.part_core_repair_inputs import fields
    _, params, _ = prepared_case('crossover-place-batch', False)
    paths = [path for path, *_ in fields('crossover-place-batch', params)]
    assert not any(path[-1] == 'crossover_id' for path in paths)
    source = native_source(scoped=True)
    kind, params = command_input(source.feature_log[-1])
    assert not any(path[0] in {'id', 'target_ranges', 'affected_helix_ids'} for path, *_ in fields(kind, params))
