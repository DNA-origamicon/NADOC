"""DELETE /md/jobs/{id} must refuse a job whose background preparation is still
writing into its package dir — deleting out from under `_prepare_job_bg` used to
race `shutil.rmtree` against that thread (observed live as "Directory not empty"
from rmtree, then the prep thread hitting FileNotFoundError on a file the race had
just removed). GPU-free: the guard fires before any NAMD/package work."""

from __future__ import annotations

import pytest

from fastapi.testclient import TestClient

import backend.api.routes_md as routes_md

# Imported at MODULE level (collection time) so the app is built with the REAL routers
# BEFORE any test that swaps a fake fastapi into sys.modules (test_md_milestone1) runs.
from backend.api.main import app
from backend.core.md_job import MdStatus, new_job


@pytest.fixture(autouse=True)
def _clean_default_doc():
    from backend.api import doc_context

    doc_context.set_current_doc(None)
    yield


def _make_job(tmp_path, status):
    job = new_job("6hb", "equilibrium_aware", "", "")
    job.status = status
    job.save(tmp_path)
    return job


@pytest.fixture(autouse=True)
def _no_reconcile(monkeypatch):
    # `_load_job` runs every loaded job through `reconcile_job_status`, which heals a
    # `preparing`/`running` job with no live evidence behind it (dead heartbeat, no
    # registered thread) back to `failed`/`completed` — appropriate crash recovery, but
    # it would silently launder the exact states this test needs to hold in place to
    # exercise `delete_md_job`'s OWN guard. Make it a pass-through here.
    monkeypatch.setattr(routes_md, "reconcile_job_status", lambda job, ws: job)


def test_delete_refuses_a_job_still_preparing(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_job(tmp_path, MdStatus.preparing)

    c = TestClient(app)
    resp = c.delete(f"/api/md/jobs/{job.job_id}")

    assert resp.status_code == 400
    assert "preparation" in resp.json()["detail"].lower()
    # Refused before touching disk — the job directory must still be there.
    assert job.job_dir(tmp_path).exists()


def test_delete_still_refuses_a_running_job(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_job(tmp_path, MdStatus.running)

    c = TestClient(app)
    resp = c.delete(f"/api/md/jobs/{job.job_id}")

    assert resp.status_code == 400
    assert job.job_dir(tmp_path).exists()


def test_delete_still_allows_a_failed_job(monkeypatch, tmp_path):
    monkeypatch.setattr(routes_md, "_WORKSPACE_DIR", tmp_path)
    job = _make_job(tmp_path, MdStatus.failed)

    c = TestClient(app)
    resp = c.delete(f"/api/md/jobs/{job.job_id}")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True
    assert not job.job_dir(tmp_path).exists()
