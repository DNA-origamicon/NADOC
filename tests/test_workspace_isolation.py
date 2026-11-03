"""Server startup must never write audit/session files into the user's workspace."""

import asyncio
import os

import pytest

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


@pytest.fixture(scope="module")
def module_startup_paths(_isolate_module_workspace):
    # Exercise the ordering that used to let a module TestClient use real storage.
    assert main._WORKSPACE_DIR == _isolate_module_workspace
    path = alpine_operations.configure(main._WORKSPACE_DIR)
    alpine_operations.event("module_fixture_startup")
    return path, os.environ["NADOC_WORKSPACE"]


def test_module_startup_precedes_function_overrides_safely(module_startup_paths, _isolate_module_workspace):
    path, workspace_env = module_startup_paths
    assert path == _isolate_module_workspace / "logs" / "alpine_operations.jsonl"
    assert workspace_env == str(_isolate_module_workspace)
    assert '"event": "module_fixture_startup"' in path.read_text()


def test_startup_isolation_closes_handlers_and_restores_globals_after_failure(tmp_path):
    from tests.workspace_isolation import isolated_startup_workspace

    original = (main._WORKSPACE_DIR, assembly._WORKSPACE_DIR, alpine_operations._LOGGER,
                alpine_operations._PATH, os.environ.get("NADOC_WORKSPACE"))
    with pytest.raises(RuntimeError, match="injected"):
        with isolated_startup_workspace(tmp_path):
            path = alpine_operations.configure(tmp_path)
            handler = alpine_operations._LOGGER.handlers[0]
            alpine_operations.event("private_failure")
            raise RuntimeError("injected")
    assert handler.stream is None
    assert '"event": "private_failure"' in path.read_text()
    assert (main._WORKSPACE_DIR, assembly._WORKSPACE_DIR, alpine_operations._LOGGER,
            alpine_operations._PATH, os.environ.get("NADOC_WORKSPACE")) == original
