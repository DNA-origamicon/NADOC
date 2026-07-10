"""Crossover placement edge cases: a crossover placed close to a strand end.

Two behaviours, both reproduced from ``workspace/crossover_edge_cases.nadoc``:

1. Helices 0/1 — a staple crossover one bp *short* of the strand end must form
   the connection AND leave the single-nucleotide stub past the crossover.
2. Helices 2/3 — a crossover landing *exactly* on an existing crossover junction
   (a multi-domain staple's turn) must be rejected. Free termini / helix-end
   u-turns are NOT junctions and stay allowed (covered by test_crossover_placement).
"""
from __future__ import annotations

import pytest
from fastapi import HTTPException

from backend.api.crud import PlaceCrossoverRequest, _build_place_crossover
from backend.core.models import (
    Design, Direction, Domain, Helix, LatticeType, OverhangSpec, Strand, StrandType, Vec3,
)


def _helix(hid: str, grid) -> Helix:
    return Helix(
        id=hid,
        axis_start=Vec3(x=0.0, y=0.0, z=0.0),
        axis_end=Vec3(x=0.0, y=0.0, z=5.344),
        phase_offset=0.0,
        length_bp=17,
        grid_pos=grid,
    )


def _place(design, ha, hb, index, dir_a, dir_b, nick_a, nick_b):
    body = PlaceCrossoverRequest.model_validate({
        "half_a": {"helix_id": ha, "index": index, "strand": dir_a},
        "half_b": {"helix_id": hb, "index": index, "strand": dir_b},
        "nick_bp_a": nick_a,
        "nick_bp_b": nick_b,
    })
    return _build_place_crossover(design, body)


# ── Helices 0/1: crossover one bp short of the strand end ──────────────────────

def _design_01() -> Design:
    return Design(
        lattice_type=LatticeType.SQUARE,
        helices=[_helix("h0", (0, 1)), _helix("h1", (0, 2))],
        strands=[
            Strand(id="stp0", strand_type=StrandType.STAPLE,
                   domains=[Domain(helix_id="h0", start_bp=0, end_bp=16, direction=Direction.FORWARD)]),
            Strand(id="stp1", strand_type=StrandType.STAPLE,
                   domains=[Domain(helix_id="h1", start_bp=16, end_bp=0, direction=Direction.REVERSE)]),
        ],
    )


def test_near_end_crossover_ligates():
    """Crossover at bp 15 (strands span 0..16) joins the two staples into one
    2-domain strand spanning both helices."""
    design, xover, ligated = _place(_design_01(), "h0", "h1", 15, "FORWARD", "REVERSE", 15, 16)
    assert ligated is True
    spanning = [s for s in design.strands
                if {d.helix_id for d in s.domains} == {"h0", "h1"}]
    assert len(spanning) == 1
    assert [d.helix_id for d in spanning[0].domains] == ["h0", "h1"]


def test_near_end_crossover_makes_single_nt_stubs():
    """The bp past the crossover (bp 16) is left as a 1-nt stub on each helix."""
    design, _x, _lig = _place(_design_01(), "h0", "h1", 15, "FORWARD", "REVERSE", 15, 16)
    stubs = [s for s in design.strands
             if len(s.domains) == 1
             and s.domains[0].start_bp == 16 and s.domains[0].end_bp == 16]
    stub_helices = {s.domains[0].helix_id for s in stubs}
    assert stub_helices == {"h0", "h1"}, f"expected 1-nt stubs on both helices, got {stub_helices}"


def test_near_end_crossover_preserves_nucleotide_count():
    """No nucleotides created or destroyed: 17 + 17 = 34 bp across all strands."""
    design, _x, _lig = _place(_design_01(), "h0", "h1", 15, "FORWARD", "REVERSE", 15, 16)
    total = sum(abs(d.end_bp - d.start_bp) + 1 for s in design.strands for d in s.domains)
    assert total == 34


# ── Helices 2/3: crossover on an existing junction is rejected ─────────────────

def _design_23() -> Design:
    return Design(
        lattice_type=LatticeType.SQUARE,
        helices=[_helix("h2", (0, 3)), _helix("h3", (0, 4))],
        strands=[
            # Two-domain staple that already turns (crosses over) at bp 16.
            Strand(id="stpJ", strand_type=StrandType.STAPLE, domains=[
                Domain(helix_id="h2", start_bp=0, end_bp=16, direction=Direction.FORWARD),
                Domain(helix_id="h3", start_bp=16, end_bp=0, direction=Direction.REVERSE),
            ]),
        ],
    )


def test_crossover_on_existing_junction_rejected():
    with pytest.raises(HTTPException) as exc:
        _place(_design_23(), "h3", "h2", 16, "REVERSE", "FORWARD", 16, 15)
    assert exc.value.status_code == 422
    assert "junction" in exc.value.detail.lower()


# ── Edge of coverage: crossover with nothing on its bow side is rejected ────────

def test_right_edge_crossover_rejected():
    """bp 16 (bow-right → needs bp 17) is the rightmost bp: nothing to connect
    toward on the right, so the crossover must be rejected."""
    with pytest.raises(HTTPException) as exc:
        _place(_design_01(), "h0", "h1", 16, "FORWARD", "REVERSE", 15, 16)
    assert exc.value.status_code == 422
    assert "connect toward" in exc.value.detail.lower()


def _design_01_extended() -> Design:
    """Helices 0/1 with staples extended one bp into the negative region (-1..16)."""
    return Design(
        lattice_type=LatticeType.SQUARE,
        helices=[_helix("h0", (0, 1)), _helix("h1", (0, 2))],
        strands=[
            Strand(id="stp0", strand_type=StrandType.STAPLE,
                   domains=[Domain(helix_id="h0", start_bp=-1, end_bp=16, direction=Direction.FORWARD)]),
            Strand(id="stp1", strand_type=StrandType.STAPLE,
                   domains=[Domain(helix_id="h1", start_bp=16, end_bp=-1, direction=Direction.REVERSE)]),
        ],
    )


def test_left_edge_crossover_rejected():
    """bp -1 (bow-left → needs bp -2) is the leftmost covered bp: nothing to
    connect toward on the left, so the crossover must be rejected."""
    with pytest.raises(HTTPException) as exc:
        _place(_design_01_extended(), "h0", "h1", -1, "FORWARD", "REVERSE", -1, 0)
    assert exc.value.status_code == 422
    assert "connect toward" in exc.value.detail.lower()

# NOTE: that valid near-end crossovers are NOT over-rejected by the edge check is
# covered by test_near_end_crossover_ligates (bp 15, bow-left, needs bp 14 —
# covered) and by test_crossover_placement.test_crossover_at_bp0_family (helix-end
# u-turns at bp 0/20/21/41).


# ── Crossover through an inline-overhang boundary (helix 1↔2 case) ─────────────
# A staple extended past the scaffold gets an inline-overhang tail; a crossover
# whose connection point sits at that same-helix paired/overhang boundary must
# still connect the paired domains AND sever the overhang tail into a standalone
# plain length-1 staple (losing overhang status). Reproduces crossover_edge_cases
# helices 1/2 (the bp-0 crossover).

def _design_overhang_boundary() -> Design:
    return Design(
        lattice_type=LatticeType.SQUARE,
        helices=[_helix("hA", (0, 2)), _helix("hB", (0, 3))],
        strands=[
            # hA REVERSE staple: 5' overhang tail (19->17), paired 16->0, 3' overhang stub (-1)
            Strand(id="sA", strand_type=StrandType.STAPLE, domains=[
                Domain(helix_id="hA", start_bp=19, end_bp=17, direction=Direction.REVERSE, overhang_id="ovhg_inline_sA_5p"),
                Domain(helix_id="hA", start_bp=16, end_bp=0, direction=Direction.REVERSE),
                Domain(helix_id="hA", start_bp=-1, end_bp=-1, direction=Direction.REVERSE, overhang_id="ovhg_inline_sA_3p"),
            ]),
            # hB FORWARD staple: 5' overhang stub (-1), paired 0->16
            Strand(id="sB", strand_type=StrandType.STAPLE, domains=[
                Domain(helix_id="hB", start_bp=-1, end_bp=-1, direction=Direction.FORWARD, overhang_id="ovhg_inline_sB_5p"),
                Domain(helix_id="hB", start_bp=0, end_bp=16, direction=Direction.FORWARD),
            ]),
            Strand(id="scA", strand_type=StrandType.SCAFFOLD, domains=[Domain(helix_id="hA", start_bp=0, end_bp=16, direction=Direction.FORWARD)]),
            Strand(id="scB", strand_type=StrandType.SCAFFOLD, domains=[Domain(helix_id="hB", start_bp=16, end_bp=0, direction=Direction.REVERSE)]),
        ],
        overhangs=[
            OverhangSpec(id="ovhg_inline_sA_5p", helix_id="hA", strand_id="sA"),
            OverhangSpec(id="ovhg_inline_sA_3p", helix_id="hA", strand_id="sA"),
            OverhangSpec(id="ovhg_inline_sB_5p", helix_id="hB", strand_id="sB"),
        ],
    )


def test_crossover_through_overhang_boundary_connects():
    """The crossover connects the paired domains across both helices."""
    design, _x, ligated = _place(_design_overhang_boundary(), "hB", "hA", 0, "FORWARD", "REVERSE", -1, 0)
    assert ligated is True
    spanning = [s for s in design.strands if {d.helix_id for d in s.domains} == {"hA", "hB"}]
    assert len(spanning) == 1, "expected one strand spanning both helices"


def test_crossover_severs_overhang_into_plain_stub():
    """The overhang tail severed by the crossover becomes a standalone length-1
    staple with NO overhang tag, and its OverhangSpec is dropped."""
    design, _x, _lig = _place(_design_overhang_boundary(), "hB", "hA", 0, "FORWARD", "REVERSE", -1, 0)
    # The two -1 stubs are now standalone single-domain strands, untagged.
    stubs = [s for s in design.strands
             if len(s.domains) == 1 and s.domains[0].start_bp == -1 and s.domains[0].end_bp == -1]
    assert len(stubs) == 2
    assert all(s.domains[0].overhang_id is None for s in stubs), "severed stubs must lose overhang tag"
    # Orphaned specs dropped; the legit 5' tail overhang (paired anchor) survives.
    spec_ids = {o.id for o in design.overhangs}
    assert "ovhg_inline_sA_3p" not in spec_ids
    assert "ovhg_inline_sB_5p" not in spec_ids
    assert "ovhg_inline_sA_5p" in spec_ids
