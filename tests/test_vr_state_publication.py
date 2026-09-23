"""Session readers must never observe a partially published launch record."""
import json
from pathlib import Path
from backend.api import routes_vr as vr


def test_launch_publication_keeps_previous_record_until_atomic_replace(monkeypatch, tmp_path):
    state = tmp_path / 'state.json'
    state.write_text('{"pid": 1}')
    monkeypatch.setattr(vr, '_STATE_PATH', state)
    replace = vr.os.replace
    def observe(source, target):
        assert json.loads(state.read_text()) == {'pid': 1}
        assert json.loads(Path(source).read_text()) == {'pid': 2}
        assert Path(source).stat().st_mode & 0o777 == 0o600
        replace(source, target)
    monkeypatch.setattr(vr.os, 'replace', observe)
    vr._write_state({'pid': 2})
    assert json.loads(state.read_text()) == {'pid': 2}
    assert list(tmp_path.iterdir()) == [state]


def test_invalid_status_read_does_not_delete_replacement(monkeypatch, tmp_path):
    state = tmp_path / 'state.json'
    state.write_text('old invalid record')
    monkeypatch.setattr(vr, '_STATE_PATH', state)
    read = Path.read_text
    def racing_read(path, *args, **kwargs):
        if path == state:
            state.write_text('{"pid": 2}')
            return 'old invalid record'
        return read(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'read_text', racing_read)
    assert vr._read_state() is None
    assert state.exists()
    assert json.loads(read(state)) == {'pid': 2}
