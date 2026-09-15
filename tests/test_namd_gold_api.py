from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_namd_gold as gold
from backend.core.md_job import MdStatus


def client():
    app = FastAPI()
    app.include_router(gold.router, prefix="/api")
    return TestClient(app)


def test_model_has_explicit_missing_physics():
    r = client().get("/api/md/gold/model")
    assert r.status_code == 200
    d = r.json()
    assert d["physical_qualification"] is False
    assert d["model"]["capabilities"]["electronic_polarization"] is False


def test_create_preserves_settings_without_starting(monkeypatch):
    seen = {}
    def prepare(workspace, geometry, **kwargs):
        seen.update(geometry=geometry, **kwargs)
        return SimpleNamespace(job_id="goldtest", status=MdStatus.queued)
    monkeypatch.setattr(gold, "prepare_job", prepare)
    r = client().post("/api/md/gold/jobs", json={"geometry": {"kind": "nanoparticle"},
                        "salt_mM": 175, "timestep_fs": .5, "water_loading_scale": 1.02})
    assert r.status_code == 200 and r.json()["status"] == "queued"
    assert seen["salt_mM"] == 175 and seen["timestep_fs"] == .5
    assert seen["water_loading_scale"] == 1.02


def test_reject_unrecognized_physics_before_preparation(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("No preparation allowed")
    monkeypatch.setattr(gold, "prepare_job", forbidden)
    r = client().post("/api/md/gold/jobs", json={"geometry": {"kind": "slab"}, "voltage": 1})
    assert r.status_code == 422
