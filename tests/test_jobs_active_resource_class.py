"""`/api/jobs/active` tags each job with a ``resource_class`` ("gpu"/"cpu") so the
frontend guard only makes jobs that actually contend block each other. A local
NAMD run and a CUDA oxDNA run hold the GPU; a CPU-backend oxDNA run (e.g. an
E-field study) uses only spare cores and may launch alongside a GPU job.
"""

from __future__ import annotations

import backend.api.routes_jobs as routes_jobs
import backend.core.namd_runner as namd_runner
import backend.core.oxdna_runner as oxdna_runner
from backend.core.md_job import MdStatus, new_job
from backend.core.oxdna_job import OxdnaStatus, new_oxdna_job


def _make_md_job(ws):
    job = new_job(
        design_name="md_d",
        protocol="mgh_slow_release",
        name_stem="md_d",
        package_subdir="pkg",
        design_source_path="/w/md.nadoc",
    )
    job.status = MdStatus.running
    job.save(ws)
    return job


def _make_oxdna_job(ws, *, backend, name):
    job = new_oxdna_job(
        design_name=name,
        stages=[],
        backend=backend,
        design_source_path=f"/w/{name}.nadoc",
    )
    job.status = OxdnaStatus.running
    job.save(ws)
    return job


def test_collect_active_tags_resource_class(tmp_path, monkeypatch):
    ws = tmp_path
    monkeypatch.setattr(routes_jobs, "_WORKSPACE_DIR", ws)
    # Keep the fixture jobs "running": reconcile would flip a persisted-running
    # job with no live process to a terminal state, and the ETA readers touch the
    # (absent) logs.
    monkeypatch.setattr(routes_jobs, "_md_eta_seconds", lambda *a, **k: None)
    monkeypatch.setattr(routes_jobs, "_oxdna_eta_seconds", lambda *a, **k: None)
    monkeypatch.setattr(namd_runner, "reconcile_job_status", lambda j, w: j)
    monkeypatch.setattr(oxdna_runner, "reconcile_oxdna_status", lambda j, w: j)

    _make_md_job(ws)
    _make_oxdna_job(ws, backend="CUDA", name="ox_cuda")
    _make_oxdna_job(ws, backend="CPU", name="ox_cpu")

    active = routes_jobs._collect_active()
    by_name = {j["design_name"]: j for j in active}

    # NAMD is always GPU-resident here.
    assert by_name["md_d"]["resource_class"] == "gpu"
    # oxDNA follows its backend.
    assert by_name["ox_cuda"]["resource_class"] == "gpu"
    assert by_name["ox_cpu"]["resource_class"] == "cpu"
    assert all("resource_class" in j for j in active)
