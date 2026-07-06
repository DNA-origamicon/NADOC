"""`/api/jobs/active` tags each job with its execution_target so the frontend's
concurrent-launch guard can ignore jobs running on the remote Alpine cluster
(they consume no local GPU/disk and must not block a local launch, or vice versa).
"""

from __future__ import annotations

import backend.api.routes_jobs as routes_jobs
from backend.core.md_job import MdStatus, new_job


def _make_md_job(ws, *, execution_target="local", status=MdStatus.running):
    job = new_job(
        design_name="d",
        protocol="mgh_slow_release",
        name_stem="d",
        package_subdir="pkg",
        design_source_path=f"/w/{execution_target}.nadoc",
    )
    job.execution_target = execution_target
    job.status = status
    job.save(ws)
    return job


def test_collect_active_tags_execution_target(tmp_path, monkeypatch):
    ws = tmp_path
    monkeypatch.setattr(routes_jobs, "_WORKSPACE_DIR", ws)
    # reconcile would flip a persisted-running local job with no live process to a
    # terminal state; stub it out so the fixture jobs stay "running" for the test.
    monkeypatch.setattr(routes_jobs, "_md_eta_seconds", lambda *a, **k: None)
    import backend.core.namd_runner as namd_runner
    monkeypatch.setattr(namd_runner, "reconcile_job_status", lambda j, w: j)

    _make_md_job(ws, execution_target="local")
    _make_md_job(ws, execution_target="alpine")

    active = routes_jobs._collect_active()
    md = {j["design_name"]: j for j in active if j["engine"] == "md"}
    targets = sorted(j["execution_target"] for j in active if j["engine"] == "md")
    # Both jobs are listed (welcome-screen spinner still shows remote runs) but each
    # carries its target so the guard can distinguish them.
    assert targets == ["alpine", "local"]
    assert all("execution_target" in j for j in active)
