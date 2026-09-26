"""Server startup must never write audit/session files into the user's workspace."""

import asyncio

from fastapi.testclient import TestClient

from backend.api import assembly, main, routes_runpod
from backend.core import alpine_operations, surface_acceleration


def test_startup_writes_only_to_the_isolated_workspace(monkeypatch):
    warmed = []
    monkeypatch.setattr(
        surface_acceleration,
        "initialize_surface_cuda",
        lambda: warmed.append(True) or True,
    )

    async def no_remote_operation():
        pass

    async def idle_supervisor():
        await asyncio.Event().wait()

    monkeypatch.setattr(routes_runpod, "autoconnect", no_remote_operation)
    monkeypatch.setattr(main, "_terminate_runpod_pods", no_remote_operation)
    monkeypatch.setattr(main, "_begin_runpod_reload_handoff", lambda: False)
    monkeypatch.setattr(main, "_md_supervisor_loop", idle_supervisor)

    with TestClient(main.app):
        # GPU startup completes before the app accepts requests.
        assert warmed == [True]
        audit = alpine_operations.log_path()
        assert audit == assembly._WORKSPACE_DIR / "logs" / "alpine_operations.jsonl"
        alpine_operations.event("isolated_test_startup")
        assert '"event": "isolated_test_startup"' in audit.read_text()
        assert (assembly._WORKSPACE_DIR / "md_jobs").is_dir()
