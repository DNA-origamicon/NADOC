"""Tests for backend/core/seamless_router.py"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from backend.core.lattice import make_bundle_design
from backend.core.models import Design, Direction, LatticeType, StrandType
from backend.core.seamless_router import auto_scaffold_seamless
from tests.conftest import make_teeth_design

# ── Cell layouts ──────────────────────────────────────────────────────────────

CELLS_2HB = [(0, 0), (0, 1)]
CELLS_4HB = [(0, 0), (0, 1), (0, 2), (0, 3)]
CELLS_6HB = [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3)]
CELLS_4SQ = [(0, 0), (0, 1), (1, 0), (1, 1)]


def _scaf_strands(design: Design):
    return [s for s in design.strands if s.strand_type == StrandType.SCAFFOLD]


def _make_two_group_design() -> Design:
    """4HB HC where (0,0)/(0,1) have scaffold [0,41] and (0,2)/(0,3) have [0,83].

    Two coverage-signature groups force a bridge HJ between them.
    """
    base = make_bundle_design(CELLS_4HB, length_bp=84)
    arm_ids = {h.id for h in base.helices if h.grid_pos in [(0, 0), (0, 1)]}
    new_strands = []
    for s in base.strands:
        if s.strand_type == StrandType.SCAFFOLD and s.domains[0].helix_id in arm_ids:
            dom = s.domains[0]
            if dom.direction == Direction.FORWARD:
                new_dom = dom.model_copy(update={"end_bp": 41})
            else:
                new_dom = dom.model_copy(update={"start_bp": 41})
            new_strands.append(s.model_copy(update={"domains": [new_dom]}))
        else:
            new_strands.append(s)
    return base.copy_with(strands=new_strands)


# Explicit open-path mode is retained for section windows.
# ── Single-section crossover count tests ──────────────────────────────────────


def test_seamless_2hb_hc():
    design = make_bundle_design(CELLS_2HB, length_bp=42)
    updated, result = auto_scaffold_seamless(design, close_cycle=False)
    assert not result.warnings, result.warnings
    assert result.end_xovers == 1
    assert result.bridge_xovers == 0


def test_seamless_4hb_hc():
    design = make_bundle_design(CELLS_4HB, length_bp=84)
    updated, result = auto_scaffold_seamless(design, close_cycle=False)
    assert not result.warnings, result.warnings
    assert result.end_xovers == 3
    assert result.bridge_xovers == 0


def test_seamless_6hb_hc():
    design = make_bundle_design(CELLS_6HB, length_bp=84)
    updated, result = auto_scaffold_seamless(design, close_cycle=False)
    assert not result.warnings, result.warnings
    assert result.end_xovers == 5
    assert result.bridge_xovers == 0


def test_seamless_4hb_sq():
    design = make_bundle_design(
        CELLS_4SQ, length_bp=32, lattice_type=LatticeType.SQUARE
    )
    updated, result = auto_scaffold_seamless(design, close_cycle=False)
    assert not result.warnings, result.warnings
    assert result.end_xovers == 3
    assert result.bridge_xovers == 0


# ── Structural invariant tests ────────────────────────────────────────────────


def test_scaffold_visits_each_helix_at_most_twice():
    """Each helix should have at most 2 seamless crossovers (in + out).

    Bridge helices may have 4 (in + out for each section's zig-zag) — not
    counted here since the single-section 4HB has no bridges.
    """
    design = make_bundle_design(CELLS_4HB, length_bp=84)
    updated, result = auto_scaffold_seamless(design, close_cycle=False)

    xover_count: dict[str, int] = {}
    for xo in updated.crossovers:
        for hid in (xo.half_a.helix_id, xo.half_b.helix_id):
            xover_count[hid] = xover_count.get(hid, 0) + 1

    for hid, count in xover_count.items():
        assert count <= 2, (
            f"Helix {hid} has {count} crossovers; expected ≤2 in a single-section design."
        )


def test_scaffold_is_linear():
    """No scaffold strand should wrap around (circular) after seamless routing."""
    design = make_bundle_design(CELLS_6HB, length_bp=84)
    updated, _ = auto_scaffold_seamless(design, close_cycle=False)
    for s in _scaf_strands(updated):
        if len(s.domains) > 1:
            first, last = s.domains[0], s.domains[-1]
            assert not (
                first.helix_id == last.helix_id and first.start_bp == last.end_bp
            ), f"Circular scaffold strand detected: {s.id}"


def test_total_crossover_count_2hb():
    """2HB: exactly 1 scaffold crossover total in design."""
    design = make_bundle_design(CELLS_2HB, length_bp=42)
    updated, _ = auto_scaffold_seamless(design, close_cycle=False)
    scaf_xovers = [
        xo for xo in updated.crossovers if xo.process_id and "seamless" in xo.process_id
    ]
    assert len(scaf_xovers) == 1


def test_total_crossover_count_6hb():
    """6HB: exactly 5 scaffold crossovers total in design."""
    design = make_bundle_design(CELLS_6HB, length_bp=84)
    updated, _ = auto_scaffold_seamless(design, close_cycle=False)
    scaf_xovers = [
        xo for xo in updated.crossovers if xo.process_id and "seamless" in xo.process_id
    ]
    assert len(scaf_xovers) == 5


# ── Multi-section test ────────────────────────────────────────────────────────


def test_two_group_design_has_bridge_xovers():
    """2-group design: bridge HJ placed, all helices touched by a crossover."""
    design = _make_two_group_design()
    updated, result = auto_scaffold_seamless(design, close_cycle=False)
    assert result.bridge_xovers > 0, "Expected bridge crossovers for 2-group design"
    assert result.end_xovers > 0, "Expected zig-zag crossovers for 2-group design"

    all_hids = {h.id for h in updated.helices}
    touched = set()
    for xo in updated.crossovers:
        touched.add(xo.half_a.helix_id)
        touched.add(xo.half_b.helix_id)
    assert touched == all_hids, f"These helices had no crossovers: {all_hids - touched}"


def test_teeth_closing_zig():
    """teeth.nadoc (clean, pre-routing fixture): the bridge HJs break circularity,
    which enables a closing-zig end crossover across each pair of tooth tips
    (e.g. h_XY_2_2 ↔ h_XY_2_3).

    On the clean uniform-face fixture the seamless router routes the whole teeth
    cluster to ONE scaffold strand with no fragmentation warning.  (The old fixture
    was already seamless-routed — its ragged, gap-extended faces broke the
    Hamiltonian path and fragmented the re-route into 5 pieces; that fragmentation,
    and the warning, were artifacts of routing an already-routed design.  See the
    double-routing issue in issues_ledger.md.)
    """
    # Built from the same feature-log ops as teeth.nadoc (deterministic h_XY_r_c
    # ids + strands; equivalence pinned by test_teeth_builder_matches_fixture).
    design = make_teeth_design()
    design = design.copy_with(crossovers=[])
    updated, result = auto_scaffold_seamless(design)

    # Clean teeth is one connected cluster and routes to a single strand — no
    # fragmentation warning.
    assert result.warnings == [], result.warnings
    assert result.bridge_xovers == 6, (
        f"Expected 6 bridge xovers, got {result.bridge_xovers}"
    )

    # The closing zig across the tooth tips must be placed.
    closing_zig = [
        xo
        for xo in updated.crossovers
        if {xo.half_a.helix_id, xo.half_b.helix_id} == {"h_XY_2_2", "h_XY_2_3"}
    ]
    assert closing_zig, (
        "Expected a closing-zig crossover across tooth tips h_XY_2_2 ↔ h_XY_2_3"
    )

    # Determinism guard: the tiebroken Hamiltonian path (seamed_router `(len(adj[n]), n)`
    # key) makes the route — and thus the single-strand result and crossover set —
    # identical run-to-run.  Any reintroduced set-iteration nondeterminism fails this
    # across CI hash seeds.
    scaffold = [s for s in updated.strands if s.strand_type == StrandType.SCAFFOLD]
    assert len(scaffold) == 1, (
        f"Expected 1 scaffold strand (deterministic), got {len(scaffold)}"
    )

    def _xover_sig(d):
        return sorted(
            tuple(
                sorted(
                    [
                        (x.half_a.helix_id, x.half_a.index),
                        (x.half_b.helix_id, x.half_b.index),
                    ]
                )
            )
            for x in d.crossovers
        )

    rerun_design = make_teeth_design()
    rerun_design = rerun_design.copy_with(crossovers=[])
    rerun_updated, _ = auto_scaffold_seamless(rerun_design)
    assert _xover_sig(updated) == _xover_sig(rerun_updated), (
        "seamless route is not deterministic"
    )


def _assert_closed_route(seed, routed):
    """Every base is visited once; every inter-helix step uses a crossover;
    the sole nick is adjacent, on one helix, inside the structural duplex.
    """
    from backend.core.scaffold_invariants import scaffold_routing_invariants
    from backend.core.validator import validate_design

    scaffold = _scaf_strands(routed)
    assert len(scaffold) == 1
    strand = scaffold[0]
    first, last = strand.domains[0], strand.domains[-1]
    step = 1 if first.direction == Direction.FORWARD else -1
    assert first.helix_id == last.helix_id
    assert first.direction == last.direction
    assert last.end_bp + step == first.start_bp
    seed_helix = next(h for h in seed.helices if h.id == first.helix_id)
    assert (
        seed_helix.bp_start
        < first.start_bp
        < seed_helix.bp_start + seed_helix.length_bp - 1
    )
    coverage = Counter(
        (dom.helix_id, bp)
        for dom in strand.domains
        for bp in range(
            min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp) + 1
        )
    )
    assert set(coverage.values()) == {1}
    for s in _scaf_strands(seed):
        for dm in s.domains:
            for bp in range(
                min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp) + 1
            ):
                assert coverage[dm.helix_id, bp] == 1
    crossovers = {
        frozenset(
            (
                (xo.half_a.helix_id, xo.half_a.index),
                (xo.half_b.helix_id, xo.half_b.index),
            )
        )
        for xo in routed.crossovers
    }
    for a, b in zip(strand.domains, strand.domains[1:]):
        if a.helix_id != b.helix_id:
            assert (
                frozenset(((a.helix_id, a.end_bp), (b.helix_id, b.start_bp)))
                in crossovers
            )
    assert not scaffold_routing_invariants(routed, require_seams=False)
    assert validate_design(routed).passed
    assert [s for s in seed.strands if not s.is_scaffold] == [
        s for s in routed.strands if not s.is_scaffold
    ]


@pytest.mark.parametrize(
    "cells,lattice",
    [
        ([(r, c) for r in range(6) for c in range(6)], LatticeType.SQUARE),
        ([(r, c) for r in range(3) for c in range(4)], LatticeType.SQUARE),
        (CELLS_6HB, LatticeType.HONEYCOMB),
    ],
)
def test_default_closes_cycle_at_free_face(cells, lattice):
    seed = make_bundle_design(cells, length_bp=40, lattice_type=lattice)
    routed, result = auto_scaffold_seamless(seed)
    assert not result.warnings
    assert result.end_xovers == len(cells)
    assert result.bridge_xovers == 0
    _assert_closed_route(seed, routed)


def test_cube_pore_saved_route_closes_and_is_idempotent():
    from backend.core.scaffold_reset import reset_scaffold_to_structure
    from tests.test_scaffold_idempotence import _topology

    path = Path(__file__).resolve().parents[1] / "workspace/cube_pore.nadoc"
    if not path.exists():
        pytest.skip(
            "local cube_pore design unavailable; synthetic 6x6 covered separately"
        )
    saved = Design.model_validate_json(path.read_text())
    seed, _ = reset_scaffold_to_structure(saved)
    routed, result = auto_scaffold_seamless(saved)
    _assert_closed_route(seed, routed)
    assert result.end_xovers == 36
    assert not any("[Seamless]" in w for w in result.warnings)
    again, _ = auto_scaffold_seamless(routed)
    assert _topology(again) == _topology(routed)


@pytest.mark.parametrize(
    "cells",
    [
        [(r, c) for r in range(3) for c in range(3)],  # unequal bipartite counts
        [(0, c) for c in range(6)],  # degree-one ends
    ],
)
def test_uncloseable_single_strand_warns(cells):
    seed = make_bundle_design(cells, length_bp=40, lattice_type=LatticeType.SQUARE)
    routed, result = auto_scaffold_seamless(seed)
    assert len(_scaf_strands(routed)) == 1
    assert any(
        "No closed route" in w and "separated termini" in w for w in result.warnings
    )
    # Internal windows still intentionally request an open route without warnings.
    _, open_result = auto_scaffold_seamless(seed, close_cycle=False)
    assert not open_result.warnings


def test_cycle_search_backtracks_past_complete_open_path():
    from backend.core.seamed_router import _ham_path_search
    from backend.core.seamless_router import _closeable_path

    ids = [f"{r}{c}" for r in range(3) for c in range(4)]
    adj = {
        n: {
            m
            for m in ids
            if abs(int(n[0]) - int(m[0])) + abs(int(n[1]) - int(m[1])) == 1
        }
        for n in ids
    }
    key = lambda n: (len(adj[n]), n)
    open_path = _ham_path_search(ids, adj, key, [min(ids, key=key)])
    assert open_path[0] not in adj[open_path[-1]]
    cycle = _closeable_path(ids, adj)
    assert len(cycle) == len(ids) and set(cycle) == set(ids)
    assert all(b in adj[a] for a, b in zip(cycle, cycle[1:] + cycle[:1]))


def test_cycle_search_exhaustion_warns_without_claiming_impossibility(monkeypatch):
    import backend.core.seamless_router as router

    monkeypatch.setattr(router, "_HAM_PATH_BUDGET", 1)
    seed = make_bundle_design(
        [(r, c) for r in range(3) for c in range(4)],
        length_bp=40,
        lattice_type=LatticeType.SQUARE,
    )
    routed, result = router.auto_scaffold_seamless(seed)
    assert len(_scaf_strands(routed)) == 1
    assert any(
        "No closed route" in w and "could not find or realize" in w
        for w in result.warnings
    )
