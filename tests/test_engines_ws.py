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

import pytest
from fastapi.testclient import TestClient

import backend.core.engines as engines
import backend.core.fs_browse as fs_browse
from backend.api.main import app


@pytest.fixture(scope="module")
def lifespan_client():
    """One lifespan-started ``TestClient`` for the whole module.

    ``with TestClient(app)`` runs the *entire* app lifespan (workspace scan,
    session-cache restore, MD-supervisor task) — ~0.5–1.5 s.  Function-scoped it
    multiplies by test count for no isolation benefit: these tests read
    ``/api/engines/status`` and ``/api/engines/browse``, which hold no per-client
    state (their inputs come from monkeypatched probes / env vars, applied
    per-test).  Module-scoped, the lifespan is paid once.
    """
    with TestClient(app) as client:
        yield client


@pytest.fixture
def stub_host_probes(monkeypatch):
    """Pin the host probes so ``engines_status()`` runs entirely in-process.

    The real probe is *slow on WSL*: one ``engines_status()`` fires ~39
    ``shutil.which`` calls — each walking the whole Windows PATH over the
    ``/mnt/c`` drvfs mount (~950 ``stat`` syscalls) — plus six subprocess spawns
    (``nvidia-smi`` ×2, a real ``mpicxx -E`` C++ preprocess, ``lmp -h`` …).  That
    is ~3–5 s **per request**, and it measures this laptop, not the code.

    These tests are about the *aggregation* and about ``NADOC_ENGINES_FORCE_MISSING``
    reaching the route — so we pin the probes exactly as ``test_engines.py::_patch_all``
    already does for the same function.  Pinning every engine *found* also sharpens
    the assertions: FORCE_MISSING now has to override a **located** binary rather
    than merely agree with an absent one.
    """
    for name, path in (
        ("find_oxdna", "/o/oxDNA"),
        ("find_oxdna_anm", "/a/oxDNA"),
        ("find_dnanalysis", "/o/DNAnalysis"),
        ("find_namd", "/n/namd3"),
        ("find_gmx", "/g/gmx"),
        ("find_psfgen", "/n/psfgen"),
        ("find_lammps", "/l/lmp"),
        ("find_mrdna", "/m/mrdna"),
        ("find_arbd", "/b/arbd"),
    ):
        monkeypatch.setattr(engines, name, lambda p=path: p)
    monkeypatch.setattr(
        engines.hardware,
        "enumerate_cuda_devices",
        lambda: [{"index": 0, "name": "RTX 2080", "uuid": "GPU-x"}],
    )
    monkeypatch.setattr(engines, "_gpu_arch", lambda: "75")
    monkeypatch.setattr(engines, "_mpi_build_usable", lambda: True)
    monkeypatch.setattr(engines, "lammps_supports_cgdna", lambda _p: True)
    monkeypatch.setattr(engines.shutil, "which", lambda c: "/usr/bin/" + c)


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


def test_status_endpoint_reflects_simulation(
    monkeypatch, stub_host_probes, lifespan_client
):
    monkeypatch.setenv("NADOC_ENGINES_FORCE_MISSING", "oxdna,namd")
    st = lifespan_client.get("/api/engines/status").json()
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


def test_browse_endpoint_lists_a_directory(tmp_path, lifespan_client):
    # a folder with a subdir and a file → the navigator shape
    (tmp_path / "sub").mkdir()
    (tmp_path / "NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz").write_text("x")
    body = lifespan_client.get(
        "/api/engines/browse", params={"path": str(tmp_path), "kind": "namd"}
    ).json()
    assert body["cwd"] == str(tmp_path)
    names = [e["name"] for e in body["entries"]]
    assert "sub" in names and "NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz" in names
    namd = next(e for e in body["entries"] if e["name"].startswith("NAMD_"))
    assert namd["is_dir"] is False and namd["matches"] is True


def test_browse_endpoint_defaults_to_downloads(tmp_path, monkeypatch, lifespan_client):
    # Point the default at a tmp folder instead of the *real* Downloads: on WSL that
    # is the Windows one (`/mnt/c/Users/<you>/Downloads`, 2000+ files) and scandir+stat
    # over the drvfs mount costs ~4 s.  Redirecting it also lets us assert the actual
    # landing folder rather than merely "cwd is truthy".
    (tmp_path / "arbd-may24.tar.gz").write_text("x")
    monkeypatch.setattr(fs_browse, "default_downloads_dir", lambda: str(tmp_path))
    body = lifespan_client.get("/api/engines/browse").json()
    assert body["cwd"] == str(tmp_path)  # opened at the Downloads default
    assert [e["name"] for e in body["entries"]] == ["arbd-may24.tar.gz"]


def test_install_ws_finishes_a_downloaded_namd_archive(tmp_path, monkeypatch):
    """The 'check download & install' round-trip: hand the WS a downloaded tarball
    → it verifies + extracts + reports complete, no NAMD download needed."""
    import backend.core.engine_artifact as art

    home = tmp_path / "home"
    home.mkdir()
    tar = _make_namd_tar(str(tmp_path))
    monkeypatch.setenv("HOME", str(home))
    extracted = str(
        home / "Applications" / "NAMD_3.0.2_Linux-x86_64-multicore-CUDA" / "namd3"
    )
    monkeypatch.setattr(art, "find_namd", lambda: extracted)
    monkeypatch.setattr(art, "find_psfgen", lambda: None)
    monkeypatch.setattr(
        art, "gpu_info", lambda: {"present": True, "names": ["RTX"], "arch": "75"}
    )

    client = TestClient(app)
    with client.websocket_connect("/ws/engines/install") as ws:
        ws.send_json({"engine": "namd", "archive_path": tar})
        types, last = [], None
        for _ in range(50):
            m = ws.receive_json()
            types.append(m["type"])
            last = m
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


# ── mrDNA + ARBD (the coarse-grained pipeline deps) ───────────────────────────


def _make_arbd_tar(dirpath, filename="arbd-may24-beta.tar.gz"):
    payload = os.path.join(dirpath, "_ap")
    os.makedirs(payload, exist_ok=True)
    f = os.path.join(payload, "CMakeLists.txt")
    with open(f, "w") as fh:
        fh.write("project(arbd)")
    tar_path = os.path.join(dirpath, filename)
    with tarfile.open(tar_path, "w:gz") as tar:
        tar.add(f, arcname="arbd-may24-beta/CMakeLists.txt")
    return tar_path


def test_status_lists_mrdna_arbd_cuda_rows(stub_host_probes, lifespan_client):
    st = lifespan_client.get("/api/engines/status").json()
    for key in ("mrdna", "arbd", "cuda"):
        assert key in st["engines"], key


def test_install_ws_mrdna_simulated_streams_progress_then_error(monkeypatch):
    monkeypatch.setenv("NADOC_ENGINES_FORCE_MISSING", "mrdna")
    client = TestClient(app)
    with client.websocket_connect("/ws/engines/install") as ws:
        ws.send_json({"engine": "mrdna"})
        types, last = [], None
        for _ in range(20):
            m = ws.receive_json()
            types.append(m["type"])
            last = m
            if m["type"] == "error":
                break
    assert "progress" in types
    assert last["type"] == "error" and "Simulation mode" in last["message"]


def test_install_ws_finishes_built_arbd_no_password(tmp_path, monkeypatch):
    """The no-password finish: hand the WS install_built → copies the built binary
    onto PATH and reports complete, no sudo needed."""
    import backend.core.mrdna_bridge as mb

    home = tmp_path / "home"
    (home / ".local").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    built = tmp_path / "build" / "arbd"
    built.parent.mkdir()
    built.write_text("x")
    os.chmod(built, 0o755)
    monkeypatch.setattr(mb, "find_arbd_build", lambda: str(built))
    dest = str(home / ".local" / "bin" / "arbd")
    monkeypatch.setattr(mb, "find_arbd", lambda: dest if os.path.isfile(dest) else None)

    client = TestClient(app)
    with client.websocket_connect("/ws/engines/install") as ws:
        ws.send_json({"engine": "arbd", "install_built": True})
        last = None
        for _ in range(30):
            m = ws.receive_json()
            if m["type"] in ("complete", "error"):
                last = m
                break
    assert last["type"] == "complete", last
    assert os.path.isfile(dest)


def test_install_ws_sudo_rejects_empty_password(tmp_path, monkeypatch):
    import backend.core.mrdna_bridge as mb

    built = tmp_path / "build" / "arbd"
    built.parent.mkdir(parents=True)
    built.write_text("x")
    monkeypatch.setattr(mb, "find_arbd_build", lambda: str(built))
    client = TestClient(app)
    with client.websocket_connect("/ws/engines/install") as ws:
        ws.send_json({"engine": "arbd", "sudo_install": True, "password": ""})
        m = ws.receive_json()
        while m["type"] not in ("error", "complete"):
            m = ws.receive_json()
    assert m["type"] == "error" and "password" in m["message"].lower()


def test_install_ws_builds_downloaded_arbd_and_asks_for_sudo(tmp_path, monkeypatch):
    """ARBD 'check download & install': hand the WS a source tarball → it verifies,
    unpacks, 'builds' (cmake/make stubbed), and asks for the one sudo line."""
    import backend.core.engine_artifact as art

    home = tmp_path / "home"
    home.mkdir()
    tar = _make_arbd_tar(str(tmp_path))
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(
        art, "gpu_info", lambda: {"present": True, "names": ["RTX"], "arch": "75"}
    )

    async def _ok(argv, cwd, send):
        return 0

    monkeypatch.setattr(art, "_stream_build", _ok)

    client = TestClient(app)
    with client.websocket_connect("/ws/engines/install") as ws:
        ws.send_json({"engine": "arbd", "archive_path": tar})
        types, last = [], None
        for _ in range(50):
            m = ws.receive_json()
            types.append(m["type"])
            last = m
            if m["type"] in ("manual_step", "complete", "error"):
                break
    assert last["type"] == "manual_step", last
    assert "sudo make install" in last["command"]
    assert last["can_finish_built"] is True
    assert "progress" in types
