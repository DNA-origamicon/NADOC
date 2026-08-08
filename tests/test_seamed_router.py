"""Tests for backend/core/seamed_router.py."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import pytest

from backend.core.constants import HC_CROSSOVER_PERIOD
from backend.core.crossover_positions import crossover_neighbor
from backend.core.lattice import make_bundle_design
from backend.core.models import Design, LatticeType, StrandType
from backend.core.seamed_router import (
    _HC_SCAF_BOW_RIGHT,
    _active_scaffolds,
    _forced_scaffold_strand_ids,
    auto_scaffold_matched,
    auto_scaffold_seamed,
)
from backend.core.validator import validate_design
from tests.conftest import EIGHTEEN_HB_CELLS


def _scaffold_forced_ligation_edges(
    design: Design,
) -> dict[str, list[tuple[str, int, int]]]:
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


def test_matched_ends_far_is_left_side_translate_of_near():
    """Matched-ends routing: single scaffold, far face = left-side translate of near.

    Each near-end crossover is mirrored to the far face one repeat period P (a
    whole multiple of the lattice period) away, then stepped to the LEFT side of
    its junction so copy N's far crossover and copy N+1's near crossover form an
    adjacent (bp-1, bp) HJ pair when polymerized.
    """
    # The 18hb honeycomb layout (and 388 bp) is the confirmed repro for the
    # bow-left near-crossover bug: it contains the three vertical (row-differing)
    # bonds whose legal xover sites straddle the near floor.  A plain 3×6 block did
    # NOT reproduce it (its near faces fall elsewhere relative to the bows), so the
    # regression must run on this layout to exercise the fix.
    design = make_bundle_design(
        EIGHTEEN_HB_CELLS, 388, lattice_type=LatticeType.HONEYCOMB
    )

    updated, result = auto_scaffold_matched(design)

    # One clean scaffold strand, design validates.
    assert len(_active_scaffolds(updated)) == 1
    report = validate_design(updated)
    assert report.passed, str(report)

    near: dict[tuple, list[int]] = defaultdict(list)
    far: dict[tuple, list[int]] = defaultdict(list)
    for xo in updated.crossovers:
        key = tuple(sorted([xo.half_a.helix_id, xo.half_b.helix_id]))
        if xo.process_id == "create_near_ends":
            near[key].append(xo.half_a.index)
        elif xo.process_id == "create_far_ends":
            far[key].append(xo.half_a.index)

    assert near and far

    # Every NEAR crossover sits on its BOW-RIGHT site, and every FAR crossover on the
    # LEFT side of its junction.  All three honeycomb bond directions must be
    # bow-consistent on the near face: the vertical (row-differing) bond's legal sites
    # straddle the near floor, so the descending search used to land its near crossover
    # on the bow-LEFT member (one bp off), giving that pair a period one bp longer than
    # the rest and putting its seam crossover on the wrong strand of the junction.
    for bps in near.values():
        for bp in bps:
            assert bp % HC_CROSSOVER_PERIOD in _HC_SCAF_BOW_RIGHT, (
                f"near crossover at bp {bp} (phase {bp % HC_CROSSOVER_PERIOD}) is "
                "bow-left — not all bond directions landed on their bow-right site"
            )
    for bps in far.values():
        for bp in bps:
            assert bp % HC_CROSSOVER_PERIOD not in _HC_SCAF_BOW_RIGHT

    # far = near + P, modulo the one-bp left-side step; P is a whole period multiple.
    deltas = set()
    for key in near:
        if key in far:
            for a, b in zip(sorted(near[key]), sorted(far[key])):
                deltas.add(b - a)
    assert deltas
    # REGRESSION: every pair must share ONE uniform period (the far face is a single
    # clean translate of the near face).  The bow-left near-crossover bug gave the
    # vertical-bond pairs a period of P while the rest were P-1 — a non-uniform seam
    # that broke end-to-end polymer stacking.  A single distinct period is the oracle.
    assert len(deltas) == 1, f"non-uniform matched-ends period: {sorted(deltas)}"
    (period,) = deltas
    # the uniform period is P-1 (one whole crossover period minus the left-side step).
    assert period % HC_CROSSOVER_PERIOD == HC_CROSSOVER_PERIOD - 1


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


def test_circular_scaffold_is_linearized_at_buried_noncrossover_nick():
    """A scaffold whose 5'/3' are joined by a crossover (circular) is reopened into
    one linear strand, nicked at a buried, non-crossover bp near the structure middle."""
    from backend.core.models import (
        Crossover,
        Direction,
        Domain,
        HalfCrossover,
        Strand,
    )
    from backend.core.seamed_router import (
        SeamedResult,
        _linearize_circular_scaffolds,
        _scaffold_end_join_xover,
    )

    base = make_bundle_design(
        [(0, 0), (0, 1)],
        length_bp=60,
        lattice_type=LatticeType.SQUARE,
        strand_filter="scaffold",
    )
    h0, h1 = [h.id for h in base.helices]
    scaf = Strand(
        id="scaf_loop",
        strand_type=StrandType.SCAFFOLD,
        domains=[
            Domain(helix_id=h0, start_bp=0, end_bp=50, direction=Direction.FORWARD),
            Domain(helix_id=h1, start_bp=50, end_bp=0, direction=Direction.REVERSE),
        ],
    )
    xo_turn = Crossover(
        half_a=HalfCrossover(helix_id=h0, index=50, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id=h1, index=50, strand=Direction.REVERSE),
    )
    xo_close = Crossover(
        half_a=HalfCrossover(helix_id=h1, index=0, strand=Direction.REVERSE),
        half_b=HalfCrossover(helix_id=h0, index=0, strand=Direction.FORWARD),
    )
    design = base.copy_with(strands=[scaf], crossovers=[xo_turn, xo_close])

    circ = [s for s in design.strands if s.is_scaffold and not s.is_reference]
    assert (
        _scaffold_end_join_xover(design, circ[0]) is not None
    )  # confirm it starts circular

    result = SeamedResult()
    out = _linearize_circular_scaffolds(design, result)

    out_scaf = [s for s in out.strands if s.is_scaffold and not s.is_reference]
    assert len(out_scaf) == 1  # still a single strand
    assert _scaffold_end_join_xover(out, out_scaf[0]) is None  # no longer circular
    s = out_scaf[0]
    assert s.domains[0].start_bp not in (0, 50)  # nick is interior, not a crossover bp
    assert s.domains[-1].end_bp not in (0, 50)
    assert not result.warnings


# ── Routability guard (seamed_routability_errors) ─────────────────────────────
# The seamed router silently fragments two shape classes into a DISJOINT scaffold
# instead of one strand: (A) an ODD-helix group orphans the last path helix
# (3×3 → 8+1, L → 6+1), and (B) a cross-section whose crossover-adjacency graph
# has NO Hamiltonian path (staircase triangle) skips the whole group so every
# helix stays its own scaffold.  The endpoints call this guard and refuse (422)
# rather than emit the broken scaffold.  Seamless routing pairs helices
# differently and handles both, so the guard is seamed/matched-only.

from backend.core.seamed_router import seamed_routability_errors

SQ = LatticeType.SQUARE


def _sq_bundle(cells):
    return make_bundle_design(cells, length_bp=160, lattice_type=SQ)


def test_guard_passes_even_hamiltonian_bundles():
    """Even-helix, Hamiltonian-traceable cross-sections route cleanly → no errors."""
    solid_2x3 = [(r, c) for r in range(2) for c in range(3)]
    notch = [(r, c) for r in range(4) for c in range(4) if not (r < 2 and c >= 2)]
    for cells in (solid_2x3, notch):
        assert seamed_routability_errors(_sq_bundle(cells)) == []


@pytest.mark.parametrize(
    "cells,n",
    [
        ([(r, c) for r in range(3) for c in range(3)], 9),  # 3×3
        ([(r, 0) for r in range(4)] + [(3, c) for c in range(1, 4)], 7),  # L
    ],
)
def test_guard_flags_odd_helix_group(cells, n):
    """An odd-helix group would orphan the trailing helix — flagged as 'even'."""
    errs = seamed_routability_errors(_sq_bundle(cells))
    assert errs and any("even number of helices" in e for e in errs)
    assert any(str(n) in e for e in errs)


def test_guard_flags_no_hamiltonian_path():
    """The staircase triangle's crossover graph has no single path — flagged."""
    triangle = [(r, c) for r in range(4) for c in range(r + 1)]
    errs = seamed_routability_errors(_sq_bundle(triangle))
    assert errs and any("continuous crossover path" in e for e in errs)


def test_guard_is_out_of_scope_for_forced_ligation_designs():
    """Forced-ligation (hinge) designs route through their own router — not guarded."""
    d = _sq_bundle([(r, c) for r in range(3) for c in range(3)])  # odd, would flag
    from backend.core.models import Direction, ForcedLigation

    d = d.copy_with(
        forced_ligations=[
            ForcedLigation(
                three_prime_helix_id=d.helices[0].id,
                three_prime_bp=10,
                three_prime_direction=Direction.FORWARD,
                five_prime_helix_id=d.helices[1].id,
                five_prime_bp=10,
                five_prime_direction=Direction.REVERSE,
            )
        ]
    )
    assert seamed_routability_errors(d) == []


def test_seamed_endpoint_refuses_odd_helix_design_with_422():
    """End-to-end: the seamed endpoint 422s on an odd-helix design (feeds the toast),
    while seamless still routes it to a single scaffold."""
    from fastapi import HTTPException
    from backend.api import headless_build as hb
    from backend.api import state as ds

    cells = [(r, c) for r in range(3) for c in range(3)]  # 3×3, 9 helices
    with hb.scratch_session(SQ):
        hb.create_bundle(cells, 160, lattice=SQ, name="guard")
        with pytest.raises(HTTPException) as exc:
            hb.auto_scaffold(seamless=False)
        assert exc.value.status_code == 422
        assert "even number of helices" in str(exc.value.detail)
        # the design must be untouched by the refused route (no scaffold fragmentation)
        assert sum(s.is_scaffold for s in ds.get_or_404().strands) == 9
        # seamless handles the odd count → one strand
        hb.auto_scaffold(seamless=True)
        assert sum(s.is_scaffold for s in ds.get_or_404().strands) == 1
