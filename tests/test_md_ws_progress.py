"""The MD status WebSocket must stamp `progress_fraction` on its live `state` push.

The master job card's overall progress bar reads `progress_fraction` (backend-stamped)
so it advances instead of reading "hung".  `list_md_jobs` stamps it on REST polls, but
the *live* WS `state` push used to omit it — so a running job whose master card wasn't
self-polling (notably an oxDNA-SEEDED run, which first appears as a DRAFT and so isn't
adopted as the master's active node) showed a frozen bar even while its detail timeline
advanced over the same socket.

This pins that the WS `state` payload now carries `progress_fraction` for a running job,
computed by the SAME helper the REST list uses (so the two channels never disagree).
"""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

import backend.api.assembly as assembly
import backend.core.namd_runner as namd_runner
from backend.api.main import app
from backend.core.md_job import MdJob, MdSegmentStatus, MdStatus, new_job


def _running_job(ws: Path) -> MdJob:
    """A local NAMD job mid-ladder: 2 of 4 chunks done, the 3rd running (no live log →
    the fraction falls back to done/total = 0.5)."""
    job = new_job(
        "VoltronCore",
        "equilibrium_aware_namd",
        "VoltronCore",
        "package/VoltronCore_namd_solvated",
        design_source_path="VoltronCore.nadoc",
        seed_oxdna_job_id="5ce768ef2acf",
    )  # a SEEDED run — the case that regressed
    job.status = MdStatus.running
    job.current_segment_idx = 2
    job.segments = [
        MdSegmentStatus(
            name="s0", stage="k0p5", percent=10.0, steps=1000, status="done"
        ),
        MdSegmentStatus(
            name="s1", stage="k0p5", percent=50.0, steps=1000, status="done"
        ),
        MdSegmentStatus(
            name="s2", stage="k0p5", percent=100.0, steps=1000, status="running"
        ),
        MdSegmentStatus(
            name="s3", stage="k0p1", percent=10.0, steps=1000, status="pending"
        ),
    ]
    job.save(ws)
    return job


def test_ws_state_push_includes_progress_fraction(tmp_path, monkeypatch):
    # Point the WS handler's workspace at the scratch dir and neutralise the
    # process-liveness reconcile so the saved 'running' job stays running.
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(namd_runner, "reconcile_job_status", lambda job, ws: job)

    job = _running_job(tmp_path)

    client = TestClient(app)
    with client.websocket_connect(f"/ws/md-jobs/{job.job_id}") as ws:
        msg = ws.receive_json()

    assert msg["type"] == "state"
    body = msg["job"]
    assert body["status"] == "running"
    # THE PIN: the live push carries the overall fraction (2 of 4 chunks done = 0.5),
    # not just per-segment live_metrics.  Before the fix this key was absent.
    assert "progress_fraction" in body
    assert body["progress_fraction"] == 0.5


def test_ws_state_push_omits_progress_fraction_for_non_running(tmp_path, monkeypatch):
    """A queued/terminal job has no live fraction — the key stays absent (the bar
    falls back to done/total), matching list_md_jobs."""
    monkeypatch.setattr(assembly, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(namd_runner, "reconcile_job_status", lambda job, ws: job)

    job = new_job(
        "VoltronCore",
        "equilibrium_aware_namd",
        "VoltronCore",
        "package/VoltronCore_namd_solvated",
    )
    job.status = MdStatus.queued
    job.save(tmp_path)

    client = TestClient(app)
    with client.websocket_connect(f"/ws/md-jobs/{job.job_id}") as ws:
        msg = ws.receive_json()

    assert msg["job"]["status"] == "queued"
    assert "progress_fraction" not in msg["job"]


def test_paused_remote_job_keeps_exact_last_observed_progress(tmp_path):
    """A vanished pod must show its durable observation, not fall back to 0 %."""
    from backend.api.routes_md import _namd_live_progress

    job = _running_job(tmp_path)
    job.execution_target = "runpod"
    job.status = MdStatus.paused
    job.current_segment_idx = 2
    job.live_metrics = {"segment": "s2", "step": 250, "retrieved_at": 123.0}

    fraction, eta, estimated = _namd_live_progress(job, tmp_path)

    # 2 completed segments plus 25 % of segment 3, across four equal segments.
    assert fraction == 0.5625
    assert eta is None
    assert estimated is False


def test_running_remote_minimization_has_live_progress_and_eta(tmp_path):
    """The pre-segment minimisation is the first progress unit, not a frozen 0 %."""
    from backend.api.routes_md import _namd_live_progress

    job = _running_job(tmp_path)
    job.execution_target = "alpine"
    job.current_segment_idx = 0
    for seg in job.segments:
        seg.status = "pending"
    job.minimization = MdSegmentStatus(
        name="VoltronCore_00_min", stage="Minimization", percent=100,
        steps=1000, status="pending",
    )
    job.live_metrics = {
        "segment": "VoltronCore_00_min", "step": 250,
        "s_per_step": 2.0,
    }

    fraction, eta, estimated = _namd_live_progress(job, tmp_path)

    # 25% of minimisation, which is one of five total units (min + 4 segments).
    assert fraction == 0.05
    assert eta == 1500.0
    assert estimated is False


def test_completed_partial_production_reports_actual_ns_and_done(tmp_path):
    from backend.api.routes_md import _decorate_terminal_segment_progress

    job = _running_job(tmp_path)
    job.status = MdStatus.completed
    job.package_subdir = "pkg"
    pkg = job.package_dir(tmp_path)
    (pkg / "output").mkdir(parents=True, exist_ok=True)
    seg = job.segments[0]
    seg.name = "VoltronCore_01_production_200ns"
    seg.steps = 50_000_000
    (pkg / f"{seg.name}.conf").write_text("timestep 4\nrun 50000000\n")
    (pkg / "output" / f"{seg.name}.xst").write_text(
        "#$LABELS step a_x\n16492500 1.0\n"
    )
    payload = job.to_dict()

    _decorate_terminal_segment_progress(job, payload, tmp_path)

    row = payload["segments"][0]
    assert row["status"] == "done"
    assert row["completed_steps"] == 16_492_500
    assert row["completed_ns"] == 65.97
