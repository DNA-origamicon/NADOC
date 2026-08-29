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
