"""Tests for engine auto-install orchestration (backend/core/engine_install.py).

`install_steps` is pure → asserts the GPU-aware build commands + idempotent
clone.  `run_install` is exercised with `_stream` and the verify probe
monkeypatched, so the streaming/progress/error contract is checked without
cloning or compiling anything.
"""

from __future__ import annotations

import asyncio
import os

import pytest

import backend.core.engine_install as ei


def _gpu(present, arch="75"):
    return {"present": present, "arch": arch, "names": (["RTX"] if present else []),
            "devices": [], "toolkit": present}


# ── install_steps (pure) ──────────────────────────────────────────────────────

def test_oxdna_cpu_steps_no_cuda_flag():
    steps = ei.install_steps("oxdna", _gpu(False), {})
    cmake = next(s for s in steps if s["label"].startswith("Configuring"))
    assert cmake["argv"] == ["cmake", ".."]
    # clone step is idempotent on the conventional dir
    clone = steps[0]
    assert clone["skip_if_dir"].endswith("oxDNA")
    assert clone["argv"][0:2] == ["git", "clone"]


def test_oxdna_gpu_steps_add_cuda_arch():
    steps = ei.install_steps("oxdna", _gpu(True, arch="86"), {})
    cmake = next(s for s in steps if s["label"].startswith("Configuring"))
    assert "-DCUDA=ON" in cmake["argv"]
    assert "-DCMAKE_CUDA_ARCHITECTURES=86" in cmake["argv"]


def test_oxdna_builds_into_conventional_build_dir():
    """Must build into ~/oxDNA/build so find_oxdna() detects it afterward."""
    steps = ei.install_steps("oxdna", _gpu(False), {})
    make = next(s for s in steps if s["label"].startswith("Compiling"))
    assert make["cwd"] == os.path.join(os.path.expanduser("~/oxDNA"), "build")


def test_anm_runs_build_script_with_arch_env_on_gpu():
    steps = ei.install_steps("oxdna_anm", _gpu(True, arch="75"), {})
    assert len(steps) == 1
    assert steps[0]["argv"] == ["bash", "scripts/build-anm-oxdna.sh"]
    assert steps[0]["env"] == {"OXDNA_CUDA_ARCH": "75"}


def test_anm_no_arch_env_without_gpu():
    steps = ei.install_steps("oxdna_anm", _gpu(False), {})
    assert steps[0]["env"] == {}


def test_mrdna_runs_setup_script_gpu_independent():
    for gpu in (_gpu(False), _gpu(True)):
        steps = ei.install_steps("mrdna", gpu, {})
        assert len(steps) == 1
        assert steps[0]["argv"] == ["bash", "scripts/setup-mrdna.sh"]
        # no CUDA/arch env — mrdna is a pure Python install
        assert "env" not in steps[0] or steps[0].get("env") in ({}, None)


def test_lammps_steps_cgdna_flags_and_mpi():
    steps = ei.install_steps("lammps_oxdna", _gpu(False), {"mpi": True})
    clone = steps[0]
    assert clone["argv"][0:2] == ["git", "clone"]
    assert "--depth" in clone["argv"]                 # shallow — LAMMPS history is huge
    assert clone["skip_if_dir"].endswith("lammps")
    cmake = next(s for s in steps if s["label"].startswith("Configuring"))
    assert "PKG_CG-DNA=on" in cmake["argv"]           # hyphen, not underscore
    assert "PKG_MOLECULE=on" in cmake["argv"] and "PKG_ASPHERE=on" in cmake["argv"]
    assert "BUILD_MPI=on" in cmake["argv"]            # MPI toolchain present
    assert cmake["argv"][-1].endswith("cmake")        # LAMMPS's cmake source subdir


def test_lammps_steps_no_mpi_flag_without_mpi_toolchain():
    steps = ei.install_steps("lammps_oxdna", _gpu(False), {"mpi": False})
    cmake = next(s for s in steps if s["label"].startswith("Configuring"))
    assert "BUILD_MPI=on" not in cmake["argv"]
    # never a CUDA flag — this is the CPU-parallel engine
    assert not any("CUDA" in a for a in cmake["argv"])


def test_lammps_builds_into_conventional_build_dir():
    steps = ei.install_steps("lammps_oxdna", _gpu(False), {"mpi": False})
    make = next(s for s in steps if s["label"].startswith("Compiling"))
    assert make["cwd"] == os.path.join(os.path.expanduser("~/lammps"), "build")
    assert make["argv"][0:3] == ["cmake", "--build", "."]


def test_non_installable_engine_raises():
    with pytest.raises(ValueError):
        ei.install_steps("namd", _gpu(False), {})
    with pytest.raises(ValueError):
        ei.install_steps("arbd", _gpu(True), {})


# ── run_install (streaming/progress/verify contract) ──────────────────────────

class _Recorder:
    def __init__(self):
        self.msgs = []
    async def __call__(self, msg):
        self.msgs.append(msg)


def test_run_install_success_streams_progress_and_completes(monkeypatch):
    calls = []
    async def fake_stream(argv, cwd, env, send):
        calls.append(argv)
        await send({"type": "log", "line": f"ran {argv[0]}"})
        return 0
    monkeypatch.setattr(ei, "_stream", fake_stream)
    monkeypatch.setattr(ei, "_verify", lambda k: "/home/u/oxDNA/build/bin/oxDNA")
    # avoid the idempotent-skip path so all steps "run"
    monkeypatch.setattr(ei.os.path, "isdir", lambda p: False)

    rec = _Recorder()
    path = asyncio.run(ei.run_install("oxdna", rec))

    assert path.endswith("oxDNA")
    types = [m["type"] for m in rec.msgs]
    assert "progress" in types and "complete" in types
    assert rec.msgs[-1] == {"type": "complete", "engine": "oxdna", "path": path}
    assert any(m.get("pct") == 100 for m in rec.msgs if m["type"] == "progress")
    assert len(calls) == 3  # clone + cmake + make all streamed


def test_run_install_mrdna_streams_and_completes(monkeypatch):
    async def ok_stream(argv, cwd, env, send):
        await send({"type": "log", "line": " ".join(argv)})
        return 0
    monkeypatch.setattr(ei, "_stream", ok_stream)
    monkeypatch.setattr(ei, "_verify", lambda k: "/home/u/mrdna-tool/mrdna")
    monkeypatch.setattr(ei.os.path, "isdir", lambda p: False)

    rec = _Recorder()
    path = asyncio.run(ei.run_install("mrdna", rec))
    assert path.endswith("mrdna")
    assert rec.msgs[-1] == {"type": "complete", "engine": "mrdna", "path": path}


def test_run_install_step_failure_raises(monkeypatch):
    async def fail_stream(argv, cwd, env, send):
        return 1
    monkeypatch.setattr(ei, "_stream", fail_stream)
    monkeypatch.setattr(ei.os.path, "isdir", lambda p: False)
    with pytest.raises(ei.InstallError):
        asyncio.run(ei.run_install("oxdna", _Recorder()))


def test_run_install_binary_not_detected_raises(monkeypatch):
    async def ok_stream(argv, cwd, env, send):
        return 0
    monkeypatch.setattr(ei, "_stream", ok_stream)
    monkeypatch.setattr(ei, "_verify", lambda k: None)  # build "succeeds" but nothing found
    monkeypatch.setattr(ei.os.path, "isdir", lambda p: False)
    with pytest.raises(ei.InstallError):
        asyncio.run(ei.run_install("oxdna", _Recorder()))


def test_simulation_streams_progress_then_declines_without_building(monkeypatch):
    """NADOC_ENGINES_FORCE_MISSING: run_install must dry-run (stream fake stages,
    raise) and NEVER touch the real subprocess streamer."""
    def boom(*a, **k):
        raise AssertionError("_stream must not run under simulation")
    monkeypatch.setattr(ei, "_stream", boom)
    monkeypatch.setenv("NADOC_ENGINES_FORCE_MISSING", "oxdna")

    rec = _Recorder()
    with pytest.raises(ei.InstallError, match="Simulation mode"):
        asyncio.run(ei.run_install("oxdna", rec))
    # progress + log streamed, but no 'complete'
    types = [m["type"] for m in rec.msgs]
    assert "progress" in types and "log" in types
    assert "complete" not in types
