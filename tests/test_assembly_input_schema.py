"""Editor fields, ownership, historical choices and native pattern regeneration."""
import pytest
from fastapi import HTTPException

from backend.api import assembly_state, state, crud
from backend.api.assembly import (CreateAssemblyRequest, create_assembly, AddInstanceRequest,
    add_instance, PatchInstanceRequest, patch_instance, EditAssemblyFeatureRequest, edit_assembly_feature)
from backend.api.assembly_command_replay import COMMANDS
from backend.api.assembly_input_schema import command_schema, input_editor, PART_COMMANDS, validate_editor_inputs
from backend.api.assembly_history_verification import verify
from backend.api.routes_assembly_joints import AddJointRequest, add_joint, PatchJointRequest, patch_joint
from backend.api.routes_assembly_patterns import AssemblyPatternBody, linear_pattern, circular_pattern
from backend.core.models import Assembly


@pytest.fixture(autouse=True)
def sessions():
    assembly_state.close_session(); state.close_session()
    yield
    assembly_state.close_session(); state.close_session()


def native():
    create_assembly(CreateAssemblyRequest(name='Editor qualification'))
    crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=21))
    source = state.get_or_404().model_dump(mode='json')
    add_instance(AddInstanceRequest(name='Original', source={'type': 'inline', 'design': source}))
    return assembly_state.get_or_404().instances[0].id


def editor(index):
    assembly = assembly_state.get_or_404()
    return input_editor(index, assembly_state.revision(), assembly.feature_log[index].id)


@pytest.mark.parametrize('kind', [kind for kind, spec in COMMANDS.items() if spec[2] and kind not in PART_COMMANDS])
def test_all_editable_requests_have_typed_controls_and_account_for_every_input(kind):
    from importlib import import_module
    schema, excluded = command_schema(kind)
    spec = COMMANDS[kind]
    model = getattr(import_module('backend.api.' + spec[0]), spec[2])
    assert (set(schema['properties']) - {'_targets'}) | set(excluded) == set(model.model_fields)
    def visit(node):
        assert node['type'] in {'object', 'array', 'string', 'number', 'integer', 'boolean'}
        if node['type'] == 'object':
            assert 'properties' in node
            for value in node['properties'].values(): visit(value)
        if node['type'] == 'array': visit(node['items'])
    visit(schema)


@pytest.mark.parametrize('kind', sorted(PART_COMMANDS))
def test_part_definition_commands_are_not_assembly_input_editors(kind):
    with pytest.raises(HTTPException, match='assembly-owned'):
        command_schema(kind)


def test_historical_reference_choices_are_bound_and_do_not_mutate_source():
    part = native()
    add_joint(AddJointRequest(instance_b_id=part))
    patch_instance(part, PatchInstanceRequest(name='Later name'))
    before, revision = assembly_state.copy_for_persist()
    result = editor(1)
    assert result['references']['instance'] == [{'value': part, 'label': 'Original'}]
    assert result['schema']['properties']['min_limit']['nullable']
    assert assembly_state.copy_for_persist() == (before, revision)
    with pytest.raises(HTTPException) as error:
        input_editor(1, revision - 1, before.feature_log[1].id)
    assert error.value.status_code == 409
    assert 'source' not in editor(0)['inputs']
    assert 'source' in editor(0)['excluded']


def test_joint_clear_vs_omitted_limits_survive_suffix_and_reopened_proof():
    part = native()
    add_joint(AddJointRequest(instance_b_id=part, min_limit=-2, max_limit=3))
    joint = assembly_state.get_or_404().joints[0].id
    patch_joint(joint, PatchJointRequest(current_value=0.1))
    patch_instance(part, PatchInstanceRequest(name='Downstream'))
    edit_assembly_feature(2, EditAssemblyFeatureRequest(params={'min_limit': None}))
    saved = Assembly.from_json(assembly_state.get_or_404().to_json())
    assert saved.joints[0].min_limit is None
    assert saved.joints[0].max_limit == 3
    assert saved.instances[0].name == 'Downstream'
    assert 'max_limit' not in saved.feature_log[2].params['input_fields_set']
    assert 'min_limit' in saved.feature_log[2].params['input_fields_set']
    assert verify(saved)['status'] == 'verified'


@pytest.mark.parametrize('field', ['source', 'cluster_transform_overrides', 'joint_states', 'allow_part_joints'])
def test_source_definition_inputs_cannot_be_injected(field):
    with pytest.raises(HTTPException, match='assembly-owned'):
        validate_editor_inputs('assembly-patch-instance', {field: {}})


@pytest.mark.parametrize('circular', [False, True])
def test_patterns_record_replay_edit_sources_and_refuse_dangling_downstream(circular):
    part = native()
    source_design = state.get_or_404().model_dump(mode='json')
    assembly = assembly_state.get_or_404()
    parameters = ({'instances': 3, 'total_angle': 180, 'axis_point': [0, 0, 0], 'axis_direction': [0, 0, 1]}
        if circular else {'instances': 3, 'spacing': 8, 'direction': 'X'})
    operation = circular_pattern if circular else linear_pattern
    operation(AssemblyPatternBody(instance_ids=[part], parameters=parameters,
        expected_assembly_id=assembly.id, expected_revision=assembly_state.revision(),
        expected_feature_ids=[row.id for row in assembly.feature_log]))
    saved = Assembly.from_json(assembly_state.get_or_404().to_json())
    assert verify(saved)['status'] == 'verified'
    assert len(saved.instances) == 3
    copies = [item.id for item in saved.instances]
    assert saved.feature_log[-1].params['command_version'] == 1
    assert editor(1)['schema']['properties']['parameters']['properties']['instances']['maximum'] == 128
    patch_instance(copies[-1], PatchInstanceRequest(name='Later copy edit'))
    params = {**parameters, 'instances': 4}
    edit_assembly_feature(1, EditAssemblyFeatureRequest(params={'parameters': params}))
    grown = Assembly.from_json(assembly_state.get_or_404().to_json())
    assert [item.id for item in grown.instances[:3]] == copies
    assert grown.instances[2].name == 'Later copy edit'
    assert all(item.source.design.model_dump(mode='json') == source_design for item in grown.instances)
    assert verify(grown)['status'] == 'verified'
    before, revision = assembly_state.copy_for_persist()
    with pytest.raises(HTTPException):
        edit_assembly_feature(1, EditAssemblyFeatureRequest(params={'parameters': {**parameters, 'instances': 2}}))
    assert assembly_state.copy_for_persist() == (before, revision)


def test_reference_target_edit_replays_later_commands_and_keeps_identity():
    first = native()
    source = state.get_or_404().model_dump(mode='json')
    add_instance(AddInstanceRequest(name='Second', source={'type': 'inline', 'design': source}))
    second = assembly_state.get_or_404().instances[-1].id
    patch_instance(first, PatchInstanceRequest(name='Retargeted'))
    patch_instance(second, PatchInstanceRequest(fixed=True))
    before = assembly_state.get_or_404().feature_log[2].id
    assert editor(2)['inputs']['_targets'] == {'instance_id': first}
    edit_assembly_feature(2, EditAssemblyFeatureRequest(params={'_targets': {'instance_id': second}}))
    saved = Assembly.from_json(assembly_state.get_or_404().to_json())
    assert [item.name for item in saved.instances] == ['Original', 'Retargeted']
    assert saved.instances[1].fixed
    assert saved.feature_log[2].id == before
    assert verify(saved)['status'] == 'verified'
    before_state, revision = assembly_state.copy_for_persist()
    with pytest.raises(HTTPException):
        edit_assembly_feature(2, EditAssemblyFeatureRequest(params={'_targets': {'instance_id': 'missing'}}))
    assert assembly_state.copy_for_persist() == (before_state, revision)


def test_parameterless_target_actions_have_an_editor_but_sync_has_none():
    schema, _ = command_schema('assembly-delete-joint')
    assert schema['properties']['_targets']['required'] == ['joint_id']
    assert command_schema('assembly-duplex-sync')[0]['properties'] == {}


def test_evicted_recovery_uses_recorded_prefix_without_changing_live_state(monkeypatch):
    import backend.api.assembly as routes
    part = native()
    add_joint(AddJointRequest(instance_b_id=part))
    before, revision = assembly_state.copy_for_persist()
    def evicted(*args):
        raise HTTPException(422, 'Recovery evicted')
    monkeypatch.setattr(routes, '_decode_entry_pre_state', evicted)
    assert editor(1)['references']['instance'] == [{'value': part, 'label': 'Original'}]
    assert assembly_state.copy_for_persist() == (before, revision)
