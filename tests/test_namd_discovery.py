"""Tests for NAMD binary discovery in backend/core/namd_runner.py.

`find_namd()` resolves a NAMD3 executable from, in order:
  1. ``$NADOC_NAMD_BIN`` (explicit override),
  2. ``namd3`` on PATH,
  3. conventional ``~/Applications`` install paths.

These tests stub the candidate list + env so they need NO real NAMD install
and never touch the developer's actual ``~/Applications``.
"""

from __future__ import annotations

import stat

import pytest

from backend.core import namd_runner
from backend.core import namd_topology


def _make_exe(path) -> str:
    """Create a tiny executable file and return its path string."""
    path.write_text("#!/bin/sh\necho namd3\n")
    path.chmod(path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return str(path)


def test_env_override_takes_precedence(tmp_path, monkeypatch):
    """$NADOC_NAMD_BIN wins even when a conventional candidate also resolves."""
    override = _make_exe(tmp_path / "override_namd3")
    fallback = _make_exe(tmp_path / "fallback_namd3")
    monkeypatch.setenv("NADOC_NAMD_BIN", override)
    monkeypatch.setattr(namd_runner, "_namd_candidates", lambda: [fallback])
    assert namd_runner.find_namd() == override


def test_override_ignored_when_not_executable(tmp_path, monkeypatch):
    """A bogus override path is skipped; resolution falls through to candidates."""
    fallback = _make_exe(tmp_path / "namd3")
    monkeypatch.setenv("NADOC_NAMD_BIN", str(tmp_path / "does_not_exist"))
    monkeypatch.setattr(namd_runner, "_namd_candidates", lambda: [fallback])
    assert namd_runner.find_namd() == fallback


def test_raises_with_actionable_guidance_when_absent(monkeypatch):
    """With nothing resolvable, the error names the override env var + the doc."""
    monkeypatch.delenv("NADOC_NAMD_BIN", raising=False)
    monkeypatch.setattr(namd_runner, "_namd_candidates", lambda: [])
    with pytest.raises(RuntimeError, match=r"NADOC_NAMD_BIN.*namd_setup"):
        namd_runner.find_namd()


def test_prefer_cpu_returns_non_cuda_build(tmp_path, monkeypatch):
    """GBIS needs the CPU build: prefer_cpu skips the CUDA binary for the multicore one."""
    cuda = _make_exe(tmp_path / "cuda_namd3")
    cpu = _make_exe(tmp_path / "cpu_namd3")
    monkeypatch.delenv("NADOC_NAMD_BIN", raising=False)
    monkeypatch.setattr(namd_runner, "_namd_candidates", lambda: [cuda, cpu])
    monkeypatch.setattr(namd_runner, "namd_is_cuda_build", lambda b: b == cuda)
    assert namd_runner.find_namd(prefer_cpu=True) == cpu
    # Default (GPU) resolution still returns the first candidate (CUDA).
    assert namd_runner.find_namd() == cuda


def test_prefer_cpu_raises_when_only_cuda_available(tmp_path, monkeypatch):
    """No CPU build → clear error (silently using CUDA would just crash GBIS again)."""
    cuda = _make_exe(tmp_path / "cuda_namd3")
    monkeypatch.delenv("NADOC_NAMD_BIN", raising=False)
    monkeypatch.setattr(namd_runner, "_namd_candidates", lambda: [cuda])
    monkeypatch.setattr(namd_runner, "namd_is_cuda_build", lambda b: True)
    with pytest.raises(RuntimeError, match=r"GBIS.*CPU.*non-CUDA|multicore"):
        namd_runner.find_namd(prefer_cpu=True)


IMPLICIT = "implicit_gbis_namd"


@pytest.mark.parametrize("protocol,devices,expected", [
    (IMPLICIT, "0", True),      # GBIS always CPU, even with a GPU device
    (IMPLICIT, "cpu", True),
    ("equilibrium_aware_namd", "cpu", True),
    ("equilibrium_aware_namd", "none", True),
    ("equilibrium_aware_namd", "0", False),
    ("equilibrium_aware_namd", "", False),   # empty = GPU auto, NOT cpu
    ("equilibrium_aware_namd", "0,1", False),
])
def test_job_wants_cpu(protocol, devices, expected):
    assert namd_runner.job_wants_cpu(protocol, devices) is expected


def _both_builds(tmp_path, monkeypatch):
    cuda = _make_exe(tmp_path / "cuda_namd3")
    cpu = _make_exe(tmp_path / "cpu_namd3")
    monkeypatch.delenv("NADOC_NAMD_BIN", raising=False)
    monkeypatch.setattr(namd_runner, "_namd_candidates", lambda: [cuda, cpu])
    monkeypatch.setattr(namd_runner, "namd_is_cuda_build", lambda b: b == cuda)
    return cuda, cpu


def test_resolve_launch_gpu_uses_cuda_with_devices(tmp_path, monkeypatch):
    cuda, cpu = _both_builds(tmp_path, monkeypatch)
    assert namd_runner.resolve_namd_launch("equilibrium_aware_namd", "0") == (cuda, "0")


def test_resolve_launch_cpu_request_uses_multicore_no_devices(tmp_path, monkeypatch):
    cuda, cpu = _both_builds(tmp_path, monkeypatch)
    assert namd_runner.resolve_namd_launch("equilibrium_aware_namd", "cpu") == (cpu, "")


def test_resolve_launch_gbis_forces_cpu_even_with_gpu_device(tmp_path, monkeypatch):
    cuda, cpu = _both_builds(tmp_path, monkeypatch)
    assert namd_runner.resolve_namd_launch(IMPLICIT, "0") == (cpu, "")


def test_resolve_launch_gpu_on_cpu_only_machine_degrades(tmp_path, monkeypatch):
    cpu = _make_exe(tmp_path / "cpu_namd3")
    monkeypatch.delenv("NADOC_NAMD_BIN", raising=False)
    monkeypatch.setattr(namd_runner, "_namd_candidates", lambda: [cpu])
    monkeypatch.setattr(namd_runner, "namd_is_cuda_build", lambda b: False)
    # GPU requested but no CUDA build → runs on CPU build with no +devices.
    assert namd_runner.resolve_namd_launch("equilibrium_aware_namd", "0") == (cpu, "")


def test_resolve_launch_gbis_raises_on_cuda_only_machine(tmp_path, monkeypatch):
    cuda = _make_exe(tmp_path / "cuda_namd3")
    monkeypatch.delenv("NADOC_NAMD_BIN", raising=False)
    monkeypatch.setattr(namd_runner, "_namd_candidates", lambda: [cuda])
    monkeypatch.setattr(namd_runner, "namd_is_cuda_build", lambda b: True)
    with pytest.raises(RuntimeError, match=r"GBIS.*CPU|multicore"):
        namd_runner.resolve_namd_launch(IMPLICIT, "0")


def test_resolve_launch_explicit_cpu_request_degrades_when_only_cuda(tmp_path, monkeypatch):
    cuda = _make_exe(tmp_path / "cuda_namd3")
    monkeypatch.delenv("NADOC_NAMD_BIN", raising=False)
    monkeypatch.setattr(namd_runner, "_namd_candidates", lambda: [cuda])
    monkeypatch.setattr(namd_runner, "namd_is_cuda_build", lambda b: True)
    # Explicit CPU request with no CPU build → best-effort GPU ("0"), does not raise.
    assert namd_runner.resolve_namd_launch("equilibrium_aware_namd", "cpu") == (cuda, "0")


# ── psfgen discovery (mirrors NAMD; psfgen ships inside the NAMD tarball) ──────


def test_psfgen_env_override_takes_precedence(tmp_path, monkeypatch):
    """$NADOC_PSFGEN_BIN wins over the conventional candidate paths."""
    override = _make_exe(tmp_path / "override_psfgen")
    fallback = _make_exe(tmp_path / "fallback_psfgen")
    monkeypatch.setenv("NADOC_PSFGEN_BIN", override)
    monkeypatch.setattr(namd_topology, "_psfgen_candidates", lambda: [fallback])
    # Neutralize the PATH 'psfgen' probe so the test is hermetic.
    monkeypatch.setattr(namd_topology.shutil, "which", lambda c: None)
    assert namd_topology.find_psfgen() == override


def test_psfgen_falls_through_to_build_dir(tmp_path, monkeypatch):
    """A bogus override is skipped; the bundled build-dir psfgen is found."""
    bundled = _make_exe(tmp_path / "psfgen")
    monkeypatch.setenv("NADOC_PSFGEN_BIN", str(tmp_path / "missing"))
    monkeypatch.setattr(namd_topology, "_psfgen_candidates", lambda: [bundled])
    monkeypatch.setattr(namd_topology.shutil, "which", lambda c: None)
    assert namd_topology.find_psfgen() == bundled


def test_psfgen_raises_with_actionable_guidance(monkeypatch):
    """Absent psfgen: error names the override env var + the doc."""
    monkeypatch.delenv("NADOC_PSFGEN_BIN", raising=False)
    monkeypatch.setattr(namd_topology, "_psfgen_candidates", lambda: [])
    monkeypatch.setattr(namd_topology.shutil, "which", lambda c: None)
    with pytest.raises(RuntimeError, match=r"NADOC_PSFGEN_BIN.*namd_setup"):
        namd_topology.find_psfgen()
