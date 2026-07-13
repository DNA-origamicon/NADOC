"""Tests for the SNUPI FEM job model + runner + routes (P5 frontend-tab backend).

SNUPI is the SAME in-process FEM as CanDo, run with the anisotropic SNUPI material law
(``predict_shape(material="snupi")``).  The solver numerics + material are validated in
tests/test_snupi_{params,material,element}.py; here we assert the JOB machinery wraps
predict_shape correctly (threading ``material``), persists, and normalizes for the unified
list — Physical-layer only.
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


def _run_to_completion(design, ws: Path, *, nonlinear: bool, material: str = "snupi"):
    from backend.core import snupi_runner as sr
    from backend.core.snupi_job import SnupiJob, SnupiStatus, new_snupi_job

    job = new_snupi_job("6hb", nonlinear=nonlinear, with_rmsf=True, n_steps=5,
                        material=material, n_nucleotides=1000)
    job.status = SnupiStatus.preparing
    job.save(ws)
    sr.prepare_snupi_job(design, job, ws)
    job.status = SnupiStatus.running
    job.save(ws)
    sr.start_job(job, ws)                       # detached worker subprocess
    for _ in range(240):                       # ≤120 s guard
        if not sr.is_running(job.job_id, ws):
            break
        time.sleep(0.5)
    return SnupiJob.load(job.job_id, ws)


def test_job_persistence_roundtrip(tmp_path):
    from backend.core.snupi_job import SnupiJob, SnupiStatus, new_snupi_job

    job = new_snupi_job("mydesign", nonlinear=False, n_steps=12, with_rmsf=False,
                        material="snupi", n_nucleotides=500,
                        design_source_path="/ws/mydesign.nadoc")
    job.save(tmp_path)
    loaded = SnupiJob.load(job.job_id, tmp_path)
    assert loaded.job_id == job.job_id
    assert loaded.nonlinear is False
    assert loaded.n_steps == 12
    assert loaded.with_rmsf is False
    assert loaded.material == "snupi"
    assert loaded.status == SnupiStatus.queued
    assert loaded.stages and loaded.stages[0].name == "linear"
    ids = [j.job_id for j in SnupiJob.list_jobs(tmp_path)]
    assert job.job_id in ids


def test_new_job_stage_name_tracks_solver(tmp_path):
    from backend.core.snupi_job import new_snupi_job

    assert new_snupi_job("d", nonlinear=True).stages[0].name == "nonlinear"
    assert new_snupi_job("d", nonlinear=False).stages[0].name == "linear"
    # Dynamics jobs run a Langevin trajectory, not the static solve → honest stage label.
    assert new_snupi_job("d", dynamics=True).stages[0].name == "dynamics"
    assert new_snupi_job("d", dynamics=True, hydrodynamics=True).stages[0].name == "dynamics-rpy"


def test_estimate_seconds_accounts_for_dynamics_and_rpy():
    """The progress-bar ETA must reflect the dynamics/RPY workload: a Langevin run (fixed 60k GJF
    steps) is far slower than the ~20-step static solve, and full-RPY hydrodynamics slower still —
    otherwise ``overall = elapsed/est`` pins at its 0.97 cap in seconds while minutes of work run."""
    from backend.core.snupi_runner import _estimate_seconds
    from backend.core.snupi_job import new_snupi_job

    nuc = 1764  # ≈ 882 FEM nodes, the demo design
    static = _estimate_seconds(new_snupi_job("d", nonlinear=True, n_nucleotides=nuc))
    dyn = _estimate_seconds(new_snupi_job("d", dynamics=True, n_nucleotides=nuc))
    rpy = _estimate_seconds(new_snupi_job("d", dynamics=True, hydrodynamics=True, n_nucleotides=nuc))

    # The pin bug was RPY-only: the old static model estimated ~47 s for a run that took 658 s.
    assert rpy > static                      # RPY estimate now exceeds the old static figure
    assert rpy > 5.0 * dyn                   # dense RPY friction dominates the Langevin base cost
    assert 300.0 < rpy < 1500.0              # order-of-magnitude sane for ~880 nodes (observed ≈ 650 s)
    assert dyn > 2.0                         # Stokes dynamics still gets a real (non-trivial) estimate


def test_material_defaults_snupi_and_is_validated(tmp_path):
    """The material knob defaults to 'snupi', accepts 'cando', and rejects garbage → 'snupi'."""
    from backend.core.snupi_job import SnupiJob, new_snupi_job

    assert new_snupi_job("d").material == "snupi"
    assert new_snupi_job("d", material="cando").material == "cando"
    assert new_snupi_job("d", material="bogus").material == "snupi"
    # A legacy job.json without the material key loads as 'snupi'.
    import json
    job = new_snupi_job("d")
    job.save(tmp_path)
    p = job.job_dir(tmp_path) / "job.json"
    data = json.loads(p.read_text())
    data.pop("material", None)
    p.write_text(json.dumps(data))
    assert SnupiJob.load(job.job_id, tmp_path).material == "snupi"


def test_job_roundtrips_anchors_and_field(tmp_path):
    from backend.core.snupi_job import SnupiJob, new_snupi_job

    anchors = [{"kind": "cluster", "id": "c1"}]
    field = {"field_pN": 0.2, "dir": [0.0, 1.0, 0.0]}
    job = new_snupi_job("d", anchors=anchors, field=field)
    job.save(tmp_path)
    loaded = SnupiJob.load(job.job_id, tmp_path)
    assert loaded.anchors == anchors
    assert loaded.field == field
    plain = new_snupi_job("d")
    assert plain.anchors is None and plain.field is None


def test_create_request_model_defaults_and_material():
    from backend.api.routes_snupi import CreateSnupiJobRequest

    assert CreateSnupiJobRequest().material == "snupi"
    assert CreateSnupiJobRequest().anchors is None
    req = CreateSnupiJobRequest(material="cando",
                                anchors=[{"kind": "cluster", "id": "c1"}],
                                field={"field_pN": 0.1, "dir": [1, 0, 0]})
    assert req.material == "cando"
    assert req.field == {"field_pN": 0.1, "dir": [1, 0, 0]}


def test_runner_forwards_material_anchors_field_to_predict_shape(routed_6hb, tmp_path, monkeypatch):
    """The load-bearing wiring: a SNUPI job's material + anchors + field reach predict_shape.

    Exercises ``solve_and_cache`` in-process (the exact body the detached worker runs), so the
    monkeypatched spy is visible — a real subprocess worker would import the true predict_shape.
    """
    import backend.physics.fem_solver as fs
    from backend.core import snupi_runner as sr
    from backend.core.snupi_job import SnupiStatus, new_snupi_job

    captured = {}

    def _spy(design, **kw):
        captured.update(kw)
        raise RuntimeError("stop-after-capture")

    monkeypatch.setattr(fs, "predict_shape", _spy)

    anchors = [{"kind": "base", "helix_id": routed_6hb.helices[0].id, "bp": 5,
                "direction": "forward"}]
    field = {"field_pN": 0.1, "dir": [1.0, 0.0, 0.0]}
    job = new_snupi_job("6hb", nonlinear=False, with_rmsf=False, n_steps=5,
                        material="snupi", n_nucleotides=1000, anchors=anchors, field=field)
    job.status = SnupiStatus.preparing
    job.save(tmp_path)
    sr.prepare_snupi_job(routed_6hb, job, tmp_path)
    sr.solve_and_cache(job, tmp_path)          # in-process → the spy applies
    assert captured.get("material") == "snupi"
    assert captured.get("anchors") == anchors
    assert captured.get("field") == field
    # The spy raised → solve_and_cache surfaces it as a failed job (never re-raises).
    assert job.status == SnupiStatus.failed
    assert "stop-after-capture" in (job.error or "")


def test_linear_snupi_job_completes_and_caches(routed_6hb, tmp_path):
    from backend.core import snupi_runner as sr
    from backend.core.snupi_job import SnupiStatus

    job = _run_to_completion(routed_6hb, tmp_path, nonlinear=False)
    assert job.status == SnupiStatus.completed
    assert job.sim_seconds is not None and job.sim_seconds >= 0
    assert job.n_nodes and job.n_nodes > 0
    assert job.rmsf_min_nm is not None and job.rmsf_max_nm is not None
    assert 0.0 <= job.rmsf_min_nm <= job.rmsf_max_nm

    disp = sr.load_display(job.job_dir(tmp_path))
    assert disp and disp["solver"] == "linear"
    assert len(disp["positions"]) >= 2 * job.n_nodes
    rmsf = sr.load_rmsf(job.job_dir(tmp_path))
    assert rmsf and len(rmsf["rmsf"]) == job.n_nodes


def test_progress_and_reconcile(routed_6hb, tmp_path):
    from backend.core import snupi_runner as sr
    from backend.core.snupi_job import SnupiJob, SnupiStatus

    job = _run_to_completion(routed_6hb, tmp_path, nonlinear=False)
    prog = sr.job_progress(job, tmp_path)
    assert prog["overall"] == 1.0 and prog["status"] == "completed"

    # Simulate an orphaned running job whose detached worker died (dead pid) AFTER caching:
    # reconcile must recover it to completed. (Use a guaranteed-dead pid, not the finished
    # worker's real pid — under parallel test load that pid can be recycled by a live process.)
    job.status = SnupiStatus.running
    job.pid = 2_000_000_000
    job.save(tmp_path)
    reconciled = sr.reconcile_snupi_status(SnupiJob.load(job.job_id, tmp_path), tmp_path)
    assert reconciled.status == SnupiStatus.completed


def test_stop_marks_stray_running_stopped(tmp_path):
    from backend.core import snupi_runner as sr
    from backend.core.snupi_job import SnupiJob, SnupiStatus, new_snupi_job

    job = new_snupi_job("d", nonlinear=True)
    job.status = SnupiStatus.running
    job.save(tmp_path)
    assert sr.stop_job(job.job_id, tmp_path) is False
    assert SnupiJob.load(job.job_id, tmp_path).status == SnupiStatus.stopped


def test_pid_alive_helper():
    import os

    from backend.core import snupi_runner as sr

    assert sr._pid_alive(os.getpid()) is True
    assert sr._pid_alive(None) is False
    assert sr._pid_alive(0) is False
    # A pid that (almost certainly) names no live process.
    assert sr._pid_alive(2_000_000_000) is False


def test_pid_field_persists(tmp_path):
    from backend.core.snupi_job import SnupiJob, new_snupi_job

    job = new_snupi_job("d")
    job.pid = 4242
    job.save(tmp_path)
    assert SnupiJob.load(job.job_id, tmp_path).pid == 4242
    # A legacy job.json without the pid key loads as None.
    import json
    p = job.job_dir(tmp_path) / "job.json"
    data = json.loads(p.read_text())
    data.pop("pid", None)
    p.write_text(json.dumps(data))
    assert SnupiJob.load(job.job_id, tmp_path).pid is None


def test_kill_pid_terminates_detached_process():
    """_kill_pid group-kills a detached (own-session) child — the mechanism stop_job uses."""
    import subprocess

    from backend.core import snupi_runner as sr

    proc = subprocess.Popen(["sleep", "30"], start_new_session=True)
    try:
        assert sr._pid_alive(proc.pid) is True
        sr._kill_pid(proc.pid)
        proc.wait(timeout=5)
        assert sr._pid_alive(proc.pid) is False
    finally:
        if proc.poll() is None:
            proc.kill()


def test_reconcile_completed_when_pid_dead_and_display_cached(tmp_path):
    """A worker that finished (display.json exists) but whose pid is gone → completed."""
    import json

    from backend.core import snupi_runner as sr
    from backend.core.snupi_job import SnupiJob, SnupiStatus, new_snupi_job

    job = new_snupi_job("d", nonlinear=True)
    job.status = SnupiStatus.running
    job.pid = 2_000_000_000                      # dead pid
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "display.json").write_text(json.dumps({"positions": []}))
    out = sr.reconcile_snupi_status(SnupiJob.load(job.job_id, tmp_path), tmp_path)
    assert out.status == SnupiStatus.completed


def test_reconcile_stopped_when_pid_dead_and_no_cache(tmp_path):
    """A worker killed mid-solve (dead pid, no display.json) → stopped, not left running."""
    from backend.core import snupi_runner as sr
    from backend.core.snupi_job import SnupiJob, SnupiStatus, new_snupi_job

    job = new_snupi_job("d", nonlinear=True)
    job.status = SnupiStatus.running
    job.pid = 2_000_000_000                      # dead pid, no display.json written
    job.save(tmp_path)
    out = sr.reconcile_snupi_status(SnupiJob.load(job.job_id, tmp_path), tmp_path)
    assert out.status == SnupiStatus.stopped


def test_reconcile_leaves_running_while_worker_alive(tmp_path):
    """The whole point of the subprocess: a live worker (e.g. surviving a --reload) stays running."""
    import os

    from backend.core import snupi_runner as sr
    from backend.core.snupi_job import SnupiJob, SnupiStatus, new_snupi_job

    job = new_snupi_job("d", nonlinear=True)
    job.status = SnupiStatus.running
    job.pid = os.getpid()                        # a live pid stands in for the worker
    job.save(tmp_path)
    out = sr.reconcile_snupi_status(SnupiJob.load(job.job_id, tmp_path), tmp_path)
    assert out.status == SnupiStatus.running


def test_start_job_spawns_detached_worker_and_completes(routed_6hb, tmp_path):
    """End-to-end: start_job launches a real detached subprocess that solves + caches + completes,
    and records the worker pid on the job (proving the solve ran out-of-process)."""
    from backend.core import snupi_runner as sr
    from backend.core.snupi_job import SnupiJob, SnupiStatus, new_snupi_job

    job = new_snupi_job("6hb", nonlinear=False, with_rmsf=True, n_steps=5,
                        material="snupi", n_nucleotides=1000)
    job.save(tmp_path)
    sr.prepare_snupi_job(routed_6hb, job, tmp_path)
    sr.start_job(job, tmp_path)
    assert job.pid is not None                   # a subprocess was spawned
    for _ in range(240):                         # ≤120 s guard
        if not sr.is_running(job.job_id, tmp_path):
            break
        time.sleep(0.5)
    done = SnupiJob.load(job.job_id, tmp_path)
    assert done.status == SnupiStatus.completed
    assert sr.load_display(done.job_dir(tmp_path)) is not None


def test_normalize_snupi_job_shape():
    """The unified-list normalizer tags the node engine=snupi + a flat relax root."""
    from backend.core.sim_jobs import normalize_snupi_job

    node = normalize_snupi_job({"job_id": "x", "status": "completed", "n_nucleotides": 42})
    assert node["engine"] == "snupi"
    assert node["kind"] == "relax"
    assert node["is_child"] is False
    assert node["production_state"] is None
    assert node["n_units"] == 42
    assert node["viewable"] is True
