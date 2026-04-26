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
    assert isinstance(data, dict), "geometry endpoint must return { nucleotides, helix_axes }"
    assert "nucleotides" in data
    assert "helix_axes" in data
    nucs = data["nucleotides"]
    # Demo design: 42 bp × 2 strands = 84 nucleotides
    assert len(nucs) == 84
    nuc = nucs[0]
    for field in ("helix_id", "bp_index", "direction", "backbone_position",
                  "base_position", "base_normal", "axis_tangent", "strand_id",
                  "is_five_prime", "is_three_prime"):
        assert field in nuc, f"Missing field {field!r} in geometry response"
    # helix_axes: one entry per helix, each with helix_id, start, end
    axes = data["helix_axes"]
    assert isinstance(axes, list) and len(axes) >= 1
    ax = axes[0]
    assert "helix_id" in ax and "start" in ax and "end" in ax
    assert len(ax["start"]) == 3 and len(ax["end"]) == 3


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
    from backend.core.models import Direction, StrandType
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
        strand_type=StrandType.SCAFFOLD,
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


def _make_design_with_five_prime_extension():
    """Minimal design: one FORWARD helix, one FORWARD staple strand, one 5' TT extension."""
    from backend.core.models import (
        Design, Helix, Strand, Domain, StrandExtension, DesignMetadata,
        Direction, StrandType, LatticeType,
    )
    helix_id = "h_test"
    strand_id = "s_test"
    h = Helix(
        id=helix_id,
        length_bp=10,
        bp_start=0,
        axis_start={"x": 0, "y": 0, "z": 0},
        axis_end={"x": 0, "y": 0, "z": 3.34},
        phase_offset=0.0,
    )
    domain = Domain(helix_id=helix_id, direction=Direction.FORWARD, start_bp=0, end_bp=9)
    strand = Strand(id=strand_id, domains=[domain], strand_type=StrandType.STAPLE)
    ext = StrandExtension(strand_id=strand_id, end="five_prime", sequence="TT")
    design = Design(
        metadata=DesignMetadata(name="test"),
        lattice_type=LatticeType.HONEYCOMB,
        helices=[h],
        strands=[strand],
        extensions=[ext],
    )
    return design, ext


def test_five_prime_extension_tip_is_cube():
    """Outermost bead of a 5' extension must have is_five_prime=True (cube marker)."""
    from backend.api.crud import _geometry_for_design
    design, ext = _make_design_with_five_prime_extension()
    nucs = _geometry_for_design(design)
    ext_nucs = [n for n in nucs if n.get("extension_id") == ext.id and not n.get("is_modification")]
    assert ext_nucs, "No extension nucleotides found in geometry"
    ext_nucs.sort(key=lambda n: n["bp_index"])
    outermost = ext_nucs[-1]
    assert outermost["is_five_prime"], (
        f"Outermost 5' extension bead (bp={outermost['bp_index']}) "
        f"should be is_five_prime=True, got False"
    )


def test_five_prime_extension_old_terminal_loses_cube():
    """Original 5' terminal on the real helix must lose is_five_prime when a 5' extension exists."""
    from backend.api.crud import _geometry_for_design
    from backend.core.models import Direction
    design, _ = _make_design_with_five_prime_extension()
    nucs = _geometry_for_design(design)
    real_terminal = next(
        (n for n in nucs
         if n["helix_id"] == "h_test"
         and n["bp_index"] == 0
         and n["direction"] == Direction.FORWARD.value
         and not n["helix_id"].startswith("__")),
        None,
    )
    assert real_terminal is not None, "Original 5' terminal nuc not found"
    assert not real_terminal["is_five_prime"], (
        "Original 5' terminal should no longer be is_five_prime=True once a 5' extension is attached"
    )


# ── Extension bead coordinate helpers ────────────────────────────────────────

def _get_extension_bead_coords(nucs):
    """Return {extension_id: {bp_index: [x, y, z]}} for all extension sequence beads."""
    result = {}
    for nuc in nucs:
        ext_id = nuc.get("extension_id")
        if not ext_id or nuc.get("is_modification"):
            continue
        result.setdefault(ext_id, {})[nuc["bp_index"]] = nuc["backbone_position"]
    return result


def _measure_terminal_ext_xy_distances(design, nucs):
    """For each extension return {ext_id: {bp_index: xy_distance_from_terminal}} (XY only)."""
    import math
    nuc_by_key = {
        (n["helix_id"], n["bp_index"], n["direction"]): n
        for n in nucs if not n["helix_id"].startswith("__")
    }
    strand_by_id = {s.id: s for s in design.strands}
    ext_by_id    = {e.id: e for e in design.extensions}
    ext_coords   = _get_extension_bead_coords(nucs)
    distances = {}
    for ext_id, bead_map in ext_coords.items():
        ext    = ext_by_id.get(ext_id)
        strand = strand_by_id.get(ext.strand_id) if ext else None
        if not strand or not strand.domains:
            continue
        if ext.end == "five_prime":
            dom, term_bp = strand.domains[0], strand.domains[0].start_bp
        else:
            dom, term_bp = strand.domains[-1], strand.domains[-1].end_bp
        term_nuc = nuc_by_key.get((dom.helix_id, term_bp, dom.direction.value))
        if not term_nuc:
            continue
        tx, ty, _ = term_nuc["backbone_position"]
        distances[ext_id] = {
            bp_idx: math.sqrt((pos[0] - tx) ** 2 + (pos[1] - ty) ** 2)
            for bp_idx, pos in bead_map.items()
        }
    return distances


def _simulate_unfold_positions(design, nucs, spacing=3.0):
    """Python replica of JS unfold XY translation: offset = (-cx, -row*spacing - cy, 0)."""
    helix_offset = {}
    for row_idx, h in enumerate(design.helices):
        cx = (h.axis_start.x + h.axis_end.x) / 2
        cy = (h.axis_start.y + h.axis_end.y) / 2
        helix_offset[h.id] = (-cx, -row_idx * spacing - cy, 0.0)
    strand_by_id = {s.id: s for s in design.strands}
    ext_to_helix = {}
    for ext in design.extensions:
        strand = strand_by_id.get(ext.strand_id)
        if not strand or not strand.domains:
            continue
        dom = strand.domains[0] if ext.end == "five_prime" else strand.domains[-1]
        ext_to_helix[ext.id] = dom.helix_id
    result = []
    for nuc in nucs:
        n = dict(nuc)
        x, y, z = nuc["backbone_position"]
        ext_id = nuc.get("extension_id")
        if ext_id:
            off = helix_offset.get(ext_to_helix.get(ext_id), (0.0, 0.0, 0.0))
            n["backbone_position"] = [x + off[0], y + off[1], z]
        else:
            off = helix_offset.get(nuc["helix_id"], (0.0, 0.0, 0.0))
            n["backbone_position"] = [x + off[0], y + off[1], z]
        result.append(n)
    return result


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
        "strand_type": "staple",
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
        "strand_type": "staple",
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
    r = client.post("/api/design/strands", json={"domains": [], "strand_type": "staple"})
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


def test_snapshot_undo_not_corrupted_by_later_mutation():
    """snapshot() must deep-copy so later in-place mutations don't corrupt the undo entry."""
    design_state.clear_history()

    # Record how many helices we start with
    original = client.get("/api/design").json()["design"]
    n_helices_before = len(original["helices"])

    # Use snapshot + set_design_silent (the multi-step pattern used by cadnano editor ops)
    design_state.snapshot()
    # set_design_silent with a copy_with — shallow copy shares helices list
    d = design_state.get_or_404()
    new_d = d.copy_with(strands=list(d.strands))  # only strands overridden, helices shared
    design_state.set_design_silent(new_d)

    # Now a second mutation via mutate_and_validate that appends a helix in-place
    from backend.core.models import Helix, Vec3
    design_state.mutate_and_validate(lambda d: d.helices.append(
        Helix(id="test_hx", bp_start=0, length_bp=10,
              axis_start=Vec3(x=0, y=0, z=0), axis_end=Vec3(x=0, y=0, z=3.4))
    ))

    # After the in-place mutation, the active design should have one more helix
    current = client.get("/api/design").json()["design"]
    assert len(current["helices"]) == n_helices_before + 1

    # First undo should revert the mutate_and_validate (remove test_hx)
    r1 = client.post("/api/design/undo")
    assert r1.status_code == 200
    after_first_undo = r1.json()["design"]
    assert len(after_first_undo["helices"]) == n_helices_before

    # Second undo should revert the snapshot (back to original)
    r2 = client.post("/api/design/undo")
    assert r2.status_code == 200
    after_second_undo = r2.json()["design"]
    # CRITICAL: the snapshot entry must NOT have been corrupted by the in-place append
    assert len(after_second_undo["helices"]) == n_helices_before


def test_undo_after_crossover_placement():
    """Undo after cadnano editor crossover placement restores the prior state."""
    # Build a 2-helix honeycomb bundle to get crossover-eligible helices
    r = client.post("/api/design/bundle", json={
        "cells": [[0, 0], [0, 1]], "length_bp": 42, "plane": "XY",
    })
    assert r.status_code == 201
    body = r.json()
    n_strands_before = len(body["design"]["strands"])
    n_xovers_before = len(body["design"].get("crossovers", []))

    # Auto-crossover creates crossovers (snapshot-based multi-step op)
    r2 = client.post("/api/design/crossovers/auto")
    assert r2.status_code == 200
    n_xovers_after = len(r2.json()["design"].get("crossovers", []))
    # Should have placed at least one crossover
    assert n_xovers_after > n_xovers_before

    # Undo should fully revert
    r3 = client.post("/api/design/undo")
    assert r3.status_code == 200
    after_undo = r3.json()["design"]
    assert len(after_undo.get("crossovers", [])) == n_xovers_before
    assert len(after_undo["strands"]) == n_strands_before


def test_bundle_continuation_extends_existing_strands():
    """POST /design/bundle-continuation extends strand domains for occupied cells."""
    from backend.core.constants import BDNA_RISE_PER_BP
    # Create a single-cell bundle
    r = client.post("/api/design/bundle", json={"cells": [[0, 0]], "length_bp": 42, "plane": "XY"})
    assert r.status_code == 201
    offset = round(42 * BDNA_RISE_PER_BP, 6)
    # Continuation extrude from the free end (default extend_inplace=True → single helix grows)
    r2 = client.post("/api/design/bundle-continuation", json={
        "cells": [[0, 0]], "length_bp": 21, "plane": "XY", "offset_nm": offset,
    })
    assert r2.status_code == 201
    body = r2.json()
    # In-place extension: same helix ID, length grows from 42 to 63
    assert len(body["design"]["helices"]) == 1
    assert body["design"]["helices"][0]["length_bp"] == 63
    # Strand count unchanged; domains merged into 1 per strand (in-place extension)
    assert len(body["design"]["strands"]) == 2
    for strand in body["design"]["strands"]:
        assert len(strand["domains"]) == 1

    # extend_inplace=False creates a new helix (legacy behaviour)
    r3 = client.post("/api/design/bundle-continuation", json={
        "cells": [[0, 0]], "length_bp": 21, "plane": "XY",
        "offset_nm": round(63 * BDNA_RISE_PER_BP, 6), "extend_inplace": False,
    })
    assert r3.status_code == 201
    body3 = r3.json()
    assert len(body3["design"]["helices"]) == 2


# ── Phase 4: staple crossover endpoints ───────────────────────────────────────

def _make_two_helix_design():
    """Create a 2-helix bundle via the API and return its design body."""
    r = client.post("/api/design/bundle", json={
        "cells": [[0, 0], [0, 1]], "length_bp": 42, "plane": "XY",
    })
    assert r.status_code == 201
    return r.json()["design"]


def _make_single_helix_scaffold_only():
    """Create an empty design with one 42-bp scaffold-only helix via the API."""
    client.post("/api/design", json={"name": "trim_test", "lattice_type": "HONEYCOMB"})
    r = client.post("/api/design/bundle-segment", json={
        "cells": [[0, 0]], "length_bp": 42, "plane": "XY",
        "offset_nm": 0.0, "strand_filter": "scaffold",
    })
    assert r.status_code == 201
    return r.json()["design"]


def test_delete_sole_strand_removes_helix():
    """Deleting the only strand on a helix auto-removes that helix."""
    design = _make_single_helix_scaffold_only()
    assert len(design["helices"]) == 1
    assert len(design["strands"]) == 1
    strand_id = design["strands"][0]["id"]

    r = client.delete(f"/api/design/strands/{strand_id}")
    assert r.status_code == 200
    result = r.json()["design"]
    assert result["helices"] == [], "helix should be removed when its only strand is deleted"


def test_delete_half_nicked_strand_preserves_helix():
    """Nick a single-strand helix then delete one half — helix axis is preserved intact.

    Helix geometry is a topological property fixed at creation; strand operations
    must not modify axis_start, axis_end, bp_start, or length_bp.

    Before: helix bp_start=0, length_bp=42, one scaffold strand bp 0–41.
    Nick at bp 20 (FORWARD) → left=bp 0–20 (original id), right=bp 21–41 (new id).
    Delete left half.
    After: helix still present with original bp_start=0, length_bp=42, and
           axis_start/axis_end unchanged.
    """
    design = _make_single_helix_scaffold_only()
    helix    = design["helices"][0]
    helix_id = helix["id"]
    strand_id = design["strands"][0]["id"]  # original scaffold id (becomes left after nick)

    # Nick at bp 20 — creates left (keeps strand_id) and right (new id)
    r = client.post("/api/design/nick", json={
        "helix_id": helix_id, "bp_index": 20, "direction": "FORWARD",
    })
    assert r.status_code == 201

    # Delete the left half (bp 0–20, original strand id)
    r = client.delete(f"/api/design/strands/{strand_id}")
    assert r.status_code == 200
    result = r.json()["design"]

    # Helix still exists (right half remains)
    assert len(result["helices"]) == 1, "helix should persist because right half is still present"
    h = result["helices"][0]

    # Helix geometry must not be trimmed — axis is fixed at creation.
    assert h["bp_start"]  == helix["bp_start"],  "bp_start must not change on strand deletion"
    assert h["length_bp"] == helix["length_bp"], "length_bp must not change on strand deletion"
    assert abs(h["axis_start"]["z"] - helix["axis_start"]["z"]) < 1e-6, "axis_start must not change"
    assert abs(h["axis_end"]["z"]   - helix["axis_end"]["z"])   < 1e-6, "axis_end must not change"


# ── Multiselect crossover deletion (no cascade) ─────────────────────────────

def test_delete_subset_of_crossovers_no_cascade():
    """Deleting N crossovers sequentially should remove exactly those N — no cascade.

    Reproduces the bug where deleting multi-selected crossovers caused a
    deletion cascade: the selected crossover was removed, then an adjacent
    crossover, then a domain/end — because end-cap keys at the same position
    were inadvertently included in the selection.

    This test validates the backend side: sequential DELETE calls should each
    succeed and only remove their target crossover.
    """
    # Create a 6HB honeycomb bundle
    cells = [[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]]
    r = client.post("/api/design/bundle", json={
        "cells": cells, "length_bp": 42, "name": "6hb_test",
    })
    assert r.status_code == 201
    design = r.json()["design"]
    assert len(design["helices"]) == 6

    # Run autocrossover
    r = client.post("/api/design/crossovers/auto")
    assert r.status_code == 200
    design = r.json()["design"]
    all_xovers = design["crossovers"]
    total = len(all_xovers)
    assert total >= 3, f"Expected at least 3 crossovers on 6HB, got {total}"

    # Pick a subset to delete (first 3)
    to_delete = [xo["id"] for xo in all_xovers[:3]]
    to_keep   = {xo["id"] for xo in all_xovers[3:]}

    # Delete them one by one (same as the frontend loop)
    for xo_id in to_delete:
        r = client.delete(f"/api/design/crossovers/{xo_id}")
        assert r.status_code == 200, f"Failed to delete crossover {xo_id}: {r.json()}"

    # Verify exactly the kept crossovers remain
    design = r.json()["design"]
    remaining_ids = {xo["id"] for xo in design["crossovers"]}
    assert remaining_ids == to_keep, (
        f"Expected {len(to_keep)} crossovers to remain, got {len(remaining_ids)}.\n"
        f"  Missing: {to_keep - remaining_ids}\n"
        f"  Unexpected: {remaining_ids - to_keep}"
    )
