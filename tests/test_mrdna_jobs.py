"""
Tests for the managed mrDNA/ARBD relaxation job system (mrdna_job / mrdna_runner
/ routes_mrdna).

mrDNA's ``model.simulate()`` needs a real ARBD + GPU, so the runner's execution
body is NOT exercised here (it is the manual-validation item).  What IS pinned:
the job model round-trip, the availability probe shape, the time-based progress
estimate, the reconcile state machine (which recovers a restart-orphaned job from
its cached ``display.json``), and the HTTP routes (create/list/stop/delete +
availability gating) with a mocked-out runner + design.
"""

from __future__ import annotations

import json

from backend.core.mrdna_job import MrdnaJob, MrdnaStatus, new_mrdna_job


# ── Job model ─────────────────────────────────────────────────────────────────

def test_new_mrdna_job_single_coarse_stage():
    job = new_mrdna_job("mydesign", coarse_steps=50_000, n_nucleotides=1200)
    assert job.status == MrdnaStatus.queued
    assert job.coarse_steps == 50_000
    assert len(job.stages) == 1
    assert job.stages[0].name == "coarse"
    assert job.stages[0].steps == 50_000


def test_mrdna_job_save_load_roundtrip(tmp_path):
    job = new_mrdna_job("d", coarse_steps=1000, n_nucleotides=42,
                        design_source_path="foo/bar.nadoc")
    job.sim_seconds = 12.3
    job.n_beads = 99
    job.save(tmp_path)
    loaded = MrdnaJob.load(job.job_id, tmp_path)
    assert loaded.job_id == job.job_id
    assert loaded.status == MrdnaStatus.queued
    assert loaded.coarse_steps == 1000
    assert loaded.n_beads == 99
    assert loaded.design_source_path == "foo/bar.nadoc"
    assert loaded.stages[0].name == "coarse"


def test_mrdna_job_list_jobs(tmp_path):
    a = new_mrdna_job("a"); a.save(tmp_path)
    b = new_mrdna_job("b"); b.save(tmp_path)
    ids = {j.job_id for j in MrdnaJob.list_jobs(tmp_path)}
    assert {a.job_id, b.job_id} <= ids


# ── Availability probe ────────────────────────────────────────────────────────

def test_mrdna_available_shape(monkeypatch):
    import backend.core.mrdna_runner as r
    import backend.core.mrdna_bridge as bridge
    monkeypatch.setattr(bridge, "find_mrdna", lambda: "/x/mrdna")
    monkeypatch.setattr(bridge, "find_arbd", lambda: "/x/arbd")
    out = r.mrdna_available()
    assert out["available"] is True
    assert out["mrdna"] == "/x/mrdna"
    assert out["arbd"] == "/x/arbd"

    monkeypatch.setattr(bridge, "find_arbd", lambda: None)
    assert r.mrdna_available()["available"] is False


# ── Progress ──────────────────────────────────────────────────────────────────

def test_job_progress_states(tmp_path):
    import time
    from backend.core.mrdna_runner import job_progress

    job = new_mrdna_job("d", coarse_steps=100_000, n_nucleotides=1270)

    job.status = MrdnaStatus.queued
    assert job_progress(job, tmp_path)["overall"] == 0.0

    job.status = MrdnaStatus.completed
    assert job_progress(job, tmp_path)["overall"] == 1.0

    job.status = MrdnaStatus.running
    job.stages[0].status = "running"
    job.stages[0].started_at = time.time()
    p = job_progress(job, tmp_path)
    assert 0.0 <= p["overall"] < 1.0
    assert p["eta_seconds"] is not None and p["eta_seconds"] >= 0.0


# ── Reconcile (restart recovery) ──────────────────────────────────────────────

def test_reconcile_running_with_cached_display_completes(tmp_path):
    from backend.core.mrdna_runner import reconcile_mrdna_status

    job = new_mrdna_job("d")
    job.status = MrdnaStatus.running
    job.stages[0].status = "running"
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "display.json").write_text(json.dumps({"positions": [1]}))

    out = reconcile_mrdna_status(job, tmp_path)
    assert out.status == MrdnaStatus.completed
    assert out.stages[0].status == "done"


def test_reconcile_running_no_output_and_no_process_stops(tmp_path, monkeypatch):
    import backend.core.mrdna_runner as r
    monkeypatch.setattr(r, "_external_arbd_pid", lambda job, ws: None)

    job = new_mrdna_job("d")
    job.status = MrdnaStatus.running
    job.stages[0].status = "running"
    job.save(tmp_path)

    out = r.reconcile_mrdna_status(job, tmp_path)
    assert out.status == MrdnaStatus.stopped


def test_reconcile_noop_for_terminal_jobs(tmp_path):
    from backend.core.mrdna_runner import reconcile_mrdna_status
    job = new_mrdna_job("d")
    job.status = MrdnaStatus.completed
    job.save(tmp_path)
    assert reconcile_mrdna_status(job, tmp_path).status == MrdnaStatus.completed


# ── HTTP routes ───────────────────────────────────────────────────────────────

def test_mrdna_available_route(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.core.mrdna_bridge as bridge
    monkeypatch.setattr(bridge, "find_mrdna", lambda: None)
    monkeypatch.setattr(bridge, "find_arbd", lambda: None)
    r = TestClient(app).get("/api/mrdna/available")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is False
    assert "mrdna" in body and "arbd" in body


def test_mrdna_create_rejects_when_unavailable(monkeypatch):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_mrdna as routes_mrdna
    monkeypatch.setattr(routes_mrdna, "mrdna_available",
                        lambda: {"available": False, "mrdna": None, "arbd": None})
    r = TestClient(app).post("/api/mrdna/jobs", json={"coarse_steps": 1000})
    assert r.status_code == 400
    assert "not installed" in r.json()["detail"]


def test_mrdna_create_and_lifecycle(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_mrdna as routes_mrdna
    from backend.api import state as design_state
    from tests.conftest import make_6hb_design

    monkeypatch.setattr(routes_mrdna, "_WORKSPACE_DIR", tmp_path)
    monkeypatch.setattr(routes_mrdna, "mrdna_available",
                        lambda: {"available": True, "mrdna": "/x", "arbd": "/y"})
    monkeypatch.setattr(routes_mrdna, "start_job", lambda job, ws: None)
    design_state.set_design_silent(make_6hb_design())

    client = TestClient(app)
    r = client.post("/api/mrdna/jobs", json={"coarse_steps": 5000, "autostart": True})
    assert r.status_code == 200, r.text
    job = r.json()
    assert job["status"] == "queued"
    assert job["coarse_steps"] == 5000
    assert job["n_nucleotides"] > 0
    jid = job["job_id"]

    lst = client.get("/api/mrdna/jobs").json()
    assert any(j["job_id"] == jid for j in lst)

    assert client.get(f"/api/mrdna/jobs/{jid}").json()["job_id"] == jid
    assert "overall" in client.get(f"/api/mrdna/jobs/{jid}/progress").json()

    # Not-running stop is a no-op-ok; delete removes the folder.
    assert client.post(f"/api/mrdna/jobs/{jid}/stop").json()["ok"] is True
    assert client.delete(f"/api/mrdna/jobs/{jid}").json()["ok"] is True
    assert not (tmp_path / "mrdna_jobs" / jid).exists()


def test_mrdna_display_and_beads_serve_cached(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_mrdna as routes_mrdna

    monkeypatch.setattr(routes_mrdna, "_WORKSPACE_DIR", tmp_path)
    job = new_mrdna_job("d")
    job.status = MrdnaStatus.completed
    job.stages[0].status = "done"
    job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / "display.json").write_text(json.dumps({"positions": [
        {"helix_id": "h", "bp_index": 0, "direction": "FORWARD", "backbone_position": [1, 2, 3]},
    ]}))
    (jd / "beads.json").write_text(json.dumps({
        "beads": [[0, 0, 0], [1, 1, 1]], "edges": [[0, 1]]}))

    client = TestClient(app)
    disp = client.get(f"/api/mrdna/jobs/{job.job_id}/display").json()
    assert disp["ready"] is True and disp["n_positions"] == 1
    beads = client.get(f"/api/mrdna/jobs/{job.job_id}/beads").json()
    assert beads["ready"] is True and beads["n_beads"] == 2
    assert beads["edges"] == [[0, 1]]   # CG bond connectivity for the sticks view


def test_load_beads_with_edges_passthrough(tmp_path):
    import backend.core.mrdna_runner as r
    job = new_mrdna_job("d"); job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / "beads.json").write_text(json.dumps({"beads": [[0, 0, 0]], "edges": [[0, 0]]}))
    assert r.load_beads_with_edges(jd)["edges"] == [[0, 0]]


def test_load_beads_with_edges_backfills_from_psf(tmp_path, monkeypatch):
    """A job cached before the edges feature (beads.json has no 'edges') gets its CG
    connectivity backfilled from the coarse PSF on read, and re-cached."""
    import backend.core.mrdna_runner as r
    job = new_mrdna_job("d"); job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / "beads.json").write_text(json.dumps({"beads": [[0, 0, 0], [1, 1, 1]]}))  # no edges
    (jd / "mrdna_relax.psf").write_text("dummy")   # exists → backfill attempts
    monkeypatch.setattr(r, "_psf_dna_edges", lambda psf: [[0, 1]])
    out = r.load_beads_with_edges(jd)
    assert out["edges"] == [[0, 1]]
    assert json.loads((jd / "beads.json").read_text())["edges"] == [[0, 1]]   # persisted


def test_load_display_passthrough_current_version(tmp_path):
    import backend.core.mrdna_runner as r
    job = new_mrdna_job("d"); job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / "display.json").write_text(json.dumps(
        {"version": r._DISPLAY_VERSION, "positions": [{"a": 1}]}))
    assert r.load_display(jd)["positions"] == [{"a": 1}]   # served as-is, not recomputed


def test_load_display_regenerates_stale_cache(tmp_path, monkeypatch):
    """A display cached by an older reconstruction (no/old 'version') is recomputed
    from the on-disk PSF/DCD on read and re-cached — no re-run needed."""
    import backend.core.mrdna_runner as r
    job = new_mrdna_job("d"); job.save(tmp_path)
    jd = job.job_dir(tmp_path)
    (jd / "display.json").write_text(json.dumps({"positions": [{"old": 1}]}))  # no version
    (jd / "design.json").write_text('{"dummy": 1}')
    (jd / "mrdna_relax.psf").write_text("x")
    (jd / "output").mkdir()
    (jd / "output" / "mrdna_relax.dcd").write_text("x")
    monkeypatch.setattr(r, "_load_snapshot_design", lambda d: object())
    fresh = [{"helix_id": "h", "bp_index": 0, "direction": "FORWARD",
              "backbone_position": [9, 9, 9]}]
    monkeypatch.setattr(r, "_display_positions", lambda design, jd_: (fresh, 1))
    out = r.load_display(jd)
    assert out["version"] == r._DISPLAY_VERSION
    assert out["positions"] == fresh
    assert json.loads((jd / "display.json").read_text())["version"] == r._DISPLAY_VERSION


def test_mrdna_display_not_ready_when_no_cache(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_mrdna as routes_mrdna

    monkeypatch.setattr(routes_mrdna, "_WORKSPACE_DIR", tmp_path)
    job = new_mrdna_job("d")
    job.save(tmp_path)
    disp = TestClient(app).get(f"/api/mrdna/jobs/{job.job_id}/display").json()
    assert disp["ready"] is False


# ── Fine stage + curvature ────────────────────────────────────────────────────

def test_new_mrdna_job_fine_adds_second_stage():
    coarse = new_mrdna_job("d", coarse_steps=1000, fine_steps=0)
    assert [s.name for s in coarse.stages] == ["coarse"]
    fine = new_mrdna_job("d", coarse_steps=1000, fine_steps=5000)
    assert [s.name for s in fine.stages] == ["coarse", "fine"]
    assert fine.fine_steps == 5000


def test_mrdna_job_fine_steps_roundtrip(tmp_path):
    job = new_mrdna_job("d", fine_steps=200000); job.save(tmp_path)
    assert MrdnaJob.load(job.job_id, tmp_path).fine_steps == 200000


def test_analytic_curvature_from_marks():
    from backend.core.models import Design
    from backend.core.mrdna_curvature import analytic_curvature
    d = Design.model_validate_json(open("workspace/6hb_curved.nadoc").read())
    a = analytic_curvature(d)
    assert a["has_marks"] is True
    assert a["n_loops"] == 18 and a["n_skips"] == 18
    assert 25.0 < a["radius_nm"] < 50.0          # ~36 nm Dietz prediction
    assert a["kappa_deg_per_nm"] > 1.0


def test_analytic_curvature_no_marks_is_straight():
    from backend.core.models import Design
    from backend.core.mrdna_curvature import analytic_curvature
    d = Design.model_validate_json(open("workspace/6hb_sim_v2.nadoc").read())
    a = analytic_curvature(d)
    assert a["has_marks"] is False
    assert a["kappa_deg_per_nm"] == 0.0


def test_measured_curvature_straight_and_bent():
    import math
    from backend.core.mrdna_curvature import measured_curvature
    # a straight line of bp midpoints → ~infinite radius, ~0 curvature
    straight = [{"helix_id": "h", "bp_index": i, "direction": "FORWARD",
                 "backbone_position": [i * 0.34, 0.0, 0.0]} for i in range(60)]
    assert measured_curvature(straight)["kappa_deg_per_nm"] < 0.05
    # a clean arc of radius 30 nm → measured radius ≈ 30
    R = 30.0
    arc = [{"helix_id": "h", "bp_index": i, "direction": "FORWARD",
            "backbone_position": [R * math.sin(i * 0.03), R * (1 - math.cos(i * 0.03)), 0.0]}
           for i in range(60)]
    r = measured_curvature(arc)["radius_nm"]
    assert 25.0 < r < 35.0


def test_curvature_endpoint(monkeypatch, tmp_path):
    import json as _json
    from fastapi.testclient import TestClient
    from backend.api.main import app
    import backend.api.routes_mrdna as routes_mrdna
    monkeypatch.setattr(routes_mrdna, "_WORKSPACE_DIR", tmp_path)
    job = new_mrdna_job("d", fine_steps=200000)
    job.status = MrdnaStatus.completed
    job.save(tmp_path)
    (job.job_dir(tmp_path) / "curvature.json").write_text(_json.dumps({
        "analytic": {"has_marks": True, "radius_nm": 36.0, "kappa_deg_per_nm": 1.58, "bend_deg": 88.0},
        "measured": {"radius_nm": 45.0, "kappa_deg_per_nm": 1.27, "bend_deg": 70.0},
        "ratio": 0.8}))
    r = TestClient(app).get(f"/api/mrdna/jobs/{job.job_id}/curvature").json()
    assert r["ready"] is True and r["fine"] is True
    assert r["analytic"]["radius_nm"] == 36.0 and r["ratio"] == 0.8
