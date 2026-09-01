from fastapi.testclient import TestClient

from backend.api import assembly
from backend.api.main import app


def _client_at(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    return TestClient(app)


def test_trash_hides_and_restores_file(monkeypatch, tmp_path):
    client = _client_at(monkeypatch, tmp_path)
    (tmp_path / "parts").mkdir()
    (tmp_path / "parts" / "a.nadoc").write_text("{}")

    trashed = client.post("/api/library/trash", json={"path": "parts/a.nadoc"})
    assert trashed.status_code == 200, trashed.text
    trash_id = trashed.json()["id"]
    assert not (tmp_path / "parts" / "a.nadoc").exists()
    assert client.get("/api/library/trash").json()["items"][0]["original_path"] == "parts/a.nadoc"
    assert "parts/a.nadoc" not in {item["path"] for item in client.get("/api/library/files").json()}

    restored = client.post("/api/library/trash/restore", json={"trash_id": trash_id})
    assert restored.status_code == 200, restored.text
    assert (tmp_path / "parts" / "a.nadoc").read_text() == "{}"
    assert client.get("/api/library/trash").json() == {"items": []}


def test_restore_refuses_to_overwrite(monkeypatch, tmp_path):
    client = _client_at(monkeypatch, tmp_path)
    source = tmp_path / "a.nadoc"
    source.write_text("old")
    trash_id = client.post("/api/library/trash", json={"path": "a.nadoc"}).json()["id"]
    source.write_text("new")

    response = client.post("/api/library/trash/restore", json={"trash_id": trash_id})
    assert response.status_code == 409
    assert source.read_text() == "new"
