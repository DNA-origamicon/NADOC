"""Explicit presentation checkpoints, native replay, navigation and persistence."""
from fastapi.testclient import TestClient

from backend.api import state, assembly_state
from backend.api.main import app
from backend.api.crud import _seek_feature_log
from backend.api.part_proof_commands import execute, dependencies
from backend.core.part_history_contract import create_empty_part
from backend.core.models import Annotation, Design
from backend.core.models import Assembly

client = TestClient(app)


def test_part_checkpoint_replays_saved_configuration_not_later_autosaves():
    state.load_design(create_empty_part('Checkpoint test', 'HONEYCOMB'))
    doc = state.get_or_404()
    note = {'id': 'note', 'text': 'First', 'manual': True, 'screen_pos': [0.2, 0.3]}
    assert client.put('/api/design/annotations', json={'annotations': [note], 'enabled': False}).status_code == 200
    assert not state.get_or_404().feature_log
    response = client.post('/api/design/features/presentation-state', json={'document_id': doc.id, 'kind': 'annotations-state'})
    assert response.status_code == 200, response.text
    saved = state.get_or_404()
    entry = saved.feature_log[-1]
    assert dependencies(entry.op_kind, entry.params).known
    replayed = execute(entry.op_kind, create_empty_part('Replay', 'HONEYCOMB'), entry.params)
    assert replayed.annotations == saved.annotations
    note['text'] = 'Unrecorded draft'
    assert client.put('/api/design/annotations', json={'annotations': [note]}).status_code == 200
    source = Design.from_json(state.get_or_404().to_json())
    assert len(source.feature_log) == 1
    assert _seek_feature_log(source, 0).annotations[0].text == 'First'
    assert _seek_feature_log(source, -2).annotations == []
    assert source.annotations[0].text == 'Unrecorded draft'
    # Cold command replay also works with all acceleration payloads removed.
    source.feature_log[0].design_snapshot_gz_b64 = ''
    source.feature_log[0].post_state_gz_b64 = ''
    assert _seek_feature_log(source, 0).annotations == replayed.annotations


def test_volume_checkpoint_is_independent_and_rejects_stale_host_or_cursor():
    state.load_design(create_empty_part('Volumes', 'HONEYCOMB'))
    doc = state.get_or_404()
    state.mutate_display_metadata(lambda d: setattr(d, 'annotations', [Annotation(text='Live')]))
    volume = {'id': 'volume', 'min_corner': [0, 0, 0], 'max_corner': [5, 5, 5]}
    assert client.put('/api/design/view-volumes', json={'volumes': [volume]}).status_code == 200
    body = {'document_id': doc.id, 'kind': 'view-volumes-state'}
    assert client.post('/api/design/features/presentation-state', json={**body, 'document_id': 'wrong'}).status_code == 409
    result = client.post('/api/design/features/presentation-state', json=body)
    assert result.status_code == 200, result.text
    source = state.get_or_404()
    restored = _seek_feature_log(source, -2)
    assert restored.view_volumes == []
    assert restored.annotations[0].text == 'Live'
    assert _seek_feature_log(source, 0).view_volumes[0].id == 'volume'
    state.set_design(restored)
    assert client.post('/api/design/features/presentation-state', json=body).status_code == 409


def test_assembly_checkpoint_seek_and_replay():
    assembly_state.load_assembly(Assembly(name='Checkpoint assembly'))
    doc = assembly_state.get_or_404()
    assert client.put('/api/assembly/annotations', json={'annotations': [{'id': 'a', 'text': 'Saved'}]}).status_code == 200
    result = client.post('/api/assembly/features/presentation-state', json={'document_id': doc.id, 'kind': 'annotations-state'})
    assert result.status_code == 200, result.text
    entry = assembly_state.get_or_404().feature_log[-1]
    from backend.api.assembly import _replay_assembly_op
    assert _replay_assembly_op(Assembly(), entry.op_kind, entry.params).annotations[0].text == 'Saved'
    client.put('/api/assembly/annotations', json={'annotations': []})
    assert client.post('/api/assembly/features/seek', json={'position': 0}).status_code == 200
    assert assembly_state.get_or_404().annotations[0].text == 'Saved'
    assert client.post('/api/assembly/features/seek', json={'position': -2}).status_code == 200
    assert assembly_state.get_or_404().annotations == []


def test_explicit_history_undo_restores_checkpoint_but_ordinary_autosaves_do_not_add_rows():
    state.load_design(create_empty_part('Undo', 'HONEYCOMB'))
    doc = state.get_or_404()
    body = {'document_id': doc.id, 'kind': 'annotations-state'}
    for text in ['One', 'Two']:
        client.put('/api/design/annotations', json={'annotations': [{'id': 'a', 'text': text}]})
        assert client.post('/api/design/features/presentation-state', json=body).status_code == 200
    assert len(state.get_or_404().feature_log) == 2
    state.undo()
    assert state.get_or_404().annotations[0].text == 'One'
    state.redo()
    assert state.get_or_404().annotations[0].text == 'Two'


def test_assembly_keyframe_retains_and_clears_checkpoint_pin():
    assembly_state.load_assembly(Assembly(name='Animation checkpoints'))
    animation = client.post('/api/assembly/animations', json={'name': 'States'})
    assert animation.status_code == 200, animation.text
    anim = assembly_state.get_or_404().animations[-1]
    result = client.post(f'/api/assembly/animations/{anim.id}/keyframes', json={'feature_log_index': -2})
    assert result.status_code == 200, result.text
    keyframe = assembly_state.get_or_404().animations[-1].keyframes[-1]
    assert keyframe.feature_log_index == -2
    assert client.patch(f'/api/assembly/animations/{anim.id}/keyframes/{keyframe.id}', json={'feature_log_index': None}).status_code == 200
    assert assembly_state.get_or_404().animations[-1].keyframes[-1].feature_log_index is None


def test_saved_part_passes_publication_guard_and_independent_replay(tmp_path):
    from scripts.agent_structure_guard import publish
    from backend.api.part_history_navigation import replay_prefix
    state.load_design(create_empty_part('Published checkpoint', 'HONEYCOMB'))
    document = state.get_or_404()
    client.put('/api/design/annotations', json={'annotations': [{'id': 'a', 'text': 'Verified'}]})
    response = client.post('/api/design/features/presentation-state', json={'document_id': document.id, 'kind': 'annotations-state'})
    assert response.status_code == 200
    path = tmp_path / 'checkpoint.nadoc'
    try:
        publish(state.get_or_404(), path)
        reopened = Design.model_validate_json(path.read_text())
        replayed = replay_prefix(reopened, reopened.feature_log)
        assert replayed.annotations == reopened.annotations
        assert reopened.feature_log[0].op_kind == 'annotations-state'
    finally:
        path.unlink(missing_ok=True)
