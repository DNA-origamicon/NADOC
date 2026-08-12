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
    targets = sorted(j["execution_target"] for j in active if j["engine"] == "md")
    # Both jobs are listed (welcome-screen spinner still shows remote runs) but each
    # carries its target so the guard can distinguish them.
    assert targets == ["alpine", "local"]
    assert all("execution_target" in j for j in active)


def test_missing_runpod_job_is_dropped_and_marked_resumable(tmp_path, monkeypatch):
    """A runpod job with no live pod backing it (killed CLI launcher) is orphaned — the
    detector must stop claiming it as active without falsely declaring NAMD failed."""
    ws = tmp_path
    monkeypatch.setattr(routes_jobs, "_WORKSPACE_DIR", ws)
    monkeypatch.setattr(routes_jobs, "_md_eta_seconds", lambda *a, **k: None)
    import backend.core.namd_runner as namd_runner

    monkeypatch.setattr(namd_runner, "reconcile_job_status", lambda j, w: j)

    live = _make_md_job(ws, execution_target="runpod")  # id will be in a live pod name
    dead = _make_md_job(ws, execution_target="runpod")  # no pod → orphaned
    # RunPod ground truth: only `live` has a pod (name embeds the job id).
    monkeypatch.setattr(
        routes_jobs, "_live_remote_pod_names", lambda: {f"nadoc-d-{live.job_id}"}
    )

    active = routes_jobs._collect_active()
    ids = {j["job_id"] for j in active if j["engine"] == "md"}
    assert live.job_id in ids  # pod-backed → still reported
    assert dead.job_id not in ids  # orphaned → dropped
    from backend.core.md_job import MdJob, MdStatus

    recovered = MdJob.load(dead.job_id, ws)
    assert recovered.status == MdStatus.paused
    assert recovered.resumable is True
    assert recovered.runpod_pod_id is None


def test_preparing_runpod_job_is_not_mistaken_for_a_lost_pod(tmp_path, monkeypatch):
    """Local package preparation happens before any explicit RunPod submission."""
    ws = tmp_path
    monkeypatch.setattr(routes_jobs, "_WORKSPACE_DIR", ws)
    monkeypatch.setattr(routes_jobs, "_md_eta_seconds", lambda *a, **k: None)
    import backend.core.namd_runner as namd_runner

    monkeypatch.setattr(namd_runner, "reconcile_job_status", lambda j, w: j)
    monkeypatch.setattr(
        routes_jobs, "_live_remote_pod_names",
        lambda: (_ for _ in ()).throw(AssertionError("queued job must not query pod liveness")),
    )
    job = _make_md_job(ws, execution_target="runpod", status=MdStatus.preparing)

    active = routes_jobs._collect_active()
    assert any(row["job_id"] == job.job_id for row in active)
    from backend.core.md_job import MdJob

    assert MdJob.load(job.job_id, ws).status == MdStatus.preparing


def test_runpod_liveness_uses_persisted_pod_id_not_only_display_name(
    tmp_path, monkeypatch
):
    """RunPod list responses can omit a pod display name; the durable id still proves
    that the job is live and must prevent a false orphan classification."""
    ws = tmp_path
    monkeypatch.setattr(routes_jobs, "_WORKSPACE_DIR", ws)
    monkeypatch.setattr(routes_jobs, "_md_eta_seconds", lambda *a, **k: None)
    import backend.core.namd_runner as namd_runner

    monkeypatch.setattr(namd_runner, "reconcile_job_status", lambda j, w: j)
    job = _make_md_job(ws, execution_target="runpod")
    job.runpod_pod_id = "pod-authoritative-id"
    job.save(ws)
    monkeypatch.setattr(
        routes_jobs, "_live_remote_pod_names", lambda: {"pod-authoritative-id"}
    )

    ids = {j["job_id"] for j in routes_jobs._collect_active() if j["engine"] == "md"}
    assert job.job_id in ids


def test_runpod_job_kept_when_liveness_undeterminable(tmp_path, monkeypatch):
    """Fail-open: if RunPod can't be reached (_live_remote_pod_names -> None) we must NOT
    hide a runpod job we simply couldn't verify."""
    ws = tmp_path
    monkeypatch.setattr(routes_jobs, "_WORKSPACE_DIR", ws)
    monkeypatch.setattr(routes_jobs, "_md_eta_seconds", lambda *a, **k: None)
    import backend.core.namd_runner as namd_runner

    monkeypatch.setattr(namd_runner, "reconcile_job_status", lambda j, w: j)
    monkeypatch.setattr(routes_jobs, "_live_remote_pod_names", lambda: None)

    job = _make_md_job(ws, execution_target="runpod")
    ids = {j["job_id"] for j in routes_jobs._collect_active() if j["engine"] == "md"}
    assert job.job_id in ids
