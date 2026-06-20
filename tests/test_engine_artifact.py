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


def test_pick_best_prefers_cuda_on_gpu_box():
    cands = [
        {"filename": "NAMD_3.0.2_Linux-x86_64-multicore.tar.gz", "is_cuda": False, "matches_name": True},
        {"filename": "NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz", "is_cuda": True, "matches_name": True},
    ]
    assert art.pick_best_candidate(cands, _gpu(True))["is_cuda"] is True
    assert art.pick_best_candidate(cands, _gpu(False))["is_cuda"] is False


def test_pick_best_none_when_empty():
    assert art.pick_best_candidate([], _gpu(True)) is None


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


# ── scan ──────────────────────────────────────────────────────────────────────

def test_scan_finds_namd_tarballs(tmp_path):
    _make_tar(str(tmp_path), "NAMD_3.0.2_Linux-x86_64-multicore-CUDA.tar.gz", inner_names=["a/namd3"])
    _make_tar(str(tmp_path), "unrelated.tar.gz", inner_names=["a/b"])
    found = art.scan_namd_downloads(_gpu(True), search_dirs=[str(tmp_path)])
    assert len(found) == 1
    assert found[0]["build"] == "CUDA"
    assert found[0]["matches_name"] is True


def test_scan_empty_when_no_dir():
    assert art.scan_namd_downloads(_gpu(False), search_dirs=["/no/such/dir/xyz"]) == []


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
