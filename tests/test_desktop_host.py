"""Desktop transport and production entry point; no scientific fixtures."""

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from desktop.backend import LocalCapability


def test_desktop_capability_rejects_unrelated_local_clients():
    app = FastAPI()

    @app.get("/")
    def root():
        return {"ok": True}

    client = TestClient(LocalCapability(app, "a" * 64))
    assert client.get("/").status_code == 403
    assert client.get("/", headers={"X-NADOC-Desktop": "wrong"}).status_code == 403
    assert client.get("/", headers={"X-NADOC-Desktop": "a" * 64}).json() == {"ok": True}


def test_desktop_capability_rejects_websocket():
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc:
        with TestClient(LocalCapability(FastAPI(), "a" * 64)).websocket_connect("/ws"):
            pass
    assert exc.value.code == 1008


def test_production_root_serves_installed_index(tmp_path, monkeypatch):
    from backend.api import main

    monkeypatch.setattr(main, "_frontend_dist", str(tmp_path))
    client = TestClient(main.app)
    assert client.get("/", follow_redirects=False).status_code == 307
    (tmp_path / "index.html").write_text("<title>NADOC installed</title>")
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 200
    assert "NADOC installed" in response.text


def test_installed_shared_binding_trusts_only_explicit_target(tmp_path, monkeypatch):
    from desktop.install import configure_shared_library
    from backend.core import workspace_location

    destination = tmp_path / "installed"
    shared = tmp_path / "repository" / "Shared Designs"
    shared.mkdir(parents=True)
    workspace = tmp_path / "external"
    workspace.mkdir()
    (workspace / "Shared Designs").symlink_to(shared, target_is_directory=True)
    monkeypatch.setattr(workspace_location, "PROJECT_ROOT", destination / "resources/payload")
    assert workspace_location.linked_shared_root(workspace) is None
    configure_shared_library(destination, shared)
    assert workspace_location.linked_shared_root(workspace) == shared.resolve()
    with pytest.raises(FileExistsError):
        configure_shared_library(destination, shared)
    (workspace / "Shared Designs").unlink()
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    (workspace / "Shared Designs").symlink_to(unrelated, target_is_directory=True)
    assert workspace_location.linked_shared_root(workspace) is None


def test_installer_prepares_exact_executable_user_namespace_rule(tmp_path):
    import hashlib
    from desktop.install import prepare_linux_sandbox

    destination = tmp_path / "NADOC app"
    destination.mkdir()
    executable = destination / "NADOC"
    executable.touch()
    setup = prepare_linux_sandbox(destination)
    profile = (destination / "nadoc.apparmor").read_text()
    assert f'"{executable}" flags=(unconfined)' in profile
    assert "  userns," in profile
    assert "sysctl" not in setup.read_text()
    assert "--no-sandbox" not in setup.read_text()
    assert hashlib.sha256(str(executable).encode()).hexdigest()[:12] in profile
    bad = tmp_path / "wild*card"
    bad.mkdir()
    (bad / "NADOC").touch()
    with pytest.raises(ValueError):
        prepare_linux_sandbox(bad)
