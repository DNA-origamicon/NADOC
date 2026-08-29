from __future__ import annotations

from fastapi.testclient import TestClient

from backend.api import assembly
from backend.api.main import app
from backend.core.models import Design
from backend.core.project_revisions import ProjectRevisionStore


def _client(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setenv("NADOC_PEER_TOKEN", "test-secret")
    return TestClient(app)


def _source_project(path):
    design = Design(id="project-1")
    store = ProjectRevisionStore(path)
    revision = store.commit(
        design,
        loadout_id="main",
        loadout_name="Main",
        parent_revision_id=None,
        expected_head=None,
    )
    return store, revision


def test_peer_routes_are_disabled_or_reject_invalid_token(monkeypatch, tmp_path):
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.delenv("NADOC_PEER_TOKEN", raising=False)
    client = TestClient(app)
    assert client.get("/api/collaboration/projects/p/manifest").status_code == 503
    monkeypatch.setenv("NADOC_PEER_TOKEN", "correct")
    assert client.get(
        "/api/collaboration/projects/p/manifest",
        headers={"Authorization": "Bearer wrong"},
    ).status_code == 401


def test_local_project_overview_needs_no_peer_token(monkeypatch, tmp_path):
    store, revision = _source_project(tmp_path)
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.delenv("NADOC_PEER_TOKEN", raising=False)
    response = TestClient(app).get(
        "/api/collaboration/projects/project-1/overview"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["refs"]["main"]["head_revision_id"] == revision.revision_id
    assert payload["jobs"] == []
    assert store.branch_head("project-1", "main") == revision.revision_id


def test_authenticated_peer_can_transfer_and_fast_forward_project(monkeypatch, tmp_path):
    source, revision = _source_project(tmp_path / "source")
    client = _client(monkeypatch, tmp_path / "target")
    auth = {"Authorization": "Bearer test-secret"}
    snapshot = source.snapshot_path("project-1", revision.snapshot_sha256).read_bytes()

    put_snapshot = client.put(
        f"/api/collaboration/projects/project-1/snapshots/{revision.snapshot_sha256}",
        content=snapshot,
        headers={**auth, "Content-Type": "application/gzip"},
    )
    assert put_snapshot.status_code == 201, put_snapshot.text
    put_revision = client.put(
        f"/api/collaboration/projects/project-1/revisions/{revision.revision_id}",
        json=source.export_revision("project-1", revision.revision_id),
        headers=auth,
    )
    assert put_revision.status_code == 201, put_revision.text
    advance = client.post(
        "/api/collaboration/projects/project-1/refs",
        json={
            "loadout_id": "main",
            "new_head": revision.revision_id,
            "expected_head": None,
            "name": "Main",
        },
        headers=auth,
    )
    assert advance.status_code == 200, advance.text
    manifest = client.get(
        "/api/collaboration/projects/project-1/manifest", headers=auth
    )
    assert manifest.status_code == 200
    assert manifest.json()["refs"]["main"]["head_revision_id"] == revision.revision_id


def test_peer_ref_conflict_is_structured_and_never_overwrites(monkeypatch, tmp_path):
    store, revision = _source_project(tmp_path)
    client = _client(monkeypatch, tmp_path)
    response = client.post(
        "/api/collaboration/projects/project-1/refs",
        json={
            "loadout_id": "main",
            "new_head": revision.revision_id,
            "expected_head": "0" * 64,
            "name": "Main",
        },
        headers={"Authorization": "test-secret"},
    )
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert detail["kind"] == "branch_diverged"
    assert detail["current_head"] == revision.revision_id
    assert store.branch_head("project-1", "main") == revision.revision_id


def test_lease_api_returns_read_only_and_can_auto_fork(monkeypatch, tmp_path):
    _source_project(tmp_path)
    client = _client(monkeypatch, tmp_path)
    url = "/api/collaboration/projects/project-1/loadouts/main/lease"
    first = client.post(url, json={"server_id": "a", "client_id": "one"})
    blocked = client.post(url, json={"server_id": "b", "client_id": "two"})
    forked = client.post(
        url,
        json={
            "server_id": "b",
            "client_id": "two",
            "server_name": "Laptop",
            "auto_fork": True,
        },
    )
    assert first.json()["status"] == "acquired"
    assert blocked.json()["status"] == "read_only"
    assert forked.json()["status"] == "forked"
    assert forked.json()["forked_from_loadout_id"] == "main"


def test_peer_registry_api_never_returns_tokens(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    identity = client.get("/api/collaboration/identity")
    assert identity.status_code == 200
    assert identity.json()["server_id"]
    created = client.post(
        "/api/collaboration/peers",
        json={
            "id": "remote",
            "name": "Remote PC",
            "base_url": "https://remote.example.ts.net",
            "token": "remote-secret",
        },
    )
    assert created.status_code == 201
    assert "token" not in created.json()
    listed = client.get("/api/collaboration/peers").json()["peers"]
    assert listed == [
        {
            "id": "remote",
            "name": "Remote PC",
            "base_url": "https://remote.example.ts.net",
        }
    ]
    assert client.delete("/api/collaboration/peers/remote").json() == {
        "removed": True
    }


def test_peer_registry_rejects_plain_non_tailnet_http(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    response = client.post(
        "/api/collaboration/peers",
        json={
            "id": "unsafe",
            "name": "Unsafe",
            "base_url": "http://192.168.1.2:5173",
            "token": "secret",
        },
    )
    assert response.status_code == 400
    assert "Tailscale" in response.text
