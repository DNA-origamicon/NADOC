"""Join capture must preserve sequence ownership and fail on partial evidence."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from tools.vr_workflows.join_recording import record_join_operation


def test_capture_disabled_runs_the_operation_without_a_runtime(monkeypatch, tmp_path):
    monkeypatch.delenv('NADOC_JOIN_FINAL_CAPTURE', raising=False)
    assert record_join_operation(None, tmp_path, 'move', lambda: 42) == 42


@pytest.mark.parametrize('status', ['saved', 'partial', 'error'])
@pytest.mark.parametrize('label,seconds', [('move', 2), ('apply', 5)])
def test_recording_resynchronizes_before_input_and_after_journal_commands(monkeypatch, tmp_path, status, label, seconds):
    from tools.vr_capture import viewer_record
    monkeypatch.setenv('NADOC_JOIN_FINAL_CAPTURE', str(tmp_path))
    original = Path.read_bytes
    monkeypatch.setattr(Path, 'read_bytes', lambda path: b'viewer\0--pose-journal\0/archive/journal\0' if str(path) == '/proc/123/cmdline' else original(path))
    observations = iter([{'session': '123-456', 'command_sequence': 8}, {'session': '123-456', 'command_sequence': 12}])
    live = SimpleNamespace(session='123-456', state={'frame_identity': {'enabled': True}, 'command_sequence': 1},
        bridge=SimpleNamespace(socket_path='/archive/private/viewer.sock', call=lambda *_: next(observations)))
    calls = []

    def record(directory, emit, **kwargs):
        assert kwargs['seconds'] == seconds
        assert kwargs['context']['diagnostics_required'] is True
        assert kwargs['context']['pose_journal']['session'] == live.session
        emit({'phase': 'awaiting_ack'})
        emit({'phase': 'recording'})
        emit({'phase': 'recording'})
        return {'status': status}

    monkeypatch.setattr(viewer_record, 'record', record)
    action = lambda: calls.append(live.state['command_sequence'])
    if status == 'saved':
        record_join_operation(live, tmp_path, label, action)
    else:
        with pytest.raises(RuntimeError, match='recording failed'):
            record_join_operation(live, tmp_path, label, action)
    assert calls == [8]
    assert live.state['command_sequence'] == 12
    assert json.loads((tmp_path / f'{label}-final-output.json').read_text())['status'] == status
