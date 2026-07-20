"""BLADE job model + runner unit tests.

Fast-suite only: nothing here launches OpenMM, psfgen, or a subprocess.  The pieces that DO
need the gpu env (``blade_available``'s deep probe, ``relax_and_cache``) are exercised by
monkeypatching their boundaries — the point is to pin the job lifecycle, the guard decisions,
and the request validation, all of which are pure logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core import sim_jobs
from backend.core.blade_job import BladeJob, BladeStatus, new_blade_job
from backend.core import blade_runner


# ── Job model ─────────────────────────────────────────────────────────────────

def test_new_blade_job_defaults_to_relax_with_two_stages():
    job = new_blade_job("mydesign")
    assert job.mode == "relax"
    assert job.correction == "baseline"
    assert job.status == BladeStatus.queued
    # build (uv env, psfgen) then relax (gpu env, OpenMM) — the two process hops.
    assert [s.name for s in job.stages] == ["build", "relax"]
    assert all(s.status == "pending" for s in job.stages)


@pytest.mark.parametrize("field,bad,expected", [
    ("mode", "rollout", "relax"),
    ("correction", "magic", "baseline"),
    ("platform", "OPENCL", "CUDA"),
])
def test_new_blade_job_clamps_unknown_enums(field, bad, expected):
    """An unrecognised value falls back to the safe default rather than reaching the worker,
    where it would fail minutes later inside OpenMM."""
    job = new_blade_job("d", **{field: bad})
    assert getattr(job, field) == expected


def test_save_load_roundtrip(tmp_path: Path):
    job = new_blade_job("d", langevin_ps=7.5, nb_cutoff_A=22.0, platform="CPU")
    job.n_atoms = 1234
    job.save(tmp_path)
    back = BladeJob.load(job.job_id, tmp_path)
    assert back.job_id == job.job_id
    assert back.langevin_ps == 7.5
    assert back.nb_cutoff_A == 22.0
    assert back.platform == "CPU"
    assert back.n_atoms == 1234
    assert [s.name for s in back.stages] == ["build", "relax"]


def test_load_backfills_missing_fields_on_an_older_job_json(tmp_path: Path):
    """A job.json written before a field existed must still load — the panel polls every job
    on disk, so one un-backfilled key would break the whole list, not just that row."""
    job = new_blade_job("d")
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    data = json.loads((jd / "job.json").read_text())
    for k in ("nb_cutoff_A", "traj_frames", "platform", "uncertainty", "temp_K"):
        data.pop(k, None)
    (jd / "job.json").write_text(json.dumps(data))

    back = BladeJob.load(job.job_id, tmp_path)
    assert back.nb_cutoff_A == 18.0
    assert back.traj_frames == 60
    assert back.platform == "CUDA"
    assert back.uncertainty is False
    assert back.temp_K == 300.0


def test_job_dir_is_under_blade_jobs(tmp_path: Path):
    job = new_blade_job("d")
    assert job.job_dir(tmp_path) == tmp_path / "blade_jobs" / job.job_id


# ── Unified job list ──────────────────────────────────────────────────────────

def test_normalize_blade_job_is_a_flat_viewable_root():
    node = sim_jobs.normalize_blade_job(
        {"job_id": "x", "status": "completed", "n_nucleotides": 400})
    assert node["engine"] == "blade"
    assert node["kind"] == "relax"
    assert node["is_child"] is False
    assert node["n_units"] == 400
    assert node["viewable"] is True


def test_normalize_blade_job_not_viewable_until_completed():
    node = sim_jobs.normalize_blade_job({"job_id": "x", "status": "running"})
    assert node["viewable"] is False


# ── Progress estimate ─────────────────────────────────────────────────────────

def test_estimate_scales_with_system_size_and_langevin_time():
    small = new_blade_job("d", n_nucleotides=100)
    big = new_blade_job("d", n_nucleotides=10_000)
    assert blade_runner._estimate_seconds(big) > blade_runner._estimate_seconds(small)

    short = new_blade_job("d", n_nucleotides=1000, langevin_ps=1.0)
    long = new_blade_job("d", n_nucleotides=1000, langevin_ps=30.0)
    assert blade_runner._estimate_seconds(long) > blade_runner._estimate_seconds(short)


def test_cpu_platform_estimate_is_much_larger_than_cuda():
    """A CPU run really is ~20× slower; if the estimate didn't reflect that the bar would pin
    at its cap in seconds and tell the user nothing for the rest of a long run."""
    cuda = new_blade_job("d", n_nucleotides=1000, platform="CUDA")
    cpu = new_blade_job("d", n_nucleotides=1000, platform="CPU")
    assert blade_runner._estimate_seconds(cpu) > 10 * blade_runner._estimate_seconds(cuda)


def test_job_progress_reports_one_for_completed_and_zero_for_failed(tmp_path: Path):
    job = new_blade_job("d")
    job.status = BladeStatus.completed
    job.save(tmp_path)
    assert blade_runner.job_progress(job, tmp_path)["overall"] == 1.0

    job.status = BladeStatus.failed
    assert blade_runner.job_progress(job, tmp_path)["overall"] == 0.0


def test_job_progress_prefers_the_workers_real_fraction(tmp_path: Path):
    """Once the gpu script reports, the bar must follow IT, not the wall-clock guess."""
    import time
    job = new_blade_job("d", n_nucleotides=1000)
    job.status = BladeStatus.running
    job.stages[0].started_at = time.time() - 5.0
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    blade_runner.write_progress(jd, 0.42, "langevin", {"step": 420, "n_steps": 1000})

    prog = blade_runner.job_progress(job, tmp_path)
    assert prog["overall"] == pytest.approx(0.42)
    assert prog["phase"] == "langevin"
    assert prog["step"] == 420


def test_write_progress_clamps_to_unit_interval(tmp_path: Path):
    blade_runner.write_progress(tmp_path, 5.0, "x")
    assert blade_runner.read_progress(tmp_path)["fraction"] == 1.0
    blade_runner.write_progress(tmp_path, -3.0, "x")
    assert blade_runner.read_progress(tmp_path)["fraction"] == 0.0


# ── Sim guard ─────────────────────────────────────────────────────────────────

def test_sim_guard_blocks_a_cuda_run_while_a_heavy_sim_owns_the_machine(monkeypatch):
    monkeypatch.delenv("NADOC_IGNORE_SIM_GUARD", raising=False)
    monkeypatch.setattr("backend.core.hardware.heavy_sim_running",
                        lambda: (True, "NAMD production job 1234"))
    with pytest.raises(RuntimeError, match="heavy simulation"):
        blade_runner._check_sim_guard(new_blade_job("d", platform="CUDA"))


def test_sim_guard_exempts_a_cpu_run(monkeypatch):
    """Choosing CPU is exactly the escape hatch for a busy GPU — the guard must not block it."""
    monkeypatch.delenv("NADOC_IGNORE_SIM_GUARD", raising=False)
    monkeypatch.setattr("backend.core.hardware.heavy_sim_running",
                        lambda: (True, "NAMD production job 1234"))
    blade_runner._check_sim_guard(new_blade_job("d", platform="CPU"))   # no raise


def test_sim_guard_respects_the_override(monkeypatch):
    monkeypatch.setenv("NADOC_IGNORE_SIM_GUARD", "1")
    monkeypatch.setattr("backend.core.hardware.heavy_sim_running",
                        lambda: (True, "NAMD production job 1234"))
    blade_runner._check_sim_guard(new_blade_job("d", platform="CUDA"))   # no raise


def test_sim_guard_fails_open_when_the_probe_raises(monkeypatch):
    """A probe glitch must never block a run the user asked for."""
    monkeypatch.delenv("NADOC_IGNORE_SIM_GUARD", raising=False)

    def _boom():
        raise OSError("procfs unreadable")
    monkeypatch.setattr("backend.core.hardware.heavy_sim_running", _boom)
    blade_runner._check_sim_guard(new_blade_job("d", platform="CUDA"))   # no raise


# ── Reconcile (orphan recovery) ───────────────────────────────────────────────

def test_reconcile_marks_a_dead_worker_with_a_cache_completed(tmp_path: Path):
    job = new_blade_job("d")
    job.status = BladeStatus.running
    job.pid = 999_999_999          # certainly dead
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "display.json").write_text("{}")

    out = blade_runner.reconcile_blade_status(job, tmp_path)
    assert out.status == BladeStatus.completed
    assert all(s.status == "done" for s in out.stages)


def test_reconcile_marks_a_dead_worker_without_a_cache_stopped(tmp_path: Path):
    job = new_blade_job("d")
    job.status = BladeStatus.running
    job.pid = 999_999_999
    job.save(tmp_path)

    out = blade_runner.reconcile_blade_status(job, tmp_path)
    assert out.status == BladeStatus.stopped


def test_reconcile_leaves_a_live_worker_running(tmp_path: Path):
    """The whole point of the detached worker: it survives a uvicorn --reload, and reconcile
    must not then declare it dead."""
    import os
    job = new_blade_job("d")
    job.status = BladeStatus.running
    job.pid = os.getpid()          # alive by construction
    job.save(tmp_path)

    assert blade_runner.reconcile_blade_status(job, tmp_path).status == BladeStatus.running


def test_reconcile_is_a_noop_for_a_terminal_job(tmp_path: Path):
    job = new_blade_job("d")
    job.status = BladeStatus.completed
    job.save(tmp_path)
    assert blade_runner.reconcile_blade_status(job, tmp_path).status == BladeStatus.completed


# ── Environment resolution ────────────────────────────────────────────────────

def test_find_blade_python_honours_the_env_override(tmp_path: Path, monkeypatch):
    prefix = tmp_path / "myenv"
    (prefix / "bin").mkdir(parents=True)
    (prefix / "bin" / "python").write_text("#!/bin/sh\n")
    monkeypatch.setenv("BLADE_OPENMM_ENV", str(prefix))
    assert blade_runner.find_blade_python() == str(prefix / "bin" / "python")


def test_find_blade_python_returns_none_when_the_override_is_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("BLADE_OPENMM_ENV", str(tmp_path / "nope"))
    assert blade_runner.find_blade_python() is None


def test_blade_available_reports_the_missing_interpreter(monkeypatch):
    monkeypatch.setattr(blade_runner, "find_blade_python", lambda: None)
    ok, reason = blade_runner.blade_available()
    assert ok is False
    assert "BLADE_OPENMM_ENV" in reason


# ── Relax failure path ────────────────────────────────────────────────────────

def test_relax_and_cache_marks_failed_when_the_snapshot_is_missing(tmp_path: Path):
    """relax_and_cache must never raise — the worker's only job is to call it, so an
    exception would leave the job stranded 'running' until reconcile guessed."""
    job = new_blade_job("d")
    job.save(tmp_path)
    blade_runner.relax_and_cache(job, tmp_path)      # no design.json written
    assert job.status == BladeStatus.failed
    assert "design snapshot" in (job.error or "")


def test_relax_and_cache_marks_failed_when_no_openmm_env_exists(tmp_path: Path, monkeypatch):
    job = new_blade_job("d")
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / "design.json").write_text("{}")
    monkeypatch.setattr(blade_runner, "_load_snapshot_design", lambda _jd: object())
    monkeypatch.setattr(blade_runner, "build_solute_inputs",
                        lambda _d, _jd: {"n_solute": 10})
    monkeypatch.setattr(blade_runner, "find_blade_python", lambda: None)

    blade_runner.relax_and_cache(job, tmp_path)
    assert job.status == BladeStatus.failed
    assert "OpenMM environment" in (job.error or "")
