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
