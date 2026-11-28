"""Replay newly recorded commands without consulting recovery snapshots."""

import pytest
from fastapi import HTTPException

from backend.api import assembly_state
from backend.api.assembly import AddInstanceRequest, _replay_assembly_op, add_instance
from backend.api.assembly_command_replay import replay
from backend.api.routes_assembly_gears import (
    CreateGearRelationRequest, PatchGearRelationRequest, create_gear_relation,
    delete_gear_relation, patch_gear_relation, resolve_gear_relation,
)
from backend.api.routes_assembly_joints import AddJointRequest, CreateMateRequest, add_joint, create_mate
from backend.api.routes_assembly_groups import (
    CreateGroupRequest, DuplicateGroupRequest, PatchGroupRequest, cascade_delete_group,
    create_group, duplicate_group, patch_group, ungroup,
)
from backend.core.models import Assembly, Design


@pytest.fixture(autouse=True)
def session():
    assembly_state.close_session()
    yield
    assembly_state.close_session()


def add_empty_part(name):
    add_instance(AddInstanceRequest(name=name, source={"type": "inline", "design": Design().model_dump(mode="json")}))
    return assembly_state.get_or_404().instances[-1].id


def authored(assembly):
    return assembly.model_dump(mode="json", exclude={"feature_log", "feature_log_cursor"})


def replay_saved(root, saved):
    # Reopen the serialized document; execute only recorded commands, without
    # reading either pre- or post-state recovery payloads.
    reopened = Assembly.from_json(saved.to_json())
    current = root
    for entry in reopened.feature_log:
        current = _replay_assembly_op(current, entry.op_kind, entry.params)
    def differences(left, right, path=""):
        if type(left) is not type(right):
            return [path + ": type"]
        if isinstance(left, dict):
            return [item for key in left.keys() | right.keys() for item in
                    (differences(left.get(key), right.get(key), path + "/" + key))]
        if isinstance(left, list):
            if len(left) != len(right):
                return [path + ": length"]
            return [item for i, (a, b) in enumerate(zip(left, right)) for item in differences(a, b, path + f"/{i}")]
        return [] if left == right else [path]
    mismatch = differences(authored(current), authored(saved))
    assert not mismatch, mismatch[:20]
    return current


def gears():
    root = Assembly()
    assembly_state.load_assembly(root)
    first, second = add_empty_part("First"), add_empty_part("Second")
    add_joint(AddJointRequest(instance_b_id=first, current_value=0.4))
    a = assembly_state.get_or_404().joints[-1].id
    add_joint(AddJointRequest(instance_b_id=second))
    b = assembly_state.get_or_404().joints[-1].id
    create_gear_relation(CreateGearRelationRequest(joint_a_id=a, joint_b_id=b, ratio=2,
                                                  invert=True, capture_anchors_from_current=False))
    return root, assembly_state.get_or_404().gear_relations[-1].id


def test_gear_lifecycle_saved_commands_reproduce_every_stage():
    root, relation = gears()
    replay_saved(root, assembly_state.get_or_404())
    patch_gear_relation(relation, PatchGearRelationRequest(ratio=3, name="Changed", joint_b_anchor=0.2))
    replay_saved(root, assembly_state.get_or_404())
    before = assembly_state.get_or_404().model_copy(deep=True)
    resolve_gear_relation(relation)
    saved = assembly_state.get_or_404()
    assert saved.joints[1].current_value == pytest.approx(-1.0)
    assert saved.feature_log[-1].op_kind == "assembly-resolve-gear"
    replay_saved(root, saved)
    assert assembly_state.undo() == before
    assembly_state.redo()
    delete_gear_relation(relation)
    assert not assembly_state.get_or_404().gear_relations
    replay_saved(root, assembly_state.get_or_404())


def test_mate_replays_connector_registration_and_pose_with_stable_identity():
    root = Assembly()
    assembly_state.load_assembly(root)
    a, b = add_empty_part("Anchor"), add_empty_part("Moved")
    body = CreateMateRequest(
        child_connector={"instance_id": b, "label": "child", "is_blunt_end": True,
                         "position": [0, 0, 1], "normal": [0, 0, -1]},
        parent_connector={"instance_id": a, "label": "parent", "is_blunt_end": True,
                          "position": [0, 0, 5], "normal": [0, 0, 1]},
        moved_instance_id=b,
        transform={"values": [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 4, 0, 0, 0, 1]},
        name="Recorded mate",
    )
    create_mate(body)
    saved = assembly_state.get_or_404()
    entry = saved.feature_log[-1]
    assert entry.params["inputs"] == body.model_dump(mode="json")
    rebuilt = replay_saved(root, saved)
    assert rebuilt.joints[0].id == saved.joints[0].id
    assert rebuilt.instances[1].transform.values[11] == pytest.approx(4)


def test_replay_does_not_publish_or_allocate_new_output_identities():
    root, _ = gears()
    saved, revision = assembly_state.copy_for_persist()
    depth = assembly_state.undo_depth()
    first = replay_saved(root, saved)
    second = replay_saved(root, saved)
    assert authored(first) == authored(second)
    assert assembly_state.get_or_404() == saved
    assert assembly_state.revision() == revision
    assert assembly_state.undo_depth() == depth


def test_nested_group_lifecycle_replays_exact_membership_and_output_ids():
    root = Assembly()
    assembly_state.load_assembly(root)
    a, b = add_empty_part("A"), add_empty_part("B")
    add_joint(AddJointRequest(instance_a_id=a, instance_b_id=b))
    create_group(CreateGroupRequest(instance_ids=[a], name="Inner"))
    inner = assembly_state.get_or_404().groups[-1].id
    create_group(CreateGroupRequest(instance_ids=[b], subgroup_ids=[inner], name="Outer"))
    outer = assembly_state.get_or_404().groups[-1].id
    patch_group(inner, PatchGroupRequest(name="Renamed", representation="beads", expanded=False))
    duplicate_group(outer, DuplicateGroupRequest(name="Copy", offset=[7, 2, 0]))
    saved = assembly_state.get_or_404()
    outputs = saved.feature_log[-1].params["outputs"]
    assert f"instance:{a}" in outputs and f"group:{inner}" in outputs
    clone = saved.feature_log[-1].params["new_group_id"]
    replay_saved(root, saved)
    patch_group(clone, PatchGroupRequest(name="Edited copy"))
    replay_saved(root, assembly_state.get_or_404())
    ungroup(inner)
    replay_saved(root, assembly_state.get_or_404())
    cascade_delete_group(clone)
    replay_saved(root, assembly_state.get_or_404())


def test_surgical_delete_replays_new_group_and_gear_commands():
    from backend.api.assembly import delete_assembly_feature

    root, relation = gears()
    patch_gear_relation(relation, PatchGearRelationRequest(name="Transient name"))
    removed_index = len(assembly_state.get_or_404().feature_log) - 1
    create_group(CreateGroupRequest(instance_ids=[assembly_state.get_or_404().instances[0].id], name="Retained"))
    patch_gear_relation(relation, PatchGearRelationRequest(ratio=5))
    delete_assembly_feature(removed_index)
    saved = assembly_state.get_or_404()
    assert saved.gear_relations[0].name == "Gear"
    assert saved.gear_relations[0].ratio == 5
    assert saved.groups[0].name == "Retained"
    replay_saved(root, saved)


def test_earlier_gear_edit_regenerates_downstream_pose_and_preserves_features():
    from backend.api.assembly import EditAssemblyFeatureRequest, edit_assembly_feature

    root, relation = gears()
    index = len(assembly_state.get_or_404().feature_log) - 1
    resolve_gear_relation(relation)
    before, revision = assembly_state.copy_for_persist()
    depth = assembly_state.undo_depth()
    edit_assembly_feature(index, EditAssemblyFeatureRequest(params={"ratio": 3}))
    after = assembly_state.get_or_404()
    assert after.joints[1].current_value == pytest.approx(-1.2)
    assert [row.id for row in after.feature_log] == [row.id for row in before.feature_log]
    assert assembly_state.revision() == revision + 1
    assert assembly_state.undo_depth() == depth + 1
    replay_saved(root, after)
    assert assembly_state.undo() == before
    assert assembly_state.redo() == after


def test_earlier_edit_missing_downstream_reference_is_atomic_and_identifies_feature():
    from backend.api.assembly import EditAssemblyFeatureRequest, edit_assembly_feature

    root = Assembly()
    assembly_state.load_assembly(root)
    a, b = add_empty_part("A"), add_empty_part("B")
    create_group(CreateGroupRequest(instance_ids=[a, b]))
    group_id = assembly_state.get_or_404().groups[-1].id
    index = len(assembly_state.get_or_404().feature_log) - 1
    duplicate_group(group_id)
    saved, revision = assembly_state.copy_for_persist()
    # Removing a source member changes the named clone outputs. Do not silently
    # bind downstream references to a different object or discard output slots.
    with pytest.raises(HTTPException) as error:
        edit_assembly_feature(index, EditAssemblyFeatureRequest(params={"instance_ids": [a]}))
    assert error.value.detail["feature_id"] == saved.feature_log[-1].id
    assert assembly_state.get_or_404() == saved
    assert assembly_state.revision() == revision


def test_earlier_group_edit_replays_named_duplicate_override():
    from backend.api.assembly import EditAssemblyFeatureRequest, edit_assembly_feature

    root = Assembly()
    assembly_state.load_assembly(root)
    a = add_empty_part("A")
    create_group(CreateGroupRequest(instance_ids=[a], name="Original"))
    index = len(assembly_state.get_or_404().feature_log) - 1
    group_id = assembly_state.get_or_404().groups[-1].id
    duplicate_group(group_id, DuplicateGroupRequest(name="Explicit copy"))
    edit_assembly_feature(index, EditAssemblyFeatureRequest(params={"inputs": {"name": "Changed"}}))
    after = assembly_state.get_or_404()
    assert {g.name for g in after.groups} == {"Changed", "Explicit copy"}
    replay_saved(root, after)


def test_delayed_playback_cannot_reverse_drive_edited_gear():
    from backend.api.routes_assembly_joints import PatchJointRequest, patch_joint

    _, relation = gears()
    resolve_gear_relation(relation)
    obsolete_revision = assembly_state.revision()
    driven = assembly_state.get_or_404().joints[1].id
    patch_gear_relation(relation, PatchGearRelationRequest(ratio=3))
    before, revision = assembly_state.copy_for_persist()
    depth = assembly_state.undo_depth()
    response = patch_joint(driven, PatchJointRequest(current_value=-0.8, silent=True,
                                                    expected_revision=obsolete_revision))
    assert response["stale_playback"] is True
    assert assembly_state.get_or_404() == before
    assert assembly_state.revision() == revision
    assert assembly_state.undo_depth() == depth
    resolve_gear_relation(relation)
    assert assembly_state.get_or_404().joints[1].current_value == pytest.approx(-1.2)


def test_current_playback_remains_silent_and_atomic():
    from backend.api.routes_assembly_joints import PatchJointRequest, patch_joint

    _, _ = gears()
    source, revision = assembly_state.copy_for_persist()
    depth = assembly_state.undo_depth()
    response = patch_joint(source.joints[0].id, PatchJointRequest(current_value=0.7, silent=True,
                                                                expected_revision=revision))
    assert response["stale_playback"] is False
    assert assembly_state.get_or_404().joints[0].current_value == pytest.approx(0.7)
    assert assembly_state.get_or_404().feature_log == source.feature_log
    assert assembly_state.undo_depth() == depth
    assert assembly_state.revision() == revision + 1


def test_playback_from_other_assembly_is_rejected_even_at_same_revision():
    from backend.api.routes_assembly_joints import PatchJointRequest, patch_joint

    gears()
    source, revision = assembly_state.copy_for_persist()
    response = patch_joint(source.joints[0].id, PatchJointRequest(current_value=0.7, silent=True,
        expected_revision=revision, expected_assembly_id="other-document"))
    assert response["stale_playback"] is True
    assert assembly_state.get_or_404() == source
    assert assembly_state.revision() == revision


@pytest.mark.parametrize("defect", ["legacy", "missing_input", "unknown_input", "missing_output", "duplicate_output", "version"])
def test_incomplete_or_invalid_contract_refuses_without_publication(defect):
    _, relation = gears()
    saved, revision = assembly_state.copy_for_persist()
    entry = saved.feature_log[-1]
    params = entry.model_copy(deep=True).params
    prefix = saved.model_copy(update={"gear_relations": []})
    if defect == "legacy":
        params = {"relation_id": relation, "name": "Gear"}
    elif defect == "missing_input":
        del params["inputs"]["ratio"]
    elif defect == "unknown_input":
        params["inputs"]["unknown"] = True
    elif defect == "missing_output":
        del params["relation_id"]
    elif defect == "duplicate_output":
        prefix = saved
    else:
        params["command_version"] = 999
    with pytest.raises(HTTPException) as error:
        replay(prefix, entry.op_kind, params)
    assert error.value.status_code == 422
    assert assembly_state.get_or_404() == saved
    assert assembly_state.revision() == revision


def test_group_move_records_resolved_state_and_replays_earlier_edit():
    from backend.api.assembly import EditAssemblyFeatureRequest, edit_assembly_feature
    from backend.api.routes_assembly_groups import TransformGroupRequest, transform_group

    root, relation = gears()
    create_group(CreateGroupRequest(instance_ids=[assembly_state.get_or_404().instances[0].id]))
    group_id = assembly_state.get_or_404().groups[-1].id
    before = assembly_state.get_or_404().model_copy(deep=True)
    depth = assembly_state.undo_depth()
    body = TransformGroupRequest(translation=[1, 2, 3])
    transform_group(group_id, body)
    after = assembly_state.get_or_404()
    assert after.feature_log[-1].params['inputs'] == body.model_dump(mode='json')
    assert assembly_state.undo_depth() == depth + 1
    replay_saved(root, after)
    assert assembly_state.undo() == before
    assert assembly_state.redo() == after
    # A later operation's pre-state must recover the completed move, including
    # the solver's derived base transforms and coupled joint values.
    index = len(after.feature_log) - 1
    patch_gear_relation(relation, PatchGearRelationRequest(name='After move'))
    recovered = assembly_state.lookup_pre_state(assembly_state.get_or_404().feature_log, index + 1)
    assert authored(recovered) == authored(after)
    edit_assembly_feature(index, EditAssemblyFeatureRequest(params={'translation': [4, 5, 6]}))
    replay_saved(root, assembly_state.get_or_404())


def test_group_move_solver_failure_leaves_history_and_live_state_untouched(monkeypatch):
    from backend.api import routes_assembly_groups as groups

    gears()
    create_group(CreateGroupRequest(instance_ids=[assembly_state.get_or_404().instances[0].id]))
    before, revision = assembly_state.copy_for_persist()
    depth = assembly_state.undo_depth()

    def fail():
        raise HTTPException(422, detail='Solver failure')

    monkeypatch.setattr(groups, 'resolve_assembly', fail)
    with pytest.raises(HTTPException, match='Solver failure'):
        groups.transform_group(before.groups[0].id, groups.TransformGroupRequest(translation=[1, 2, 3]))
    assert assembly_state.get_or_404() == before
    assert assembly_state.revision() == revision
    assert assembly_state.undo_depth() == depth


@pytest.mark.parametrize('direction', ['forward', 'backward', 'both'])
def test_polymer_commands_preserve_primary_pattern_and_joint_references(direction):
    from backend.api.routes_assembly_polymerize import PolymerizeAssemblyRequest, polymerize_assembly

    root = Assembly()
    assembly_state.load_assembly(root)
    design = Design().model_dump(mode='json')
    ids = []
    for name in ['Anchor', 'Repeat', 'Pattern']:
        add_instance(AddInstanceRequest(name=name, source={'type': 'inline', 'design': design}))
        ids.append(assembly_state.get_or_404().instances[-1].id)
    add_joint(AddJointRequest(instance_a_id=ids[0], instance_b_id=ids[1], joint_type='rigid'))
    seed_joint = assembly_state.get_or_404().joints[-1].id
    add_joint(AddJointRequest(instance_a_id=ids[1], instance_b_id=ids[2], joint_type='rigid'))
    before = assembly_state.get_or_404().model_copy(deep=True)
    polymerize_assembly(PolymerizeAssemblyRequest(joint_id=seed_joint, count=6,
                                                  direction=direction, additional_instance_ids=[ids[2]]))
    saved = assembly_state.get_or_404()
    outputs = saved.feature_log[-1].params['outputs']
    assert set(outputs.values()) == {item.id for item in [*saved.instances, *saved.joints]} - {
        item.id for item in [*before.instances, *before.joints]
    }
    replay_saved(root, saved)
    # Downstream selections must keep identifying exactly the generated object.
    clone = saved.instances[-1].id
    create_group(CreateGroupRequest(instance_ids=[clone]))
    replay_saved(root, assembly_state.get_or_404())
    assert assembly_state.undo() == saved
    assert assembly_state.undo() == before


def test_polymer_length_edit_preserves_surviving_slots_and_rejects_dangling_selection():
    from backend.api.assembly import EditAssemblyFeatureRequest, edit_assembly_feature
    from backend.api.routes_assembly_polymerize import PolymerizeAssemblyRequest, polymerize_assembly

    root = Assembly()
    assembly_state.load_assembly(root)
    design = Design().model_dump(mode='json')
    for name in ['Anchor', 'Repeat']:
        add_instance(AddInstanceRequest(name=name, source={'type': 'inline', 'design': design}))
    a, b = assembly_state.get_or_404().instances
    add_joint(AddJointRequest(instance_a_id=a.id, instance_b_id=b.id, joint_type='rigid'))
    joint = assembly_state.get_or_404().joints[-1].id
    polymerize_assembly(PolymerizeAssemblyRequest(joint_id=joint, count=4))
    index = len(assembly_state.get_or_404().feature_log) - 1
    old_outputs = assembly_state.get_or_404().feature_log[index].params['outputs']
    selected = assembly_state.get_or_404().instances[-1].id
    create_group(CreateGroupRequest(instance_ids=[selected]))
    edit_assembly_feature(index, EditAssemblyFeatureRequest(params={'count': 6}))
    after = assembly_state.get_or_404()
    new_outputs = after.feature_log[index].params['outputs']
    assert old_outputs.items() <= new_outputs.items()
    assert len(after.instances) == 6
    assert after.groups[0].instance_ids == [selected]
    replay_saved(root, after)
    revision, depth = assembly_state.revision(), assembly_state.undo_depth()
    with pytest.raises(HTTPException) as error:
        edit_assembly_feature(index, EditAssemblyFeatureRequest(params={'count': 3}))
    assert error.value.detail['feature_id'] == after.feature_log[-1].id
    assert assembly_state.get_or_404() == after
    assert assembly_state.revision() == revision
    assert assembly_state.undo_depth() == depth
    # Shrink still works when the selected repeat survives.
    edit_assembly_feature(index, EditAssemblyFeatureRequest(params={'count': 4}))
    shrunk = assembly_state.get_or_404()
    assert shrunk.feature_log[index].params['outputs'] == old_outputs
    replay_saved(root, shrunk)


@pytest.mark.parametrize('direction', ['forward', 'backward', 'both'])
def test_periodic_command_replays_with_recorded_part_history(direction):
    from backend.api import state
    from backend.api.crud import BundleRequest, ForcedLigationRequest, NickRequest, add_nick, create_bundle, forced_ligation
    from backend.api.routes_assembly_polymerize import PolymerizePeriodicRequest, polymerize_periodic_assembly

    state.close_session()
    try:
        create_bundle(BundleRequest(cells=[[0, 0]], length_bp=21, ligate_adjacent=False))
        strand = state.get_or_404().strands[0]
        domain = strand.domains[0]
        add_nick(NickRequest(helix_id=domain.helix_id, bp_index=10, direction=domain.direction))
        fragments = [s for s in state.get_or_404().strands if s.strand_type == strand.strand_type]
        three = next(s for s in fragments if s.domains[-1].end_bp == domain.end_bp)
        five = next(s for s in fragments if s.domains[0].start_bp == domain.start_bp)
        forced_ligation(ForcedLigationRequest(three_prime_strand_id=three.id,
                                              five_prime_strand_id=five.id, is_periodic_seam=True))
        design = state.get_or_404()
        assert design.feature_log[0].op_kind == 'bundle-create'
        assert [child.op_subtype for child in design.feature_log[1].children] == ['nick', 'forced-ligation-create']
        from backend.api import part_proof_commands
        from backend.core.part_history_contract import assess_part_history
        proof = assess_part_history(design, execute=part_proof_commands.execute, dependencies=part_proof_commands.dependencies)
        assert proof['status'] == 'verified', proof
        root = Assembly()
        assembly_state.load_assembly(root)
        add_instance(AddInstanceRequest(name='Periodic', source={'type': 'inline', 'design': design.model_dump(mode='json')}))
        seed = assembly_state.get_or_404().instances[0].id
        polymerize_periodic_assembly(PolymerizePeriodicRequest(instance_id=seed, count=5, direction=direction))
        saved = assembly_state.get_or_404()
        assert len(saved.feature_log[-1].params['outputs']) == 8
        replay_saved(root, saved)
    finally:
        state.close_session()


def test_joint_patch_records_limits_presence_pose_gears_and_deletion_cascade():
    from backend.api.routes_assembly_joints import PatchJointRequest, patch_joint, delete_joint

    root, _ = gears()
    joint_id = assembly_state.get_or_404().joints[0].id
    patch_joint(joint_id, PatchJointRequest(min_limit=-0.5, max_limit=0.5))
    before = assembly_state.get_or_404().model_copy(deep=True)
    patch_joint(joint_id, PatchJointRequest(current_value=2, endpoint_side='b'))
    after = assembly_state.get_or_404()
    assert after.joints[0].current_value == 0.5
    assert after.joints[1].current_value == -1
    assert after.feature_log[-1].op_kind == 'assembly-patch-joint'
    replay_saved(root, after)
    assert assembly_state.undo() == before
    assert assembly_state.redo() == after
    # Explicit null clears only the specified limit; omitted fields retain it.
    patch_joint(joint_id, PatchJointRequest(min_limit=None, name='Edited'))
    assert assembly_state.get_or_404().joints[0].min_limit is None
    assert assembly_state.get_or_404().joints[0].max_limit == 0.5
    replay_saved(root, assembly_state.get_or_404())
    delete_joint(joint_id)
    assert not assembly_state.get_or_404().gear_relations
    replay_saved(root, assembly_state.get_or_404())


def test_earlier_joint_patch_edit_replays_explicit_null_and_rejects_transport():
    from backend.api.assembly import EditAssemblyFeatureRequest, edit_assembly_feature
    from backend.api.routes_assembly_joints import PatchJointRequest, patch_joint

    root, relation = gears()
    joint_id = assembly_state.get_or_404().joints[0].id
    patch_joint(joint_id, PatchJointRequest(min_limit=0, max_limit=1))
    patch_joint(joint_id, PatchJointRequest(current_value=0.8))
    index = len(assembly_state.get_or_404().feature_log) - 1
    resolve_gear_relation(relation)
    edit_assembly_feature(index, EditAssemblyFeatureRequest(params={'max_limit': None, 'current_value': 2}))
    after = assembly_state.get_or_404()
    assert after.joints[0].max_limit is None
    assert after.joints[0].current_value == 2
    assert after.joints[1].current_value == -4
    replay_saved(root, after)
    with pytest.raises(HTTPException):
        edit_assembly_feature(index, EditAssemblyFeatureRequest(params={'silent': True}))
    assert assembly_state.get_or_404() == after


def test_mate_refresh_records_actual_command_and_one_undo():
    from backend.api.routes_assembly_joints import refresh_mate

    root = Assembly()
    assembly_state.load_assembly(root)
    a, b = add_empty_part('Anchor'), add_empty_part('Mate')
    create_mate(CreateMateRequest(
        child_connector={'instance_id': b, 'label': 'child', 'is_blunt_end': True,
                         'position': [0, 0, 1], 'normal': [0, 0, -1]},
        parent_connector={'instance_id': a, 'label': 'parent', 'is_blunt_end': True,
                          'position': [0, 0, 5], 'normal': [0, 0, 1]},
    ))
    before = assembly_state.get_or_404().model_copy(deep=True)
    refresh_mate(before.joints[0].id)
    after = assembly_state.get_or_404()
    assert after.feature_log[-1].op_kind == 'assembly-refresh-mate'
    assert after.instances[1].transform.values[11] == pytest.approx(4)
    replay_saved(root, after)
    assert assembly_state.undo() == before
    assert assembly_state.redo() == after


def test_connector_generated_labels_survive_surgical_delete_and_replay():
    from backend.api.assembly import delete_assembly_feature
    from backend.api.routes_assembly_connectors import AddConnectorRequest, add_connector, delete_connector

    root = Assembly()
    assembly_state.load_assembly(root)
    part = add_empty_part('Connectors')
    add_connector(part, AddConnectorRequest(position=[0, 0, 0], normal=[0, 0, 1]))
    first_index = len(assembly_state.get_or_404().feature_log) - 1
    add_connector(part, AddConnectorRequest(position=[1, 2, 3], normal=[0, 1, 0], clearance_nm=2))
    replay_saved(root, assembly_state.get_or_404())
    delete_assembly_feature(first_index)
    saved = assembly_state.get_or_404()
    assert [ip.label for ip in saved.instances[0].interface_points] == ['C2']
    replay_saved(root, saved)
    delete_connector(part, 'C2')
    replay_saved(root, assembly_state.get_or_404())


def test_belt_lifecycle_replays_inputs_poses_outputs_and_cascade_detachment():
    from backend.api.assembly import EditAssemblyFeatureRequest, edit_assembly_feature
    from backend.api.routes_assembly_belts import (
        CreateBeltPathRequest, PatchBeltPathRequest, CreateBeltRiderRequest, PolymerizeBeltRequest,
        create_belt_path, patch_belt_path, delete_belt_path, create_belt_rider, delete_belt_rider, polymerize_belt,
    )
    from backend.core.models import Mat4x4

    root, _ = gears()
    a, b = assembly_state.get_or_404().joints
    create_belt_path(CreateBeltPathRequest(
        pulley_a={'joint_id': a.id, 'radius': 2, 'center_world': [0, 0, 0]},
        pulley_b={'joint_id': b.id, 'radius': 3, 'center_world': [10, 0, 0]},
    ))
    belt = assembly_state.get_or_404().belt_paths[0].id
    before = assembly_state.get_or_404().model_copy(deep=True)
    patch_belt_path(belt, PatchBeltPathRequest(name='Renamed', pulley_a={'joint_id': a.id, 'radius': 4}))
    patched = assembly_state.get_or_404()
    index = len(patched.feature_log) - 1
    replay_saved(root, patched)
    assert assembly_state.undo() == before
    assert assembly_state.redo() == patched
    cargo = add_empty_part('Cargo')
    transform = Mat4x4().model_dump(mode='json')
    transform['values'][3] = 7
    create_belt_rider(CreateBeltRiderRequest(belt_path_id=belt, instance_id=cargo,
                                            arc_param=0.2, ref_angle=0.4, transform=transform))
    rider = assembly_state.get_or_404().belt_riders[0].id
    transform['values'][3] = 8
    polymerize_belt(PolymerizeBeltRequest(rider_id=rider, copies=[{'arc_param': 0.4, 'transform': transform}]))
    saved = assembly_state.get_or_404()
    assert len(saved.feature_log[-1].params['outputs']) == 2
    replay_saved(root, saved)
    edit_assembly_feature(index, EditAssemblyFeatureRequest(params={'name': 'Edited earlier'}))
    after = assembly_state.get_or_404()
    assert [r.id for r in after.belt_riders] == [r.id for r in saved.belt_riders]
    assert after.belt_paths[0].name == 'Edited earlier'
    replay_saved(root, after)
    delete_belt_rider(rider)
    replay_saved(root, assembly_state.get_or_404())
    parts = [i.id for i in assembly_state.get_or_404().instances]
    delete_belt_path(belt)
    assert not assembly_state.get_or_404().belt_riders
    assert [i.id for i in assembly_state.get_or_404().instances] == parts
    replay_saved(root, assembly_state.get_or_404())


def test_connector_label_edit_records_new_output_and_rejects_old_downstream_selection():
    from backend.api.assembly import EditAssemblyFeatureRequest, edit_assembly_feature
    from backend.api.routes_assembly_connectors import AddConnectorRequest, add_connector, delete_connector

    root = Assembly()
    assembly_state.load_assembly(root)
    part = add_empty_part('Connector')
    add_connector(part, AddConnectorRequest(position=[0, 0, 0], normal=[0, 0, 1]))
    index = len(assembly_state.get_or_404().feature_log) - 1
    edit_assembly_feature(index, EditAssemblyFeatureRequest(params={'label': 'Attachment'}))
    assert assembly_state.get_or_404().instances[0].interface_points[0].label == 'Attachment'
    replay_saved(root, assembly_state.get_or_404())
    delete_connector(part, 'Attachment')
    before, revision = assembly_state.copy_for_persist()
    with pytest.raises(HTTPException) as error:
        edit_assembly_feature(index, EditAssemblyFeatureRequest(params={'label': 'Renamed'}))
    assert error.value.detail['feature_id'] == before.feature_log[-1].id
    assert assembly_state.get_or_404() == before
    assert assembly_state.revision() == revision


def test_instance_properties_combined_move_duplicate_and_propagation_replay():
    from backend.api.assembly import (
        PatchInstanceRequest, patch_instance, DuplicateInstanceRequest, duplicate_instance,
        PropagateFKRequest, propagate_fk, EditAssemblyFeatureRequest, edit_assembly_feature,
    )
    from backend.core.models import Mat4x4

    root = Assembly()
    assembly_state.load_assembly(root)
    part = add_empty_part('Part')
    patch_instance(part, PatchInstanceRequest(name='Configured', mode='flexible', allow_part_joints=True))
    replay_saved(root, assembly_state.get_or_404())
    transform = Mat4x4().model_dump(mode='json')
    transform['values'][3] = 3
    before = assembly_state.get_or_404().model_copy(deep=True)
    patch_instance(part, PatchInstanceRequest(name='Moved and renamed', transform=transform, fixed=False))
    after = assembly_state.get_or_404()
    index = len(after.feature_log) - 1
    replay_saved(root, after)
    assert assembly_state.undo() == before
    assert assembly_state.redo() == after
    duplicate_instance(part, DuplicateInstanceRequest(name='Chosen copy', offset=[4, 2, 0]))
    copy = assembly_state.get_or_404().instances[-1].id
    transform['values'][3] = 10
    propagate_fk(PropagateFKRequest(instance_id=copy, transform=transform))
    replay_saved(root, assembly_state.get_or_404())
    edit_assembly_feature(index, EditAssemblyFeatureRequest(params={'name': 'Earlier edit'}))
    current = assembly_state.get_or_404()
    assert current.instances[0].name == 'Earlier edit'
    assert current.instances[1].name == 'Chosen copy'
    assert current.instances[1].id == copy
    replay_saved(root, current)


def test_failed_combined_instance_patch_does_not_leak_display_preferences():
    from backend.api.assembly import PatchInstanceRequest, patch_instance

    assembly_state.load_assembly(Assembly())
    part = add_empty_part('Part')
    before, revision = assembly_state.copy_for_persist()
    with pytest.raises(HTTPException):
        patch_instance(part, PatchInstanceRequest(visible=False, representation='invalid', name='Refused'))
    assert assembly_state.get_or_404() == before
    assert assembly_state.revision() == revision
    patch_instance(part, PatchInstanceRequest(name='Valid'))
    assert assembly_state.undo().instances[0].visible


def test_instance_cluster_request_replays_override_and_mated_child_delta():
    from backend.api import crud, state
    from backend.api.assembly import PatchInstanceClusterTransformRequest, patch_instance_cluster_transform
    from backend.core.models import Mat4x4

    state.close_session()
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=21))
        design = state.get_or_404()
        cluster = design.cluster_transforms[0]
        root = Assembly()
        assembly_state.load_assembly(root)
        add_instance(AddInstanceRequest(source={'type': 'inline', 'design': design.model_dump(mode='json')}))
        parent = assembly_state.get_or_404().instances[0].id
        child = add_empty_part('Child')
        add_joint(AddJointRequest(instance_a_id=parent, instance_b_id=child, cluster_id_a=cluster.id))
        transform = Mat4x4().model_dump(mode='json')
        transform['values'][3] = 5
        body = PatchInstanceClusterTransformRequest(cluster_id=cluster.id,
            cluster_transform=cluster.model_copy(update={'translation': [5, 0, 0]}).model_dump(mode='json'),
            delta_transform=transform)
        before = assembly_state.get_or_404().model_copy(deep=True)
        patch_instance_cluster_transform(parent, body)
        after = assembly_state.get_or_404()
        assert after.feature_log[-1].params['inputs'] == body.model_dump(mode='json')
        assert after.instances[1].transform.values[3] == 5
        assert after.instances[0].source.design == before.instances[0].source.design
        replay_saved(root, after)
        assert assembly_state.undo() == before
    finally:
        state.close_session()


@pytest.mark.parametrize('operation', ['instance', 'group', 'joint'])
def test_deletion_cascades_constraints_detaches_cargo_and_replays(operation):
    from backend.api.assembly import delete_instance
    from backend.api.routes_assembly_joints import delete_joint
    from backend.api.routes_assembly_belts import (
        CreateBeltPathRequest, CreateBeltRiderRequest, create_belt_path, create_belt_rider,
    )
    from backend.core.models import Mat4x4

    root, _ = gears()
    a, b = assembly_state.get_or_404().joints
    create_belt_path(CreateBeltPathRequest(
        pulley_a={'joint_id': a.id, 'radius': 2, 'center_world': [0, 0, 0]},
        pulley_b={'joint_id': b.id, 'radius': 3, 'center_world': [10, 0, 0]},
    ))
    cargo = add_empty_part('Cargo')
    create_belt_rider(CreateBeltRiderRequest(
        belt_path_id=assembly_state.get_or_404().belt_paths[0].id,
        instance_id=cargo, transform=Mat4x4().model_dump(mode='json'),
    ))
    create_group(CreateGroupRequest(instance_ids=[a.instance_b_id], name='Removed'))
    group = assembly_state.get_or_404().groups[-1].id
    create_group(CreateGroupRequest(subgroup_ids=[group], instance_ids=[cargo], name='Retained'))
    before = assembly_state.get_or_404().model_copy(deep=True)
    if operation == 'instance':
        delete_instance(a.instance_b_id)
    elif operation == 'group':
        cascade_delete_group(group)
    else:
        delete_joint(a.id)
    saved = assembly_state.get_or_404()
    assert not saved.gear_relations
    assert not saved.belt_paths
    assert not saved.belt_riders
    assert saved.joints == [b]
    assert next(i for i in saved.instances if i.id == cargo) == next(i for i in before.instances if i.id == cargo)
    Assembly.model_validate(saved.model_dump())  # surviving group references resolve
    replay_saved(root, saved)
    assert assembly_state.undo() == before
    assert assembly_state.redo() == saved


def test_surgical_delete_replays_later_instance_deletion():
    from backend.api.assembly import (
        PatchInstanceRequest, patch_instance, delete_instance, delete_assembly_feature,
    )
    root, _ = gears()
    a, b = assembly_state.get_or_404().instances
    index = len(assembly_state.get_or_404().feature_log)
    patch_instance(b.id, PatchInstanceRequest(name='Temporary name'))
    delete_instance(a.id)
    before = assembly_state.get_or_404().model_copy(deep=True)
    delete_id = before.feature_log[-1].id
    delete_assembly_feature(index)
    after = assembly_state.get_or_404()
    assert after.instances == [b]
    assert not after.gear_relations
    assert after.feature_log[-1].id == delete_id
    replay_saved(root, after)
    assert assembly_state.undo() == before
