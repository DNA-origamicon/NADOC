"""Selected-instance commands preserve native part process and assembly replay."""
import base64

import pytest
from fastapi import HTTPException

from backend.api import assembly_state, state, crud, doc_context
from backend.api.assembly import (CreateAssemblyRequest, create_assembly, AddInstanceRequest, add_instance,
    InstanceOverhangExtrudeRequest, extrude_instance_overhang, InstanceOverhangPatchRequest,
    patch_instance_overhang, PatchInstanceRequest, patch_instance)
from backend.api.assembly_history_verification import verify
from backend.api.assembly_evaluation import evaluate
from backend.core.models import Assembly
from tests.conftest import valid_overhang_sites


@pytest.fixture(autouse=True)
def sessions():
    state.close_session(); assembly_state.close_session()
    yield
    state.close_session(); assembly_state.close_session()


def authored():
    create_assembly(CreateAssemblyRequest(name='Instance commands'))
    crud.create_bundle(crud.BundleRequest(cells=[[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]], length_bp=42))
    source = state.get_or_404()
    add_instance(AddInstanceRequest(source={'type': 'inline', 'design': source.model_dump(mode='json')}, name='Part'))
    iid = assembly_state.get_or_404().instances[0].id
    return iid, InstanceOverhangExtrudeRequest(**valid_overhang_sites(source)[0], length_bp=8)


def test_reopened_instance_commands_verify_and_do_not_touch_open_part():
    iid, body = authored()
    source = state.get_or_404().model_copy(deep=True)
    stamps = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    revision, depth = assembly_state.revision(), assembly_state.undo_depth()
    response = extrude_instance_overhang(iid, body)
    assert assembly_state.revision() == revision + 1
    assert assembly_state.undo_depth() == depth + 1
    assert state.get_or_404() == source
    assert (doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()) == stamps
    part = assembly_state.get_or_404().instances[0].source.design
    row = part.feature_log[-1]
    assert row.params['_proof_version'] == 1
    assert row.params['history_seed']
    assert row.design_snapshot_gz_b64 and row.post_state_gz_b64
    assert base64.b64decode(row.post_state_gz_b64)[4:8] == bytes(4)
    oid = response['design']['overhangs'][-1]['id']
    patch_instance_overhang(iid, oid, InstanceOverhangPatchRequest(label='Selected oligo', sequence='ACGTACGT'))
    patch_instance(iid, PatchInstanceRequest(name='Downstream'))
    saved = Assembly.from_json(assembly_state.get_or_404().to_json())
    proof = verify(saved)
    assert proof['status'] == 'verified', proof
    assert saved.instances[0].source.design.feature_log[-1].op_kind == 'overhang-sequence'
    from backend.api import part_proof_commands
    from backend.core.part_history_contract import assess_part_history
    part_proof = assess_part_history(saved.instances[0].source.design, execute=part_proof_commands.execute,
                                    dependencies=part_proof_commands.dependencies)
    assert part_proof['status'] == 'verified', part_proof
    assert saved.feature_log[1].params['part_feature_id'] == row.id
    from backend.api.assembly import _decode_entry_pre_state
    prefix = _decode_entry_pre_state(saved.feature_log, 1)
    assert not prefix.instances[0].source.design.overhangs
    assert saved.feature_log[1].post_state_gz_b64


def test_earlier_extrusion_edit_replays_patch_and_later_assembly_commands():
    iid, body = authored()
    extrude_instance_overhang(iid, body)
    part = assembly_state.get_or_404().instances[0].source.design
    oid = part.overhangs[-1].id
    patch_instance_overhang(iid, oid, InstanceOverhangPatchRequest(label='Kept label'))
    patch_instance(iid, PatchInstanceRequest(name='Later name'))
    source = assembly_state.get_or_404().model_copy(deep=True)
    selected = source.feature_log[1]
    result = evaluate(source, {'operation': 'edit', 'expected_assembly_id': source.id,
        'expected_revision': assembly_state.revision(), 'feature_id': selected.id, 'inputs': {'length_bp': 10}})
    assert result['status'] == 'ready', result
    candidate = Assembly.model_validate(result['candidate'])
    assert candidate.instances[0].name == 'Later name'
    assert candidate.instances[0].source.design.overhangs[-1].label == 'Kept label'
    assert candidate.instances[0].source.design.feature_log[1].params['length_bp'] == 10
    assert candidate.instances[0].source.design.feature_log[1].id == selected.params['part_feature_id']
    assert assembly_state.get_or_404() == source


def test_failed_native_patch_is_atomic():
    iid, _ = authored()
    source = assembly_state.get_or_404().model_copy(deep=True)
    revision, depth = assembly_state.revision(), assembly_state.undo_depth()
    with pytest.raises(HTTPException):
        patch_instance_overhang(iid, 'missing', InstanceOverhangPatchRequest(label='No'))
    assert assembly_state.get_or_404() == source
    assert (assembly_state.revision(), assembly_state.undo_depth()) == (revision, depth)


def test_rotation_patch_and_deletion_replay():
    iid, body = authored()
    extrude_instance_overhang(iid, body)
    part = assembly_state.get_or_404().instances[0].source.design
    patch_instance_overhang(iid, part.overhangs[-1].id, InstanceOverhangPatchRequest(rotation=[0, 0, 0, 1]))
    source = assembly_state.get_or_404().model_copy(deep=True)
    assert verify(Assembly.from_json(source.to_json()))['status'] == 'verified'
    request = {'operation': 'delete', 'expected_assembly_id': source.id,
        'expected_revision': assembly_state.revision(), 'feature_id': source.feature_log[1].id}
    failed = evaluate(source, request)
    assert failed['status'] == 'failed'
    assert failed['issues'][0]['detail']['feature_id'] == source.feature_log[2].id
    request['feature_id'] = source.feature_log[2].id
    assert evaluate(source, request)['status'] == 'ready'
    assert assembly_state.get_or_404() == source


def test_pinned_file_revision_changes_only_the_selected_instance():
    _, body = authored()
    from backend.core.models import PartSourceFile
    from backend.core.assembly_source_versions import pin_source
    original = assembly_state.get_or_404().instances[0].source.model_copy(deep=True)
    pinned = pin_source(PartSourceFile(path='not-written.nadoc'), original.design)
    add_instance(AddInstanceRequest(name='Pinned', source=pinned.model_dump(mode='json')))
    iid = assembly_state.get_or_404().instances[-1].id
    extrude_instance_overhang(iid, body)
    saved = Assembly.from_json(assembly_state.get_or_404().to_json())
    assert saved.instances[0].source == original
    changed = saved.instances[-1].source
    assert changed.type == 'file' and changed.path == pinned.path
    assert changed.revision_sha256 != pinned.revision_sha256
    assert changed.revision.feature_log[-1].op_kind == 'overhang-extrude'
    assert verify(saved)['status'] == 'verified'
