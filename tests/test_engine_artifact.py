"""Tests for downloaded-artifact verify + install (backend/core/engine_artifact.py).

Pure filename logic is asserted directly.  Validation + extraction are exercised
against REAL fabricated tarballs (one with a `namd3`, one without) so the "is this
the right package?" check and the extract-then-detect flow are genuinely tested —
no NAMD download required.
"""

from __future__ import annotations

import asyncio
import os
import tarfile

import pytest

import backend.core.engine_artifact as art


def _gpu(present, names=None):
    return {"present": present, "names": names or (["RTX 2080"] if present else []), "arch": "75"}


# ── pure filename parsing ─────────────────────────────────────────────────────

def test_parse_cuda_and_cpu_filenames():
    cuda = art.parse_namd_filename("/d/NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz")
    assert cuda["is_cuda"] is True and cuda["multicore"] is True
    cpu = art.parse_namd_filename("NAMD_3.0.2_Linux-x86_64-multicore.tar.gz")
    assert cpu["is_cuda"] is False


def test_parse_rejects_non_namd():
    assert art.parse_namd_filename("oxDNA-source.zip") is None
    assert art.parse_namd_filename("NAMD_macOS.tar.gz") is None


# ── fabricated tarballs ───────────────────────────────────────────────────────

def _make_tar(dirpath, filename, *, inner_names):
    """Create dirpath/filename .tar.gz whose members are inner_names (each a file)."""
    tar_path = os.path.join(dirpath, filename)
    payload = os.path.join(dirpath, "_payload")
    os.makedirs(payload, exist_ok=True)
    with tarfile.open(tar_path, "w:gz") as tar:
        for nm in inner_names:
            f = os.path.join(payload, os.path.basename(nm))
            with open(f, "w") as fh:
                fh.write("x")
            tar.add(f, arcname=nm)
    return tar_path


def test_validate_accepts_archive_with_namd3(tmp_path):
    p = _make_tar(str(tmp_path), "NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz",
                  inner_names=["NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3",
                               "NAMD_3.0.2_Linux-x86_64-multicore-CUDA/psfgen"])
    v = art.validate_namd_archive(p, _gpu(True))
    assert v["valid"] is True
    assert v["contains_namd3"] is True
    assert v["build"] == "CUDA"
    assert v["warning"] == ""           # CUDA build on a GPU box → no warning


def test_validate_warns_cpu_build_on_gpu_box(tmp_path):
    p = _make_tar(str(tmp_path), "NAMD_3.0.2_Linux-x86_64-multicore.tar.gz",
                  inner_names=["NAMD_3.0.2_Linux-x86_64-multicore/namd3"])
    v = art.validate_namd_archive(p, _gpu(True))
    assert v["valid"] is True
    assert "CPU build" in v["warning"]


def test_validate_rejects_archive_without_namd3(tmp_path):
    p = _make_tar(str(tmp_path), "NAMD_3.0.2_Linux-x86_64-multicore.tar.gz",
                  inner_names=["NAMD_3.0.2_Linux-x86_64-multicore/README.txt"])
    v = art.validate_namd_archive(p, _gpu(False))
    assert v["valid"] is False
    assert "namd3" in v["error"]


def test_validate_rejects_wrong_filename(tmp_path):
    p = _make_tar(str(tmp_path), "something_else.tar.gz", inner_names=["x/namd3"])
    # rename check happens before tar read → filename rejection
    v = art.validate_namd_archive(p, _gpu(False))
    assert v["valid"] is False
    assert "NAMD" in v["error"]


def test_validate_missing_file():
    v = art.validate_namd_archive("/no/such/NAMD_3.0.2_Linux-x86_64-multicore.tar.gz", _gpu(False))
    assert v["valid"] is False
    assert "not found" in v["error"].lower()


# ── install (real extraction) ─────────────────────────────────────────────────

class _Rec:
    def __init__(self): self.msgs = []
    async def __call__(self, m): self.msgs.append(m)


def test_install_extracts_and_detects(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    p = _make_tar(str(tmp_path), "NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz",
                  inner_names=["NAMD_3.0.2_Linux-x86_64-multicore-CUDA/namd3"])
    # point ~ at a temp HOME so ~/Applications extracts into the sandbox
    monkeypatch.setenv("HOME", str(home))
    extracted = str(home / "Applications" / "NAMD_3.0.2_Linux-x86_64-multicore-CUDA" / "namd3")
    monkeypatch.setattr(art, "find_namd", lambda: extracted)
    monkeypatch.setattr(art, "find_psfgen", lambda: None)
    monkeypatch.setattr(art, "gpu_info", lambda: _gpu(True))

    rec = _Rec()
    out = asyncio.run(art.install_namd_archive(p, rec))
    assert out == extracted
    assert os.path.isfile(extracted)                       # really extracted
    assert rec.msgs[-1]["type"] == "complete"
    assert any(m["type"] == "progress" and m["pct"] == 100 for m in rec.msgs)


def test_install_raises_on_bad_archive(tmp_path, monkeypatch):
    p = _make_tar(str(tmp_path), "NAMD_3.0.2_Linux-x86_64-multicore.tar.gz", inner_names=["a/README"])
    monkeypatch.setattr(art, "gpu_info", lambda: _gpu(False))
    with pytest.raises(art.ArtifactError):
        asyncio.run(art.install_namd_archive(p, _Rec()))


# ── ARBD (source tarball → build; sudo install stays manual) ──────────────────

def test_parse_arbd_filename_accepts_and_rejects():
    assert art.parse_arbd_filename("/d/arbd-may24-beta.tar.gz")["filename"] == "arbd-may24-beta.tar.gz"
    assert art.parse_arbd_filename("arbd-2024.tar.xz") is not None
    assert art.parse_arbd_filename("NAMD_3.0.2_Linux-x86_64-multicore.tar.gz") is None
    assert art.parse_arbd_filename("not-arbd.zip") is None


def test_validate_arbd_accepts_source_with_cmakelists(tmp_path):
    p = _make_tar(str(tmp_path), "arbd-may24-beta.tar.gz",
                  inner_names=["arbd-may24-beta/CMakeLists.txt", "arbd-may24-beta/src/main.cpp"])
    v = art.validate_arbd_archive(p, _gpu(True))
    assert v["valid"] is True and v["is_source"] is True
    assert v["warning"] == ""                              # GPU present → no warning


def test_validate_arbd_warns_without_gpu(tmp_path):
    p = _make_tar(str(tmp_path), "arbd-may24-beta.tar.gz", inner_names=["arbd/CMakeLists.txt"])
    v = art.validate_arbd_archive(p, _gpu(False))
    assert v["valid"] is True
    assert "GPU" in v["warning"]


def test_validate_arbd_rejects_non_source(tmp_path):
    p = _make_tar(str(tmp_path), "arbd-blob.tar.gz", inner_names=["arbd-blob/README.txt"])
    v = art.validate_arbd_archive(p, _gpu(True))
    assert v["valid"] is False
    assert "CMakeLists" in v["error"]


def test_validate_arbd_rejects_wrong_filename(tmp_path):
    p = _make_tar(str(tmp_path), "engine.tar.gz", inner_names=["x/CMakeLists.txt"])
    v = art.validate_arbd_archive(p, _gpu(True))
    assert v["valid"] is False
    assert "ARBD" in v["error"]


def test_install_arbd_extracts_builds_and_emits_manual_step(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    p = _make_tar(str(tmp_path), "arbd-may24-beta.tar.gz",
                  inner_names=["arbd-may24-beta/CMakeLists.txt", "arbd-may24-beta/src/main.cpp"])
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(art, "gpu_info", lambda: _gpu(True))
    # don't actually run cmake/make — pretend both succeed
    async def _ok(argv, cwd, send):
        await send({"type": "log", "line": " ".join(argv)})
        return 0
    monkeypatch.setattr(art, "_stream_build", _ok)

    rec = _Rec()
    asyncio.run(art.install_arbd_archive(p, rec))
    # source really unpacked with the top-level dir stripped
    assert os.path.isfile(str(home / "arbd-src" / "CMakeLists.txt"))
    last = rec.msgs[-1]
    assert last["type"] == "manual_step"
    assert "sudo make install" in last["command"]
    assert last["can_finish_built"] is True          # no-password finish also offered
    assert "sudo make install" in last["note"]


def test_install_arbd_raises_when_cmake_fails(tmp_path, monkeypatch):
    home = tmp_path / "home"
    home.mkdir()
    p = _make_tar(str(tmp_path), "arbd-may24-beta.tar.gz", inner_names=["arbd-may24-beta/CMakeLists.txt"])
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(art, "gpu_info", lambda: _gpu(True))
    async def _fail(argv, cwd, send):
        return 1
    monkeypatch.setattr(art, "_stream_build", _fail)
    with pytest.raises(art.ArtifactError):
        asyncio.run(art.install_arbd_archive(p, _Rec()))


def test_install_arbd_raises_on_bad_archive(tmp_path, monkeypatch):
    p = _make_tar(str(tmp_path), "arbd-blob.tar.gz", inner_names=["a/README"])
    monkeypatch.setattr(art, "gpu_info", lambda: _gpu(True))
    with pytest.raises(art.ArtifactError):
        asyncio.run(art.install_arbd_archive(p, _Rec()))


# ── ARBD no-password finish (copy the built Linux binary onto PATH) ────────────

def test_install_arbd_binary_copies_built_onto_path(tmp_path, monkeypatch):
    import backend.core.mrdna_bridge as mb
    home = tmp_path / "home"; (home / ".local").mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    built = tmp_path / "build" / "arbd"; built.parent.mkdir()
    built.write_text("#!/bin/sh\n"); os.chmod(built, 0o755)
    monkeypatch.setattr(mb, "find_arbd_build", lambda: str(built))
    dest = str(home / ".local" / "bin" / "arbd")
    monkeypatch.setattr(mb, "find_arbd", lambda: dest if os.path.isfile(dest) else None)

    rec = _Rec()
    out = asyncio.run(art.install_arbd_binary(rec))
    assert out == dest
    assert os.path.isfile(dest) and os.access(dest, os.X_OK)   # really copied + executable
    assert rec.msgs[-1]["type"] == "complete"


def test_install_arbd_binary_raises_when_nothing_built(monkeypatch):
    import backend.core.mrdna_bridge as mb
    monkeypatch.setattr(mb, "find_arbd_build", lambda: None)
    with pytest.raises(art.ArtifactError):
        asyncio.run(art.install_arbd_binary(_Rec()))


# ── ARBD sudo install (run the privileged step for terminal-averse users) ─────

def test_install_arbd_sudo_rejects_empty_password(tmp_path, monkeypatch):
    import backend.core.mrdna_bridge as mb
    built = tmp_path / "build" / "arbd"; built.parent.mkdir(parents=True); built.write_text("x")
    monkeypatch.setattr(mb, "find_arbd_build", lambda: str(built))   # build dir exists
    with pytest.raises(art.ArtifactError, match="password"):
        asyncio.run(art.install_arbd_sudo("", _Rec()))


def test_install_arbd_sudo_raises_when_not_built(tmp_path, monkeypatch):
    import backend.core.mrdna_bridge as mb
    monkeypatch.setenv("HOME", str(tmp_path))          # ~/arbd-src/build absent under temp HOME
    monkeypatch.setattr(mb, "find_arbd_build", lambda: None)
    with pytest.raises(art.ArtifactError, match="built"):
        asyncio.run(art.install_arbd_sudo("pw", _Rec()))
