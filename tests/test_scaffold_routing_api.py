"""
API validation tests for advanced scaffold routing features:

  Feature 1 — POST /design/auto-scaffold-seamless
  Feature 2 — POST /design/assign-scaffold-sequence  (custom_sequence + strand_id)
  Feature 3a — POST /design/partition-scaffold
  Feature 3b — POST /design/scaffold-split

Each class exercises one endpoint end-to-end via TestClient: request shape,
status codes, response body, and persistent design-state changes.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.lattice import auto_scaffold, auto_scaffold_partition, make_bundle_design
from backend.core.models import StrandType

client = TestClient(app)

CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]
CELLS_12HB = [
    (0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1),
    (3, 1), (3, 0), (4, 0), (3, 2), (4, 2), (5, 1),
]


# ── autouse reset ─────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_state():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


# ── shared setup helpers ───────────────────────────────────────────────────────

def _load_6hb(length_bp: int = 200):
    """Unrouted 6HB (per-helix scaffold strands only)."""
    d = make_bundle_design(CELLS_6HB, length_bp=length_bp)
    design_state.set_design(d)
    return d


def _load_routed_6hb(length_bp: int = 200):
    """6HB with a single end_to_end scaffold strand."""
    d = make_bundle_design(CELLS_6HB, length_bp=length_bp)
    d = auto_scaffold(d, mode="end_to_end", scaffold_loops=True, min_end_margin=5)
    design_state.set_design(d)
    return d


def _load_12hb(length_bp: int = 200):
    """Unrouted 12HB."""
    d = make_bundle_design(CELLS_12HB, length_bp=length_bp)
    design_state.set_design(d)
    return d


def _load_partitioned_12hb(length_bp: int = 200):
    """12HB with two scaffold strands (one per 6-helix group)."""
    d = make_bundle_design(CELLS_12HB, length_bp=length_bp)
    grp1 = [h.id for h in d.helices[:6]]
    grp2 = [h.id for h in d.helices[6:12]]
    d = auto_scaffold_partition(
        d, helix_groups=[grp1, grp2], mode="end_to_end", min_end_margin=5
    )
    design_state.set_design(d)
    return d


def _scaffold_strands_in(body: dict) -> list[dict]:
    return [s for s in body["design"]["strands"] if s["strand_type"] == "scaffold"]


# ── Feature 1: POST /design/auto-scaffold-seamless ────────────────────────────


def _load_2hb(length_bp: int = 200):
    """Minimal 2-helix design: one FORWARD (0,0) and one REVERSE (0,1) helix."""
    d = make_bundle_design([(0, 0), (0, 1)], length_bp=length_bp)
    design_state.set_design(d)
    return d


class TestAutoScaffoldSeamlessAPI:
    """Phase 1: left-side crossovers only.

    CELLS_6HB uses a hexagonal arrangement where only one adjacent pair
    — (0,0)↔(0,1) — has a valid left-side crossover position (bp=6) that
    clears the default min_staple_margin=3 from the staple ends at bp=0.
    The other four helices have no valid left-side lattice neighbours in this
    design, so they remain individual per-helix strands.

    For a clean 1-pair test with guaranteed 1 crossover, _load_2hb() is used.
    """

    def test_200_on_6hb(self):
        _load_6hb()
        r = client.post("/api/design/auto-scaffold-seamless", json={})
        assert r.status_code == 200

    def test_6hb_places_at_least_one_crossover(self):
        """The hex 6HB layout yields exactly one valid left-side pair."""
        _load_6hb()
        body = client.post("/api/design/auto-scaffold-seamless", json={}).json()
        crossovers = body["design"].get("crossovers", [])
        assert len(crossovers) >= 1

    def test_response_contains_design_and_validation(self):
        _load_6hb()
        body = client.post("/api/design/auto-scaffold-seamless", json={}).json()
        assert "design" in body
        assert "validation" in body
        assert "results" in body["validation"]

    def test_422_on_single_isolated_helix(self):
        """Single helix has no XY neighbours — no crossovers can be placed."""
        d = make_bundle_design([(0, 0)], length_bp=200)
        design_state.set_design(d)
        r = client.post("/api/design/auto-scaffold-seamless", json={})
        assert r.status_code == 422

    # ── 2HB clean-pair tests ──────────────────────────────────────────────────

    def test_2hb_produces_one_crossover(self):
        """Two adjacent helices → exactly one left-side crossover."""
        _load_2hb()
        body = client.post("/api/design/auto-scaffold-seamless", json={}).json()
        crossovers = body["design"].get("crossovers", [])
        assert len(crossovers) == 1

    def test_2hb_produces_one_merged_strand(self):
        """One pair → one merged scaffold strand spanning both helices."""
        _load_2hb()
        body = client.post("/api/design/auto-scaffold-seamless", json={}).json()
        scaf = _scaffold_strands_in(body)
        assert len(scaf) == 1
        helix_ids = {d["helix_id"] for d in scaf[0]["domains"]}
        assert len(helix_ids) == 2

    def test_2hb_crossover_clears_staple_margin(self):
        """Crossover bp must be > 3 bp from any staple end on either helix."""
        _load_2hb()
        body = client.post("/api/design/auto-scaffold-seamless", json={}).json()
        design = body["design"]
        # Collect staple ends: set of (helix_id, bp)
        staple_ends: set[tuple[str, int]] = set()
        for s in design["strands"]:
            if s["strand_type"] != "staple" or not s["domains"]:
                continue
            first, last = s["domains"][0], s["domains"][-1]
            staple_ends.add((first["helix_id"], first["start_bp"]))
            staple_ends.add((last["helix_id"], last["end_bp"]))
        for xo in design["crossovers"]:
            X = xo["half_a"]["index"]
            for helix_id in (xo["half_a"]["helix_id"], xo["half_b"]["helix_id"]):
                for (hid, bp) in staple_ends:
                    if hid == helix_id:
                        assert abs(X - bp) > 3, (
                            f"Crossover at bp={X} on {helix_id} is within 3 bp "
                            f"of staple end at bp={bp}"
                        )

    def test_design_state_updated(self):
        """Persisted design reflects left-side crossover changes."""
        _load_2hb()
        client.post("/api/design/auto-scaffold-seamless", json={})
        updated = design_state.get_or_404()
        scaffolds = [s for s in updated.strands if s.strand_type == StrandType.SCAFFOLD]
        assert len(scaffolds) == 1  # one merged strand for the 2-helix pair

    # ── Maximum-matching coverage tests ──────────────────────────────────────

    def test_hc_strip_6hb_three_crossovers(self):
        """HC 6-helix linear strip: full routing → 1 scaffold strand spanning all 6 helices.
        3 left-side crossovers + 2 right-side crossovers = 5 total.
        """
        cells = [(0, 0), (0, 1), (0, 2), (0, 3), (0, 4), (0, 5)]
        d = make_bundle_design(cells, length_bp=200)
        design_state.set_design(d)
        body = client.post("/api/design/auto-scaffold-seamless", json={}).json()
        assert body.get("detail") is None, body.get("detail")
        crossovers = body["design"].get("crossovers", [])
        assert len(crossovers) == 5, f"expected 5 crossovers, got {len(crossovers)}"
        scaf = _scaffold_strands_in(body)
        # All 6 helices merged into a single scaffold strand
        assert len(scaf) == 1, f"expected 1 scaffold strand, got {len(scaf)}"
        assert len(scaf[0]["domains"]) == 6, \
            f"expected 6 domains, got {len(scaf[0]['domains'])}"

    def test_hc_8hb_grid_all_helices_covered(self):
        """HC 8HB 2-row grid: full routing → 1 scaffold strand spanning all 8 helices.
        4 left-side crossovers + 3 right-side crossovers = 7 total.
        """
        cells = [(0, 0), (0, 1), (0, 2), (0, 3), (1, 0), (1, 1), (1, 2), (1, 3)]
        d = make_bundle_design(cells, length_bp=200)
        design_state.set_design(d)
        body = client.post("/api/design/auto-scaffold-seamless", json={}).json()
        assert body.get("detail") is None, body.get("detail")
        crossovers = body["design"].get("crossovers", [])
        assert len(crossovers) == 7, f"expected 7 crossovers, got {len(crossovers)}"
        # Every helix must appear in the merged scaffold strand.
        scaf = _scaffold_strands_in(body)
        all_helix_ids = {h["id"] for h in body["design"]["helices"]}
        strand_helix_ids = {d["helix_id"] for s in scaf for d in s["domains"]}
        assert strand_helix_ids == all_helix_ids, \
            f"uncovered helices: {all_helix_ids - strand_helix_ids}"

    def test_sq_6hb_grid_all_helices_covered(self):
        """SQ 2-row 6HB: full routing → all 6 helices connected.
        3 left-side crossovers + 1 right-side crossover = 4 total.
        """
        cells = [(0, 0), (0, 1), (0, 2), (1, 0), (1, 1), (1, 2)]
        d = make_bundle_design(cells, length_bp=200, lattice_type="SQUARE")
        design_state.set_design(d)
        body = client.post("/api/design/auto-scaffold-seamless", json={}).json()
        assert body.get("detail") is None, body.get("detail")
        crossovers = body["design"].get("crossovers", [])
        assert len(crossovers) == 4, f"expected 4 crossovers, got {len(crossovers)}"
        scaf = _scaffold_strands_in(body)
        all_helix_ids = {h["id"] for h in body["design"]["helices"]}
        strand_helix_ids = {d["helix_id"] for s in scaf for d in s["domains"]}
        assert strand_helix_ids == all_helix_ids, \
            f"uncovered helices: {all_helix_ids - strand_helix_ids}"

    def test_2hb_right_side_extended(self):
        """2-helix design: full routing produces one scaffold strand spanning both
        helices, with domain endpoints extended beyond bp_start / bp_end on both sides."""
        _load_2hb(length_bp=200)
        body = client.post("/api/design/auto-scaffold-seamless", json={}).json()
        assert body.get("detail") is None, body.get("detail")
        scaf = _scaffold_strands_in(body)
        # Exactly one scaffold strand after left + right crossovers
        assert len(scaf) == 1, f"expected 1 scaffold strand, got {len(scaf)}"
        s = scaf[0]
        # Spans both helices
        assert len(s["domains"]) == 2, f"expected 2 domains, got {len(s['domains'])}"
        # Each domain extends beyond the helix boundary on both sides (negative and > bp_end)
        helix_map = {h["id"]: h for h in body["design"]["helices"]}
        for dom in s["domains"]:
            h = helix_map[dom["helix_id"]]
            lo = min(dom["start_bp"], dom["end_bp"])
            hi = max(dom["start_bp"], dom["end_bp"])
            assert lo < h["bp_start"], \
                f"left side not extended: domain lo={lo}, bp_start={h['bp_start']}"
            assert hi >= h["bp_start"] + h["length_bp"], \
                f"right side not extended: domain hi={hi}, helix end={h['bp_start'] + h['length_bp']}"

    def test_hc_strip_4hb_single_scaffold_strand(self):
        """HC 4-helix strip: full routing merges all 4 helices into ONE scaffold strand."""
        cells = [(0, 0), (0, 1), (0, 2), (0, 3)]
        d = make_bundle_design(cells, length_bp=200)
        design_state.set_design(d)
        body = client.post("/api/design/auto-scaffold-seamless", json={}).json()
        assert body.get("detail") is None, body.get("detail")
        scaf = _scaffold_strands_in(body)
        # All 4 helices merged into a single scaffold strand after both passes
        assert len(scaf) == 1, f"expected 1 scaffold strand, got {len(scaf)}"
        assert len(scaf[0]["domains"]) == 4, \
            f"expected 4 domains, got {len(scaf[0]['domains'])}"
        # 2 left-side crossovers + 1 right-side cross-strand crossover = 3 total.
        # The two terminal right-side extensions do NOT create crossovers.
        crossovers = body["design"].get("crossovers", [])
        assert len(crossovers) == 3, f"expected 3 crossovers, got {len(crossovers)}"


# ── Feature 2: POST /design/assign-scaffold-sequence (custom + strand_id) ─────


class TestAssignScaffoldSequenceAPI:

    # Custom sequence ────────────────────────────────────────────────────────

    def test_custom_sequence_200(self):
        r = client.post(
            "/api/design/assign-scaffold-sequence",
            json={"custom_sequence": "ATGC" * 500},
        )
        assert r.status_code == 200

    def test_custom_sequence_response_fields(self):
        r = client.post(
            "/api/design/assign-scaffold-sequence",
            json={"custom_sequence": "ATGC" * 500},
        )
        body = r.json()
        assert "total_nt" in body
        assert "scaffold_len" in body
        assert "padded_nt" in body
        assert body["total_nt"] >= 1

    def test_custom_sequence_scaffold_len_matches_input(self):
        seq = "ATGCATGC" * 100
        r = client.post(
            "/api/design/assign-scaffold-sequence", json={"custom_sequence": seq}
        )
        assert r.json()["scaffold_len"] == len(seq)

    def test_custom_sequence_lowercase_accepted(self):
        r = client.post(
            "/api/design/assign-scaffold-sequence",
            json={"custom_sequence": "atgcatgc" * 100},
        )
        assert r.status_code == 200

    def test_custom_sequence_invalid_chars_422(self):
        r = client.post(
            "/api/design/assign-scaffold-sequence",
            json={"custom_sequence": "ATGZATGC"},
        )
        assert r.status_code == 422

    def test_custom_sequence_stored_on_scaffold_strand(self):
        r = client.post(
            "/api/design/assign-scaffold-sequence",
            json={"custom_sequence": "GGGG" * 500},
        )
        sc = _scaffold_strands_in(r.json())[0]
        assert sc["sequence"] is not None
        assert "G" in sc["sequence"]

    # strand_id targeting ────────────────────────────────────────────────────

    def test_strand_id_assigns_only_to_named_strand(self):
        design = _load_partitioned_12hb()
        scaffolds = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
        target_id = scaffolds[0].id
        other_id  = scaffolds[1].id

        r = client.post(
            "/api/design/assign-scaffold-sequence",
            json={"scaffold_name": "M13mp18", "strand_id": target_id},
        )
        assert r.status_code == 200
        updated = design_state.get_or_404()
        target_sc = next(s for s in updated.strands if s.id == target_id)
        other_sc  = next(s for s in updated.strands if s.id == other_id)
        assert target_sc.sequence is not None
        assert other_sc.sequence is None  # must remain untouched

    def test_strand_id_staple_returns_422(self):
        design = design_state.get_or_404()
        staple_id = next(
            s.id for s in design.strands if s.strand_type == StrandType.STAPLE
        )
        r = client.post(
            "/api/design/assign-scaffold-sequence",
            json={"scaffold_name": "M13mp18", "strand_id": staple_id},
        )
        assert r.status_code == 422

    def test_custom_sequence_with_strand_id_leaves_other_strand_untouched(self):
        design = _load_partitioned_12hb()
        scaffolds = [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]
        target_id = scaffolds[0].id
        other_id  = scaffolds[1].id

        r = client.post(
            "/api/design/assign-scaffold-sequence",
            json={"custom_sequence": "CCCC" * 500, "strand_id": target_id},
        )
        assert r.status_code == 200
        updated = design_state.get_or_404()
        other_sc = next(s for s in updated.strands if s.id == other_id)
        assert other_sc.sequence is None


# ── Feature 3a: POST /design/partition-scaffold ───────────────────────────────


class TestPartitionScaffoldAPI:

    def test_200_two_groups_produce_two_scaffolds(self):
        design = _load_12hb()
        grp1 = [h.id for h in design.helices[:6]]
        grp2 = [h.id for h in design.helices[6:12]]
        r = client.post(
            "/api/design/partition-scaffold",
            json={"helix_groups": [grp1, grp2]},
        )
        assert r.status_code == 200
        assert len(_scaffold_strands_in(r.json())) == 2

    def test_response_contains_design_and_validation(self):
        design = _load_12hb()
        grp1 = [h.id for h in design.helices[:6]]
        grp2 = [h.id for h in design.helices[6:12]]
        body = client.post(
            "/api/design/partition-scaffold",
            json={"helix_groups": [grp1, grp2]},
        ).json()
        assert "design" in body
        assert "validation" in body

    def test_scaffold_strands_cover_disjoint_helices(self):
        design = _load_12hb()
        grp1 = [h.id for h in design.helices[:6]]
        grp2 = [h.id for h in design.helices[6:12]]
        body = client.post(
            "/api/design/partition-scaffold",
            json={"helix_groups": [grp1, grp2]},
        ).json()
        scaffolds = _scaffold_strands_in(body)
        helix_sets = [
            frozenset(d["helix_id"] for d in sc["domains"]) for sc in scaffolds
        ]
        assert not (helix_sets[0] & helix_sets[1]), "Scaffold strands share helices"

    def test_422_overlapping_groups(self):
        design = _load_12hb()
        grp1 = [h.id for h in design.helices[:4]]
        grp2 = [h.id for h in design.helices[2:6]]  # overlaps grp1
        r = client.post(
            "/api/design/partition-scaffold",
            json={"helix_groups": [grp1, grp2]},
        )
        assert r.status_code == 422

    def test_422_unknown_helix_id(self):
        _load_12hb()
        r = client.post(
            "/api/design/partition-scaffold",
            json={"helix_groups": [["no_such_helix_id"]]},
        )
        assert r.status_code == 422

    def test_missing_helix_groups_field_422(self):
        _load_12hb()
        r = client.post("/api/design/partition-scaffold", json={})
        assert r.status_code == 422

    def test_design_state_updated(self):
        design = _load_12hb()
        grp1 = [h.id for h in design.helices[:6]]
        grp2 = [h.id for h in design.helices[6:12]]
        client.post(
            "/api/design/partition-scaffold",
            json={"helix_groups": [grp1, grp2]},
        )
        updated = design_state.get_or_404()
        scaffolds = [s for s in updated.strands if s.strand_type == StrandType.SCAFFOLD]
        assert len(scaffolds) == 2


# ── Feature 3b: POST /design/scaffold-split ───────────────────────────────────


def _pick_split_bp(scaffold_strand) -> tuple[str, int]:
    """Return (helix_id, bp_position) at the midpoint of the scaffold's first domain."""
    d = scaffold_strand.domains[0]
    if d.direction.value == "FORWARD":
        bp = d.start_bp + max(1, (d.end_bp - d.start_bp) // 2)
    else:
        bp = d.start_bp - max(1, (d.start_bp - d.end_bp) // 2)
    return d.helix_id, bp


class TestScaffoldSplitAPI:

    def test_200_produces_two_scaffold_strands(self):
        design = _load_routed_6hb()
        sc = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
        helix_id, bp = _pick_split_bp(sc)
        r = client.post(
            "/api/design/scaffold-split",
            json={"strand_id": sc.id, "helix_id": helix_id, "bp_position": bp},
        )
        assert r.status_code == 200
        assert len(_scaffold_strands_in(r.json())) == 2

    def test_both_result_strands_are_scaffold_type(self):
        design = _load_routed_6hb()
        sc = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
        helix_id, bp = _pick_split_bp(sc)
        body = client.post(
            "/api/design/scaffold-split",
            json={"strand_id": sc.id, "helix_id": helix_id, "bp_position": bp},
        ).json()
        for s in _scaffold_strands_in(body):
            assert s["strand_type"] == "scaffold"

    def test_422_on_staple_strand(self):
        design = _load_routed_6hb()
        staple = next(s for s in design.strands if s.strand_type == StrandType.STAPLE)
        d = staple.domains[0]
        r = client.post(
            "/api/design/scaffold-split",
            json={"strand_id": staple.id, "helix_id": d.helix_id, "bp_position": d.start_bp},
        )
        assert r.status_code == 422

    def test_422_invalid_bp_position(self):
        design = _load_routed_6hb()
        sc = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
        d = sc.domains[0]
        out_of_range = (d.end_bp + 500) if d.direction.value == "FORWARD" else (d.end_bp - 500)
        r = client.post(
            "/api/design/scaffold-split",
            json={"strand_id": sc.id, "helix_id": d.helix_id, "bp_position": out_of_range},
        )
        assert r.status_code == 422

    def test_422_unknown_strand_id(self):
        _load_routed_6hb()
        r = client.post(
            "/api/design/scaffold-split",
            json={"strand_id": "ghost_strand", "helix_id": "h_XY_0_0", "bp_position": 10},
        )
        assert r.status_code == 422

    def test_design_state_updated(self):
        design = _load_routed_6hb()
        sc = next(s for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
        helix_id, bp = _pick_split_bp(sc)
        client.post(
            "/api/design/scaffold-split",
            json={"strand_id": sc.id, "helix_id": helix_id, "bp_position": bp},
        )
        updated = design_state.get_or_404()
        scaffolds = [s for s in updated.strands if s.strand_type == StrandType.SCAFFOLD]
        assert len(scaffolds) == 2
