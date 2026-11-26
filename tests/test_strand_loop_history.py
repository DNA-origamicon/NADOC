"""Exercise recorded loop commands through the actual part history hosts."""
import pytest
from backend.api import state, doc_context, crud
from backend.api.routes_loop_skip import set_strand_loop, StrandLoopRequest
from backend.api import part_ordinary_recipe_recording as host
from backend.api.part_routing_edit_inputs import normalize
from backend.core.part_command_errors import CommandContractError
from tests.test_strand_loops import process, params
from tests.test_part_history_navigation import strip_recovery, proof
from tests.test_part_pattern_recording import worker  # noqa: F401


@pytest.fixture
def loop_document():
    token = doc_context.set_current_doc('__e2e__loop_history')
    try:
        state.load_design(process().design)
        request = {**params(state.get_or_404().strands[0], 6), 'rotation_deg': 0}
        request.pop('_proof_version')
        set_strand_loop(StrandLoopRequest(**request))
        yield request
    finally:
        state.drop_doc(doc_context.get_current_doc())
        doc_context.reset_current_doc(token)


def length(design):
    return sum(loop.length for strand in design.strands for loop in strand.loops)


@pytest.mark.parametrize('cold', [False, True])
def test_loop_scrub_revert_delete_undo_redo(loop_document, cold):
    source = state.get_or_404()
    if cold:
        source = strip_recovery(source)
        state.load_design(source)
    assert source.feature_log[1].children[0].op_subtype == 'strand-loop-set'
    expected = proof(source)
    for position, sub, count in [(1, -2, 0), (1, 0, 6), (0, None, 0), (-1, None, 6)]:
        viewed = crud._seek_feature_log(source, position, sub)
        assert length(viewed) == count
        assert sum(len(s.sequence or '') for s in viewed.strands) == (21 + count if count else 0)
    assert proof(crud._seek_feature_log(source, -1)) == expected
    for operation in [lambda: crud.revert_to_before_feature(1, 0),
                      lambda: crud.delete_feature(1, sub_index=0)]:
        operation()
        assert length(state.get_or_404()) == 0
        proof(state.get_or_404())
        state.undo()
        assert length(state.get_or_404()) == 6
        assert proof(state.get_or_404()) == expected
        state.redo()
        assert length(state.get_or_404()) == 0
        state.undo()


def test_loop_owned_editor_and_remove_restore_sequences(loop_document, worker, tmp_path):
    from scripts.agent_structure_guard import publish, audit
    from backend.core.models import Design
    source = state.get_or_404()
    parent = source.feature_log[1]
    guards = dict(expected_design_id=source.id, expected_revision=state.revision(),
                  expected_feature_id=parent.id, expected_child_id=parent.children[0].id)
    packet = host.routing_inputs(1, 0, **guards)
    assert packet['params']['length'] == 6
    host.edit_routing(1, 0, dict(length=12, aspect_ratio=2, rotation_deg=90), **guards)
    edited = state.get_or_404()
    assert length(edited) == 12
    assert edited.strands[0].loops[0].rotation_deg == 90
    proof(edited)
    state.undo()
    assert length(state.get_or_404()) == 6
    state.redo()
    assert length(state.get_or_404()) == 12
    path = tmp_path / '__e2e__loop_history.nadoc'
    publish(state.get_or_404(), path)
    assert audit(Design.model_validate_json(path.read_text()))['status'] == 'verified'
    sequence = state.get_or_404().strands[0].sequence
    set_strand_loop(StrandLoopRequest(**{**loop_document, 'length': 0}))
    assert length(state.get_or_404()) == 0
    proof(state.get_or_404())
    state.undo()
    assert state.get_or_404().strands[0].sequence == sequence
    state.redo()
    assert length(state.get_or_404()) == 0
    proof(state.get_or_404())


@pytest.mark.parametrize('patch', [
    {'length': -1}, {'length': 513}, {'length': True}, {'length': 1.5},
    {'aspect_ratio': 0}, {'aspect_ratio': 11}, {'rotation_deg': 181},
    {'rotation_deg': float('nan')}, {'_proof_version': 2},
])
def test_loop_history_rejects_invalid_inputs(patch):
    previous = {**params(process().design.strands[0]), 'rotation_deg': 0}
    with pytest.raises(CommandContractError):
        normalize('strand-loop-set', previous, patch)


def test_older_loop_defaults_remain_editable():
    previous = params(process().design.strands[0])
    result = normalize('strand-loop-set', previous, {'length': 9})
    assert result['rotation_deg'] == 0
    assert result['aspect_ratio'] == 3


def test_edit_and_delete_keep_later_independent_loop(loop_document, worker):
    target = state.get_or_404().strands[1]
    request = params(target, 8)
    request.pop('_proof_version')
    set_strand_loop(StrandLoopRequest(**request))
    source = state.get_or_404()
    parent = source.feature_log[1]
    host.edit_routing(1, 0, {'length': 10}, expected_design_id=source.id,
        expected_revision=state.revision(), expected_feature_id=parent.id,
        expected_child_id=parent.children[0].id)
    assert [s.loops[0].length for s in state.get_or_404().strands] == [10, 8]
    proof(state.get_or_404())
    crud.delete_feature(1, sub_index=0)
    result = state.get_or_404()
    assert not result.strands[0].loops
    assert result.strands[1].loops[0].length == 8
    proof(result)
    state.undo()
    assert length(state.get_or_404()) == 18
    state.redo()
    assert length(state.get_or_404()) == 8
