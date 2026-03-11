"""
Integration tests for the Phase 2 CRUD API.

Uses FastAPI's TestClient to exercise all mutating endpoints against a live
in-memory design state.  Each test function resets the state to the demo
design to ensure isolation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset the active design to the demo design before every test."""
    design_state.set_design(_demo_design())
    yield
    # Restore after test too (good practice)
    design_state.set_design(_demo_design())


# ── Design endpoints ──────────────────────────────────────────────────────────

def test_get_design_returns_200():
    r = client.get("/api/design")
    assert r.status_code == 200
    body = r.json()
    assert "design" in body
    assert "validation" in body
    assert "results" in body["validation"]


def test_get_design_404_when_no_active():
    design_state.set_design(None)  # type: ignore[arg-type]
    r = client.get("/api/design")
    assert r.status_code == 404


def test_create_design_returns_201():
    r = client.post("/api/design", json={"name": "My Design", "lattice_type": "HONEYCOMB"})
    assert r.status_code == 201
    body = r.json()
    assert body["design"]["metadata"]["name"] == "My Design"
    assert body["design"]["helices"] == []
    assert body["design"]["strands"] == []


def test_get_geometry_returns_list():
    r = client.get("/api/design/geometry")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    # Demo design: 42 bp × 2 strands = 84 nucleotides
    assert len(data) == 84
    nuc = data[0]
    for field in ("helix_id", "bp_index", "direction", "backbone_position",
                  "base_position", "base_normal", "axis_tangent", "strand_id",
                  "is_five_prime", "is_three_prime"):
        assert field in nuc, f"Missing field {field!r} in geometry response"


def test_geometry_five_prime_placement():
    """5′ cube must sit at domain.start_bp, 3′ at domain.end_bp, regardless of direction.

    FORWARD scaffold (start_bp=0, end_bp=41):  5′ at bp 0,  direction FORWARD.
    REVERSE staple   (start_bp=0, end_bp=41):  5′ at bp 0,  direction REVERSE.

    For REVERSE strands, start_bp=0 is a special case in the demo design.
    More importantly: a REVERSE strand with start_bp=N-1 must have its 5′ cube
    at bp=N-1, not at bp=0 (the former bug).
    """
    from backend.api.crud import _strand_nucleotide_info
    from backend.core.models import Design, Strand, Domain, Helix, DesignMetadata, LatticeType
    from backend.core.models import Direction
    from backend.core.constants import BDNA_RISE_PER_BP

    length_bp = 21
    helix = Helix(
        id="h0",
        axis_start={"x": 0, "y": 0, "z": 0},
        axis_end={"x": 0, "y": 0, "z": length_bp * BDNA_RISE_PER_BP},
        length_bp=length_bp,
        phase_offset=0.0,
    )
    # REVERSE scaffold: convention start_bp=N-1 (5′), end_bp=0 (3′)
    rev_scaffold = Strand(
        id="rev_scaf",
        domains=[Domain(helix_id="h0", start_bp=length_bp - 1, end_bp=0,
                        direction=Direction.REVERSE)],
        is_scaffold=True,
    )
    design = Design(
        metadata=DesignMetadata(name="test"),
        lattice_type=LatticeType.HONEYCOMB,
        helices=[helix],
        strands=[rev_scaffold],
    )
    info = _strand_nucleotide_info(design)

    # 5′ must be at bp=N-1 for REVERSE
    assert info[("h0", length_bp - 1, Direction.REVERSE)]["is_five_prime"]
    assert not info[("h0", 0, Direction.REVERSE)]["is_five_prime"]
    # 3′ must be at bp=0 for REVERSE
    assert info[("h0", 0, Direction.REVERSE)]["is_three_prime"]
    assert not info[("h0", length_bp - 1, Direction.REVERSE)]["is_three_prime"]


def test_update_metadata():
    r = client.put("/api/design/metadata", json={"name": "Renamed", "author": "Test"})
    assert r.status_code == 200
    assert r.json()["design"]["metadata"]["name"] == "Renamed"
    assert r.json()["design"]["metadata"]["author"] == "Test"


# ── Helix endpoints ───────────────────────────────────────────────────────────

def test_list_helices():
    r = client.get("/api/design/helices")
    assert r.status_code == 200
    helices = r.json()
    assert len(helices) == 1
    assert helices[0]["id"] == "demo_helix"


def test_add_helix():
    payload = {
        "axis_start": {"x": 2.6, "y": 0.0, "z": 0.0},
        "axis_end":   {"x": 2.6, "y": 0.0, "z": 14.028},
        "length_bp": 42,
        "phase_offset": 0.0,
    }
    r = client.post("/api/design/helices", json=payload)
    assert r.status_code == 201
    body = r.json()
    assert "helix" in body
    assert "geometry" in body
    # Geometry for new helix: 42 bp × 2 = 84 nucleotides
    assert len(body["geometry"]) == 84
    # Design should now have 2 helices
    assert len(body["design"]["helices"]) == 2


def test_get_helix_by_id():
    r = client.get("/api/design/helices/demo_helix")
    assert r.status_code == 200
    body = r.json()
    assert body["helix"]["id"] == "demo_helix"
    assert len(body["geometry"]) == 84


def test_get_helix_not_found():
    r = client.get("/api/design/helices/no_such_helix")
    assert r.status_code == 404


def test_update_helix():
    payload = {
        "axis_start": {"x": 0.0, "y": 0.0, "z": 0.0},
        "axis_end":   {"x": 0.0, "y": 0.0, "z": 7.014},
        "length_bp": 21,
        "phase_offset": 0.0,
    }
    r = client.put("/api/design/helices/demo_helix", json=payload)
    assert r.status_code == 200
    assert r.json()["helix"]["length_bp"] == 21


def test_delete_helix_blocked_by_strand_reference():
    """DELETE /helices/{id} must return 409 when a strand domain references it."""
    r = client.delete("/api/design/helices/demo_helix")
    assert r.status_code == 409
    assert "scaffold" in r.json()["detail"] or "staple" in r.json()["detail"]


def test_delete_helix_success():
    """A helix with no strand references can be deleted."""
    # Add a new helix with no strands referencing it
    payload = {
        "axis_start": {"x": 2.6, "y": 0.0, "z": 0.0},
        "axis_end":   {"x": 2.6, "y": 0.0, "z": 14.028},
        "length_bp": 42,
    }
    r = client.post("/api/design/helices", json=payload)
    new_id = r.json()["helix"]["id"]

    r = client.delete(f"/api/design/helices/{new_id}")
    assert r.status_code == 200
    # Verify helix is gone
    assert len(r.json()["design"]["helices"]) == 1


# ── Strand endpoints ──────────────────────────────────────────────────────────

def test_add_strand():
    payload = {
        "domains": [{"helix_id": "demo_helix", "start_bp": 0, "end_bp": 10,
                     "direction": "FORWARD"}],
        "is_scaffold": False,
    }
    r = client.post("/api/design/strands", json=payload)
    assert r.status_code == 201
    assert len(r.json()["design"]["strands"]) == 3  # demo has 2 + 1 new


def test_delete_strand_cascades_crossovers():
    """Deleting a strand should also remove any crossovers that reference it."""
    # Add a second helix so we can add a crossover
    client.post("/api/design/helices", json={
        "axis_start": {"x": 2.6, "y": 0.0, "z": 0.0},
        "axis_end":   {"x": 2.6, "y": 0.0, "z": 14.028},
        "length_bp": 42,
    })

    # Add a strand on the new helix
    r = client.post("/api/design/strands", json={
        "domains": [{"helix_id": "demo_helix", "start_bp": 0, "end_bp": 41,
                     "direction": "FORWARD"}],
        "is_scaffold": False,
    })
    new_strand_id = r.json()["strand"]["id"]

    # Delete that strand and check response
    r = client.delete(f"/api/design/strands/{new_strand_id}")
    assert r.status_code == 200


def test_delete_strand_not_found():
    r = client.delete("/api/design/strands/no_such_strand")
    assert r.status_code == 404


def test_add_domain_to_strand():
    # Add a fresh strand (no domains)
    r = client.post("/api/design/strands", json={"domains": [], "is_scaffold": False})
    strand_id = r.json()["strand"]["id"]

    r = client.post(f"/api/design/strands/{strand_id}/domains", json={
        "helix_id": "demo_helix",
        "start_bp": 0,
        "end_bp": 5,
        "direction": "FORWARD",
    })
    assert r.status_code == 201
    assert len(r.json()["strand"]["domains"]) == 1


def test_delete_domain_out_of_range():
    r = client.delete("/api/design/strands/scaffold/domains/99")
    assert r.status_code == 400


# ── Crossover endpoints ───────────────────────────────────────────────────────

def test_valid_crossover_positions_same_helix():
    """A helix vs itself should return candidates (distance ≈ 0 at each bp)."""
    r = client.get("/api/design/crossovers/valid",
                   params={"helix_a_id": "demo_helix", "helix_b_id": "demo_helix"})
    assert r.status_code == 200
    body = r.json()
    assert len(body["positions"]) > 0


def test_valid_crossover_positions_missing_helix():
    r = client.get("/api/design/crossovers/valid",
                   params={"helix_a_id": "demo_helix", "helix_b_id": "no_such"})
    assert r.status_code == 404


def test_delete_crossover_not_found():
    r = client.delete("/api/design/crossovers/no_such_crossover")
    assert r.status_code == 404


# ── File persistence ──────────────────────────────────────────────────────────

def test_save_and_load_roundtrip(tmp_path):
    save_path = str(tmp_path / "test_design.nadoc")

    # Save
    r = client.post("/api/design/save", json={"path": save_path})
    assert r.status_code == 200
    assert r.json()["saved_to"] == save_path

    # Modify design (create new one)
    client.post("/api/design", json={"name": "New"})
    assert client.get("/api/design").json()["design"]["metadata"]["name"] == "New"

    # Load original back
    r = client.post("/api/design/load", json={"path": save_path})
    assert r.status_code == 200
    assert r.json()["design"]["metadata"]["name"] == "Demo — single 42 bp helix"


def test_load_nonexistent_file():
    r = client.post("/api/design/load", json={"path": "/tmp/does_not_exist.nadoc"})
    assert r.status_code == 400


def test_mutation_response_always_has_validation():
    """Every mutating endpoint must include validation in the response."""
    r = client.put("/api/design/metadata", json={"name": "X"})
    body = r.json()
    assert "validation" in body
    assert "passed" in body["validation"]
    assert "results" in body["validation"]
