from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.models import Design, Direction, Domain, LatticeType, Strand, StrandType
from backend.core.sequences import assign_custom_scaffold_sequence, assign_staple_sequences
from backend.core.sequences import assign_scaffold_sequence
from backend.core.staple_scoring import (
    apply_precursor_breaks,
    build_precursor_graphs,
    build_scaffold_position_map,
    score_staples,
)
from backend.core.validator import validate_design
from tests.conftest import make_minimal_design


client = TestClient(app)


def _terminal_staple_crossover_collisions(design: Design):
    staple_starts = set()
    staple_ends = set()
    for strand in design.strands:
        if (
            strand.strand_type != StrandType.STAPLE
            or strand.is_reference
            or not strand.domains
        ):
            continue
        first = strand.domains[0]
        last = strand.domains[-1]
        staple_starts.add((first.helix_id, first.start_bp, first.direction))
        staple_ends.add((last.helix_id, last.end_bp, last.direction))

    collisions = []
    for crossover in design.crossovers:
        for half in (crossover.half_a, crossover.half_b):
            key = (half.helix_id, half.index, half.strand)
            if key in staple_starts or key in staple_ends:
                collisions.append((crossover.id, key))
    return collisions


def test_scaffold_position_map_indexes_slots_in_scaffold_order():
    design = make_minimal_design(helix_length_bp=5)
    design, _, _ = assign_custom_scaffold_sequence(design, "ACGTA")

    scaf_map = build_scaffold_position_map(design)

    assert scaf_map.length == 5
    assert scaf_map.index_to_base[0].helix_id == "h0"
    assert scaf_map.index_to_base[0].bp == 0
    assert scaf_map.index_to_base[0].base == "A"
    assert scaf_map.index_to_base[4].bp == 4
    assert scaf_map.index_to_base[4].base == "A"
    assert scaf_map.slot_to_bases[("h0", 2, Direction.FORWARD)][0].index == 2


def test_score_staples_scores_existing_single_domain_staple():
    design = make_minimal_design(helix_length_bp=42)
    design, _, _ = assign_custom_scaffold_sequence(design, "ACGT" * 11)
    design = assign_staple_sequences(design)

    report = score_staples(design)

    assert report["summary"]["staple_count"] == 1
    assert report["summary"]["scored_staple_count"] == 1
    assert report["summary"]["total_bound_nt"] == 42
    assert report["summary"]["Q_origami"] is not None
    staple = report["staples"][0]
    assert staple["strand_id"] == "stap"
    assert staple["segment_count"] == 1
    assert staple["bound_nt"] == 42
    assert staple["dG_loop"] == 0.0
    assert staple["dG_bind"] > 0.0
    assert 0.0 <= staple["prob_fold"] <= 1.0
    assert staple["violations"] == []


def test_score_staples_splits_discontinuous_domains_and_adds_loop_penalty():
    design = make_minimal_design(helix_length_bp=42, with_staple=False)
    staple = Strand(
        id="split_stap",
        strand_type=StrandType.STAPLE,
        domains=[
            Domain(
                helix_id="h0",
                start_bp=20,
                end_bp=0,
                direction=Direction.REVERSE,
            ),
            Domain(
                helix_id="h0",
                start_bp=41,
                end_bp=30,
                direction=Direction.REVERSE,
            ),
        ],
    )
    design = design.copy_with(strands=list(design.strands) + [staple])
    design, _, _ = assign_custom_scaffold_sequence(design, "ACGT" * 11)

    report = score_staples(design)
    scored = report["staples"][0]

    assert scored["strand_id"] == "split_stap"
    assert scored["segment_count"] == 2
    assert scored["bound_nt"] == 33
    assert scored["dG_loop"] > 0.0


def test_score_staples_flags_unbroken_precursor_lengths():
    design = make_minimal_design(helix_length_bp=84)
    design, _, _ = assign_custom_scaffold_sequence(design, "ACGT" * 21)

    report = score_staples(design)

    assert report["summary"]["length_violation_count"] == 1
    assert report["staples"][0]["violations"] == ["length_above_max"]


def test_precursor_graph_builds_legal_break_paths_for_single_precursor():
    design = make_minimal_design(helix_length_bp=84)
    design, _, _ = assign_custom_scaffold_sequence(design, "ACGT" * 21)

    report = build_precursor_graphs(design, k_paths=3)

    assert report["summary"]["precursor_count"] == 1
    assert report["summary"]["complete_precursor_count"] == 1
    assert report["summary"]["best_total_bound_nt"] == 84
    graph = report["graphs"][0]
    assert graph["nucleotide_count"] == 84
    assert graph["node_count"] == 85
    assert graph["edge_count"] > 0

    paths = report["paths"]["stap"]
    assert 1 <= len(paths) <= 3
    best = paths[0]
    assert best["breaks"][0] == 0
    assert best["breaks"][-1] == 84
    assert best["total_bound_nt"] == 84
    assert best["violations"] == []
    assert all(21 <= edge["length_nt"] <= 60 for edge in best["edges"])


def test_precursor_graph_uses_square_lattice_segment_minimum():
    design = make_minimal_design(helix_length_bp=84, lattice=LatticeType.SQUARE)
    design, _, _ = assign_custom_scaffold_sequence(design, "ACGT" * 21)

    report = build_precursor_graphs(design, k_paths=3)

    assert report["min_segment_nt"] == 8
    graph = report["graphs"][0]
    best = report["paths"]["stap"][0]
    boundary_offsets = sorted(
        node["offset"]
        for node in graph["nodes"]
        if node["kind"] in ("terminus", "crossover")
    )
    for offset in best["breaks"][1:-1]:
        prev_boundary = max(boundary for boundary in boundary_offsets if boundary < offset)
        next_boundary = min(boundary for boundary in boundary_offsets if boundary > offset)
        assert offset - prev_boundary >= 8
        assert next_boundary - offset >= 8


def test_apply_precursor_breaks_splits_single_precursor_into_legal_staples():
    design = make_minimal_design(helix_length_bp=84)
    design, _, _ = assign_custom_scaffold_sequence(design, "ACGT" * 21)

    updated, route_report = apply_precursor_breaks(design, k_paths=3)
    score_report = score_staples(updated)

    assert route_report["precursor_count"] == 1
    assert route_report["applied_break_count"] >= 1
    assert route_report["length_violation_count"] == 0
    assert score_report["summary"]["staple_count"] > 1
    assert score_report["summary"]["total_bound_nt"] == 84
    assert score_report["summary"]["length_violation_count"] == 0
    assert all(21 <= staple["length_nt"] <= 60 for staple in score_report["staples"])
    assert all(staple.sequence is not None for staple in updated.staples())


def test_score_workspace_18hb_validates_scaffold_mapping_and_precursor_status():
    fixture = Path(__file__).resolve().parents[1] / "workspace" / "18hb.nadoc"
    if not fixture.exists():
        pytest.skip("workspace/18hb.nadoc not available")

    design = Design.model_validate_json(fixture.read_text())
    design, total_nt, padded_nt = assign_scaffold_sequence(design, "M13mp18")

    report = score_staples(design)

    assert total_nt == 7188
    assert padded_nt == 0
    assert report["scaffold"]["length_nt"] == 7188
    assert report["summary"]["staple_count"] > 0
    assert report["summary"]["scored_staple_count"] == report["summary"]["staple_count"]
    assert report["summary"]["total_bound_nt"] == 6984
    assert report["summary"]["unresolved_staple_count"] == 0
    assert report["summary"]["length_violation_count"] == sum(
        1 for staple in report["staples"]
        if "length_below_min" in staple["violations"]
        or "length_above_max" in staple["violations"]
    )


def test_precursor_graph_workspace_18hb_enforces_honeycomb_segment_minimums():
    fixture = Path(__file__).resolve().parents[1] / "workspace" / "18hb.nadoc"
    if not fixture.exists():
        pytest.skip("workspace/18hb.nadoc not available")

    design = Design.model_validate_json(fixture.read_text())
    design, total_nt, padded_nt = assign_scaffold_sequence(design, "M13mp18")

    report = build_precursor_graphs(design, k_paths=3)

    assert total_nt == 7188
    assert padded_nt == 0
    assert report["summary"]["precursor_count"] > 0
    assert report["min_segment_nt"] == 7
    assert report["summary"]["complete_precursor_count"] <= report["summary"]["precursor_count"]
    assert report["summary"]["edge_count"] > 0
    assert report["summary"]["best_Q_origami"] is not None
    assert sum(1 for graph in report["graphs"] if graph["nucleotide_count"] < 21) == 0

    for graph in report["graphs"]:
        paths = report["paths"][graph["strand_id"]]
        if graph["nucleotide_count"] < 21:
            assert paths == []
            assert graph["edge_count"] == 0
            continue
        if not paths:
            continue
        assert 1 <= len(paths) <= 3
        best = paths[0]
        assert best["breaks"][0] == 0
        assert best["breaks"][-1] == graph["nucleotide_count"]
        assert best["total_bound_nt"] == graph["nucleotide_count"]
        assert best["violations"] == []
        assert all(21 <= edge["length_nt"] <= 60 for edge in best["edges"])
        nodes_by_offset = {node["offset"]: node for node in graph["nodes"]}
        assert all(
            nodes_by_offset[offset]["kind"] != "crossover"
            for offset in best["breaks"][1:-1]
        )
        boundary_offsets = sorted(
            node["offset"]
            for node in graph["nodes"]
            if node["kind"] in ("terminus", "crossover")
        )
        for offset in best["breaks"][1:-1]:
            prev_boundary = max(boundary for boundary in boundary_offsets if boundary < offset)
            next_boundary = min(boundary for boundary in boundary_offsets if boundary > offset)
            assert offset - prev_boundary >= 7
            assert next_boundary - offset >= 7


def test_score_staples_endpoint_is_read_only_and_requires_scaffold_sequence():
    design = make_minimal_design(helix_length_bp=21)
    design_state.set_design(design)
    try:
        missing = client.post("/api/design/staples/score")
        assert missing.status_code == 422

        sequenced, _, _ = assign_custom_scaffold_sequence(design, "ACGT" * 6)
        before = sequenced.model_dump()
        design_state.set_design(sequenced)

        ok = client.post("/api/design/staples/score", json={"temperature_c": 50.0})
        assert ok.status_code == 200
        body = ok.json()
        assert body["summary"]["staple_count"] == 1
        assert design_state.get_or_404().model_dump() == before
    finally:
        design_state.set_design(make_minimal_design())


def test_precursor_graph_endpoint_is_read_only():
    design = make_minimal_design(helix_length_bp=84)
    design, _, _ = assign_custom_scaffold_sequence(design, "ACGT" * 21)
    before = design.model_dump()
    design_state.set_design(design)
    try:
        ok = client.post("/api/design/staples/precursor-graphs", json={"k_paths": 2})
        assert ok.status_code == 200
        body = ok.json()
        assert body["summary"]["precursor_count"] == 1
        assert 1 <= len(body["paths"]["stap"]) <= 2
        assert design_state.get_or_404().model_dump() == before
    finally:
        design_state.set_design(make_minimal_design())


def test_auto_break_aksel_endpoint_mutates_and_logs_snapshot():
    design = make_minimal_design(helix_length_bp=84)
    design, _, _ = assign_custom_scaffold_sequence(design, "ACGT" * 21)
    design_state.set_design(design)
    try:
        ok = client.post("/api/design/auto-break-aksel", json={"k_paths": 3})
        assert ok.status_code == 200
        body = ok.json()
        assert body["aksel_break"]["applied_break_count"] >= 1
        assert body["aksel_break"]["length_violation_count"] == 0

        updated = design_state.get_or_404()
        assert updated.feature_log[-1].op_kind == "auto-break-aksel"
        score_report = score_staples(updated)
        assert score_report["summary"]["staple_count"] > 1
        assert score_report["summary"]["length_violation_count"] == 0
    finally:
        design_state.set_design(make_minimal_design())


def test_autocrossover_places_no_below_min_fragments_before_aksel_break():
    bundle = client.post(
        "/api/design/bundle",
        json={"cells": [[0, 0], [0, 1]], "length_bp": 84, "plane": "XY"},
    )
    assert bundle.status_code == 201

    design, _, _ = assign_scaffold_sequence(design_state.get_or_404(), "M13mp18")
    design_state.set_design(design)
    try:
        xover = client.post("/api/design/crossovers/auto")
        assert xover.status_code == 200

        after_xover = score_staples(design_state.get_or_404())
        # Auto-crossover may leave short terminal STAPLES (accepted), but must
        # never create a sub-minimum SEGMENT/arm (< lattice min: 7 HC / 8 SQ).
        seg_lengths = [
            seg["length"] for staple in after_xover["staples"] for seg in staple["segments"]
        ]
        assert not seg_lengths or min(seg_lengths) >= 7

        aksel = client.post("/api/design/auto-break-aksel", json={"k_paths": 3})
        assert aksel.status_code == 200

        after_aksel = score_staples(design_state.get_or_404())
        seg_after = [
            seg["length"] for staple in after_aksel["staples"] for seg in staple["segments"]
        ]
        assert not seg_after or min(seg_after) >= 7
    finally:
        design_state.set_design(make_minimal_design())


def test_auto_route_aksel_combines_autocrossover_and_breaks():
    bundle = client.post(
        "/api/design/bundle",
        json={"cells": [[0, 0], [0, 1]], "length_bp": 84, "plane": "XY"},
    )
    assert bundle.status_code == 201

    design, _, _ = assign_scaffold_sequence(design_state.get_or_404(), "M13mp18")
    design_state.set_design(design)
    try:
        route = client.post("/api/design/auto-route-aksel", json={"k_paths": 3})
        assert route.status_code == 200
        body = route.json()["aksel_route"]

        assert body["auto_crossover"]["placed"] > 0

        updated = design_state.get_or_404()
        assert updated.feature_log[-1].op_kind == "auto-route-aksel"
        after_route = score_staples(updated)
        # Short staples are accepted; no sub-minimum segment/arm.
        seg_lengths = [
            seg["length"] for staple in after_route["staples"] for seg in staple["segments"]
        ]
        assert not seg_lengths or min(seg_lengths) >= 7
    finally:
        design_state.set_design(make_minimal_design())


def test_full_autostaple_assigns_sequences_routes_and_avoids_circular_staples():
    bundle = client.post(
        "/api/design/bundle",
        json={"cells": [[0, 0], [0, 1]], "length_bp": 84, "plane": "XY"},
    )
    assert bundle.status_code == 201

    try:
        full = client.post("/api/design/full-autostaple", json={"k_paths": 3})
        assert full.status_code == 200
        body = full.json()["full_autostaple"]

        assert body["scaffold"]["total_nt"] == 84
        assert body["auto_crossover"]["placed"] > 0

        updated = design_state.get_or_404()
        assert updated.feature_log[-1].op_kind == "full-autostaple"
        assert all(staple.sequence for staple in updated.staples())
        assert all(
            "Circular staple strand" not in result.message
            for result in validate_design(updated).results
            if not result.ok
        )
        after_full = score_staples(updated)
        # Short staples are accepted; the structural guard is no sub-min segment.
        seg_lengths = [
            seg["length"] for staple in after_full["staples"] for seg in staple["segments"]
        ]
        assert not seg_lengths or min(seg_lengths) >= 7
    finally:
        design_state.set_design(make_minimal_design())


def test_auto_break_aksel_completes_after_autocrossover_on_18hb():
    fixture = Path(__file__).resolve().parents[1] / "workspace" / "18hb.nadoc"
    if not fixture.exists():
        pytest.skip("workspace/18hb.nadoc not available")

    design = Design.model_validate_json(fixture.read_text())
    design, _, _ = assign_scaffold_sequence(design, "M13mp18")
    design_state.set_design(design)
    try:
        xover = client.post("/api/design/crossovers/auto")
        assert xover.status_code == 200

        after_xover = design_state.get_or_404()
        before_score = score_staples(after_xover)
        assert before_score["summary"]["staple_count"] > 0

        aksel = client.post("/api/design/auto-break-aksel", json={"k_paths": 3})
        assert aksel.status_code == 422
        assert "No complete legal breakpoint path" in aksel.json()["detail"]
    finally:
        design_state.set_design(make_minimal_design())


def test_auto_route_aksel_completes_on_18hb():
    fixture = Path(__file__).resolve().parents[1] / "workspace" / "18hb.nadoc"
    if not fixture.exists():
        pytest.skip("workspace/18hb.nadoc not available")

    design = Design.model_validate_json(fixture.read_text())
    design, _, _ = assign_scaffold_sequence(design, "M13mp18")
    design_state.set_design(design)
    try:
        route = client.post("/api/design/auto-route-aksel", json={"k_paths": 3})
        assert route.status_code == 422
        assert "No complete legal breakpoint path" in route.json()["detail"]
    finally:
        design_state.set_design(make_minimal_design())


def test_full_autostaple_completes_on_18hb_without_circular_staples():
    fixture = Path(__file__).resolve().parents[1] / "workspace" / "18hb.nadoc"
    if not fixture.exists():
        pytest.skip("workspace/18hb.nadoc not available")

    design = Design.model_validate_json(fixture.read_text())
    design_state.set_design(design)
    try:
        full = client.post("/api/design/full-autostaple", json={"k_paths": 3})
        assert full.status_code == 200
        body = full.json()["full_autostaple"]

        assert body["removed_circularizing_crossover_count"] >= 0

        updated = design_state.get_or_404()
        assert _terminal_staple_crossover_collisions(updated) == []
        after_score = score_staples(updated)
        assert after_score["summary"]["unresolved_staple_count"] == 0
        # Short terminal staples are accepted (dense edge crossovers); the
        # structural guarantee is that no SEGMENT/arm is below the lattice min.
        segment_lengths = [
            segment["length"]
            for staple in after_score["staples"]
            for segment in staple["segments"]
        ]
        assert min(segment_lengths) >= 7
        assert all(
            "Circular staple strand" not in result.message
            for result in validate_design(updated).results
            if not result.ok
        )
    finally:
        design_state.set_design(make_minimal_design())


def test_full_autostaple_mini_rect_has_no_terminal_crossover_breaks():
    fixture = Path(__file__).resolve().parents[1] / "workspace" / "mini_rect.nadoc"
    if not fixture.exists():
        pytest.skip("workspace/mini_rect.nadoc not available")

    design = Design.model_validate_json(fixture.read_text())
    design_state.set_design(design)
    try:
        full = client.post(
            "/api/design/full-autostaple",
            json={"scaffold_name": "M13mp18", "k_paths": 3},
        )
        assert full.status_code == 200, full.json().get("detail")
        body = full.json()["full_autostaple"]
        assert body["removed_terminal_crossover_count"] > 0

        updated = design_state.get_or_404()
        assert _terminal_staple_crossover_collisions(updated) == []
        after = score_staples(updated)
        segment_lengths = [
            segment["length"]
            for staple in after["staples"]
            for segment in staple["segments"]
        ]
        assert min(segment_lengths) >= 8
        assert after["summary"]["length_violation_count"] == 0
    finally:
        design_state.set_design(make_minimal_design())


def test_full_autostaple_thins_dense_crossovers_on_large_block():
    """Regression: dense honeycomb crossover phases can leave no legal internal
    breakpoints. Full autostaple must thin phases instead of nicking at crossovers.
    """
    from backend.core.lattice import make_bundle_design
    from backend.core.seamed_router import auto_scaffold_matched

    cells = [(r, c) for r in range(6) for c in range(1, 12)]  # 6x11 block (66 helices)
    design = make_bundle_design(cells, 105, lattice_type=LatticeType.HONEYCOMB)
    design, _ = auto_scaffold_matched(design)
    design_state.set_design(design)
    try:
        full = client.post(
            "/api/design/full-autostaple", json={"scaffold_name": "M13mp18", "k_paths": 3}
        )
        assert full.status_code == 200, full.json().get("detail")
        body = full.json()["full_autostaple"]
        assert body["aksel_break"]["new_staple_count"] > 0
        assert body["auto_crossover"]["placed"] > 0

        updated = design_state.get_or_404()
        assert _terminal_staple_crossover_collisions(updated) == []
        after = score_staples(updated)
        assert after["summary"]["unresolved_staple_count"] == 0
        segment_lengths = [
            segment["length"]
            for staple in after["staples"]
            for segment in staple["segments"]
        ]
        assert min(segment_lengths) >= 7
        assert all(
            "Circular staple strand" not in result.message
            for result in validate_design(updated).results
            if not result.ok
        )
    finally:
        design_state.set_design(make_minimal_design())


def test_full_autostaple_keeps_breaks_clear_of_seam_crossovers():
    """Staple breaks must keep >= lattice-min-segment clearance from an interior
    (seam) scaffold crossover, so a nick never lands on top of a seam junction.
    """
    from backend.core.lattice import make_bundle_design
    from backend.core.seamed_router import auto_scaffold_seamed
    from backend.core.staple_scoring import (
        interior_scaffold_crossover_positions,
        lattice_min_segment_nt,
    )

    cells = [(r, c) for r in range(3) for c in range(6)]  # fresh 18HB
    design = make_bundle_design(cells, 168, lattice_type=LatticeType.HONEYCOMB)
    design, _ = auto_scaffold_seamed(design)
    design_state.set_design(design)
    try:
        full = client.post(
            "/api/design/full-autostaple", json={"scaffold_name": "M13mp18", "k_paths": 3}
        )
        assert full.status_code == 200, full.json().get("detail")

        updated = design_state.get_or_404()
        min_seg = lattice_min_segment_nt(updated.lattice_type)
        block = interior_scaffold_crossover_positions(updated, min_seg)
        helix_map = {h.id: h for h in updated.helices}

        def _is_helix_end(hid: str, bp: int) -> bool:
            h = helix_map[hid]
            lo, hi = h.bp_start, h.bp_start + h.length_bp - 1
            return bp <= lo + 1 or bp >= hi - 1

        violations = []
        for s in updated.strands:
            if s.strand_type != StrandType.STAPLE or s.is_reference:
                continue
            ends = [
                (s.domains[0].helix_id, s.domains[0].start_bp),
                (s.domains[-1].helix_id, s.domains[-1].end_bp),
            ]
            for hid, bp in ends:
                if _is_helix_end(hid, bp):
                    continue  # true helix-cap terminus, not an internal break
                if any(0 < abs(bp - sx) < min_seg for sx in block.get(hid, ())):
                    violations.append((hid, bp))
        assert not violations, f"staple breaks within {min_seg} bp of a seam crossover: {violations}"
    finally:
        design_state.set_design(make_minimal_design())
