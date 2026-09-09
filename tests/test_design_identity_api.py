from fastapi.testclient import TestClient
import time

from backend.api import assembly, state as design_state
from backend.api.main import app
from backend.core.models import Design


def _client_at(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    return TestClient(app)


def test_save_as_forks_identity_and_keeps_old_file(monkeypatch, tmp_path):
    client = _client_at(monkeypatch, tmp_path)
    design_state.set_design(Design(id="original"))

    first = client.post(
        "/api/design/save-workspace", json={"path": "a.nadoc", "overwrite": True}
    )
    assert first.status_code == 200
    assert first.json()["design"]["id"] == "original"
    assert first.json()["design"]["active_loadout_id"] == "main"
    first_saved = Design.from_json((tmp_path / "a.nadoc").read_text())
    assert first_saved.loadouts[0].head_revision_id

    second = client.post(
        "/api/design/save-workspace", json={"path": "b.nadoc", "overwrite": True}
    )
    assert second.status_code == 200
    fork_id = second.json()["design"]["id"]
    assert fork_id != "original"
    assert Design.from_json((tmp_path / "a.nadoc").read_text()).id == "original"
    assert Design.from_json((tmp_path / "b.nadoc").read_text()).id == fork_id


def test_opening_external_copy_forks_duplicate_id(monkeypatch, tmp_path):
    client = _client_at(monkeypatch, tmp_path)
    original = Design(id="same")
    original.metadata.identity_last_known_path = "a.nadoc"
    (tmp_path / "a.nadoc").write_text(original.to_json())
    (tmp_path / "copy.nadoc").write_text(original.to_json())

    response = client.get("/api/library/content", params={"path": "copy.nadoc"})
    assert response.status_code == 200
    assert response.json()["identity_disposition"] == "copy"
    copied = Design.from_json(response.json()["content"])
    assert copied.id != "same"
    assert copied.metadata.identity_last_known_path == "copy.nadoc"


def test_managed_move_retains_identity_and_updates_signoff(monkeypatch, tmp_path):
    client = _client_at(monkeypatch, tmp_path)
    design = Design(id="stable")
    design.metadata.identity_last_known_path = "a.nadoc"
    (tmp_path / "a.nadoc").write_text(design.to_json())

    response = client.post(
        "/api/library/move", json={"path": "a.nadoc", "dest_folder": "parts"}
    )
    assert response.status_code == 200, response.text
    moved = Design.from_json((tmp_path / "parts" / "a.nadoc").read_text())
    assert moved.id == "stable"
    assert moved.metadata.identity_last_known_path == "parts/a.nadoc"


def test_library_audit_separates_duplicate_legacy_files(monkeypatch, tmp_path):
    client = _client_at(monkeypatch, tmp_path)
    legacy = Design(id="duplicated-old-id")
    (tmp_path / "a.nadoc").write_text(legacy.to_json())
    (tmp_path / "b.nadoc").write_text(legacy.to_json())

    response = client.get("/api/library/files")
    assert response.status_code == 200
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        a = Design.from_json((tmp_path / "a.nadoc").read_text())
        b = Design.from_json((tmp_path / "b.nadoc").read_text())
        if a.id != b.id:
            break
        time.sleep(0.01)
    a = Design.from_json((tmp_path / "a.nadoc").read_text())
    b = Design.from_json((tmp_path / "b.nadoc").read_text())
    assert a.id != b.id
    assert {
        a.metadata.identity_last_known_path,
        b.metadata.identity_last_known_path,
    } == {
        "a.nadoc",
        "b.nadoc",
    }


def test_autosave_after_undo_redo_and_further_edit(monkeypatch, tmp_path):
    client = _client_at(monkeypatch, tmp_path)
    design_state.set_design_branch(Design(id="undo-save"))
    design_state.clear_history()
    save = lambda: client.post('/api/design/save-workspace', json={"path": "undo.nadoc", "overwrite": True})
    assert save().status_code == 200
    design_state.mutate_and_validate(lambda d: setattr(d.metadata, 'name', 'Edited'))
    assert save().status_code == 200
    design_state.undo()
    assert save().status_code == 200
    design_state.redo()
    assert save().status_code == 200
    design_state.mutate_and_validate(lambda d: setattr(d.metadata, 'name', 'After redo'))
    assert save().status_code == 200
    assert Design.from_json((tmp_path / 'undo.nadoc').read_text()).metadata.name == 'After redo'


def test_autosave_after_history_snapshot_restore(monkeypatch, tmp_path):
    client = _client_at(monkeypatch, tmp_path)
    design_state.set_design_branch(Design(id="history-save"))
    design_state.clear_history()
    def save():
        return client.post('/api/design/save-workspace', json={"path": "history.nadoc", "overwrite": True})
    assert save().status_code == 200
    old = design_state.get_or_404().model_copy(deep=True)
    design_state.mutate_and_validate(lambda d: setattr(d.metadata, 'description', 'Later'))
    assert save().status_code == 200
    design_state.set_design(old)
    assert save().status_code == 200
    assert Design.from_json((tmp_path / 'history.nadoc').read_text()).metadata.description == ''


def test_autosave_does_not_adopt_another_documents_revision(monkeypatch, tmp_path):
    from backend.core.project_revisions import refresh_active_revision
    client = _client_at(monkeypatch, tmp_path)
    design_state.set_design_branch(Design(id="conflicting-save"))
    design_state.clear_history()
    def save():
        return client.post('/api/design/save-workspace', json={"path": "conflict.nadoc", "overwrite": True})
    assert save().status_code == 200
    other = design_state.get_or_404().model_copy(deep=True)
    other.metadata.description = 'Another document changed this'
    refresh_active_revision(tmp_path, other)
    design_state.mutate_and_validate(lambda d: setattr(d.metadata, 'description', 'My edit'))
    response = save()
    assert response.status_code == 409
    assert response.json()['detail']['kind'] == 'branch_diverged'
    assert Design.from_json((tmp_path / 'conflict.nadoc').read_text()).metadata.description == ''


def test_save_acknowledgement_preserves_edit_made_during_save(monkeypatch, tmp_path):
    from backend.core import project_revisions
    client = _client_at(monkeypatch, tmp_path)
    design_state.set_design_branch(Design(id="save-race"))
    design_state.clear_history()
    refresh = project_revisions.refresh_active_revision
    def interleaved_refresh(workspace, design):
        result = refresh(workspace, design)
        design_state.mutate_and_validate(lambda d: setattr(d.metadata, 'description', 'Newer edit'))
        return result
    monkeypatch.setattr(project_revisions, 'refresh_active_revision', interleaved_refresh)
    response = client.post('/api/design/save-workspace', json={"path": "race.nadoc", "overwrite": True})
    assert response.status_code == 200
    assert design_state.get_or_404().metadata.description == 'Newer edit'
    assert Design.from_json((tmp_path / 'race.nadoc').read_text()).metadata.description == ''
    monkeypatch.setattr(project_revisions, 'refresh_active_revision', refresh)
    response = client.post('/api/design/save-workspace', json={"path": "race.nadoc", "overwrite": True})
    assert response.status_code == 200
    assert Design.from_json((tmp_path / 'race.nadoc').read_text()).metadata.description == 'Newer edit'


def test_autosave_after_undo_survives_code_reload(monkeypatch, tmp_path):
    from backend.api import session_cache
    from backend.api.doc_context import DEFAULT_DOC_ID
    client = _client_at(monkeypatch, tmp_path)
    design_state.set_design_branch(Design(id="reload-save"))
    design_state.clear_history()
    def save():
        return client.post('/api/design/save-workspace', json={"path": "reload.nadoc", "overwrite": True})
    assert save().status_code == 200
    design_state.mutate_and_validate(lambda d: setattr(d.metadata, 'name', 'Edited'))
    assert save().status_code == 200
    design_state.undo()
    monkeypatch.setattr(session_cache, '_session_dir', tmp_path / '.session')
    session_cache._write_doc(DEFAULT_DOC_ID)
    design_state.drop_doc(DEFAULT_DOC_ID)
    assert session_cache.restore() == 1
    assert save().status_code == 200
    assert Design.from_json((tmp_path / 'reload.nadoc').read_text()).metadata.name == 'Untitled'
