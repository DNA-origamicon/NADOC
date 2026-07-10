"""
Tests for the Chain Simulations project endpoints (routes_chain_sim.py).

A chain-sim project is persisted on the design like a DesignAnimation. These
assert the CRUD round-trip (create → rename → replace stages → delete) plus that
the projects survive a full model serialize/deserialize (the .nadoc save/load
path), so a queued chain plan travels with the file.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import Design

client = TestClient(app)

BASE = "/api/design/chain-sim-projects"


@pytest.fixture(autouse=True)
def reset_state():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


def _projects():
    return design_state.get_or_404().chain_sim_projects


def test_create_project():
    r = client.post(BASE, json={"name": "Deposition"})
    assert r.status_code == 200
    projs = _projects()
    assert len(projs) == 1
    assert projs[0].name == "Deposition"
    assert projs[0].stages == []
    assert projs[0].id  # a uuid was assigned


def test_rename_project():
    client.post(BASE, json={"name": "P1"})
    pid = _projects()[0].id
    r = client.patch(f"{BASE}/{pid}", json={"name": "Renamed"})
    assert r.status_code == 200
    assert _projects()[0].name == "Renamed"


def test_rename_missing_project_404():
    r = client.patch(f"{BASE}/nope", json={"name": "x"})
    assert r.status_code == 404


def test_set_stages_replaces_the_list():
    client.post(BASE, json={"name": "P"})
    pid = _projects()[0].id
    stages = [
        {"engine": "oxdna", "protocol": "relax", "label": "relax"},
        {
            "engine": "oxdna",
            "protocol": "production",
            "label": "field sweep",
            "field": {"field_pN": 5.0, "dir": [1, 0, 0]},
            "anchors": [{"strand_id": "s1"}],
            "length_ns": 10.0,
        },
    ]
    r = client.put(f"{BASE}/{pid}/stages", json={"stages": stages})
    assert r.status_code == 200
    saved = _projects()[0].stages
    assert len(saved) == 2
    assert saved[0].protocol == "relax"
    assert saved[1].engine == "oxdna"
    assert saved[1].field == {"field_pN": 5.0, "dir": [1, 0, 0]}
    assert saved[1].length_ns == 10.0

    # A second PUT fully replaces (not appends).
    r = client.put(f"{BASE}/{pid}/stages", json={"stages": stages[:1]})
    assert r.status_code == 200
    assert len(_projects()[0].stages) == 1


def test_set_stages_missing_project_404():
    r = client.put(f"{BASE}/nope/stages", json={"stages": []})
    assert r.status_code == 404


def test_delete_project():
    client.post(BASE, json={"name": "P"})
    pid = _projects()[0].id
    r = client.delete(f"{BASE}/{pid}")
    assert r.status_code == 200
    assert _projects() == []


def test_delete_missing_project_404():
    r = client.delete(f"{BASE}/nope")
    assert r.status_code == 404


def test_projects_survive_serialize_round_trip():
    """The .nadoc save/load path — a full model_dump → model_validate — preserves
    chain-sim projects and every stage field."""
    client.post(BASE, json={"name": "P"})
    pid = _projects()[0].id
    stages = [
        {"engine": "namd", "protocol": "relax", "label": "eq"},
        {
            "engine": "namd",
            "protocol": "production",
            "seed_job_id": "job-abc",
            "run_target": "alpine",
            "cluster_name": "alpine",
            "steps": 5_000_000,
        },
    ]
    client.put(f"{BASE}/{pid}/stages", json={"stages": stages})

    design = design_state.get_or_404()
    reloaded = Design.model_validate(design.model_dump())
    assert len(reloaded.chain_sim_projects) == 1
    proj = reloaded.chain_sim_projects[0]
    assert proj.name == "P"
    assert len(proj.stages) == 2
    assert proj.stages[1].seed_job_id == "job-abc"
    assert proj.stages[1].run_target == "alpine"
    assert proj.stages[1].steps == 5_000_000
