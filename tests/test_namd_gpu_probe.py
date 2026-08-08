"""NAMD CUDA tile-list pre-flight probe.

NAMD 3.0.2's CUDA ``buildTileLists`` kernel dies with an illegal memory access on
the FIRST step for certain (patch-grid x atom-density) geometries.  It is
deterministic per package but NOT a function of the patch grid alone — the same
26x3x34 grid crashes at 380k atoms and runs at 611k — so the runner settles it by
running one minimization cycle on the GPU and reading the log.  See LESSONS K2.

These tests pin the probe's *decision* logic (conf rewriting, crash detection,
caching, fail-open) with a stubbed NAMD; they never launch a real GPU run.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from backend.core import namd_runner


MIN_CONF = """\
structure          p.psf
coordinates        p.pdb
stepspercycle      12
outputEnergies     9600
outputName         output/p_00_min
dcdFreq            0
minimize           60
"""

CRASH_LOG = (
    "Info: PATCH GRID IS 26 (PERIODIC) BY 3 (PERIODIC) BY 34 (PERIODIC)\n"
    "FATAL ERROR: CUDA error cudaStreamSynchronize(stream) in file "
    "src/CudaTileListKernel.cu, function buildTileLists, line 1141\n"
    " on Pe 4: an illegal memory access was encountered\n"
)
OK_LOG = "ENERGY: 60 ...\nWallClock: 6.74  CPUTime: 7.06\n"


def _package(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "p_00_min.conf").write_text(MIN_CONF)
    return pkg


def _stub_namd(monkeypatch, log: str, seen: list | None = None):
    """Replace the NAMD subprocess with one that just emits *log*."""

    def fake_run(cmd, **kw):
        if seen is not None:
            seen.append((cmd, kw))
        return subprocess.CompletedProcess(cmd, 0, stdout=log, stderr="")

    monkeypatch.setattr(namd_runner.subprocess, "run", fake_run)


# ── conf rewriting ────────────────────────────────────────────────────────────


def test_probe_conf_runs_one_cycle_and_diverts_output(tmp_path):
    """The probe must shorten the run to one stepspercycle (NAMD rejects step counts
    that aren't a multiple of it) and must never write the job's real output/."""
    src = tmp_path / "min.conf"
    src.write_text(MIN_CONF)
    dst = tmp_path / "probe.conf"
    namd_runner._write_probe_conf(src, dst, "_probe_out")
    text = dst.read_text()

    assert "minimize           12" in text  # one cycle, not 60
    assert "outputName         _probe_out" in text
    assert "output/p_00_min" not in text  # real output untouched
    assert "structure          p.psf" in text  # inputs preserved


def test_probe_conf_defaults_cycle_when_stepspercycle_absent(tmp_path):
    src = tmp_path / "min.conf"
    src.write_text("coordinates p.pdb\noutputName out/x\nminimize 500\n")
    dst = tmp_path / "probe.conf"
    namd_runner._write_probe_conf(src, dst, "_probe_out")
    assert "minimize 20" in dst.read_text()


# ── verdict ───────────────────────────────────────────────────────────────────


def test_probe_reports_unsafe_on_tilelist_crash(tmp_path, monkeypatch):
    pkg = _package(tmp_path)
    _stub_namd(monkeypatch, CRASH_LOG)
    assert (
        namd_runner.gpu_tilelist_probe(pkg, "p_00_min", "namd3", "0", threads=2)
        is False
    )


def test_probe_reports_safe_on_clean_run(tmp_path, monkeypatch):
    pkg = _package(tmp_path)
    _stub_namd(monkeypatch, OK_LOG)
    assert (
        namd_runner.gpu_tilelist_probe(pkg, "p_00_min", "namd3", "0", threads=2) is True
    )


def test_probe_leaves_no_scratch_files_behind(tmp_path, monkeypatch):
    pkg = _package(tmp_path)

    def fake_run(cmd, **kw):
        # a real NAMD writes its outputName files; make sure we clean them up
        (pkg / "_gpu_probe_out.coor").write_text("x")
        (pkg / "_gpu_probe_out.vel").write_text("x")
        return subprocess.CompletedProcess(cmd, 0, stdout=OK_LOG, stderr="")

    monkeypatch.setattr(namd_runner.subprocess, "run", fake_run)
    namd_runner.gpu_tilelist_probe(pkg, "p_00_min", "namd3", "0", threads=2)

    assert not (pkg / "_gpu_probe.conf").exists()
    assert not list(pkg.glob("_gpu_probe_out*"))


# ── caching ───────────────────────────────────────────────────────────────────


def test_probe_verdict_is_cached_and_not_re_run(tmp_path, monkeypatch):
    """A prepared package's geometry can't change, so a resume must not re-pay."""
    pkg = _package(tmp_path)
    seen: list = []
    _stub_namd(monkeypatch, CRASH_LOG, seen)

    assert (
        namd_runner.gpu_tilelist_probe(pkg, "p_00_min", "namd3", "0", threads=2)
        is False
    )
    assert len(seen) == 1
    assert (
        json.loads((pkg / namd_runner.GPU_PROBE_CACHE).read_text())["gpu_safe"] is False
    )

    # second call: cached, NAMD not invoked again
    assert (
        namd_runner.gpu_tilelist_probe(pkg, "p_00_min", "namd3", "0", threads=2)
        is False
    )
    assert len(seen) == 1


def test_probe_reprobes_when_cache_is_corrupt(tmp_path, monkeypatch):
    pkg = _package(tmp_path)
    (pkg / namd_runner.GPU_PROBE_CACHE).write_text("{not json")
    _stub_namd(monkeypatch, OK_LOG)
    assert (
        namd_runner.gpu_tilelist_probe(pkg, "p_00_min", "namd3", "0", threads=2) is True
    )


# ── fail-open ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "boom", [OSError("no binary"), subprocess.TimeoutExpired("namd3", 1)]
)
def test_probe_fails_open_when_it_cannot_run(tmp_path, monkeypatch, boom):
    """A broken probe must never be the thing that stops a job from launching."""
    pkg = _package(tmp_path)

    def fake_run(cmd, **kw):
        raise boom

    monkeypatch.setattr(namd_runner.subprocess, "run", fake_run)
    assert (
        namd_runner.gpu_tilelist_probe(pkg, "p_00_min", "namd3", "0", threads=2) is True
    )


def test_probe_safe_when_min_conf_missing(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    assert (
        namd_runner.gpu_tilelist_probe(pkg, "p_00_min", "namd3", "0", threads=2) is True
    )


# ── devices wiring ────────────────────────────────────────────────────────────


def test_probe_passes_devices_through(tmp_path, monkeypatch):
    pkg = _package(tmp_path)
    seen: list = []
    _stub_namd(monkeypatch, OK_LOG, seen)
    namd_runner.gpu_tilelist_probe(pkg, "p_00_min", "namd3", "0", threads=4)
    cmd = seen[0][0]
    assert "+devices" in cmd and cmd[cmd.index("+devices") + 1] == "0"
    assert "+p4" in cmd


def test_probe_omits_devices_when_empty(tmp_path, monkeypatch):
    pkg = _package(tmp_path)
    seen: list = []
    _stub_namd(monkeypatch, OK_LOG, seen)
    namd_runner.gpu_tilelist_probe(pkg, "p_00_min", "namd3", "", threads=4)
    assert "+devices" not in seen[0][0]
