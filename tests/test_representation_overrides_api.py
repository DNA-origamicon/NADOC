"""
Tests for per-region representation overrides (mixed-representation feature).

A RepresentationOverride pins a render rep ('full' | 'cylinders') onto a set of
duplex COLUMNS (helix + bp ranges, via RepresentationSegment), so a focal region
of one structure can be emphasized at full detail against a coarser background
(publication figures). Position-based (not strand ids) so it survives strand
break/merge/crossover edits, and covers BOTH strands at each column.

It is display-only metadata persisted on Design.representation_overrides. It must:
  - round-trip losslessly through Design.to_json / from_json,
  - default to an empty list for old files (no migration),
  - be replaceable via PUT /design/representation-overrides
    (404 on unknown helix id; 422 on an override with no segments),
  - be clearable via DELETE /design/representation-overrides,
  - survive import (POST /design/import),
  - NOT mutate topology/geometry.

The resolution (segments → columns → both strands) and rendering happen
client-side, so they are exercised in the running app rather than here.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api.main import app
from backend.api import state as design_state
from backend.api.routes import _demo_design
from backend.core.models import Design, RepresentationOverride, RepresentationSegment

HELIX = "demo_helix"


@pytest.fixture(autouse=True)
def _reset():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


@pytest.fixture
def client():
    return TestClient(app)


# ── Model round-trip ────────────────────────────────────────────────────────


def test_representation_overrides_round_trip_through_json():
    d = _demo_design()
    d.representation_overrides = [
        RepresentationOverride(
            name="focus",
            representation="full",
            segments=[RepresentationSegment(helix_id=HELIX, bp_start=0, bp_end=10)],
        ),
        RepresentationOverride(
            name="bulk",
            representation="cylinders",
            segments=[RepresentationSegment(helix_id=HELIX, bp_start=11, bp_end=41)],
        ),
    ]
    restored = Design.from_json(d.to_json())
    assert restored.representation_overrides == d.representation_overrides


def test_missing_overrides_loads_as_empty_list():
    d = _demo_design()
    restored = Design.from_json(d.to_json())
    assert restored.representation_overrides == []


def test_surface_and_atomistic_reps_round_trip():
    d = _demo_design()
    d.representation_overrides = [
        RepresentationOverride(
            representation=rep,
            segments=[RepresentationSegment(helix_id=HELIX, bp_start=0, bp_end=5)],
        )
        for rep in ("surface", "vdw", "ballstick")
    ]
    restored = Design.from_json(d.to_json())
    assert [o.representation for o in restored.representation_overrides] == [
        "surface",
        "vdw",
        "ballstick",
    ]


def test_put_overrides_bogus_rep_422(client):
    body = {
        "overrides": [
            {
                "representation": "bogus",
                "segments": [{"helix_id": HELIX, "bp_start": 0, "bp_end": 5}],
            }
        ]
    }
    assert (
        client.put("/api/design/representation-overrides", json=body).status_code == 422
    )


def test_put_overrides_atomistic_rep_persists(client):
    body = {
        "overrides": [
            {
                "representation": "vdw",
                "segments": [{"helix_id": HELIX, "bp_start": 0, "bp_end": 8}],
            }
        ]
    }
    assert (
        client.put("/api/design/representation-overrides", json=body).status_code == 200
    )
    got = client.get("/api/design").json()["design"]["representation_overrides"]
    assert got[0]["representation"] == "vdw"


# ── POST /design/surface/region ───────────────────────────────────────────────


def test_region_surface_returns_mesh(client):
    body = {"segments": [{"helix_id": HELIX, "bp_start": 0, "bp_end": 41}]}
    r = client.post("/api/design/surface/region", json=body)
    assert r.status_code == 200
    data = r.json()
    assert len(data["vertices"]) > 0
    assert len(data["faces"]) > 0


def test_region_surface_empty_segments_zero_mesh(client):
    r = client.post("/api/design/surface/region", json={"segments": []})
    assert r.status_code == 200
    data = r.json()
    assert data["vertices"] == []
    assert data["faces"] == []


# ── PUT /design/representation-overrides ──────────────────────────────────────


def test_put_overrides_happy_path(client):
    body = {
        "overrides": [
            {
                "name": "focus",
                "representation": "cylinders",
                "segments": [{"helix_id": HELIX, "bp_start": 0, "bp_end": 20}],
            }
        ]
    }
    r = client.put("/api/design/representation-overrides", json=body)
    assert r.status_code == 200
    got = client.get("/api/design").json()["design"]["representation_overrides"]
    assert len(got) == 1
    assert got[0]["representation"] == "cylinders"
    assert got[0]["segments"] == [{"helix_id": HELIX, "bp_start": 0, "bp_end": 20}]
    assert got[0]["id"]


def test_put_overrides_unknown_helix_404(client):
    body = {
        "overrides": [
            {
                "representation": "full",
                "segments": [{"helix_id": "ghost", "bp_start": 0, "bp_end": 5}],
            }
        ]
    }
    assert (
        client.put("/api/design/representation-overrides", json=body).status_code == 404
    )


def test_put_overrides_empty_segments_422(client):
    body = {"overrides": [{"representation": "full", "segments": []}]}
    assert (
        client.put("/api/design/representation-overrides", json=body).status_code == 422
    )


def test_put_overrides_leaves_geometry_untouched(client):
    before = client.get("/api/design").json()["design"]
    body = {
        "overrides": [
            {
                "representation": "full",
                "segments": [{"helix_id": HELIX, "bp_start": 0, "bp_end": 5}],
            }
        ]
    }
    assert (
        client.put("/api/design/representation-overrides", json=body).status_code == 200
    )
    after = client.get("/api/design").json()["design"]
    assert after["helices"] == before["helices"]
    assert len(after["strands"]) == len(before["strands"])


# ── DELETE /design/representation-overrides ───────────────────────────────────


def test_delete_overrides_clears(client):
    body = {
        "overrides": [
            {
                "representation": "full",
                "segments": [{"helix_id": HELIX, "bp_start": 0, "bp_end": 5}],
            }
        ]
    }
    assert (
        client.put("/api/design/representation-overrides", json=body).status_code == 200
    )
    assert client.delete("/api/design/representation-overrides").status_code == 200
    assert client.get("/api/design").json()["design"]["representation_overrides"] == []


# ── Persistence via import ────────────────────────────────────────────────────


def test_overrides_survive_import(client):
    d = _demo_design()
    d.representation_overrides = [
        RepresentationOverride(
            name="focus",
            representation="cylinders",
            segments=[RepresentationSegment(helix_id=HELIX, bp_start=3, bp_end=9)],
        )
    ]
    r = client.post("/api/design/import", json={"content": d.to_json()})
    assert r.status_code == 200
    got = client.get("/api/design").json()["design"]["representation_overrides"]
    assert len(got) == 1
    assert got[0]["segments"] == [{"helix_id": HELIX, "bp_start": 3, "bp_end": 9}]
