"""Unit tests for backend/core/slurm_script.py — pure, offline."""

from __future__ import annotations

from dataclasses import replace

import pytest

from backend.core import cluster_config as cc
from backend.core import cluster_resources as cr
from backend.core import slurm_script as ss


@pytest.fixture
def alpine():
    return cc.alpine_profile()


def _manifest(declash=False):
    return {
        "name_stem": "6hb_demo",
        "declash": declash,
        "relax_protocol_settings": {"timestep_fs": 2.0},
        "charge_audit": {"final_solvated": {"n_atoms": 100_000}},
        "minimization": {"name": "6hb_demo_00_min"},
        "segments": [
            {"name": "6hb_demo_01_p100", "steps": 1_000_000},
            {"name": "6hb_demo_02_p100", "steps": 1_000_000},
        ],
    }


@pytest.fixture
def gpu_resources(alpine):
    return cr.recommend(alpine, n_atoms=100_000, total_ns=4.0, measured_ns_per_day=50.0)


# ── is_gpu_target ─────────────────────────────────────────────────────────────

def test_is_gpu_target_gpu_partition(alpine, gpu_resources):
    assert gpu_resources["partition"] == "aa100"
    assert ss.is_gpu_target(alpine, gpu_resources) is True


def test_is_gpu_target_cpu_partition(alpine):
    cpu = cr.recommend(alpine, n_atoms=100_000, total_ns=4.0, partition="amilan")
    assert cpu["kind"] == "cpu"
    assert ss.is_gpu_target(alpine, cpu) is False


def test_is_gpu_target_unknown_partition_raises(alpine):
    with pytest.raises(ValueError):
        ss.is_gpu_target(alpine, {"partition": "nope"})


# ── strip_gpu_resident (conf amendment for CPU/multicore targets) ──────────────

def test_strip_gpu_resident_removes_directive():
    from backend.core.md_protocols import strip_gpu_resident
    conf = "timestep           4\nGPUresident        on\nrun                600000\n"
    out = strip_gpu_resident(conf)
    assert "GPUresident" not in out
    # surrounding directives are preserved, no blank-line pileup that breaks NAMD
    assert "timestep           4" in out
    assert "run                600000" in out


def test_strip_gpu_resident_noop_when_absent():
    from backend.core.md_protocols import strip_gpu_resident
    conf = "timestep           1\nrigidBonds         none\nrun                120000\n"
    assert strip_gpu_resident(conf) == conf


def test_strip_gpu_resident_idempotent():
    from backend.core.md_protocols import strip_gpu_resident
    conf = "a\nGPUresident on\nb\n"
    once = strip_gpu_resident(conf)
    assert strip_gpu_resident(once) == once
    assert "GPUresident" not in once


# ── build_remote_resume_conf (mid-segment checkpoint resume) ───────────────────

def test_build_remote_resume_conf_continues_from_checkpoint():
    from backend.core.md_protocols import build_remote_resume_conf
    conf = (
        "structure          x.psf\n"
        "binCoordinates     start.coor\n"
        "firsttimestep      0\n"
        "dcdFile            output/seg.dcd\n"
        "run                480000\n"
    )
    out = build_remote_resume_conf(conf, segment_name="seg", restart_step=144000,
                                   total_steps=480000, cont_index=2)
    # original coord/run/dcd/firsttimestep dropped, restart directives re-emitted
    assert "binCoordinates     output/seg.restart.coor" in out
    assert "binVelocities      output/seg.restart.vel" in out
    assert "extendedSystem     output/seg.restart.xsc" in out
    assert "firsttimestep      144000" in out
    assert "run                336000" in out             # 480000 - 144000
    assert "output/seg.cont2.dcd" in out
    assert "structure          x.psf" in out              # untouched directives kept
    assert "binCoordinates     start.coor" not in out     # old coords directive gone


def test_build_remote_resume_conf_rejects_completed_step():
    from backend.core.md_protocols import build_remote_resume_conf
    with pytest.raises(ValueError):
        build_remote_resume_conf("run 100\n", segment_name="s",
                                 restart_step=100, total_steps=100)


def test_generate_resume_sbatch_runs_resume_conf_for_interrupted(alpine, gpu_resources):
    interrupted = "6hb_demo_01_p100"
    script = ss.generate_sbatch(
        _manifest(), alpine, gpu_resources, "/scratch/x",
        resume_conf_for={interrupted: f"{interrupted}.resume"},
    )
    # completed-segment skip guard still keys on the segment's final .coor
    assert f'if [ -f "output/{interrupted}.coor" ]; then' in script
    # the interrupted segment runs its resume conf + logs to .resume.log
    assert f"{interrupted}.resume.conf" in script
    assert f"{interrupted}.resume.log" in script
    assert "resuming from checkpoint" in script
    # a NON-resumed segment still runs its normal conf
    assert "6hb_demo_02_p100.conf" in script


# ── sanitize_job_name ─────────────────────────────────────────────────────────

def test_sanitize_keeps_safe_chars():
    assert ss.sanitize_job_name("6hb_2xT.v3-1") == "6hb_2xT.v3-1"


def test_sanitize_collapses_bad_chars():
    assert ss.sanitize_job_name("my job / name!") == "my_job_name"


def test_sanitize_rejects_empty():
    with pytest.raises(ValueError):
        ss.sanitize_job_name("   ")
    with pytest.raises(ValueError):
        ss.sanitize_job_name("///")


# ── generate_sbatch: structure ────────────────────────────────────────────────

def test_generate_has_shebang_and_directives(alpine, gpu_resources):
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/alpine/jojo/nadoc_jobs/j1")
    assert script.startswith("#!/bin/bash\n")
    assert "#SBATCH --job-name=6hb_demo" in script
    assert f"#SBATCH --partition={gpu_resources['partition']}" in script
    assert f"#SBATCH --time={gpu_resources['walltime']}" in script
    assert f"#SBATCH --qos={gpu_resources['qos']}" in script
    assert "#SBATCH --nodes=1" in script


def test_generate_runs_min_then_all_segments_in_order(alpine, gpu_resources):
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    i_min = script.index("6hb_demo_00_min.conf")
    i_s1 = script.index("6hb_demo_01_p100.conf")
    i_s2 = script.index("6hb_demo_02_p100.conf")
    assert i_min < i_s1 < i_s2


def test_ladder_is_idempotent_skip_guarded(alpine, gpu_resources):
    """Each step is guarded by an ``output/<conf>.coor`` existence check so a
    resubmit onto the same scratch resumes at the first unfinished segment
    (auto-resubmit-on-TIMEOUT recovery)."""
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    assert 'if [ -f "output/6hb_demo_01_p100.coor" ]; then' in script
    assert "skip 6hb_demo_01_p100 (already complete)" in script
    # The min step is guarded too.
    assert 'if [ -f "output/6hb_demo_00_min.coor" ]; then' in script


def test_gpu_exec_line_is_gpu_resident(alpine, gpu_resources):
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    # aa100 requires a TYPED GRES — bare "gpu:1" is rejected by SLURM.
    assert "#SBATCH --gres=gpu:a100-40gb:1" in script


def test_untyped_gres_when_partition_has_no_gres_type(alpine):
    # A GPU partition without a gres_type falls back to the untyped form.
    res = cr.recommend(alpine, n_atoms=100_000, total_ns=4.0, measured_ns_per_day=50.0)
    res["gres_type"] = ""       # simulate a profile that doesn't specify the type
    script = ss.generate_sbatch(_manifest(), alpine, res, "/scratch/x")
    assert "#SBATCH --gres=gpu:1" in script
    assert "+setcpuaffinity +devices 0" in script
    assert "namd3 +p" in script
    assert "mpirun" not in script


def test_cpu_partition_uses_mpirun(alpine):
    res = cr.recommend(alpine, n_atoms=cr._GPU_ATOM_CEILING + 1, total_ns=4.0,
                       measured_ns_per_day=5.0)
    script = ss.generate_sbatch(_manifest(), alpine, res, "/scratch/x")
    assert "mpirun -np $SLURM_NTASKS namd3" in script
    assert "+devices" not in script
    assert "--gres=gpu" not in script


def test_module_block_present(alpine, gpu_resources):
    # A GPU target loads the GPU (CUDA) NAMD build, not the CPU MPI module set.
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    assert "module purge" in script
    assert "module load " + " ".join(alpine.modules_for(gpu=True)) in script
    assert "namd/3.0.1_gpu" in script


def test_cpu_target_loads_cpu_module_block(alpine):
    cpu = cr.recommend(alpine, n_atoms=100_000, total_ns=4.0, partition="amilan")
    script = ss.generate_sbatch(_manifest(), alpine, cpu, "/scratch/x")
    assert "module load " + " ".join(alpine.module_loads) in script
    assert "namd/3.0.1_cpu" in script and "namd/3.0.1_gpu" not in script


def test_profile_sourced_before_errexit_and_no_nounset(alpine, gpu_resources):
    # Regression: Alpine's /etc/profile references unbound vars; `set -u` before the
    # source aborted a real job at "line 47: HISTCONTROL: unbound variable" before
    # NAMD ran.  Source must precede errexit, and -u must be gone.
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    assert "set -euo pipefail" not in script          # no nounset
    assert "set -uo" not in script and "set -u\n" not in script
    assert "set -eo pipefail" in script
    assert script.index("source /etc/profile") < script.index("set -eo pipefail")


def test_cd_into_scratch(alpine, gpu_resources):
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/alpine/jojo/nadoc_jobs/j1")
    assert "cd '/scratch/alpine/jojo/nadoc_jobs/j1'" in script


def test_job_name_override_is_sanitized(alpine, gpu_resources):
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x",
                                job_name="run for paper")
    assert "#SBATCH --job-name=run_for_paper" in script


# ── module/partition sanity warning ───────────────────────────────────────────

def test_gpu_with_cpu_module_warns(alpine, gpu_resources):
    # A GPU partition whose GPU module set is (mis)configured CPU-only must warn.
    cpu_gpu_profile = replace(alpine, gpu_module_loads=["gcc/14.2.0", "namd/3.0.1_cpu"])
    script = ss.generate_sbatch(_manifest(), cpu_gpu_profile, gpu_resources, "/scratch/x")
    assert "WARNING" in script and "CPU-only" in script


def test_gpu_with_gpu_module_does_not_warn(alpine, gpu_resources):
    # The default Alpine profile now ships a GPU-resident module for GPU partitions.
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    assert "WARNING" not in script


# ── generate_sbatch: guards ───────────────────────────────────────────────────

def test_declash_manifest_is_rejected(alpine, gpu_resources):
    with pytest.raises(ValueError, match="[Dd]eclash"):
        ss.generate_sbatch(_manifest(declash=True), alpine, gpu_resources, "/scratch/x")


def test_unknown_partition_is_rejected(alpine, gpu_resources):
    bad = dict(gpu_resources, partition="nonexistent")
    with pytest.raises(ValueError, match="partition"):
        ss.generate_sbatch(_manifest(), alpine, bad, "/scratch/x")


def test_manifest_without_segments_is_rejected(alpine, gpu_resources):
    m = _manifest()
    m["segments"] = []
    with pytest.raises(ValueError, match="segments"):
        ss.generate_sbatch(m, alpine, gpu_resources, "/scratch/x")


def test_gpu_job_omits_infiniband_constraint(alpine, gpu_resources):
    # Single-node GPU-resident runs must NOT request --constraint=ib (over-constrains
    # aa100 node selection → "node configuration not available").
    script = ss.generate_sbatch(_manifest(), alpine, gpu_resources, "/scratch/x")
    assert "--constraint=ib" not in script


def test_cpu_job_keeps_infiniband_constraint(alpine):
    # CPU/MPI runs still want InfiniBand.
    res = cr.recommend(alpine, n_atoms=5_000_000, total_ns=2.0, measured_ns_per_day=50.0)
    assert res["kind"] == "cpu"
    script = ss.generate_sbatch(_manifest(), alpine, res, "/scratch/x")
    assert "#SBATCH --constraint=ib" in script
