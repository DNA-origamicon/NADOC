"""End-to-end WebSocket test of the install button — no fresh VM, no compile.

Uses the `NADOC_ENGINES_FORCE_MISSING` simulation switch so the auto-build path
runs its dry-run: the `/ws/engines/install` handler streams real progress frames
and then declines, exactly as the browser button would, exercising the whole
round-trip (request validation → run_install → progress → fall-back signal)
through the actual FastAPI app.
"""

from __future__ import annotations

import os
import tarfile

from fastapi.testclient import TestClient

from backend.api.main import app


def _make_namd_tar(dirpath, filename="NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz"):
    payload = os.path.join(dirpath, "_p")
    os.makedirs(payload, exist_ok=True)
    f = os.path.join(payload, "namd3")
    with open(f, "w") as fh:
        fh.write("x")
    tar_path = os.path.join(dirpath, filename)
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(f, arcname="NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3")
    return tar_path


def test_status_endpoint_reflects_simulation(monkeypatch):
    monkeypatch.setenv("NADOC_ENGINES_FORCE_MISSING", "oxdna,namd")
    with TestClient(app) as client:
        st = client.get("/api/engines/status").json()
    assert st["engines"]["oxdna"]["installed"] is False
    assert st["engines"]["oxdna"]["simulated"] is True
    assert st["sections"]["oxdna"]["ready"] is False
    assert "namd" in st["sections"]["md"]["missing"]


def test_install_ws_simulated_streams_progress_then_error(monkeypatch):
    monkeypatch.setenv("NADOC_ENGINES_FORCE_MISSING", "oxdna")
    client = TestClient(app)
    with client.websocket_connect("/ws/engines/install") as ws:
        ws.send_json({"engine": "oxdna"})
        types, last = [], None
        for _ in range(20):
            msg = ws.receive_json()
            types.append(msg["type"])
            last = msg
            if msg["type"] == "error":
                break
    assert "progress" in types
    assert last["type"] == "error"
    assert "Simulation mode" in last["message"]


def test_install_ws_rejects_non_installable_engine():
    client = TestClient(app)
    with client.websocket_connect("/ws/engines/install") as ws:
        ws.send_json({"engine": "namd"})  # download-only, no archive → can't build
        msg = ws.receive_json()
    assert msg["type"] == "error"
    assert "auto-install" in msg["message"]


def test_scan_namd_download_endpoint_shape():
    with TestClient(app) as client:
        body = client.get("/api/engines/namd/scan-download").json()
    assert "candidates" in body and isinstance(body["candidates"], list)
    assert "best" in body


def test_install_ws_finishes_a_downloaded_namd_archive(tmp_path, monkeypatch):
    """The 'check download & install' round-trip: hand the WS a downloaded tarball
    → it verifies + extracts + reports complete, no NAMD download needed."""
    import backend.core.engine_artifact as art
    home = tmp_path / "home"; home.mkdir()
    tar = _make_namd_tar(str(tmp_path))
    monkeypatch.setenv("HOME", str(home))
    extracted = str(home / "Applications" / "NAMD_3.0.2_Linux-x86_64-multicore-CUDA" / "namd3")
    monkeypatch.setattr(art, "find_namd", lambda: extracted)
    monkeypatch.setattr(art, "find_psfgen", lambda: None)
    monkeypatch.setattr(art, "gpu_info", lambda: {"present": True, "names": ["RTX"], "arch": "75"})

    client = TestClient(app)
    with client.websocket_connect("/ws/engines/install") as ws:
        ws.send_json({"engine": "namd", "archive_path": tar})
        types, last = [], None
        for _ in range(50):
            m = ws.receive_json(); types.append(m["type"]); last = m
            if m["type"] in ("complete", "error"):
                break
    assert last["type"] == "complete", last
    assert last["path"] == extracted
    assert "progress" in types
    assert os.path.isfile(extracted)


def test_install_ws_rejects_archive_for_non_namd():
    client = TestClient(app)
    with client.websocket_connect("/ws/engines/install") as ws:
        ws.send_json({"engine": "oxdna", "archive_path": "/x/NAMD.tar.gz"})
        msg = ws.receive_json()
    assert msg["type"] == "error"
