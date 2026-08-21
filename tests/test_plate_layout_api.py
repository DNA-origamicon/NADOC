"""
Tests for the plate/tube layout feature (IDT ordering convenience).

The plate layout is display-only metadata persisted on Design.plate_layout.
It must:
  - round-trip losslessly through Design.to_json / from_json,
  - be replaceable via PUT /design/plate-layout (404 on unknown strand_id),
  - be clearable via DELETE /design/plate-layout,
  - survive import (POST /design/import),
  - NOT mutate topology/geometry (helices unchanged).

The auto-fill ordering and tube-segregation rules are computed client-side
(they depend on the frontend-only strandGroups), so they are exercised in the
running app rather than here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api import state as design_state
from backend.api.routes import _demo_design
from backend.core.models import Design, PlateLayout, StapleGroup, TubeAssignment, WellAssignment


@pytest.fixture(autouse=True)
def _reset():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


@pytest.fixture
def client():
    return TestClient(app)


# ── Model round-trip ────────────────────────────────────────────────────────


def test_plate_layout_round_trips_through_json():
    d = _demo_design()
    d.plate_layout = PlateLayout(
        orientation="12x8",
        plate_count=2,
        wells=[
            WellAssignment(strand_id="staple_0", plate=0, row=0, col=0),
            WellAssignment(strand_id="staple_0", plate=1, row=7, col=11),
        ],
        tubes=[TubeAssignment(strand_id="staple_0", reason="both")],
    )
    restored = Design.from_json(d.to_json())
    assert restored.plate_layout is not None
    assert restored.plate_layout == d.plate_layout


def test_missing_plate_layout_loads_as_none():
    # A design JSON with no plate_layout key (old file) loads with None.
    d = _demo_design()
    restored = Design.from_json(d.to_json())
    assert restored.plate_layout is None


def test_staple_groups_round_trip_through_design_file():
    design = _demo_design()
    design.staple_groups = [
        StapleGroup(id="grp_body", name="Body", color="#74b9ff", strand_ids=["staple_0"])
    ]
    restored = Design.from_json(design.to_json())
    assert restored.staple_groups == design.staple_groups


def test_put_staple_groups_persists_sidebar_metadata(client):
    response = client.put(
        "/api/design/staple-groups",
        json={"groups": [{
            "id": "grp_body", "name": "Body", "color": "#74b9ff",
            "strand_ids": ["staple_0"],
        }]},
    )
    assert response.status_code == 200
    saved = response.json()["design"]["staple_groups"]
    assert saved == [{
        "id": "grp_body", "name": "Body", "color": "#74b9ff",
        "strand_ids": ["staple_0"],
    }]


def test_put_staple_groups_rejects_unknown_strands(client):
    response = client.put(
        "/api/design/staple-groups",
        json={"groups": [{"id": "g", "name": "Bad", "strand_ids": ["missing"]}]},
    )
    assert response.status_code == 404


# ── PUT /design/plate-layout ──────────────────────────────────────────────────


def test_put_plate_layout_happy_path(client):
    body = {
        "orientation": "8x12",
        "plate_count": 1,
        "wells": [{"strand_id": "staple_0", "plate": 0, "row": 0, "col": 0}],
        "tubes": [],
    }
    r = client.put("/api/design/plate-layout", json=body)
    assert r.status_code == 200

    got = client.get("/api/design").json()["design"]["plate_layout"]
    assert got is not None
    assert got["orientation"] == "8x12"
    assert got["plate_count"] == 1
    assert got["wells"] == [{"strand_id": "staple_0", "plate": 0, "row": 0, "col": 0}]
    assert got["tubes"] == []


def test_put_plate_layout_unknown_strand_404(client):
    body = {
        "orientation": "8x12",
        "plate_count": 1,
        "wells": [{"strand_id": "does_not_exist", "plate": 0, "row": 0, "col": 0}],
        "tubes": [],
    }
    r = client.put("/api/design/plate-layout", json=body)
    assert r.status_code == 404


def test_put_plate_layout_unknown_tube_strand_404(client):
    body = {
        "orientation": "8x12",
        "plate_count": 1,
        "wells": [],
        "tubes": [{"strand_id": "ghost", "reason": "long"}],
    }
    r = client.put("/api/design/plate-layout", json=body)
    assert r.status_code == 404


def test_put_plate_layout_leaves_geometry_untouched(client):
    before = client.get("/api/design").json()["design"]
    n_helices_before = len(before["helices"])
    n_strands_before = len(before["strands"])

    body = {
        "orientation": "8x12",
        "plate_count": 1,
        "wells": [{"strand_id": "staple_0", "plate": 0, "row": 1, "col": 2}],
        "tubes": [],
    }
    assert client.put("/api/design/plate-layout", json=body).status_code == 200

    after = client.get("/api/design").json()["design"]
    assert len(after["helices"]) == n_helices_before
    assert len(after["strands"]) == n_strands_before
    assert after["helices"] == before["helices"]


# ── DELETE /design/plate-layout ───────────────────────────────────────────────


def test_delete_plate_layout_clears(client):
    body = {
        "orientation": "8x12",
        "plate_count": 1,
        "wells": [{"strand_id": "staple_0", "plate": 0, "row": 0, "col": 0}],
        "tubes": [],
    }
    assert client.put("/api/design/plate-layout", json=body).status_code == 200
    assert client.delete("/api/design/plate-layout").status_code == 200
    assert client.get("/api/design").json()["design"]["plate_layout"] is None


# ── Persistence via import ────────────────────────────────────────────────────


def test_plate_layout_survives_import(client):
    d = _demo_design()
    d.plate_layout = PlateLayout(
        orientation="8x12",
        plate_count=1,
        wells=[WellAssignment(strand_id="staple_0", plate=0, row=3, col=5)],
        tubes=[TubeAssignment(strand_id="staple_0", reason="modification")],
    )
    r = client.post("/api/design/import", json={"content": d.to_json()})
    assert r.status_code == 200

    got = client.get("/api/design").json()["design"]["plate_layout"]
    assert got is not None
    assert got["wells"] == [{"strand_id": "staple_0", "plate": 0, "row": 3, "col": 5}]
    assert got["tubes"] == [{"strand_id": "staple_0", "reason": "modification"}]
