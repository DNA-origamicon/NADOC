"""Shared history executor honors proposed order/suppression and cancellation."""

import pytest
from fastapi import HTTPException

from backend.api import assembly_state
from backend.api.assembly import AddInstanceRequest, PatchInstanceRequest, add_instance, patch_instance
from backend.api.assembly_history_regeneration import regenerate
from backend.api.assembly_history_transaction import apply_history_change
from backend.core.models import Assembly, Design


@pytest.fixture(autouse=True)
def session():
    assembly_state.close_session()
    yield
    assembly_state.close_session()


def history():
    root = Assembly()
    assembly_state.load_assembly(root)
    add_instance(AddInstanceRequest(source={'type': 'inline', 'design': Design().model_dump(mode='json')}, name='Original'))
    identity = assembly_state.get_or_404().instances[0].id
    patch_instance(identity, PatchInstanceRequest(name='Renamed'))
    patch_instance(identity, PatchInstanceRequest(fixed=True))
    return root, assembly_state.get_or_404().model_copy(deep=True)


def test_suppressed_row_keeps_identity_and_recovery_without_executing_then_resumes():
    root, source = history()
    proposed = list(source.feature_log)
    proposed[1] = proposed[1].model_copy(update={'suppressed': True})
    candidate = apply_history_change(lambda: regenerate(root, proposed))
    assert candidate.instances[0].name == 'Original'
    assert candidate.instances[0].fixed
    assert [r.id for r in candidate.feature_log] == [r.id for r in source.feature_log]
    assert [r.timestamp for r in candidate.feature_log] == [r.timestamp for r in source.feature_log]
    reopened = Assembly.from_json(candidate.to_json())
    assert reopened.feature_log[1].suppressed
    from backend.api.assembly import _decode_entry_pre_state
    pre = _decode_entry_pre_state(reopened.feature_log, 1)
    post = assembly_state.decode_assembly_snapshot(reopened.feature_log[1].post_state_gz_b64)
    assert pre.instances == post.instances
    assert assembly_state.undo() == source
    assert assembly_state.redo() == candidate
    proposed = [r.model_copy(update={'suppressed': False}) for r in reopened.feature_log]
    restored = apply_history_change(lambda: regenerate(root, proposed))
    assert restored.instances == source.instances


def test_reordered_commands_regenerate_and_missing_dependency_is_attributed():
    root, source = history()
    reordered = [source.feature_log[i] for i in (0, 2, 1)]
    result = apply_history_change(lambda: regenerate(root, reordered))
    assert result.instances == source.instances
    assert [r.id for r in result.feature_log] == [r.id for r in reordered]
    revision = assembly_state.revision()
    depths = assembly_state.undo_depth(), assembly_state.redo_depth()
    with pytest.raises(HTTPException) as error:
        apply_history_change(lambda: regenerate(root, [source.feature_log[i] for i in (1, 0, 2)]))
    assert error.value.detail['feature_id'] == source.feature_log[1].id
    assert error.value.detail['index'] == 0
    assert assembly_state.get_or_404() == result
    assert assembly_state.revision() == revision
    assert (assembly_state.undo_depth(), assembly_state.redo_depth()) == depths


def test_cancellation_after_a_command_preserves_live_state_and_redo():
    root, source = history()
    assembly_state.undo()
    saved, revision = assembly_state.copy_for_persist()
    depths = assembly_state.undo_depth(), assembly_state.redo_depth()
    calls = 0

    def checkpoint():
        nonlocal calls
        calls += 1
        if calls == 3:
            raise InterruptedError('cancelled after first command')

    with pytest.raises(InterruptedError):
        apply_history_change(lambda: regenerate(root, source.feature_log, checkpoint=checkpoint))
    assert calls == 3
    assert assembly_state.get_or_404() == saved
    assert assembly_state.revision() == revision
    assert (assembly_state.undo_depth(), assembly_state.redo_depth()) == depths


def test_duplicate_feature_identity_rejects_before_publication():
    root, source = history()
    with pytest.raises(HTTPException, match='ambiguous'):
        apply_history_change(lambda: regenerate(root, [source.feature_log[0], source.feature_log[0]]))
    assert assembly_state.get_or_404() == source
