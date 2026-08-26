"""Route-boundary regressions for NAMD atomistic flexibility-map views."""

from fastapi.testclient import TestClient

import backend.api.routes_md as routes_md
from backend.api.main import app


client = TestClient(app)


def _inputs():
    return ("job.psf", "job.pdb", [("prod", "production", "prod.dcd")], "design")


def test_rmsf_atomistic_reorders_shared_inputs_for_analysis(monkeypatch):
    seen = {}

    async def fake(request, job_id, kind, fn, args, **kwargs):
        seen.update(job_id=job_id, kind=kind, fn=fn, args=args, kwargs=kwargs)
        return {"ready": True, "atomistic": [1.0, 2.0, 3.0]}

    monkeypatch.setattr(routes_md, "_md_traj_inputs", lambda _job_id: _inputs())
    monkeypatch.setattr(routes_md, "_run_md_analysis", fake)

    response = client.post("/api/md/jobs/J/rmsf-atomistic")
    assert response.status_code == 200
    assert seen["fn"] == "md_rmsf_atomistic"
    assert seen["args"] == (
        "job.psf",
        [("prod", "production", "prod.dcd")],
        "job.pdb",
        "design",
    )


def test_rmsf_surface_reorders_inputs_and_appends_surface_params(monkeypatch):
    seen = {}

    async def fake(request, job_id, kind, fn, args, **kwargs):
        seen.update(fn=fn, args=args)
        return {"ready": True, "surface": {"vertices": [0, 0, 0]}}

    monkeypatch.setattr(routes_md, "_md_traj_inputs", lambda _job_id: _inputs())
    monkeypatch.setattr(routes_md, "_run_md_analysis", fake)

    response = client.post(
        "/api/md/jobs/J/rmsf-surface",
        json={
            "probe_radius": 0.31,
            "grid_spacing": 0.21,
            "radius_inflate": 1.4,
            "smooth": 7,
        },
    )
    assert response.status_code == 200
    assert seen["fn"] == "md_rmsf_surface"
    assert seen["args"] == (
        "job.psf",
        [("prod", "production", "prod.dcd")],
        "job.pdb",
        "design",
        0.31,
        0.21,
        1.4,
        7,
    )


def test_photoproduct_route_runs_bounded_kimmdy_analysis(monkeypatch):
    seen = {}

    async def fake(request, job_id, kind, fn, args, **kwargs):
        seen.update(job_id=job_id, kind=kind, fn=fn, args=args, kwargs=kwargs)
        return {"ready": True, "base_likelihoods": []}

    monkeypatch.setattr(routes_md, "_md_traj_inputs", lambda _job_id: _inputs())
    monkeypatch.setattr(routes_md, "_run_md_analysis", fake)

    response = client.get("/api/md/jobs/J/photoproduct-likelihood?max_frames=250")
    assert response.status_code == 200
    assert seen["kind"] == "photoproduct"
    assert seen["fn"] == "md_photoproduct_likelihood"
    assert seen["args"][:-1] == (
        "job.psf",
        [("prod", "production", "prod.dcd")],
        "job.pdb",
        "design",
        250,
        5000,
        "upstream",
    )
    assert str(seen["args"][-1]).endswith(".json")
    assert seen["kwargs"]["timeout_s"] == 900.0


def test_photoproduct_progress_route_exposes_live_worker_stage(monkeypatch, tmp_path):
    progress_file = tmp_path / "progress.json"
    progress_file.write_text(
        '{"phase":"measuring","fraction":0.7,"done":11,"total":20,'
        '"message":"Measuring T-T geometry"}'
    )
    monkeypatch.setitem(routes_md._PHOTOPRODUCT_PROGRESS_PATHS, "J", progress_file)

    response = client.get("/api/md/jobs/J/photoproduct-progress")

    assert response.status_code == 200
    assert response.json() == {
        "active": True,
        "phase": "measuring",
        "fraction": 0.7,
        "done": 11,
        "total": 20,
        "message": "Measuring T-T geometry",
    }


def test_photoproduct_progress_route_reports_inactive_without_worker():
    response = client.get("/api/md/jobs/no-such-worker/photoproduct-progress")
    assert response.status_code == 200
    assert response.json() == {"active": False}
