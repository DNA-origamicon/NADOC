"""MD-job out-of-date detection + the snapshot roll (parity with oxDNA).  GPU-free —
the stale guard fires before any NAMD/package work."""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

import backend.api.routes_md as routes_md
from backend.api import state as design_state

# Imported at MODULE level (collection time) so the app is built with the REAL routers
# BEFORE any test that swaps a fake fastapi into sys.modules (test_md_milestone1) runs.
from backend.api.main import app
from backend.core.md_job import MdStatus, new_job
from backend.core.oxdna_staleness import design_build_fingerprint
from tests.conftest import make_18hb_design, make_6hb_design


@pytest.fixture(autouse=True)
def _clean_default_doc():
    # Reset any leaked doc-context contextvar to the default doc, so set_design (which
    # uses the contextvar) and the TestClient routes (which use the default doc) agree.
    from backend.api import doc_context
    from backend.api import state as design_state

    doc_context.set_current_doc(None)
    yield
    design_state.drop_doc(doc_context.DEFAULT_DOC_ID)


def _make_md_job(tmp_path, design, *, fingerprint):
    job = new_job("6hb", "equilibrium_aware", "", "")
    job.status = MdStatus.completed
    job.design_fingerprint = fingerprint
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "design.json").write_text(design.model_dump_json())
    return job


def test_md_out_of_date_flag_and_roll_clears_it(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)

    prepared = make_6hb_design()
    for s in prepared.strands:
        s.sequence = "ACGT"
    job = _make_md_job(
        tmp_path, prepared, fingerprint=design_build_fingerprint(prepared)
    )

    # User edits the design (clears sequences) → MD job is out of date.
    edited = prepared.model_copy(deep=True)
    for s in edited.strands:
        s.sequence = ""
    design_state.set_design(edited)
    c = TestClient(app)
    assert c.get(f"/api/md/jobs/{job.job_id}").json()["out_of_date"] is True

    # Production is refused (409) on a stale MD job.
    r409 = c.post(f"/api/md/jobs/{job.job_id}/production", json={"steps": 1000})
    assert r409.status_code == 409
    # Same design edited in place (sequences cleared) → identity matches, so the
    # message names the edit-and-roll case rather than "a different design is loaded".
    detail = r409.json()["detail"].lower()
    assert "has been edited" in detail and "roll" in detail

    # Roll to the job's prepared state → restores the sequenced snapshot, clears ⚠.
    r = c.post(f"/api/md/jobs/{job.job_id}/roll-design")
    assert r.status_code == 200, r.text
    assert r.json().get("return_loadout_id")
    assert r.json()["matches_job"] is True
    restored = design_state.get_or_404()
    assert all(s.sequence == "ACGT" for s in restored.strands)
    assert design_build_fingerprint(restored) == job.design_fingerprint
    assert c.get(f"/api/md/jobs/{job.job_id}").json()["out_of_date"] is False

    # API automation for the other half of the workflow: the toast calls this exact
    # endpoint with save_current=false so the rolled run-state cannot overwrite the
    # branch holding the user's later edits.
    rid = r.json()["return_loadout_id"]
    back_r = c.post(f"/api/design/loadouts/{rid}/select?save_current=false")
    assert back_r.status_code == 200, back_r.text
    returned = design_state.get_or_404()
    assert all(not s.sequence for s in returned.strands)
    assert c.get(f"/api/md/jobs/{job.job_id}").json()["out_of_date"] is True


def test_md_roll_migrates_old_snapshot_before_protecting_it(monkeypatch, tmp_path):
    """Old NAMD snapshots with no cluster must still become a visible protected loadout."""
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    prepared = make_6hb_design().copy_with(cluster_transforms=[])
    job = _make_md_job(
        tmp_path, prepared, fingerprint=design_build_fingerprint(prepared)
    )
    design_state.set_design(make_18hb_design())

    r = TestClient(app).post(f"/api/md/jobs/{job.job_id}/roll-design")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["matches_job"] is True
    assert body["design"]["active_loadout_id"] == body["simulation_loadout_id"]
    assert body["design"]["cluster_transforms"]
    assert body.get("nucleotides_compact")


def test_md_stale_message_names_a_different_loaded_design(monkeypatch, tmp_path):
    """When a WHOLLY different design is loaded (not an edit of the job's design), the
    409 must say so and name both designs — rolling the feature log can't fix it.
    This is the real-world 'Bundle loaded instead of the job's design' case."""
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)

    prepared = make_6hb_design()  # what the job was built from
    job = _make_md_job(
        tmp_path, prepared, fingerprint=design_build_fingerprint(prepared)
    )

    other = make_18hb_design()  # a different structure entirely
    assert len(other.helices) != len(prepared.helices)
    design_state.set_design(other)

    r409 = TestClient(app).post(
        f"/api/md/jobs/{job.job_id}/production", json={"steps": 1000}
    )
    assert r409.status_code == 409
    detail = r409.json()["detail"].lower()
    assert "different design is loaded" in detail
    assert f"{len(other.helices)} helices" in detail  # names the loaded design's size
    assert f"{len(prepared.helices)} helices" in detail  # and the job's design's size


def test_list_md_jobs_size_is_cache_only_then_warms(monkeypatch, tmp_path):
    """/md/jobs must not block on a multi-GB archived-run stat-walk: an uncached job's size
    comes back None (the frontend renders it blank), and the background warm fills in the
    real size so it appears on the next poll."""
    import asyncio

    from backend.core.design_disk_usage import (
        _size_cache,
        dir_size_bytes,
        warm_dir_sizes,
    )

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = new_job("6hb", "equilibrium_aware", "", "")
    job.design_source_path = "6hb.nadoc"
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "blob.bin").write_bytes(b"\0" * 2048)
    _size_cache.pop(str(job.job_dir(tmp_path)), None)  # ensure a cold cache
    expected = dir_size_bytes(job.job_dir(tmp_path))  # blob + job.json metadata
    assert expected >= 2048

    rows = asyncio.run(routes_md.list_md_jobs())
    row = next(r for r in rows if r["job_id"] == job.job_id)
    assert row["size_bytes"] is None  # cold → the response never walked

    warm_dir_sizes([job.job_dir(tmp_path)])  # what the scheduled bg task does
    rows2 = asyncio.run(routes_md.list_md_jobs())
    row2 = next(r for r in rows2 if r["job_id"] == job.job_id)
    assert row2["size_bytes"] == expected  # filled in on the next poll


def test_list_md_jobs_uses_live_remote_dcd_and_total_sizes(monkeypatch, tmp_path):
    import asyncio

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = new_job("6hb", "equilibrium_aware", "", "")
    job.execution_target = "alpine"
    job.live_metrics = {"dcd_size_bytes": 700, "total_size_bytes": 1200}
    job.save(tmp_path)

    rows = asyncio.run(routes_md.list_md_jobs())
    row = next(r for r in rows if r["job_id"] == job.job_id)
    assert row["dcd_size_bytes"] == 700
    assert row["size_bytes"] == 1200


def test_terminal_remote_job_uses_local_size_not_stale_live_metrics(
    monkeypatch, tmp_path
):
    import asyncio

    from backend.core.design_disk_usage import warm_dir_sizes

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = new_job("6hb", "equilibrium_aware", "6hb", "pkg")
    job.execution_target = "alpine"
    job.status = MdStatus.completed
    job.live_metrics = {"dcd_size_bytes": 700, "total_size_bytes": 1200}
    job.download_status = {
        "state": "verified",
        "total_bytes": 5000,
        "verified_bytes": 5000,
        "dcd_bytes": 4000,
    }
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "local-results.bin").write_bytes(b"x" * 8000)
    warm_dir_sizes([job.job_dir(tmp_path)], ttl=0.0)

    rows = asyncio.run(routes_md.list_md_jobs())
    row = next(r for r in rows if r["job_id"] == job.job_id)
    assert row["size_bytes"] >= 8000
    assert row["size_bytes"] != 1200
    assert row["dcd_size_bytes"] == 4000


def test_list_md_jobs_repairs_running_runpod_job_when_pod_is_gone(
    monkeypatch, tmp_path
):
    """The MD panel must use RunPod liveness, not a stale persisted pod-id string."""
    import asyncio

    from backend.api import routes_runpod
    from backend.core.md_job import MdJob

    class EmptyRunpod:
        async def list_pods(self):
            return []

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_runpod._SESSION, "client", EmptyRunpod())  # noqa: SLF001
    restarted = []
    from backend.core import runpod_supervisor

    monkeypatch.setattr(
        runpod_supervisor,
        "start_job",
        lambda j, ws, **kw: restarted.append((j.job_id, kw["network_volume_id"])),
    )

    job = new_job("6hb", "equilibrium_aware", "", "")
    job.execution_target = "runpod"
    job.status = MdStatus.running
    job.runpod_pod_id = "pod-that-no-longer-exists"
    job.runpod_volume_id = "volume1"
    job.save(tmp_path)

    rows = asyncio.run(routes_md.list_md_jobs())
    row = next(r for r in rows if r["job_id"] == job.job_id)
    assert row["status"] == "running"
    assert row["resumable"] is False
    assert row["runpod_pod_id"] is None
    assert row["runpod_pod_connected"] is False
    assert row["error"] is None
    assert restarted == [(job.job_id, "volume1")]

    saved = MdJob.load(job.job_id, tmp_path)
    assert saved.status == MdStatus.running
    assert saved.runpod_pod_id is None


def test_list_md_jobs_skips_runpod_network_when_all_runpod_jobs_are_terminal(
    monkeypatch, tmp_path
):
    """Historical RunPod rows never force an external API call on every panel poll."""
    import asyncio
    from backend.api import routes_runpod

    class MustNotProbe:
        async def list_pods(self):
            raise AssertionError("terminal-only list must not probe RunPod")

    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_runpod._SESSION, "client", MustNotProbe())  # noqa: SLF001
    job = new_job("6hb", "equilibrium_aware", "", "")
    job.execution_target = "runpod"
    job.status = MdStatus.completed
    job.save(tmp_path)

    rows = asyncio.run(routes_md.list_md_jobs())
    assert (
        next(row for row in rows if row["job_id"] == job.job_id)["status"]
        == "completed"
    )


def test_md_jobs_list_health_compaction_keeps_tail_and_each_segment_latest():
    """The poll payload stays bounded without losing any timeline's terminal state."""
    from backend.api.routes_md import _compact_list_health_samples

    samples = [{"segment": "min", "step": 1}] + [
        {"segment": "equil", "step": i} for i in range(200)
    ]
    compact, truncated = _compact_list_health_samples(samples)

    assert truncated is True
    assert len(compact) == 17
    assert compact[0] == {"segment": "min", "step": 1}
    assert compact[-1] == {"segment": "equil", "step": 199}
