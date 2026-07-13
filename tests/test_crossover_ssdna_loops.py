"""Auto-crossover must not treat an INTERIOR ssDNA scaffold loop as a defect.

Scaffold with no staple opposite it is a deliberate single-stranded loop — it
suppresses aggregation from blunt-end stacking — and it occurs in the *interior*
of a helix, not just at the bundle caps (comb / "teeth" cross-sections).

Regression for LESSONS J6: `_place_auto_crossovers` used to decide whether an
unstapled bp was a real 5'/3' terminus or an accidental hole by asking whether it
fell inside the staple slot's global [min, max] span. Interior loops fall inside
that span, so every crossover at a loop boundary was silently starved — while the
identical site at a bundle cap was allowed. See `feedback_staples_are_user_intent`.
"""

from __future__ import annotations

from backend.api.crud import _place_auto_crossovers
from backend.core.lattice import make_bundle_design
from backend.core.models import Design, LatticeType, StrandType

# Square lattice: col-adjacent (0,0)–(0,1) staple crossovers land on the bow pair
# (31, 32).  The loop below is opened at bp 32 so the bp-31 site (bow-left, which
# connects toward bp 30) stays legal while the bp-32 site (bow-right, connecting
# toward bp 33 — inside the loop) must be refused.
LOOP_LO, LOOP_HI = 32, 39
SITE_BOW_LEFT = 31
SITE_BOW_RIGHT = 32


def _teeth_like_design() -> Design:
    """Two square-lattice helices whose staples carry an interior ssDNA loop."""
    d = make_bundle_design(
        cells=[(0, 0), (0, 1)], length_bp=64, lattice_type=LatticeType.SQUARE
    )
    strands = []
    for s in d.strands:
        if s.strand_type != StrandType.STAPLE:
            strands.append(s)  # scaffold spans the loop — that IS the loop
            continue
        # Split the full-length staple into [0, LOOP_LO-1] + [LOOP_HI+1, end],
        # leaving LOOP_LO..LOOP_HI unstapled on both helices.
        dom = s.domains[0]
        lo, hi = min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp)
        fwd = dom.direction.value == "FORWARD"
        for idx, (a, b) in enumerate(((lo, LOOP_LO - 1), (LOOP_HI + 1, hi))):
            start, end = (a, b) if fwd else (b, a)
            strands.append(
                s.model_copy(
                    update={
                        "id": f"{s.id}_frag{idx}",
                        "domains": [dom.model_copy(update={"start_bp": start, "end_bp": end})],
                    }
                )
            )
    return d.model_copy(update={"strands": strands})


def _staple_coverage(d: Design) -> set[tuple[str, str, int]]:
    cov: set[tuple[str, str, int]] = set()
    for s in d.strands:
        if s.strand_type != StrandType.STAPLE:
            continue
        for dom in s.domains:
            lo, hi = min(dom.start_bp, dom.end_bp), max(dom.start_bp, dom.end_bp)
            cov.update((dom.helix_id, dom.direction.value, bp) for bp in range(lo, hi + 1))
    return cov


def test_crossover_placed_at_interior_ssdna_loop_boundary():
    """The staple ends at the loop — that is a terminus, and it may carry a crossover."""
    d = _teeth_like_design()
    out, _ = _place_auto_crossovers(d)
    placed = {x.half_a.index for x in out.crossovers}
    assert SITE_BOW_LEFT in placed, (
        f"bp {SITE_BOW_LEFT} bows toward bp {SITE_BOW_LEFT - 1} (stapled on both helices) "
        "and must be placed; the interior ssDNA loop at its back is the design, not a hole"
    )


def test_crossover_refused_when_its_bow_points_into_the_loop():
    """The complementary bow site connects toward bp 33 — inside the loop. Nothing to join."""
    d = _teeth_like_design()
    out, _ = _place_auto_crossovers(d)
    placed = {x.half_a.index for x in out.crossovers}
    assert SITE_BOW_RIGHT not in placed


def test_auto_crossover_never_staples_over_an_ssdna_loop():
    """Placement may nick and ligate, but must never lay staple where the user left none."""
    d = _teeth_like_design()
    before = _staple_coverage(d)
    out, _ = _place_auto_crossovers(d)
    after = _staple_coverage(out)
    assert after - before == set(), "auto-crossover invented staple coverage"
    assert before - after == set(), "auto-crossover destroyed staple coverage"
    for helix in d.helices:
        for direction in ("FORWARD", "REVERSE"):
            for bp in range(LOOP_LO, LOOP_HI + 1):
                assert (helix.id, direction, bp) not in after
