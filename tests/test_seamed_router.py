"""Tests for backend/core/seamed_router.py."""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from backend.core.crossover_positions import crossover_neighbor
from backend.core.models import Design, StrandType
from backend.core.seamed_router import (
    _forced_scaffold_strand_ids,
    auto_scaffold_advanced_seamed,
    auto_scaffold_seamed,
)
from backend.core.seamless_router import auto_scaffold_seamless


def _scaffold_forced_ligation_edges(design: Design) -> dict[str, list[tuple[str, int, int]]]:
    matches: dict[str, list[tuple[str, int, int]]] = {}
    for fl in design.forced_ligations:
        found: list[tuple[str, int, int]] = []
        for strand in design.strands:
            if strand.strand_type != StrandType.SCAFFOLD:
                continue
            for i in range(len(strand.domains) - 1):
                a = strand.domains[i]
                b = strand.domains[i + 1]
                if (
                    a.helix_id == fl.three_prime_helix_id
                    and a.end_bp == fl.three_prime_bp
                    and a.direction == fl.three_prime_direction
                    and b.helix_id == fl.five_prime_helix_id
                    and b.start_bp == fl.five_prime_bp
                    and b.direction == fl.five_prime_direction
                ):
                    found.append((strand.id, i, i + 1))
        matches[fl.id] = found
    return matches


def _endpoint_slots(design: Design) -> dict[tuple, list[tuple[str, str]]]:
    slots: dict[tuple, list[tuple[str, str]]] = defaultdict(list)
    for strand in design.strands:
        for dom in strand.domains:
            slots[(dom.helix_id, dom.start_bp, dom.direction)].append(
                (strand.strand_type.value, strand.id)
            )
            slots[(dom.helix_id, dom.end_bp, dom.direction)].append(
                (strand.strand_type.value, strand.id)
            )
    return slots


def test_seamed_autoscaffold_preserves_hinge_forced_scaffold_anchors():
    fixture = Path(__file__).resolve().parents[1] / "workspace" / "Hinge3.nadoc"
    if not fixture.exists():
        pytest.skip("workspace/Hinge3.nadoc not available")

    design = Design.model_validate_json(fixture.read_text())
    before_edges = _scaffold_forced_ligation_edges(design)
    assert before_edges
    assert all(matches for matches in before_edges.values())

    updated, result = auto_scaffold_seamed(design)

    assert result.seam_xovers + result.near_end_xovers + result.far_end_xovers > 0
    assert any("manual forced ligation" in warning for warning in result.warnings)
    assert _scaffold_forced_ligation_edges(updated) == before_edges


def test_seamed_autoscaffold_does_not_place_hinge_xovers_on_manual_anchor_strands():
    fixture = Path(__file__).resolve().parents[1] / "workspace" / "Hinge3.nadoc"
    if not fixture.exists():
        pytest.skip("workspace/Hinge3.nadoc not available")

    design = Design.model_validate_json(fixture.read_text())
    original_xover_ids = {x.id for x in design.crossovers}

    updated, _ = auto_scaffold_seamed(design)

    protected = _forced_scaffold_strand_ids(updated)
    assert protected

    helix_by_id = {h.id: h for h in updated.helices}
    slots = _endpoint_slots(updated)
    for xover in updated.crossovers:
        if xover.id in original_xover_ids:
            continue

        ha, hb = xover.half_a, xover.half_b
        h_a = helix_by_id[ha.helix_id]
        h_b = helix_by_id[hb.helix_id]
        assert h_a.grid_pos is not None
        assert h_b.grid_pos is not None
        assert crossover_neighbor(
            updated.lattice_type,
            h_a.grid_pos[0],
            h_a.grid_pos[1],
            ha.index,
            is_scaffold=True,
        ) == tuple(h_b.grid_pos)

        endpoint_a = slots[(ha.helix_id, ha.index, ha.strand)]
        endpoint_b = slots[(hb.helix_id, hb.index, hb.strand)]
        scaffold_ids = {
            strand_id
            for kind, strand_id in endpoint_a + endpoint_b
            if kind == StrandType.SCAFFOLD.value
        }
        assert scaffold_ids
        assert scaffold_ids.isdisjoint(protected)


def test_advanced_seamed_warns_when_hinge3_cannot_consolidate_fixed_edges():
    fixture = Path(__file__).resolve().parents[1] / "workspace" / "Hinge3.nadoc"
    if not fixture.exists():
        pytest.skip("workspace/Hinge3.nadoc not available")

    design = Design.model_validate_json(fixture.read_text())
    original_xover_ids = {x.id for x in design.crossovers}

    updated, result = auto_scaffold_advanced_seamed(design)

    scaffolds = [s for s in updated.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffolds) > 1
    assert result.seam_xovers > 0
    assert result.near_end_xovers > 0
    assert result.far_end_xovers > 0
    assert any("routing incomplete" in warning for warning in result.warnings)
    assert all(_scaffold_forced_ligation_edges(updated).values())

    seam_xovers = [
        x for x in updated.crossovers
        if x.process_id == "auto_scaffold_seamed:seam"
    ]
    assert len(seam_xovers) >= 2

    helix_by_id = {h.id: h for h in updated.helices}
    for xover in updated.crossovers:
        if xover.id in original_xover_ids:
            continue
        h_a = helix_by_id[xover.half_a.helix_id]
        h_b = helix_by_id[xover.half_b.helix_id]
        assert h_a.grid_pos is not None
        assert h_b.grid_pos is not None
        assert crossover_neighbor(
            updated.lattice_type,
            h_a.grid_pos[0],
            h_a.grid_pos[1],
            xover.half_a.index,
            is_scaffold=True,
        ) == tuple(h_b.grid_pos)


def test_advanced_seamed_clears_existing_auto_route_before_teeth_reroute():
    fixture = Path(__file__).resolve().parents[1] / "workspace" / "teeth.nadoc"
    if not fixture.exists():
        pytest.skip("workspace/teeth.nadoc not available")

    design = Design.model_validate_json(fixture.read_text())
    assert not design.forced_ligations

    # Pre-route with the seamless router so there is an existing auto-route for
    # the advanced seamed router to clear. Without this step there's nothing
    # to clear and the "Cleared ... auto scaffold crossover(s)" warning never
    # fires — the test would never exercise the clearing path it's named for.
    pre_routed, _ = auto_scaffold_seamless(design)
    pre_process_ids = {x.process_id for x in pre_routed.crossovers}
    assert "auto_scaffold_seamless:bridge" in pre_process_ids

    advanced, advanced_result = auto_scaffold_advanced_seamed(pre_routed)

    advanced_scaffolds = [
        s for s in advanced.strands if s.strand_type == StrandType.SCAFFOLD
    ]
    assert len(advanced_scaffolds) > 1
    assert advanced_result.seam_xovers > 0
    assert advanced_result.near_end_xovers > 0
    assert advanced_result.far_end_xovers > 0
    assert any("Cleared" in warning for warning in advanced_result.warnings)
    assert any("routing incomplete" in warning for warning in advanced_result.warnings)

    process_ids = {x.process_id for x in advanced.crossovers}
    assert "auto_scaffold_seamless:bridge" not in process_ids
    assert "auto_scaffold_seamless:zig" not in process_ids
    assert "auto_scaffold_seamed:seam" in process_ids
    assert "create_near_ends" in process_ids
    assert "create_far_ends" in process_ids
