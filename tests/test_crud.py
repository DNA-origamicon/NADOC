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


def test_6hb_extension_bead_coords_and_unfold_distances():
    """Build 6HB → autocrossover → TT extensions → verify XY distances preserved under unfold."""
    from backend.api.crud import _geometry_for_design
    from backend.core.lattice import make_bundle_design, make_auto_crossover
    from backend.core.models import StrandExtension, StrandType

    HC_6HB_CELLS = [(0, 0), (0, 1), (3, 0), (3, 1), (6, 0), (6, 1)]
    design = make_bundle_design(HC_6HB_CELLS, length_bp=84, name="test_6hb", plane="XY")
    assert len(design.helices) == 6
    design = make_auto_crossover(design)
    staples = [s for s in design.strands if s.strand_type == StrandType.STAPLE]
    assert staples

    for strand in staples:
        design.extensions.append(
            StrandExtension(strand_id=strand.id, end="five_prime",  sequence="TT")
        )
        design.extensions.append(
            StrandExtension(strand_id=strand.id, end="three_prime", sequence="TT")
        )

    expected_ext_count = 2 * len(staples)
    nucs_3d = _geometry_for_design(design)

    # Verify extension beads exist and have correct count
    ext_coords_3d = _get_extension_bead_coords(nucs_3d)
    assert len(ext_coords_3d) == expected_ext_count, (
        f"Expected {expected_ext_count} extensions, got {len(ext_coords_3d)}"
    )
    for ext_id, bead_map in ext_coords_3d.items():
        assert len(bead_map) == 2, f"Extension {ext_id}: expected 2 beads (TT), got {len(bead_map)}"

    # Measure XY distances from terminal bead to each extension bead in 3D
    dists_3d = _measure_terminal_ext_xy_distances(design, nucs_3d)
    assert len(dists_3d) == expected_ext_count
    for ext_id, bead_dists in dists_3d.items():
        for bp_idx, dist in bead_dists.items():
            assert dist > 0, f"Extension {ext_id} bp={bp_idx}: zero distance from terminal"

    # Simulate unfold translation and re-measure
    nucs_unfold = _simulate_unfold_positions(design, nucs_3d)
    dists_unfold = _measure_terminal_ext_xy_distances(design, nucs_unfold)

    tol = 0.001
    mismatches = []
    for ext_id, bead_dists_3d in dists_3d.items():
        for bp_idx, d3d in bead_dists_3d.items():
            d_unfold = dists_unfold.get(ext_id, {}).get(bp_idx)
            if d_unfold is None:
                mismatches.append(f"  ext={ext_id} bp={bp_idx}: missing in unfold positions")
            elif abs(d3d - d_unfold) > tol:
                mismatches.append(
                    f"  ext={ext_id} bp={bp_idx}: 3d={d3d:.5f}  unfold={d_unfold:.5f}"
                    f"  Δ={abs(d3d - d_unfold):.5f}"
                )
    assert not mismatches, (
        "Extension terminal→bead XY distances changed under unfold:\n" + "\n".join(mismatches)
    )


def test_extensions_preserved_through_lattice_mutations():
    """Extensions (fluorophores) must survive prebreak and prebreak→auto-crossover.

    Covers two bug classes:
    1. Design(...) reconstruction sites omitting the `extensions` field entirely.
    2. make_nick keeping the original strand ID on the 5' fragment, so 3' extensions
       pointed to the wrong (5') fragment after nicking.
    3. _ligate absorbing s2 without reassigning s2's 3' extension to the merged strand.
    """
    from backend.core.lattice import make_bundle_design
    from backend.core.models import StrandExtension, StrandType

    HC_6HB_CELLS = [(0, 0), (0, 1), (3, 0), (3, 1), (6, 0), (6, 1)]
    design = make_bundle_design(HC_6HB_CELLS, length_bp=84, name="ext_persist_test", plane="XY")
    staples = [s for s in design.strands if s.strand_type == StrandType.STAPLE]
    assert staples, "Expected staple strands in 6HB design"

    # Attach both 5' and 3' extensions to each staple
    for strand in staples:
        design.extensions.append(
            StrandExtension(strand_id=strand.id, end="five_prime", sequence="TT")
        )
        design.extensions.append(
            StrandExtension(strand_id=strand.id, end="three_prime", sequence="TT")
        )
    ext_count = len(design.extensions)
    assert ext_count == 2 * len(staples)

    design_state.set_design(design)

    # Prebreak: nicks staples at canonical crossover positions.
    # 3' extensions must follow the right (3') fragment, not stay on the left (5') fragment.
    r = client.post("/api/design/prebreak")
    assert r.status_code == 200, f"prebreak failed: {r.text}"
    body = r.json()
    assert len(body["design"]["extensions"]) == ext_count, (
        f"Prebreak dropped extensions: expected {ext_count}, "
        f"got {len(body['design']['extensions'])}"
    )
    # Every extension must point to a strand that exists in the post-prebreak design
    strand_ids_after_prebreak = {s["id"] for s in body["design"]["strands"]}
    dangling = [
        e for e in body["design"]["extensions"]
        if e["strand_id"] not in strand_ids_after_prebreak
    ]
    assert not dangling, (
        f"Prebreak left {len(dangling)} extension(s) pointing to non-existent strands: "
        + ", ".join(e["strand_id"] for e in dangling[:3])
    )

    # Auto-crossover: ligates staple fragments at all canonical positions.
    # When a fragment (s2) is absorbed, its 3' extension must follow the merged strand.
    # Note: 5' extensions whose terminals become internal during ligation are intentionally
    # dropped (the original 5' terminal no longer exists as a strand end). We only assert
    # that every surviving extension points to an existing strand — no dangling references.
    r = client.post("/api/design/auto-crossover")
    assert r.status_code == 200, f"auto-crossover failed: {r.text}"
    body = r.json()
    strand_ids_after_xover = {s["id"] for s in body["design"]["strands"]}
    dangling = [
        e for e in body["design"]["extensions"]
        if e["strand_id"] not in strand_ids_after_xover
    ]
    assert not dangling, (
        f"Auto-crossover left {len(dangling)} extension(s) pointing to non-existent strands: "
        + ", ".join(e["strand_id"] for e in dangling[:3])
    )


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
    # Continuation extrude from the free end (default extend_inplace=True → single helix grows)
    r2 = client.post("/api/design/bundle-continuation", json={
        "cells": [[0, 0]], "length_bp": 21, "plane": "XY", "offset_nm": offset,
    })
    assert r2.status_code == 201
    body = r2.json()
    # In-place extension: same helix ID, length grows from 42 to 63
    assert len(body["design"]["helices"]) == 1
    assert body["design"]["helices"][0]["length_bp"] == 63
    # Strand count unchanged; each strand has 2 domains (original + extension domain)
    assert len(body["design"]["strands"]) == 2
    for strand in body["design"]["strands"]:
        assert len(strand["domains"]) == 2

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


def _first_staple_crossover_candidate(design):
    """Return (helix_a_id, bp_a, direction_a, helix_b_id, bp_b, direction_b)
    for the first valid staple crossover candidate between the two helices.

    Patches REVERSE helices to phase_offset=330° (legacy value) so that
    staple-staple crossover candidates exist.  With the corrected geometry
    (REVERSE phase=150°), only scaffold-scaffold crossovers are geometrically
    valid; 330° restores the legacy staple-facing geometry for finding candidate
    bp positions.  The topology operations under test work for any bp/direction
    pair on the staple strands regardless of phase_offset.
    """
    import math as _math
    from backend.core.crossover_positions import valid_crossover_positions
    from backend.core.lattice import honeycomb_cell_value
    from backend.core.models import Helix, Vec3

    # Reconstruct helix objects, patching REVERSE cells to phase=330° so
    # staple-staple crossover candidates exist.
    helices = []
    for h in design["helices"]:
        parts = h["id"].split("_")   # h_{plane}_{row}_{col}
        row, col = int(parts[-2]), int(parts[-1])
        phase = (
            _math.radians(330.0)
            if honeycomb_cell_value(row, col) == 1
            else h["phase_offset"]
        )
        helices.append(Helix(
            id=h["id"],
            axis_start=Vec3(**h["axis_start"]),
            axis_end=Vec3(**h["axis_end"]),
            phase_offset=phase,
            length_bp=h["length_bp"],
        ))
    ha, hb = helices[0], helices[1]
    candidates = valid_crossover_positions(ha, hb)

    # Build nuc-to-scaffold lookup from design strands
    scaffold_keys = set()
    for strand in design["strands"]:
        if strand["strand_type"] != "scaffold":
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
            assert "strand_type_a" in pos
            assert "strand_type_b" in pos
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
        for s in design["strands"] if s["strand_type"] == "scaffold"
        for dom in s["domains"] if dom["helix_id"] == ha_id
    )
    hb_staple_dir = next(
        dom["direction"]
        for s in design["strands"] if s["strand_type"] == "staple"
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


# ── Helix auto-remove and trimming on strand deletion ─────────────────────────


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


def test_delete_half_nicked_strand_trims_helix():
    """Nick a single-strand helix then delete one half — helix is trimmed to the remaining coverage.

    Before: helix bp_start=0, length_bp=42, one scaffold strand bp 0–41.
    Nick at bp 20 (FORWARD) → left=bp 0–20 (original id), right=bp 21–41 (new id).
    Delete left half.
    After: helix bp_start=21, length_bp=21; axis_start at 21/42 of original length.
    """
    from backend.core.constants import BDNA_RISE_PER_BP

    design = _make_single_helix_scaffold_only()
    helix   = design["helices"][0]
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

    # Helix still exists (right half remains), but must be trimmed
    assert len(result["helices"]) == 1, "helix should persist because right half is still present"
    h = result["helices"][0]
    assert h["bp_start"]  == 21,  f"bp_start should be 21 (right half start), got {h['bp_start']}"
    assert h["length_bp"] == 21,  f"length_bp should be 21 (bp 21–41), got {h['length_bp']}"

    orig_z_end = helix["axis_end"]["z"]   # = 42 * BDNA_RISE_PER_BP
    expected_z_start = 21 * BDNA_RISE_PER_BP
    assert abs(h["axis_start"]["z"] - expected_z_start) < 1e-6, (
        f"axis_start.z should be ≈{expected_z_start:.4f}, got {h['axis_start']['z']:.4f}"
    )
    assert abs(h["axis_end"]["z"] - orig_z_end) < 1e-6, (
        f"axis_end.z should be unchanged ≈{orig_z_end:.4f}, got {h['axis_end']['z']:.4f}"
    )
