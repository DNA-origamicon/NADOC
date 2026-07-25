"""GPU-resident pinned-host pre-flight + the fast-conf downgrade.

NADOC's "fast" segments bake in `GPUresident on` (+ HMR + rigidBonds all + 4 fs).
GPU-resident pins a large host buffer; a host's PINNED pool can be far smaller than its
free RAM (WSL2 caps it at ~1.0 GB with 15 GB free), so above ~800k atoms NAMD dies at
segment START on cudaMallocHost — hours into a job.  Measured on this box: 756k atoms
runs, 971k fails, GT_corner_v2's 1.44M-atom package fails outright.

Dropping GPUresident ALONE is not enough: the 4 fs timestep survives only under
GPUresident's GPU constraint solver, and the CPU RATTLE path blows up instantly.  So the
downgrade also halves the timestep and doubles the step counts / output cadence, keeping
the simulated time and frame count identical.  See LESSONS K6.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from backend.core import namd_runner
from backend.core.md_protocols import downgrade_gpu_resident, strip_gpu_resident


FAST_CONF = """\
structure          d_hmr.psf
rigidBonds         all
timestep           4
nonbondedFreq      1
fullElectFrequency 2
stepspercycle      12
GPUresident        on
outputEnergies     9600
xstFreq            9600
restartfreq        9600
dcdFreq            9600
langevinTemp       300
run                480000
"""

SLOW_CONF = FAST_CONF.replace("GPUresident        on\n", "").replace("timestep           4", "timestep           1")

PINNED_OOM_LOG = (
    "Info: Benchmark time...\n"
    "FATAL ERROR: CUDA error cudaMallocHost(pp, sizeofT*len) in file src/CudaUtils.C, "
    "function allocate_host_T, line 88\n"
)
OK_LOG = "ENERGY: 12 ...\nWallClock: 9.1  CPUTime: 9.4\n"


# ── the pure downgrade ────────────────────────────────────────────────────────

def _val(text: str, key: str) -> str:
    return next(l.split()[1] for l in text.splitlines() if l.lower().startswith(key.lower()))


def test_downgrade_halves_timestep_and_doubles_steps_to_keep_simulated_time():
    out = downgrade_gpu_resident(FAST_CONF)
    assert "GPUresident" not in out
    assert _val(out, "timestep") == "2"          # 4 fs -> 2 fs (CPU RATTLE can't hold 4)
    assert _val(out, "run") == "960000"          # 2x steps -> SAME 1.92 ns
    # 4 fs x 480000 == 2 fs x 960000
    assert float(_val(out, "timestep")) * int(_val(out, "run")) == 4 * 480000


def test_downgrade_doubles_output_cadence_so_frame_count_is_unchanged():
    out = downgrade_gpu_resident(FAST_CONF)
    for key in ("dcdFreq", "restartfreq", "xstFreq", "outputEnergies"):
        assert _val(out, key) == "19200", key
    # frames written = run / dcdFreq  → identical before and after
    assert int(_val(out, "run")) // int(_val(out, "dcdFreq")) == 480000 // 9600


def test_downgrade_leaves_the_physics_alone():
    """Only integrator/throughput knobs may move — forcefield, PSF, constraints, thermostat."""
    out = downgrade_gpu_resident(FAST_CONF)
    for line in ("structure          d_hmr.psf", "rigidBonds         all",
                 "langevinTemp       300", "stepspercycle      12",
                 "nonbondedFreq      1", "fullElectFrequency 2"):
        assert line in out, line


def test_downgrade_is_a_noop_without_gpu_resident():
    """The gentle _p10 warmup confs never had GPUresident — must not be touched."""
    assert downgrade_gpu_resident(SLOW_CONF) == SLOW_CONF


# ── soften-for-stability (the automatic instability remedy) ─────────────────────

def test_soften_drops_rigidbonds_and_timestep_to_the_soft_integrator():
    """A RATTLE blow-up needs rigidBonds none + 1 fs (the proven-stable soft config the
    ladder's first chunk uses).  Softening flips exactly those two knobs + drops
    GPUresident, and leaves the ensemble (PSF/PME/thermostat/step count) alone."""
    from backend.core.md_protocols import soften_conf_for_stability
    out = soften_conf_for_stability(FAST_CONF)
    assert _val(out, "rigidBonds") == "none"     # the RATTLE constraint is removed
    assert _val(out, "timestep") == "1"          # 4 → 1 fs
    assert "GPUresident" not in out              # soft integrator is not GPU-resident
    # ensemble untouched — HMR PSF kept (checkpoint velocities were made under it),
    # step count unchanged (same convention as the ladder's built-in soft segments).
    assert _val(out, "structure") == "d_hmr.psf"
    assert _val(out, "langevinTemp") == "300"
    assert _val(out, "run") == "480000"


def test_soften_is_idempotent_and_a_noop_when_already_soft():
    """Applying twice == once; a conf already at rigidBonds none is returned UNCHANGED —
    the runner uses 'unchanged' as the signal that a still-crashing soft segment can't be
    rescued further (so it dead-ends instead of looping)."""
    from backend.core.md_protocols import soften_conf_for_stability
    once = soften_conf_for_stability(FAST_CONF)
    assert soften_conf_for_stability(once) == once
    already_soft = FAST_CONF.replace("rigidBonds         all", "rigidBonds         none")
    assert soften_conf_for_stability(already_soft) == already_soft


def test_downgrade_run_stays_a_multiple_of_stepspercycle():
    """NAMD rejects a step count that isn't a multiple of stepspercycle."""
    out = downgrade_gpu_resident(FAST_CONF)
    assert int(_val(out, "run")) % int(_val(out, "stepspercycle")) == 0
    assert int(_val(out, "restartfreq")) % int(_val(out, "stepspercycle")) == 0


def test_strip_alone_leaves_the_unstable_4fs_timestep():
    """Guards the docstring claim: strip_gpu_resident is NOT a safe fallback on its own."""
    assert _val(strip_gpu_resident(FAST_CONF), "timestep") == "4"


# ── the probe ─────────────────────────────────────────────────────────────────

def _package(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "seg_fast.conf").write_text(FAST_CONF)
    (pkg / "seg_slow.conf").write_text(SLOW_CONF)
    return pkg


def _stub(monkeypatch, log, seen=None):
    def fake_run(cmd, **kw):
        if seen is not None:
            seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout=log, stderr="")
    monkeypatch.setattr(namd_runner.subprocess, "run", fake_run)


def test_probe_detects_pinned_host_exhaustion(tmp_path, monkeypatch):
    pkg = _package(tmp_path)
    _stub(monkeypatch, PINNED_OOM_LOG)
    assert namd_runner.gpu_resident_probe(pkg, "seg_fast", "namd3", "0", threads=2) is False


def test_probe_passes_when_gpu_resident_works(tmp_path, monkeypatch):
    pkg = _package(tmp_path)
    _stub(monkeypatch, OK_LOG)
    assert namd_runner.gpu_resident_probe(pkg, "seg_fast", "namd3", "0", threads=2) is True


def test_probe_is_cached(tmp_path, monkeypatch):
    pkg = _package(tmp_path)
    seen: list = []
    _stub(monkeypatch, PINNED_OOM_LOG, seen)
    assert namd_runner.gpu_resident_probe(pkg, "seg_fast", "namd3", "0", threads=2) is False
    assert namd_runner.gpu_resident_probe(pkg, "seg_fast", "namd3", "0", threads=2) is False
    assert len(seen) == 1
    assert json.loads((pkg / namd_runner.GPU_RESIDENT_PROBE_CACHE).read_text())["gpu_resident_ok"] is False


@pytest.mark.parametrize("boom", [OSError("nope"), subprocess.TimeoutExpired("namd3", 1)])
def test_probe_fails_open(tmp_path, monkeypatch, boom):
    pkg = _package(tmp_path)

    def fake_run(cmd, **kw):
        raise boom

    monkeypatch.setattr(namd_runner.subprocess, "run", fake_run)
    assert namd_runner.gpu_resident_probe(pkg, "seg_fast", "namd3", "0", threads=2) is True


# ── the package rewrite ───────────────────────────────────────────────────────

def test_downgrade_confs_rewrites_only_the_fast_segments_and_keeps_originals(tmp_path):
    pkg = _package(tmp_path)
    done = namd_runner.downgrade_gpu_resident_confs(pkg, "job1")

    assert done == ["seg_fast"]                                  # seg_slow untouched
    assert (pkg / "seg_slow.conf").read_text() == SLOW_CONF
    new = (pkg / "seg_fast.conf").read_text()
    assert "GPUresident" not in new and _val(new, "timestep") == "2"
    # the original is preserved for provenance
    assert (pkg / "seg_fast.conf.gpuresident").read_text() == FAST_CONF


def test_downgrade_confs_is_idempotent(tmp_path):
    pkg = _package(tmp_path)
    namd_runner.downgrade_gpu_resident_confs(pkg, "job1")
    assert namd_runner.downgrade_gpu_resident_confs(pkg, "job1") == []  # nothing left to do
    assert _val((pkg / "seg_fast.conf").read_text(), "timestep") == "2"  # not halved twice
