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
    assert response.json()['design']['metadata']['description'] == 'Newer edit'
    assert response.json()['revision'] == design_state.revision()
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


# ── Startup audit: skip-stamp so unchanged designs are not re-parsed ─────────────


def _audit(monkeypatch, tmp_path):
    """Run the audit and return the paths it parsed (`Design.from_json` callers)."""
    from backend.api import routes_assembly_workspace as w

    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    parsed: list[str] = []
    real = Design.from_json.__func__

    def counting(cls, text, *a, **k):
        parsed.append(text)
        return real(cls, text, *a, **k)

    monkeypatch.setattr(Design, "from_json", classmethod(counting))
    w._audit_workspace_design_identities(tmp_path)
    monkeypatch.setattr(Design, "from_json", classmethod(real))
    return parsed


def _stamp_files(tmp_path):
    import json

    return json.loads((tmp_path / ".identity_audit.json").read_text())["files"]


def test_audit_skips_unchanged_confirmed_designs_on_second_pass(monkeypatch, tmp_path):
    (tmp_path / "a.nadoc").write_text(Design(id="id-a").to_json())
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "b.nadoc").write_text(Design(id="id-b").to_json())

    first = _audit(monkeypatch, tmp_path)
    assert len(first) >= 2                      # legacy files are parsed once and claimed
    stamp = _stamp_files(tmp_path)
    assert {k: v[2] for k, v in stamp.items()} == {"a.nadoc": "id-a", "sub/b.nadoc": "id-b"}
    assert all(v[3] for v in stamp.values())    # path-confirmed after the first pass

    assert _audit(monkeypatch, tmp_path) == []  # nothing changed → nothing parsed


def test_audit_reparses_only_edited_file(monkeypatch, tmp_path):
    (tmp_path / "a.nadoc").write_text(Design(id="id-a").to_json())
    (tmp_path / "b.nadoc").write_text(Design(id="id-b").to_json())
    _audit(monkeypatch, tmp_path)

    edited = Design.from_json((tmp_path / "b.nadoc").read_text())
    (tmp_path / "b.nadoc").write_text(edited.to_json() + " ")
    parsed = _audit(monkeypatch, tmp_path)
    assert len(parsed) == 1 and '"id-b"' in parsed[0]


def test_audit_forks_new_copy_of_an_unchanged_stamped_design(monkeypatch, tmp_path):
    (tmp_path / "a.nadoc").write_text(Design(id="id-a").to_json())
    _audit(monkeypatch, tmp_path)
    original = (tmp_path / "a.nadoc").read_text()
    (tmp_path / "copy.nadoc").write_text(original)   # external copy, identical id + claim

    _audit(monkeypatch, tmp_path)
    a = Design.from_json((tmp_path / "a.nadoc").read_text())
    c = Design.from_json((tmp_path / "copy.nadoc").read_text())
    assert a.id == "id-a" and c.id != "id-a"
    assert c.metadata.identity_last_known_path == "copy.nadoc"


def test_audit_treats_moved_file_as_changed(monkeypatch, tmp_path):
    (tmp_path / "a.nadoc").write_text(Design(id="id-a").to_json())
    _audit(monkeypatch, tmp_path)
    (tmp_path / "moved").mkdir()
    (tmp_path / "a.nadoc").rename(tmp_path / "moved" / "a.nadoc")

    _audit(monkeypatch, tmp_path)
    moved = Design.from_json((tmp_path / "moved" / "a.nadoc").read_text())
    assert moved.id == "id-a"                              # a move retains identity
    assert moved.metadata.identity_last_known_path == "moved/a.nadoc"


def test_audit_never_descends_into_engine_job_trees(monkeypatch, tmp_path):
    (tmp_path / "md_jobs" / "job1").mkdir(parents=True)
    (tmp_path / "md_jobs" / "job1" / "snapshot.nadoc").write_text(Design(id="x").to_json())
    (tmp_path / ".session" / "d").mkdir(parents=True)
    (tmp_path / ".session" / "d" / "active.nadoc").write_text(Design(id="y").to_json())
    (tmp_path / "keep.nadoc").write_text(Design(id="z").to_json())

    _audit(monkeypatch, tmp_path)
    assert set(_stamp_files(tmp_path)) == {"keep.nadoc"}


def test_audit_still_covers_non_job_internal_roots(monkeypatch, tmp_path):
    """Only ``*_jobs`` trees are pruned; other roots keep their historical coverage."""
    (tmp_path / "benchmark_runs").mkdir()
    (tmp_path / "benchmark_runs" / "fixture.nadoc").write_text(Design(id="f").to_json())
    _audit(monkeypatch, tmp_path)
    assert set(_stamp_files(tmp_path)) == {"benchmark_runs/fixture.nadoc"}


# ── Server-side open (no browser round trip of the file) ─────────────────────────


def test_open_part_installs_design_stamps_name_and_reports_identity(monkeypatch, tmp_path):
    client = _client_at(monkeypatch, tmp_path)
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "arm.nadoc").write_text(Design(id="arm-id").to_json())

    response = client.post("/api/library/open-part", json={"path": "sub/arm.nadoc", "name": "Arm"})
    assert response.status_code == 200
    body = response.json()
    assert body["identity_disposition"] == "claimed"       # legacy file claims its path
    assert body["design"]["id"] == "arm-id"
    assert body["design"]["metadata"]["name"] == "Arm"
    assert design_state.get_design().metadata.name == "Arm"
    # The reconcile claim is persisted, exactly as GET /library/content did.
    on_disk = Design.from_json((tmp_path / "sub" / "arm.nadoc").read_text())
    assert on_disk.metadata.identity_last_known_path == "sub/arm.nadoc"

    again = client.post("/api/library/open-part", json={"path": "sub/arm.nadoc"})
    assert again.json()["identity_disposition"] == "confirmed"


def test_open_part_rejects_missing_file_and_traversal(monkeypatch, tmp_path):
    client = _client_at(monkeypatch, tmp_path)
    assert client.post("/api/library/open-part", json={"path": "nope.nadoc"}).status_code == 404
    assert client.post("/api/library/open-part", json={"path": "../outside.nadoc"}).status_code == 400
