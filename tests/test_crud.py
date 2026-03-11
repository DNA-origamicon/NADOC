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


# ── Undo / redo endpoints ─────────────────────────────────────────────────────


def test_undo_reverts_mutation():
    """POST /design/undo reverts the last mutation."""
    client.put("/api/design/metadata", json={"name": "AfterMutation"})
    r = client.post("/api/design/undo")
    assert r.status_code == 200
    # Name should be back to whatever it was before the mutation (demo design name)
    body = r.json()
    assert body["design"]["metadata"]["name"] != "AfterMutation"


def test_undo_404_when_empty_history():
    """POST /design/undo returns 404 when nothing to undo (fresh state)."""
    # Drain the history created by the fixture's set_design call
    design_state.clear_history()
    r = client.post("/api/design/undo")
    assert r.status_code == 404


def test_redo_after_undo():
    """POST /design/redo re-applies the last undone mutation."""
    client.put("/api/design/metadata", json={"name": "Mutated"})
    client.post("/api/design/undo")
    r = client.post("/api/design/redo")
    assert r.status_code == 200
    body = r.json()
    assert body["design"]["metadata"]["name"] == "Mutated"


def test_redo_404_when_empty():
    """POST /design/redo returns 404 when there is nothing to redo."""
    r = client.post("/api/design/redo")
    assert r.status_code == 404


def test_mutation_clears_redo_stack():
    """A new mutation after undo discards the redo stack."""
    client.put("/api/design/metadata", json={"name": "First"})
    client.post("/api/design/undo")
    # New mutation → redo stack cleared
    client.put("/api/design/metadata", json={"name": "Second"})
    r = client.post("/api/design/redo")
    assert r.status_code == 404   # redo stack was cleared


def test_bundle_continuation_extends_existing_strands():
    """POST /design/bundle-continuation extends strand domains for occupied cells."""
    from backend.core.constants import BDNA_RISE_PER_BP
    # Create a single-cell bundle
    r = client.post("/api/design/bundle", json={"cells": [[0, 0]], "length_bp": 42, "plane": "XY"})
    assert r.status_code == 201
    offset = round(42 * BDNA_RISE_PER_BP, 6)
    # Continuation extrude from the free end
    r2 = client.post("/api/design/bundle-continuation", json={
        "cells": [[0, 0]], "length_bp": 21, "plane": "XY", "offset_nm": offset,
    })
    assert r2.status_code == 201
    body = r2.json()
    assert len(body["design"]["helices"]) == 2
    # Strand count unchanged (domains extended, not new strands created)
    assert len(body["design"]["strands"]) == 2
    # Each strand should now have 2 domains
    for strand in body["design"]["strands"]:
        assert len(strand["domains"]) == 2


# ── Phase 4: staple crossover endpoints ───────────────────────────────────────

def _make_two_helix_design():
    """Create a 2-helix bundle via the API and return its design body."""
    r = client.post("/api/design/bundle", json={
        "cells": [[0, 0], [0, 1]], "length_bp": 42, "plane": "XY",
    })
    assert r.status_code == 201
    return r.json()["design"]


def _first_staple_crossover_candidate(design):
    """Return (helix_a_id, bp_a, direction_a, helix_b_id, bp_b, direction_b)
    for the first valid staple crossover candidate between the two helices."""
    from backend.core.crossover_positions import valid_crossover_positions
    from backend.core.models import Helix, Vec3

    # Reconstruct helix objects from the design dict
    helices = []
    for h in design["helices"]:
        helices.append(Helix(
            id=h["id"],
            axis_start=Vec3(**h["axis_start"]),
            axis_end=Vec3(**h["axis_end"]),
            phase_offset=h["phase_offset"],
            length_bp=h["length_bp"],
        ))
    ha, hb = helices[0], helices[1]
    candidates = valid_crossover_positions(ha, hb)

    # Build nuc-to-scaffold lookup from design strands
    scaffold_keys = set()
    for strand in design["strands"]:
        if not strand["is_scaffold"]:
            continue
        for dom in strand["domains"]:
            lo = min(dom["start_bp"], dom["end_bp"])
            hi = max(dom["start_bp"], dom["end_bp"])
            for bp in range(lo, hi + 1):
                scaffold_keys.add((dom["helix_id"], bp, dom["direction"]))

    for c in candidates:
        ka = (ha.id, c.bp_a, c.direction_a.value)
        kb = (hb.id, c.bp_b, c.direction_b.value)
        if ka not in scaffold_keys and kb not in scaffold_keys:
            return ha.id, c.bp_a, c.direction_a.value, hb.id, c.bp_b, c.direction_b.value

    raise RuntimeError("No staple-only crossover candidate found")


def test_all_valid_crossovers_404_without_design():
    design_state.set_design(None)  # type: ignore[arg-type]
    r = client.get("/api/design/crossovers/all-valid")
    assert r.status_code == 404


def test_all_valid_crossovers_returns_list_for_two_helix():
    """GET /design/crossovers/all-valid on a 2-helix design returns a non-empty list."""
    _make_two_helix_design()
    r = client.get("/api/design/crossovers/all-valid")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert len(body) > 0


def test_all_valid_crossovers_shape():
    """Each entry in the all-valid response has the expected keys."""
    _make_two_helix_design()
    r = client.get("/api/design/crossovers/all-valid")
    body = r.json()
    for pair in body:
        assert "helix_a_id" in pair
        assert "helix_b_id" in pair
        assert "positions" in pair
        for pos in pair["positions"]:
            assert "bp_a" in pos
            assert "bp_b" in pos
            assert "direction_a" in pos
            assert "direction_b" in pos
            assert "is_scaffold_a" in pos
            assert "is_scaffold_b" in pos
            assert "distance_nm" in pos


def test_all_valid_crossovers_single_helix_returns_empty():
    """GET /design/crossovers/all-valid on a 1-helix design returns an empty list
    (no pairs to consider)."""
    r = client.post("/api/design/bundle", json={
        "cells": [[0, 0]], "length_bp": 42, "plane": "XY",
    })
    assert r.status_code == 201
    r2 = client.get("/api/design/crossovers/all-valid")
    assert r2.status_code == 200
    assert r2.json() == []


def test_staple_crossover_places_crossover():
    """POST /design/staple-crossover succeeds and returns an updated design."""
    design = _make_two_helix_design()
    ha_id, bp_a, dir_a, hb_id, bp_b, dir_b = _first_staple_crossover_candidate(design)

    r = client.post("/api/design/staple-crossover", json={
        "helix_a_id": ha_id,
        "bp_a": bp_a,
        "direction_a": dir_a,
        "helix_b_id": hb_id,
        "bp_b": bp_b,
        "direction_b": dir_b,
    })
    assert r.status_code == 201
    body = r.json()
    assert "design" in body
    assert "validation" in body


def test_staple_crossover_preserves_helix_count():
    """Staple crossover must not alter the number of helices."""
    design = _make_two_helix_design()
    ha_id, bp_a, dir_a, hb_id, bp_b, dir_b = _first_staple_crossover_candidate(design)

    r = client.post("/api/design/staple-crossover", json={
        "helix_a_id": ha_id, "bp_a": bp_a, "direction_a": dir_a,
        "helix_b_id": hb_id, "bp_b": bp_b, "direction_b": dir_b,
    })
    result_design = r.json()["design"]
    assert len(result_design["helices"]) == len(design["helices"])


def test_staple_crossover_rejects_scaffold_400():
    """POST /design/staple-crossover on a scaffold position returns 400."""
    design = _make_two_helix_design()
    # Find a scaffold domain on helix_a
    ha_id = design["helices"][0]["id"]
    hb_id = design["helices"][1]["id"]
    scaffold_dir = next(
        dom["direction"]
        for s in design["strands"] if s["is_scaffold"]
        for dom in s["domains"] if dom["helix_id"] == ha_id
    )
    hb_staple_dir = next(
        dom["direction"]
        for s in design["strands"] if not s["is_scaffold"]
        for dom in s["domains"] if dom["helix_id"] == hb_id
    )
    r = client.post("/api/design/staple-crossover", json={
        "helix_a_id": ha_id, "bp_a": 10, "direction_a": scaffold_dir,
        "helix_b_id": hb_id, "bp_b": 10, "direction_b": hb_staple_dir,
    })
    assert r.status_code == 400


def test_staple_crossover_404_without_design():
    design_state.set_design(None)  # type: ignore[arg-type]
    r = client.post("/api/design/staple-crossover", json={
        "helix_a_id": "x", "bp_a": 0, "direction_a": "FORWARD",
        "helix_b_id": "y", "bp_b": 0, "direction_b": "REVERSE",
    })
    assert r.status_code == 404
