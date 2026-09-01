from __future__ import annotations

import httpx
from fastapi.testclient import TestClient

from backend.api import assembly
from backend.api import routes_project_collaboration as collaboration_routes
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


def test_pairing_code_registers_caller_once_and_returns_local_credentials(
    monkeypatch, tmp_path
):
    client = _client(monkeypatch, tmp_path)
    monkeypatch.setenv("NADOC_PUBLIC_URL", "http://100.99.71.2:5173")
    started = client.post("/api/collaboration/pairing/start")
    assert started.status_code == 200
    code = started.json()["code"]
    assert len(code) == 6
    completed = client.post(
        "/api/collaboration/pairing/complete",
        json={
            "code": code,
            "peer_id": "laptop",
            "peer_name": "Laptop",
            "peer_base_url": "http://100.80.2.3:5173",
            "peer_token": "laptop-secret",
        },
    )
    assert completed.status_code == 200, completed.text
    assert completed.json()["token"] == "test-secret"
    assert completed.json()["base_url"] == "http://100.99.71.2:5173"
    assert client.get("/api/collaboration/peers").json()["peers"][0]["id"] == "laptop"
    replay = client.post(
        "/api/collaboration/pairing/complete",
        json={
            "code": code,
            "peer_id": "attacker",
            "peer_name": "Attacker",
            "peer_base_url": "http://100.80.2.4:5173",
            "peer_token": "stolen",
        },
    )
    assert replay.status_code == 410


def test_shared_library_requires_auth_and_blocks_path_escape(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    (tmp_path / "part.nadoc").write_text(Design(id="shared").to_json())
    assert client.get("/api/collaboration/library/files").status_code == 401
    auth = {"Authorization": "Bearer test-secret"}
    entries = client.get("/api/collaboration/library/files", headers=auth)
    assert entries.status_code == 200
    assert any(item["path"] == "part.nadoc" for item in entries.json())
    content = client.get(
        "/api/collaboration/library/content",
        params={"path": "part.nadoc"},
        headers=auth,
    )
    assert content.status_code == 200
    assert Design.from_json(content.text).id == "shared"
    escaped = client.get(
        "/api/collaboration/library/content",
        params={"path": "../secret.nadoc"},
        headers=auth,
    )
    assert escaped.status_code == 400


def test_remote_checkout_streams_to_atomic_local_copy(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.post(
        "/api/collaboration/peers",
        json={
            "id": "remote",
            "name": "Laptop",
            "base_url": "http://100.80.2.3:5173",
            "token": "remote-secret",
        },
    )
    remote_design = Design(id="remote-project")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer remote-secret"
        assert request.url.path == "/api/collaboration/library/content"
        assert request.url.params["path"] == "shared/Voltron.nadoc"
        return httpx.Response(200, content=remote_design.to_json().encode())

    real_client = httpx.AsyncClient

    def mock_client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(collaboration_routes.httpx, "AsyncClient", mock_client)
    checked_out = client.post(
        "/api/collaboration/peers/remote/library/checkout",
        params={"path": "shared/Voltron.nadoc"},
    )
    assert checked_out.status_code == 200, checked_out.text
    assert checked_out.json()["path"] == "shared/Voltron.nadoc"
    installed = tmp_path / "shared" / "Voltron.nadoc"
    assert Design.from_json(installed.read_text()).id == "remote-project"
    assert not list(installed.parent.glob(".nadoc-checkout-*"))


def test_peer_status_migrates_legacy_tailscale_ip_to_https_magicdns(monkeypatch, tmp_path):
    client = _client(monkeypatch, tmp_path)
    client.post(
        "/api/collaboration/peers",
        json={
            "id": "wsl",
            "name": "WSL Desktop",
            "base_url": "http://100.99.71.2:5173",
            "token": "remote-secret",
        },
    )
    monkeypatch.setattr(
        collaboration_routes.socket,
        "gethostbyaddr",
        lambda _address: ("desktop.example.ts.net.", [], []),
    )
    real_client = httpx.AsyncClient

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "100.99.71.2" or request.url.scheme != "https":
            return httpx.Response(404)
        return httpx.Response(200, json={"server_id": "wsl"})

    def mock_client(**kwargs):
        return real_client(transport=httpx.MockTransport(handler), **kwargs)

    monkeypatch.setattr(collaboration_routes.httpx, "AsyncClient", mock_client)
    status = client.get("/api/collaboration/peers/status")
    assert status.status_code == 200
    assert status.json()["peers"][0] == {
        "id": "wsl",
        "name": "WSL Desktop",
        "base_url": "https://desktop.example.ts.net:5173",
        "online": True,
    }
    assert client.get("/api/collaboration/peers").json()["peers"][0][
        "base_url"
    ] == "https://desktop.example.ts.net:5173"
