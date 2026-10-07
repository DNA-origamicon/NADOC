"""Rejected VR work must persist evidence and quarantine an installed scene."""
import json
from pathlib import Path
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from starlette.requests import Request

from backend.api import routes_placement_integrity as integrity, routes_vr as vr
from backend.api import vr_representation_loading as loading, vr_startup
from backend.core.native_full_placement import NativePlacementError
from tests.conftest import make_minimal_design
from tools.native_placement_audit import check_review_gate

pytestmark = pytest.mark.native_placement


@pytest.fixture(autouse=True)
def isolated_runtime(monkeypatch, tmp_path):
    monkeypatch.setenv("NADOC_PLACEMENT_REPORT_DIR", str(tmp_path / "reports"))
    monkeypatch.setattr(vr, "_read_state", lambda: None)
    monkeypatch.setattr(vr.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(vr.design_state, "get_or_404", lambda: make_minimal_design())


def bad_snapshot(_body, *, line_writer, **_kwargs):
    line_writer("unpublished partial geometry")
    raise NativePlacementError("Invalid O5 site", details={"identity": {"helix_id": "h0", "bp_index": 3,
        "direction": "REVERSE"}, "actual": [float("nan"), 0, 0]})


def assert_report_and_quarantine(tmp_path, event, phase):
    incidents = check_review_gate(tmp_path / "reports")
    assert len(incidents) == 1
    report = json.loads(Path(incidents[0]["report"]).read_text())
    assert report["phase"] == phase
    assert report["evidence"]["details"]["identity"]["bp_index"] == 3
    assert report["evidence"]["details"]["actual"] == ["nan", 0, 0]
    assert "bad_snapshot" in report["evidence"]["traceback"]
    signal = Path(str(event) + ".placement-error")
    assert signal.read_text().startswith("NADOCVR_PLACEMENT_ERROR 1 ")
    assert "Invalid O5 site" in signal.read_text()
    assert signal.stat().st_mode & 0o777 == 0o600
    assert not list(tmp_path.glob("nadoc-vr-*.nadocvr.gz"))


def test_startup_worker_records_failure_and_never_publishes_partial_scene(monkeypatch, tmp_path):
    scene, progress, event = (tmp_path / name for name in ("scene", "progress", "event"))
    scene.write_text("empty startup scene")
    monkeypatch.setattr(vr, "_snapshot", bad_snapshot)
    vr_startup.prepare_scene(vr.VRLaunchRequest(), scene, progress, SimpleNamespace(pid=123, poll=lambda: None), event)
    assert scene.read_text() == "empty startup scene"
    assert progress.read_text().startswith("error 0\nInvalid O5 site")
    assert_report_and_quarantine(tmp_path, event, "native-vr-startup")


def test_representation_worker_records_failure_and_retains_previous_complete_snapshot(monkeypatch, tmp_path):
    event = tmp_path / "event"
    Path(str(event) + ".repr-request").write_text("NADOCVR_REP_REQUEST 1 2 full 4\n")
    previous = tmp_path / "complete-scene"
    previous.write_text("previous valid snapshot")
    monkeypatch.setattr(vr, "_snapshot", bad_snapshot)
    monkeypatch.setattr(vr.design_state, "copy_doc_for_persist", lambda _doc: (make_minimal_design(), 4))
    alive = True
    monkeypatch.setattr(loading.time, "sleep", lambda _seconds: stop())
    def stop():
        nonlocal alive
        alive = False
    loading.serve(vr.VRLaunchRequest(), event, SimpleNamespace(poll=lambda: None if alive else 0))
    assert previous.read_text() == "previous valid snapshot"
    assert not Path(str(event) + ".repr-2").exists()
    assert_report_and_quarantine(tmp_path, event, "native-vr-representation")


def test_report_storage_failure_still_quarantines_headset(monkeypatch, tmp_path):
    def fail(*_args, **_kwargs):
        raise OSError("Report disk unavailable")
    monkeypatch.setattr(integrity, "record_failure", fail)
    event = tmp_path / "event"
    result = integrity.record_native_placement_failure(NativePlacementError("Invalid site"), event_path=event)
    assert result["message"] == "Invalid site"
    assert result["report_delivery_error"] == "Report disk unavailable"
    assert Path(str(event) + ".placement-error").exists()


def test_incident_opened_during_export_prevents_completed_candidate_publication(monkeypatch, tmp_path):
    scene, progress, event = (tmp_path / name for name in ("scene", "progress", "event"))
    scene.write_text("empty startup scene")
    def complete_snapshot(_body, *, line_writer, **_kwargs):
        line_writer("complete canonical candidate")
        integrity.record_native_placement_failure(NativePlacementError("Concurrent placement incident"),
            event_path=tmp_path / "other-session")
    monkeypatch.setattr(vr, "_snapshot", complete_snapshot)
    vr_startup.prepare_scene(vr.VRLaunchRequest(), scene, progress, SimpleNamespace(pid=123, poll=lambda: None), event)
    assert scene.read_text() == "empty startup scene"
    assert progress.read_text().startswith("error 0")
    assert Path(str(event) + ".placement-error").exists()
    assert not list(tmp_path.glob("nadoc-vr-*.nadocvr.gz"))
    assert len(check_review_gate(tmp_path / "reports")) == 1


def test_quarantine_delivery_failure_retains_report_and_original_error(monkeypatch, tmp_path):
    result = integrity.record_native_placement_failure(NativePlacementError("Invalid site"),
        event_path=tmp_path / "missing-directory" / "event")
    assert result["message"] == "Invalid site"
    assert "headset_quarantine_delivery_error" in result
    assert len(check_review_gate(tmp_path / "reports")) == 1


def test_pending_review_prevents_relaunch_without_duplicate_incident(monkeypatch, tmp_path):
    integrity.record_native_placement_failure(NativePlacementError("Review me"), event_path=tmp_path / "old-session")
    def forbidden():
        pytest.fail("A pending positioning review must be checked before starting SteamVR")
    monkeypatch.setattr(vr, "_start_steamvr", forbidden)
    request = Request({"type": "http", "client": ("127.0.0.1", 1234), "headers": []})
    with pytest.raises(HTTPException) as error:
        vr.launch_vr(vr.VRLaunchRequest(), request)
    assert error.value.status_code == 503
    assert error.value.detail["code"] == "NATIVE_PLACEMENT_REVIEW_REQUIRED"
    assert len(error.value.detail["incidents"]) == 1
    assert len(check_review_gate(tmp_path / "reports")) == 1


@pytest.mark.parametrize("corrupt", [False, True])
def test_existing_review_or_unreadable_journal_blocks_publication_and_quarantines(monkeypatch, tmp_path, corrupt):
    if corrupt:
        monkeypatch.setattr(integrity, "check_review_gate", lambda: (_ for _ in ()).throw(ValueError("journal corrupt")))
    else:
        integrity.record_native_placement_failure(NativePlacementError("Review me"), event_path=tmp_path / "old")
    event = tmp_path / "current"
    with pytest.raises(HTTPException) as error:
        integrity.require_native_placement_review_clear(event_path=event)
    assert error.value.status_code == 503
    assert Path(str(event) + ".placement-error").exists()


def test_http_failure_only_quarantines_matching_document(monkeypatch, tmp_path):
    event = tmp_path / "event"
    monkeypatch.setattr(vr, "_read_state", lambda: {"doc_id": "open-doc", "event_path": str(event)})
    def request(doc):
        return Request({"type": "http", "path": "/api/vr/scene-refresh", "headers": [(b"x-nadoc-doc", doc.encode())]})
    error = NativePlacementError("Invalid site")
    integrity.record_native_placement_failure(error, request=request("different-doc"))
    assert not Path(str(event) + ".placement-error").exists()
    integrity.record_native_placement_failure(error, request=request("open-doc"))
    assert Path(str(event) + ".placement-error").exists()


def test_native_headset_quarantine_latch_is_irreversible_within_one_session(tmp_path):
    """The same C++ state used by the renderer participates in the review gate."""
    root = Path(__file__).resolve().parents[1]
    executable = tmp_path / "placement-integrity-test"
    subprocess.run(["/usr/bin/g++", "-std=c++20", "-UNDEBUG", "-I", str(root / "native/vr_viewer/src"),
        str(root / "native/vr_viewer/tests/placement_integrity_test.cpp"), "-o", str(executable)],
        check=True, capture_output=True, text=True, timeout=30)
    subprocess.run([str(executable)], check=True, capture_output=True, text=True, timeout=10)


@pytest.mark.parametrize("transport", ["query", "bound_context"])
def test_failure_report_and_quarantine_use_query_or_bound_document(monkeypatch, tmp_path, transport):
    from backend.api.doc_context import set_current_doc, reset_current_doc
    event = tmp_path / "event"
    monkeypatch.setattr(vr, "_read_state", lambda: {"doc_id": "open-doc", "event_path": str(event)})
    request = Request({"type": "http", "path": "/api/vr/scene-refresh", "headers": [],
        "query_string": b"doc=open-doc" if transport == "query" else b""})
    token = set_current_doc("open-doc" if transport == "bound_context" else "other-doc")
    try:
        integrity.record_native_placement_failure(NativePlacementError("Invalid site"), request=request)
    finally:
        reset_current_doc(token)
    report = json.loads(Path(check_review_gate(tmp_path / "reports")[0]["report"]).read_text())
    assert report["evidence"]["document_id"] == "open-doc"
    assert Path(str(event) + ".placement-error").exists()


@pytest.mark.parametrize("failure", [None, "other_document", "other_event", "changed_session", "wrong_process", "signal_denied"])
def test_unwritable_quarantine_only_stops_verified_matching_viewer(monkeypatch, tmp_path, failure):
    import os
    import signal
    from backend.api.doc_context import get_current_doc
    event = tmp_path / "event"
    session = {"pid": 123, "doc_id": get_current_doc(), "event_path": str(event)}
    if failure == "other_document":
        session["doc_id"] = "unrelated-doc"
    if failure == "other_event":
        session["event_path"] = str(tmp_path / "other-session")
    calls = []
    reads = iter([session, {**session, "pid": 456}] if failure == "changed_session" else [session, session])
    monkeypatch.setattr(vr, "_read_state", lambda: next(reads))
    def cannot_write(*_args, **_kwargs):
        raise OSError("quarantine disk unavailable")
    monkeypatch.setattr(integrity, "_quarantine_native_viewer", cannot_write)
    monkeypatch.setattr(os, "pidfd_open", lambda pid, flags: calls.append(("open", pid, flags)) or 77)
    monkeypatch.setattr(os, "close", lambda descriptor: calls.append(("close", descriptor)))
    original_read = Path.read_bytes
    def read(path):
        if str(path) == "/proc/123/cmdline":
            return b"viewer\0--events\0" + (b"other-session" if failure == "wrong_process" else str(event).encode()) + b"\0"
        return original_read(path)
    monkeypatch.setattr(Path, "read_bytes", read)
    def stop(descriptor, number):
        if failure == "signal_denied":
            raise PermissionError("signal denied")
        calls.append(("signal", descriptor, number))
    monkeypatch.setattr(signal, "pidfd_send_signal", stop)
    result = integrity.record_native_placement_failure(NativePlacementError("Original O5 error"), event_path=event)
    assert result["message"] == "Original O5 error"
    assert result["headset_quarantine_delivery_error"] == "quarantine disk unavailable"
    assert any(call[0] == "signal" for call in calls) is (failure is None)
    if failure is None:
        assert ("signal", 77, signal.SIGKILL) in calls
        assert result["headset_stop_status"] == "stopped"
    if failure in ("wrong_process", "signal_denied"):
        assert result["headset_stop_status"] == "unrecoverable"
        assert result["headset_stop_delivery_error"]
    if failure in ("other_document", "other_event"):
        assert calls == []
    report = json.loads(Path(check_review_gate(tmp_path / "reports")[0]["report"]).read_text())
    assert report["evidence"]["headset_stop_status"] == result["headset_stop_status"]
    assert report["evidence"]["headset_quarantine_delivery_error"] == "quarantine disk unavailable"
