"""Normal-launch recorder wiring without a runtime, GPU, or document mutation."""
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.api import vr_capture_launch as capture


@pytest.fixture
def configuration(monkeypatch, tmp_path):
    mount = tmp_path/"archive"
    mount.mkdir()
    layer = mount/"layer"
    layer.mkdir()
    library = layer/"capture.so"
    library.write_bytes(b"pinned test library")
    (layer/"VkLayer_NADOC_present_capture.json").write_text(json.dumps({"layer": {
        "name": "VK_LAYER_NADOC_present_capture", "library_path": library.name}}))
    active = mount/"existing-compositor"
    active.mkdir()
    data = {"schema": 1, "archive_mount": str(mount), "storage_root": str(mount/"recordings"),
            "socket_root": str(mount/"s"), "layer_directory": str(layer),
            "layer_library_sha256": hashlib.sha256(library.read_bytes()).hexdigest(),
            "active_capture_directory": str(active)}
    path = tmp_path/"config.json"
    path.write_text(json.dumps(data))
    path.chmod(0o600)
    monkeypatch.setenv("NADOC_VR_CAPTURE_CONFIG", str(path))
    monkeypatch.setattr(capture.os.path, "ismount", lambda p: Path(p) == mount)
    # pytest's descriptive temporary paths exceed sockaddr_un on some hosts.
    # These tests don't bind a socket; the real limit has a separate rejection test.
    monkeypatch.setattr(capture, "_UNIX_SOCKET_PATH_BYTES", 4096)
    return path, data


def test_absent_config_preserves_portable_eye_recorder(monkeypatch, tmp_path):
    monkeypatch.setenv("NADOC_VR_CAPTURE_CONFIG", str(tmp_path/"absent"))
    assert capture.load_config() is None


def test_build_path_uses_default_without_config_and_explicit_environment_first(configuration, monkeypatch):
    path, data = configuration
    default = Path("/repo/native/vr_viewer/build")
    monkeypatch.delenv("NADOC_VR_BUILD_DIR", raising=False)
    assert capture.select_build_directory(default, None) == default
    data["viewer_build_directory"] = str(Path(data["archive_mount"])/"viewer-build")
    path.write_text(json.dumps(data))
    config = capture.load_config()
    assert capture.select_build_directory(default, config) == Path(data["viewer_build_directory"])
    monkeypatch.setenv("NADOC_VR_BUILD_DIR", str(Path(data["archive_mount"])/"explicit"))
    assert capture.select_build_directory(default, config).name == "explicit"


def test_viewer_build_must_remain_on_archive(configuration):
    path, data = configuration
    path.write_text(json.dumps({**data, "viewer_build_directory": "/tmp/ssd-build"}))
    with pytest.raises(capture.CaptureSetupError, match="outside mounted Archive"):
        capture.load_config()


def test_new_build_defaults_to_ninja_and_existing_makefiles_are_respected(tmp_path):
    assert capture.cmake_generator(tmp_path) == "Ninja"
    cache = tmp_path/"CMakeCache.txt"
    cache.write_text("CMAKE_GENERATOR:INTERNAL=Unix Makefiles\n")
    assert capture.cmake_generator(tmp_path) == "Unix Makefiles"
    cache.write_text("CMAKE_GENERATOR:INTERNAL=Ninja\n")
    assert capture.cmake_generator(tmp_path) == "Ninja"


@pytest.mark.parametrize("cache", ["", "CMAKE_GENERATOR:INTERNAL=Unknown\n", "CMAKE_GENERATOR:INTERNAL=Ninja\nCMAKE_GENERATOR:INTERNAL=Unix Makefiles\n"])
def test_unknown_or_ambiguous_build_generator_fails_clearly(tmp_path, cache):
    (tmp_path/"CMakeCache.txt").write_text(cache)
    with pytest.raises(capture.CaptureSetupError, match="Ninja or Unix Makefiles"):
        capture.cmake_generator(tmp_path)


def test_automatic_rebuild_uses_existing_makefiles_cache(monkeypatch, tmp_path):
    from backend.api import routes_vr
    source, build = tmp_path/"source", tmp_path/"build"
    (source/"src").mkdir(parents=True)
    (source/"CMakeLists.txt").write_text("")
    build.mkdir()
    (build/"CMakeCache.txt").write_text("CMAKE_GENERATOR:INTERNAL=Unix Makefiles\n")
    viewer = build/"nadoc-vr-viewer"
    monkeypatch.setattr(routes_vr, "_VIEWER_DIR", source)
    monkeypatch.setattr(routes_vr, "_BUILD_DIR", build)
    monkeypatch.setattr(routes_vr, "_VIEWER", viewer)
    commands = []
    def run(command, **kwargs):
        commands.append(command)
        if "--build" in command:
            viewer.write_text("binary")
        return SimpleNamespace(returncode=0, stderr="")
    monkeypatch.setattr(routes_vr.subprocess, "run", run)
    routes_vr._ensure_viewer_built()
    assert commands[0][commands[0].index("-G")+1] == "Unix Makefiles"
    assert commands[1][-4:] == ["--target", "nadoc-vr-viewer", "--parallel", "1"]


def test_owner_configured_presentation_restore_is_optional(configuration, monkeypatch):
    path, data = configuration
    monkeypatch.setattr(capture, "readiness", lambda _: {})
    assert "--presentation-state" not in capture.prepare_viewer(capture.load_config()).arguments()
    restore = Path(data["archive_mount"])/"presentation.txt"
    restore.write_text("native validates the presentation matrix")
    restore.chmod(0o600)
    path.write_text(json.dumps({**data, "restore_presentation_file": str(restore)}))
    args = capture.prepare_viewer(capture.load_config()).arguments()
    assert args[args.index("--presentation-state")+1] == str(restore)


@pytest.mark.parametrize("invalid", ["symlink", "writable", "large", "outside"])
def test_presentation_restore_rejects_unsafe_file(configuration, invalid):
    path, data = configuration
    restore = Path(data["archive_mount"])/"presentation.txt"
    restore.write_text("matrix")
    restore.chmod(0o600)
    if invalid == "symlink":
        alias = restore.with_name("alias.txt")
        alias.symlink_to(restore)
        restore = alias
    elif invalid == "writable":
        restore.chmod(0o666)
    elif invalid == "large":
        restore.write_bytes(b"x"*16385)
    else:
        restore = path.parent/"outside.txt"
        restore.write_text("matrix")
    path.write_text(json.dumps({**data, "restore_presentation_file": str(restore)}))
    with pytest.raises(capture.CaptureSetupError, match="presentation restore"):
        capture.load_config()


def test_configured_final_mode_uses_private_archive_socket_and_journal(configuration, monkeypatch):
    from tools.vr_capture import viewer_record
    monkeypatch.setattr(viewer_record, "locate_layer", lambda p: (p/"events.jsonl", {"pid": 123}))
    config = capture.load_config()
    first = capture.prepare_viewer(config)
    second = capture.prepare_viewer(config)
    assert first.socket != second.socket
    assert first.socket.parent.stat().st_mode & 0o777 == 0o700
    assert first.journal_directory.stat().st_mode & 0o777 == 0o700
    assert first.socket.is_relative_to(config.archive_mount)
    assert first.journal_directory.is_relative_to(config.archive_mount)
    assert first.arguments() == ["--pose-journal", str(first.journal_directory),
                                 "--submitted-frame-marker", "recording"]
    env = first.environment({"DISPLAY": ":9", "NADOC_VR_COMPOSITOR_CAPTURE_DIR": "stale"})
    assert env["NADOC_VR_COMPOSITOR_CAPTURE_DIR"] == str(config.active_capture_directory)
    assert env["TMPDIR"] == str(first.temporary_directory)
    assert env["DISPLAY"] == ":9"
    assert first.status["available"] is True


def test_backend_snapshot_storage_is_explicit_and_archive_first(configuration):
    from backend.api import routes_vr
    import numpy as np
    config = capture.load_config()
    body = routes_vr.VRLaunchRequest()
    files = [routes_vr._write_scene_snapshot("NADOCVR 14 full strand\nQ empty_authoring\nR full\n"),
             routes_vr._write_job_snapshot([]),
             routes_vr._write_visualization_snapshot([], mode="none", view_rotation=np.eye(3)),
             *routes_vr._write_trajectory_feeds(body, np.eye(3))]
    expected = config.storage_root/"backend-tmp"
    assert all(path.parent == expected and path.is_file() for path in files)
    assert expected.stat().st_mode & 0o777 == 0o700
    assert capture.backend_temporary_directory(None) is None


def test_uninstrumented_runtime_is_explicit_and_never_falls_back(configuration, monkeypatch):
    from tools.vr_capture import viewer_record
    def unavailable(_):
        raise RuntimeError("No unique live compositor capture layer")
    monkeypatch.setattr(viewer_record, "locate_layer", unavailable)
    launch = capture.prepare_viewer(capture.load_config())
    assert launch.status["configured"] and not launch.status["available"]
    assert "Close SteamVR normally" in launch.status["reason"]
    assert "NADOC_VR_COMPOSITOR_CAPTURE_DIR" in launch.environment({})
    assert "recording" in launch.arguments()


@pytest.mark.parametrize("change,error", [
    ({"schema": 99}, "schema"),
    ({"storage_root": "/tmp/not-archive"}, "outside mounted Archive"),
    ({"layer_library_sha256": "0"*64}, "differs"),
    ({"layer_library_sha256": "not a hash"}, "SHA256"),
])
def test_invalid_config_fails_without_portable_fallback(configuration, change, error):
    path, data = configuration
    path.write_text(json.dumps({**data, **change}))
    with pytest.raises(capture.CaptureSetupError, match=error):
        capture.load_config()


def test_missing_mount_rejected(configuration, monkeypatch):
    monkeypatch.setattr(capture.os.path, "ismount", lambda _: False)
    with pytest.raises(capture.CaptureSetupError, match="not mounted"):
        capture.load_config()


def test_config_group_writable_or_symlink_rejected(configuration, monkeypatch):
    path, _ = configuration
    path.chmod(0o660)
    with pytest.raises(capture.CaptureSetupError, match="owner-controlled"):
        capture.load_config()
    path.chmod(0o600)
    alias = path.with_name("alias.json")
    alias.symlink_to(path)
    monkeypatch.setenv("NADOC_VR_CAPTURE_CONFIG", str(alias))
    with pytest.raises(capture.CaptureSetupError, match="owner-controlled"):
        capture.load_config()


def test_nonprivate_socket_directory_rejected(configuration):
    _, data = configuration
    sockets = Path(data["socket_root"])
    sockets.mkdir(mode=0o755)
    with pytest.raises(capture.CaptureSetupError, match="private"):
        capture.load_config()


def test_unix_socket_path_limit_checked_before_launch(configuration, monkeypatch):
    monkeypatch.setattr(capture, "_UNIX_SOCKET_PATH_BYTES", 24)
    with pytest.raises(capture.CaptureSetupError, match="too long"):
        capture.load_config()


def test_runtime_restart_uses_pinned_layer_and_updates_pointer(configuration, monkeypatch):
    from tools.vr_capture import launch_compositor
    config = capture.load_config()
    calls = []
    monkeypatch.setattr(launch_compositor, "process_ids", lambda _: [])
    def start(output, layer, *, mode):
        calls.append((output, layer, mode))
        (output/"compositor").mkdir(parents=True)
    monkeypatch.setattr(launch_compositor, "launch_stack", start)
    assert capture.start_runtime_if_stopped(config)
    assert len(calls) == 1 and calls[0][1:] == (config.layer_directory, "pixels")
    assert capture.capture_directory(config) == calls[0][0]/"compositor"
    assert (config.storage_root/"active-runtime.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize("name", ["vrserver", "vrcompositor", "vrmonitor"])
def test_never_replaces_any_active_runtime_process(configuration, monkeypatch, name):
    from tools.vr_capture import launch_compositor
    config = capture.load_config()
    monkeypatch.setattr(launch_compositor, "process_ids", lambda p: [123] if p == name else [])
    def forbidden(*a, **kw):
        raise AssertionError("Existing runtime must not be replaced")
    monkeypatch.setattr(launch_compositor, "launch_stack", forbidden)
    assert capture.start_runtime_if_stopped(config) is False
    assert capture.capture_directory(config) == config.active_capture_directory


def test_configured_ready_runtime_reused_without_steam_or_replacement(configuration, monkeypatch):
    from backend.api import routes_vr
    ready = {"steamvr_running": True, "dashboard_running": False,
             "desktop_overlay_running": False, "native_desktop_available": True}
    monkeypatch.setattr(routes_vr, "_runtime_payload", lambda: ready)
    monkeypatch.setattr(routes_vr, "_detach_hmd_from_desktop", lambda: None)
    def forbidden(*a, **kw):
        raise AssertionError("Existing runtime must not be changed")
    monkeypatch.setattr(capture, "start_runtime_if_stopped", forbidden)
    monkeypatch.setattr(routes_vr.subprocess, "Popen", forbidden)
    assert routes_vr._start_steamvr() == ready


def test_configured_cold_launch_waits_for_final_recorder(configuration, monkeypatch):
    from backend.api import routes_vr
    stopped = {"steamvr_running": False}
    ready = {"steamvr_running": True}
    observations = iter([stopped, ready])
    monkeypatch.setattr(routes_vr, "_runtime_payload", lambda: next(observations))
    monkeypatch.setattr(routes_vr, "_detach_hmd_from_desktop", lambda: None)
    monkeypatch.setattr(routes_vr, "_assert_vr_display_lease_available", lambda: None)
    calls = []
    monkeypatch.setattr(capture, "start_runtime_if_stopped", lambda config: calls.append(config) or True)
    monkeypatch.setattr(capture, "readiness", lambda config: {"available": True})
    assert routes_vr._start_steamvr() == ready
    assert len(calls) == 1


def test_configured_partial_runtime_returns_actionable_error(configuration, monkeypatch):
    from backend.api import routes_vr
    from fastapi import HTTPException
    monkeypatch.setattr(routes_vr, "_runtime_payload", lambda: {"steamvr_running": False})
    monkeypatch.setattr(routes_vr, "_detach_hmd_from_desktop", lambda: None)
    monkeypatch.setattr(routes_vr, "_assert_vr_display_lease_available", lambda: None)
    monkeypatch.setattr(capture, "start_runtime_if_stopped", lambda config: False)
    with pytest.raises(HTTPException, match="partially running"):
        routes_vr._start_steamvr()


@pytest.mark.parametrize("requested_mode,expected_mode", [("off", "inspect"), ("transactions", "transactions")])
def test_normal_route_enables_coherent_final_recording(configuration, monkeypatch, tmp_path,
                                                       requested_mode, expected_mode):
    from starlette.requests import Request
    from backend.api import routes_vr, vr_dimensions, vr_view_volumes
    from backend.core.models import Design
    from tools.vr_capture import viewer_record
    import tempfile

    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path/"placement-reports"))
    monkeypatch.setattr(routes_vr.design_state, "get_or_404", lambda: Design())
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(routes_vr, "_LOG_PATH", tmp_path/"viewer.log")
    monkeypatch.setattr(routes_vr, "_start_steamvr", lambda: None)
    monkeypatch.setattr(routes_vr, "_ensure_viewer_built", lambda: None)
    monkeypatch.setattr(routes_vr, "_read_state", lambda: None)
    monkeypatch.setattr(routes_vr, "_status_payload", lambda: {"running": True})
    monkeypatch.setattr(routes_vr.time, "sleep", lambda _: None)
    monkeypatch.setattr(viewer_record, "locate_layer", lambda p: (p/"events.jsonl", {"pid": 123}))
    state, spawned = {}, {}
    monkeypatch.setattr(routes_vr, "_write_state", state.update)
    def start(command, **kwargs):
        spawned.update(command=command, **kwargs)
        return SimpleNamespace(pid=123, poll=lambda: None)
    monkeypatch.setattr(routes_vr.subprocess, "Popen", start)
    monkeypatch.setattr("backend.api.vr_lifecycle.track", lambda *a: None)
    monkeypatch.setattr(routes_vr.threading, "Thread", lambda **kw: SimpleNamespace(start=lambda: None))
    for module in (vr_dimensions, vr_view_volumes):
        monkeypatch.setattr(module, "prepare", lambda *a: None)
        monkeypatch.setattr(module, "start", lambda *a: None)
    request = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})
    routes_vr.launch_vr(routes_vr.VRLaunchRequest(scrywrite_live=requested_mode), request)
    command = spawned["command"]
    value = lambda flag: command[command.index(flag)+1]
    assert value("--scrywrite-live-mode") == expected_mode
    assert value("--submitted-frame-marker") == "recording"
    assert value("--pose-journal") == state["pose_journal_directory"]
    assert value("--scrywrite-live") == state["scrywrite_socket"]
    assert state["scrywrite_live"] == expected_mode
    assert state["final_capture"]["available"]
    assert spawned["env"]["NADOC_VR_COMPOSITOR_CAPTURE_DIR"] == state["final_capture"]["directory"]
    for flag in ("--events", "--tool-execution-feedback", "--trajectory", "--coordinates", "--visualization", "--loading-status"):
        assert flag in command
        assert Path(value(flag)).is_relative_to(Path(configuration[1]["storage_root"])/"backend-tmp")
    assert Path(command[1]).is_relative_to(Path(configuration[1]["storage_root"])/"backend-tmp")



def test_active_status_refreshes_bound_capture_readiness_and_retains_launch_snapshot(monkeypatch):
    from backend.api import routes_vr
    snapshot = {"configured": True, "available": True, "directory": "/archive/original-runtime",
                "checked_unix_ns": 1, "compositor_pid": 101}
    state = {"pid": 202, "final_capture": snapshot}
    monkeypatch.setattr(routes_vr, "_native_platform_reason", lambda: None)
    monkeypatch.setattr(routes_vr, "_read_state", lambda: state)
    monkeypatch.setattr(routes_vr, "_runtime_payload", lambda: {})
    monkeypatch.setattr(routes_vr, "_event_payload", lambda _: {})
    monkeypatch.setattr(routes_vr, "_runtime_timing", lambda *_: {})
    calls = []
    current = {"configured": True, "available": False, "directory": snapshot["directory"],
               "checked_unix_ns": 2, "reason": "Layer heartbeat is stale"}

    def probe(path):
        calls.append(path)
        return dict(current)

    monkeypatch.setattr(capture, "directory_readiness", probe)
    first = routes_vr._status_payload()
    assert first["running"] is True
    assert first["final_capture"]["available"] is False
    assert first["final_capture"]["checked_unix_ns"] == 2
    assert first["final_capture_launch_snapshot"] == snapshot
    assert state["final_capture"]["available"] is True
    current.update(available=True, checked_unix_ns=3, reason=None)
    second = routes_vr._status_payload()
    assert second["final_capture"]["available"] is True
    assert second["final_capture"]["checked_unix_ns"] == 3
    assert calls == [Path("/archive/original-runtime")] * 2
    assert second["final_capture_launch_snapshot"]["checked_unix_ns"] == 1


@pytest.mark.parametrize("snapshot", [None, {"configured": False}])
def test_portable_active_status_does_not_probe_capture(monkeypatch, snapshot):
    from backend.api import routes_vr
    monkeypatch.setattr(routes_vr, "_native_platform_reason", lambda: None)
    monkeypatch.setattr(routes_vr, "_read_state", lambda: {"pid": 202, "final_capture": snapshot})
    monkeypatch.setattr(routes_vr, "_runtime_payload", lambda: {})
    monkeypatch.setattr(routes_vr, "_event_payload", lambda _: {})
    monkeypatch.setattr(routes_vr, "_runtime_timing", lambda *_: {})
    monkeypatch.setattr(capture, "directory_readiness", lambda _: pytest.fail("Portable status must not probe capture"))
    result = routes_vr._status_payload()
    assert result["final_capture"] == snapshot


def test_configured_status_missing_bound_directory_reports_unavailable(monkeypatch):
    from backend.api import routes_vr
    monkeypatch.setattr(routes_vr, "_native_platform_reason", lambda: None)
    monkeypatch.setattr(routes_vr, "_read_state", lambda: {
        "pid": 202, "final_capture": {"configured": True, "available": True}})
    monkeypatch.setattr(routes_vr, "_runtime_payload", lambda: {})
    monkeypatch.setattr(routes_vr, "_event_payload", lambda _: {})
    monkeypatch.setattr(routes_vr, "_runtime_timing", lambda *_: {})
    monkeypatch.setattr(capture, "directory_readiness", lambda _: pytest.fail("Missing directory must not probe cwd"))
    result = routes_vr._status_payload()
    assert result["final_capture"]["available"] is False
    assert "no saved capture directory" in result["final_capture"]["reason"]
