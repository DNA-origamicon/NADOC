"""Pure-logic pins for the RunPod benchmark harness (experiments/exp43_runpod_bench).

The harness itself runs on a rented pod with nothing but stdlib, so its pure parts
live in a standalone module. These tests are the only thing standing between a
typo in a regex and a benchmark report that confidently states the wrong cause of
a failure — which is not hypothetical: NADOC recorded VoltronCore job
``f702f4a3282f`` as ``failure_kind=vram_oom`` when the log's FIRST fatal was a
*pinned host* allocation failure. The card was not the binding constraint.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

_MOD = (
    Path(__file__).resolve().parents[1]
    / "experiments"
    / "exp43_runpod_bench"
    / "bench_matrix.py"
)


def _load():
    spec = importlib.util.spec_from_file_location("bench_matrix", _MOD)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    # @dataclass resolves its own module via sys.modules[cls.__module__]; a
    # path-loaded module must be registered BEFORE exec or every dataclass in it
    # dies on `NoneType.__dict__`.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


bm = _load()


# ---------------------------------------------------------------------------
# Failure classification — ordering is the whole point
# ---------------------------------------------------------------------------

REAL_VOLTRONCORE_LOG = """
Info: 4695675 ATOMS
TCL: Minimizing for 4800 steps
FATAL ERROR: CUDA error cudaHostAlloc(pp, sizeofT*(*curlen), flag) in file src/CudaUtils.C,
 function reallocate_host_T, line 208
 on Pe 4 (DESKTOP-T44QS0K device 0 pci 0:7:0): out of memory
[Partition 0][Node 0] End of program
FATAL ERROR: CUDA error cudaGetLastError() in file src/CudaTileListKernel.cu,
 function sortTileLists, line 1268
 on Pe 4 (DESKTOP-T44QS0K device 0 pci 0:7:0): out of memory
"""


def test_pinned_host_oom_beats_the_device_oom_that_follows_it():
    """The real 8 GB failure. A device OOM CASCADES from the host OOM.

    Reporting the second fatal is how the job got mislabelled `vram_oom` and how
    "VoltronCore needs a bigger card" became the working theory. The host was out
    of *pinned* memory; the card was collateral.
    """
    kind, why = bm.classify_failure(REAL_VOLTRONCORE_LOG)
    assert kind == "pinned_host_oom"
    assert "pinned" in why.lower()


def test_device_oom_alone_is_still_reported_as_device_oom():
    log = "FATAL ERROR: CUDA error cudaGetLastError() in sortTileLists: out of memory"
    kind, _ = bm.classify_failure(log)
    assert kind == "device_oom"


def test_stock_namd_tilelist_bug_is_called_out_by_name():
    log = "FATAL ERROR: CUDA error in buildTileLists: an illegal memory access was encountered"
    kind, why = bm.classify_failure(log)
    assert kind == "tilelist_bug"
    assert "3.0.2p1" in why  # the report must tell you which binary to use


def test_carve_gpuresident_conflict_is_its_own_kind():
    log = "FATAL ERROR: Low global CUDA exclusion count!"
    kind, _ = bm.classify_failure(log)
    assert kind == "carve_gpuresident_conflict"


def test_clean_log_classifies_as_nothing():
    assert bm.classify_failure("Info: Benchmark time: 32 CPUs 0.01 s/step 0.5 days/ns") is None


# ---------------------------------------------------------------------------
# Throughput + cost
# ---------------------------------------------------------------------------


def test_ns_per_day_inverts_days_per_ns():
    log = "Info: Benchmark time: 32 CPUs 0.004 s/step 0.05 days/ns 1200 MB memory"
    assert bm.parse_days_per_ns(log) == pytest.approx(0.05)
    assert bm.ns_per_day(log) == pytest.approx(20.0)


def test_last_benchmark_line_wins():
    """NAMD prints several; the later ones are warmed up and are the honest number."""
    log = (
        "Info: Benchmark time: 32 CPUs 0.02 s/step 0.20 days/ns 1 MB memory\n"
        "Info: Benchmark time: 32 CPUs 0.01 s/step 0.10 days/ns 1 MB memory\n"
    )
    assert bm.ns_per_day(log) == pytest.approx(10.0)


def test_gpu_resident_reports_ns_per_day_directly_not_days_per_ns():
    """NAMD switches units by execution mode. Offload prints `days/ns`; GPU-resident
    prints `ns/day`. Parsing only one silently drops every cell of the other mode —
    the resident cell came back rc=0 with no throughput and read as a failure."""
    resident = "Info: Benchmark time: 16 CPUs 0.0516647 s/step 6.68928 ns/day 0 MB memory"
    offload = "Info: Benchmark time: 16 CPUs 0.0483142 s/step 0.139798 days/ns 0 MB memory"
    assert bm.ns_per_day(resident) == pytest.approx(6.68928)
    assert bm.ns_per_day(offload) == pytest.approx(1 / 0.139798, rel=1e-4)


def test_initial_time_lines_are_ignored():
    """`Initial time` is pre-warmup and reads slower. Only `Benchmark time` counts."""
    log = (
        "Info: Initial time: 16 CPUs 0.0602873 s/step 5.73255 ns/day 0 MB memory\n"
        "Info: Benchmark time: 16 CPUs 0.0516647 s/step 6.68928 ns/day 0 MB memory\n"
    )
    assert bm.ns_per_day(log) == pytest.approx(6.68928)


def test_no_benchmark_line_is_none_not_zero():
    assert bm.ns_per_day("FATAL ERROR: it died") is None


def test_cost_per_ns_at_community_cloud_rate():
    # 10 ns/day => 2.4 h/ns => 2.4 * 0.34
    assert bm.cost_per_ns(10.0, 0.34) == pytest.approx(0.816)
    assert bm.cost_per_ns(None, 0.34) is None
    assert bm.cost_per_ns(0.0, 0.34) is None


def test_parse_atom_count():
    assert bm.parse_atom_count("Info: 4695675 ATOMS") == 4695675


# ---------------------------------------------------------------------------
# Conf rewriting — must move ONLY integrator/execution knobs
# ---------------------------------------------------------------------------

SRC_CONF = """structure          VoltronCore.psf
coordinates        VoltronCore.pdb
PME                yes
cutoff             10.0
rigidBonds         all
timestep           2.0
fullElectFrequency 2
stepspercycle      12
outputEnergies     9600
dcdFreq            9600
outputName         output/VoltronCore_01
dcdFile            output/VoltronCore_01.dcd
xstFile            output/VoltronCore_01.xst
temperature        0
langevinPiston     on
extraBondsFile     VoltronCore_k0.5.enm.extra
binCoordinates     output/VoltronCore_00_min.coor
run                240000
"""


def test_bench_conf_swaps_psf_and_timestep_and_steps():
    out = bm.make_bench_conf(
        SRC_CONF,
        psf="VoltronCore_hmr.psf",
        timestep_fs=4.0,
        gpu_resident=False,
        run_steps=2400,
        out_stem="output/bench_A2",
        seed_stem="output/min",
    )
    assert "structure          VoltronCore_hmr.psf" in out
    assert "timestep           4" in out
    assert "run                2400" in out
    assert "outputName         output/bench_A2" in out
    assert "binCoordinates     output/min.coor" in out


def test_run_is_the_last_directive_and_gpu_resident_precedes_it():
    """NAMD executes `run` immediately; anything after it is a runtime change to a
    finished run. GPUresident placed after `run` dies with "Can't modify
    CUDASOAintegrate when that mode was never enabled" — AFTER silently running the
    whole segment in offload mode, so the cell reports a plain-offload speed under a
    GPU-resident label. This exact bug produced a bogus 6hb result."""
    out = bm.make_bench_conf(
        SRC_CONF, psf="p.psf", timestep_fs=4.0, gpu_resident=True,
        run_steps=2400, out_stem="o", seed_stem="s",
    )
    lines = [l for l in out.splitlines() if l.strip()]
    assert lines[-1].split()[0] == "run", lines[-1]
    assert sum(1 for l in lines if l.startswith("run")) == 1
    gpu_i = next(i for i, l in enumerate(lines) if l.startswith("GPUresident"))
    assert gpu_i < len(lines) - 1


def test_bench_conf_adds_and_removes_gpu_resident():
    on = bm.make_bench_conf(
        SRC_CONF, psf="p.psf", timestep_fs=4.0, gpu_resident=True,
        run_steps=2400, out_stem="o", seed_stem="s",
    )
    off = bm.make_bench_conf(
        SRC_CONF, psf="p.psf", timestep_fs=4.0, gpu_resident=False,
        run_steps=2400, out_stem="o", seed_stem="s",
    )
    assert "GPUresident" in on
    assert "GPUresident" not in off


def test_bench_conf_drops_temperature_when_seeding_velocities():
    """NAMD refuses `temperature` and `binVelocities` together."""
    out = bm.make_bench_conf(
        SRC_CONF, psf="p.psf", timestep_fs=2.0, gpu_resident=False,
        run_steps=2400, out_stem="o", seed_stem="s",
    )
    assert "binVelocities" in out
    assert not any(l.startswith("temperature") for l in out.splitlines())


def test_bench_conf_preserves_the_physics():
    """Electrostatics, cutoffs, barostat and the ENM restraints must NOT move —
    otherwise we are benchmarking a simulation nobody would ever run."""
    out = bm.make_bench_conf(
        SRC_CONF, psf="p.psf", timestep_fs=4.0, gpu_resident=True,
        run_steps=2400, out_stem="o", seed_stem="s",
    )
    assert "PME                yes" in out
    assert "cutoff             10.0" in out
    assert "langevinPiston     on" in out
    assert "extraBondsFile     VoltronCore_k0.5.enm.extra" in out
    assert "fullElectFrequency 2" in out


def test_bench_steps_is_a_multiple_of_stepspercycle():
    """NAMD hard-rejects a `run` that is not a multiple of stepspercycle."""
    assert bm.BENCH_STEPS % bm.STEPSPERCYCLE == 0


# ---------------------------------------------------------------------------
# Matrix shape
# ---------------------------------------------------------------------------


def test_every_cell_names_a_real_package():
    for cell in bm.MATRIX:
        assert cell.package in bm.PACKAGES, cell.cid


def test_gpu_resident_is_only_ever_attempted_on_cuda_cells():
    for cell in bm.MATRIX:
        if cell.cfg.gpu_resident:
            assert cell.cfg.build == "cuda", cell.cid


def test_unrunnable_designs_are_excluded_but_still_named():
    """An unrunnable package must not burn GPU minutes — but it must still be NAMED
    in the report, so the exclusion is a stated result, not a silent omission."""
    blocked = bm.Package(key="x", label="X", why="", runnable=False, blocked_reason="because")
    assert not blocked.runnable
    for cell in bm.MATRIX:
        assert bm.PACKAGES[cell.package].runnable, cell.cid


def test_voltroncore_is_runnable_again_after_the_rebuild():
    """The package that shipped with job f702f4a3282f was corrupt (279 coincident
    atoms, min distance 0.000 A) and NaN'd NAMD's minimiser at step 0. A rebuild from
    the SAME design is clean (0 coincident, min 0.408 A) — the design was never the
    problem, so VoltronCore belongs in the matrix."""
    assert bm.PACKAGES["voltron"].runnable
    assert any(c.package == "voltron" for c in bm.MATRIX)


def test_the_shipped_config_is_the_baseline_and_is_2fs_without_hmr():
    cons = next(c for c in bm.CONFIGS if c.key == "conservative")
    assert cons.timestep_fs == 2.0
    assert not cons.hmr and not cons.gpu_resident


def test_fast_offload_keeps_4fs():
    """Superseded 2026-07-12: 4 fs is viable on the offload path WITHOUT residency.
    If someone 'fixes' this to 2 fs, the benchmark measures a config we don't run."""
    fast = next(c for c in bm.CONFIGS if c.key == "fast_offload")
    assert fast.timestep_fs == 4.0
    assert fast.hmr and not fast.gpu_resident


def test_degenerate_structure_outranks_everything():
    """A NaN minimiser means the STRUCTURE is broken. If a hardware signature were
    matched first we would go buy a bigger GPU to fix a geometry bug."""
    log = "LINE MINIMIZER BRACKET: DX 0 1.28e-07 DU nan nan DUDX -nan -nan -nan"
    kind, why = bm.classify_failure(log)
    assert kind == "degenerate_structure"
    assert "hardware" in why.lower()


def test_no_kernel_image_names_the_right_arch():
    kind, why = bm.classify_failure("FATAL: no kernel image is available for execution")
    assert kind == "no_kernel_image"
    assert "sm_89" in why


def test_report_renders_without_results():
    out = bm.render_report(bm.HostInfo(), [])
    assert "not run" in out
