"""Video/HTML artifacts only; these tests never author molecular documents."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import assembly, routes_presentations
from backend.core.presentation_library import LIBRARY_FOLDER

HTML = b'<!doctype html><script id="nadoc-presentation-data" type="application/json">{"version":1}</script>'


def client_at(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    app = FastAPI()
    app.include_router(routes_presentations.router, prefix="/api")
    return TestClient(app)


def upload(client, content=HTML):
    return client.post("/api/presentations?name=Conference%20talk&kind=presentation",
                       content=content, headers={"Content-Type": "text/html"})


def test_library_survives_clients_and_delivers_complete_attachment(monkeypatch, tmp_path):
    client = client_at(monkeypatch, tmp_path)
    assert client.get("/api/presentations").json()["items"] == []
    saved = upload(client)
    assert saved.status_code == 201, saved.text
    entry = saved.json()
    assert entry["size"] == len(HTML)
    assert entry["name"] == "Conference talk"
    assert len(entry["id"]) == 64
    assert client_at(monkeypatch, tmp_path).get("/api/presentations").json() == {
        "folder": LIBRARY_FOLDER, "items": [entry],
    }
    response = client.get(f'/api/presentations/{entry["id"]}/content')
    assert response.content == HTML
    assert response.headers["content-disposition"].startswith("attachment;")
    assert response.headers["content-type"] == "application/octet-stream"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "sandbox" in response.headers["content-security-policy"]
    assert upload(client).json() == entry
    assert len(list((tmp_path / LIBRARY_FOLDER).iterdir())) == 2


def test_rejects_bad_uploads_and_cleans_partials(monkeypatch, tmp_path):
    client = client_at(monkeypatch, tmp_path)
    assert upload(client, b"not a presentation").status_code == 400
    monkeypatch.setattr(routes_presentations, "MAX_PRESENTATION_BYTES", 5)
    assert upload(client).status_code == 413
    assert client.post("/api/presentations?name=x", content=HTML).status_code == 415
    assert list((tmp_path / LIBRARY_FOLDER).iterdir()) == []


def test_rejects_paths_and_symbolic_links(monkeypatch, tmp_path):
    client = client_at(monkeypatch, tmp_path)
    assert client.get("/api/presentations/not-an-id/content").status_code == 400
    assert client.get(f'/api/presentations/{"a" * 64}/content').status_code == 404
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / LIBRARY_FOLDER).symlink_to(outside, target_is_directory=True)
    assert client.get("/api/presentations").status_code == 400
    assert upload(client).status_code == 400
    assert list(outside.iterdir()) == []


def test_incomplete_or_corrupt_records_are_not_listed(monkeypatch, tmp_path):
    client = client_at(monkeypatch, tmp_path)
    entry = upload(client).json()
    root = tmp_path / LIBRARY_FOLDER
    (root / (entry["id"] + ".html")).write_bytes(b"truncated")
    (root / ("a" * 64 + ".json")).write_text("invalid json")
    assert client.get("/api/presentations").json()["items"] == []
