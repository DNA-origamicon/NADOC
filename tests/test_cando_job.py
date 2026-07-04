"""Tests for the CanDo FEM job model + runner (Phase-5 Item 1).

Covers the persistence round-trip, the threaded predict_shape lifecycle
(create → run → completed with cached display/RMSF), and status reconcile. The
FEM numerics themselves are validated in tests/test_fem_solver.py; here we assert
the JOB machinery wraps predict_shape correctly and is Physical-layer only.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.core.models import LatticeType


@pytest.fixture(scope="module")
def routed_6hb():
    from backend.api import headless_build as hb
    from backend.api import state as design_state

    cells = [(0, 1), (1, 1), (1, 2), (1, 3), (0, 3), (0, 2)]
    with hb.scratch_session(LatticeType.HONEYCOMB):
        hb.create_bundle(cells, 84, lattice=LatticeType.HONEYCOMB, name="6hb")
        hb.auto_scaffold(seamless=False)
        hb.auto_crossover()
        hb.auto_break()
        return design_state.get_or_404().model_copy(deep=True)


def _run_to_completion(design, ws: Path, *, nonlinear: bool):
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoJob, CandoStatus, new_cando_job

    job = new_cando_job("6hb", nonlinear=nonlinear, with_rmsf=True, n_steps=5,
                        n_nucleotides=1000)
    job.status = CandoStatus.preparing
    job.save(ws)
    cr.prepare_cando_job(design, job, ws)
    job.status = CandoStatus.running
    job.save(ws)
    cr.start_job(job, ws)
    for _ in range(240):                       # ≤120 s guard
        if not cr.is_running(job.job_id):
            break
        time.sleep(0.5)
    return CandoJob.load(job.job_id, ws)


def test_job_persistence_roundtrip(tmp_path):
    from backend.core.cando_job import CandoJob, CandoStatus, new_cando_job

    job = new_cando_job("mydesign", nonlinear=False, n_steps=12, with_rmsf=False,
                        n_nucleotides=500, design_source_path="/ws/mydesign.nadoc")
    job.save(tmp_path)
    loaded = CandoJob.load(job.job_id, tmp_path)
    assert loaded.job_id == job.job_id
    assert loaded.nonlinear is False
    assert loaded.n_steps == 12
    assert loaded.with_rmsf is False
    assert loaded.status == CandoStatus.queued
    assert loaded.stages and loaded.stages[0].name == "linear"
    # list_jobs finds it
    ids = [j.job_id for j in CandoJob.list_jobs(tmp_path)]
    assert job.job_id in ids


def test_new_job_stage_name_tracks_solver(tmp_path):
    from backend.core.cando_job import new_cando_job

    assert new_cando_job("d", nonlinear=True).stages[0].name == "nonlinear"
    assert new_cando_job("d", nonlinear=False).stages[0].name == "linear"


def test_linear_job_completes_and_caches(routed_6hb, tmp_path):
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoStatus

    job = _run_to_completion(routed_6hb, tmp_path, nonlinear=False)
    assert job.status == CandoStatus.completed
    assert job.sim_seconds is not None and job.sim_seconds >= 0
    assert job.n_nodes and job.n_nodes > 0
    assert job.rmsf_min_nm is not None and job.rmsf_max_nm is not None
    assert 0.0 <= job.rmsf_min_nm <= job.rmsf_max_nm

    disp = cr.load_display(job.job_dir(tmp_path))
    assert disp and disp["solver"] == "linear"
    # The display covers EVERY nucleotide, not just the duplex-core mesh nodes:
    # two entries (FORWARD/REVERSE) per axis node PLUS the gap-filled ssDNA scaffold
    # ends + loop/skip bases (which ride along their nearest covered bp).  So the
    # position count strictly exceeds 2 * n_nodes whenever the design has ss ends /
    # loops — the fix for the "stranded ssDNA/loop" deform-display bug.
    assert len(disp["positions"]) >= 2 * job.n_nodes
    for p in disp["positions"][:5]:
        assert set(p) >= {"helix_id", "bp_index", "direction", "backbone_position"}
        assert len(p["backbone_position"]) == 3

    rmsf = cr.load_rmsf(job.job_dir(tmp_path))
    assert rmsf and len(rmsf["rmsf"]) == job.n_nodes


def test_progress_and_reconcile(routed_6hb, tmp_path):
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoJob, CandoStatus

    job = _run_to_completion(routed_6hb, tmp_path, nonlinear=False)
    prog = cr.job_progress(job, tmp_path)
    assert prog["overall"] == 1.0 and prog["status"] == "completed"

    # A completed job with a cached display reconciles to completed even if its
    # persisted status were flipped back to running by an interrupted run.
    job.status = CandoStatus.running
    job.save(tmp_path)
    reconciled = cr.reconcile_cando_status(CandoJob.load(job.job_id, tmp_path), tmp_path)
    assert reconciled.status == CandoStatus.completed


def test_stop_marks_stray_running_stopped(tmp_path):
    from backend.core import cando_runner as cr
    from backend.core.cando_job import CandoJob, CandoStatus, new_cando_job

    # No live thread → stop() marks a stray running job stopped.
    job = new_cando_job("d", nonlinear=True)
    job.status = CandoStatus.running
    job.save(tmp_path)
    assert cr.stop_job(job.job_id, tmp_path) is False
    assert CandoJob.load(job.job_id, tmp_path).status == CandoStatus.stopped
