"""Regression gate for scaffold routing — the contract EVERY autoscaffold entry
point must satisfy.

This is the guardrail that the 2026-06-26 hinge regression slipped past: a new
return path produced a seamless single-pass raster (no seams, scaffold crossovers
buried in staple domains with zero ssDNA margin), and nothing caught it because
``validate_design`` doesn't encode these properties and the router tests were each
path-specific.  The checker (``backend/core/scaffold_invariants.py``) makes the
properties explicit; the property test below asserts them on the output of EVERY
autoscaffold entry point, so a new path is forced through the same gate.

If you add a new autoscaffold entry point (or a new return path to an existing
one), add it to ``ROUTING_ENTRY_POINTS`` — that is the merge rule.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.lattice import (
    grow_staples,
    make_bundle_design,
    nick_all_major_ticks,
)
from backend.core.models import (
    Crossover,
    Design,
    Direction,
    Domain,
    HalfCrossover,
    LatticeType,
    Strand,
    StrandType,
)
from backend.core.scaffold_invariants import scaffold_routing_invariants
from backend.core.seamed_router import (
    auto_scaffold_matched,
    auto_scaffold_seamed,
)
from backend.core.seamless_router import auto_scaffold_seamless


def _bundle() -> Design:
    cells = [(r, c) for r in range(3) for c in range(6)]  # 18hb SQUARE
    return make_bundle_design(cells, length_bp=128, lattice_type=LatticeType.SQUARE)


# (entry-point callable, require_seams) — EVERY autoscaffold entry point that can
# become the routing returned to the user.  Add new paths here (the merge rule).
ROUTING_ENTRY_POINTS = [
    pytest.param(auto_scaffold_seamed, True, id="seamed"),
    pytest.param(auto_scaffold_matched, True, id="matched"),
    pytest.param(auto_scaffold_seamless, False, id="seamless"),
]


@pytest.mark.parametrize("entry_point, require_seams", ROUTING_ENTRY_POINTS)
def test_entry_point_output_satisfies_routing_invariants(entry_point, require_seams):
    """Every autoscaffold entry point's output passes the routing contract."""
    out, _ = entry_point(_bundle().model_copy(deep=True))
    violations = scaffold_routing_invariants(out, require_seams=require_seams)
    assert not violations, "\n".join(violations)


def test_seamed_with_staples_keeps_ssdna_margin():
    """The ssDNA-margin invariant is meaningfully exercised (staples present): after
    seamed routing + autostaple, every end/turn scaffold crossover stays ≥3 bp clear
    of the staple domains."""
    out, _ = auto_scaffold_seamed(_bundle().model_copy(deep=True))
    stapled = grow_staples(nick_all_major_ticks(out))
    assert any(s.strand_type == StrandType.STAPLE for s in stapled.strands)
    assert not scaffold_routing_invariants(stapled, require_seams=True)


# ── Checker unit tests (deterministic, synthetic) ─────────────────────────────


def _two_helix_scaffold(staple_lo: int, staple_hi: int) -> Design:
    """A minimal 2-helix SQUARE design with one staple domain per helix."""
    d = make_bundle_design(
        [(0, 0), (0, 1)],
        length_bp=64,
        lattice_type=LatticeType.SQUARE,
        strand_filter="scaffold",
    )
    staples = [
        Strand(
            id=f"st_{h.id}",
            domains=[
                Domain(
                    helix_id=h.id,
                    start_bp=staple_lo,
                    end_bp=staple_hi,
                    direction=Direction.FORWARD,
                )
            ],
            strand_type=StrandType.STAPLE,
        )
        for h in d.helices
    ]
    return d.copy_with(strands=list(d.strands) + staples)


def test_checker_flags_missing_seams():
    d = _bundle()
    out, _ = auto_scaffold_seamless(d.model_copy(deep=True))  # legitimately seamless
    # As a SEAMLESS route it is fine; demanded as SEAMED it must be flagged.
    assert not scaffold_routing_invariants(out, require_seams=False)
    flagged = scaffold_routing_invariants(out, require_seams=True)
    assert any("seam" in v for v in flagged)


def test_checker_flags_crossover_buried_in_staple():
    d = _two_helix_scaffold(staple_lo=8, staple_hi=56)
    h0, h1 = d.helices[0], d.helices[1]
    s0 = Direction.FORWARD  # (0,0) parity even
    s1 = Direction.REVERSE  # (0,1) parity odd
    # an end/turn scaffold crossover at bp 30 — squarely INSIDE the staple [8,56]
    buried = Crossover(
        half_a=HalfCrossover(helix_id=h0.id, index=30, strand=s0),
        half_b=HalfCrossover(helix_id=h1.id, index=30, strand=s1),
        process_id="create_near_ends",
    )
    bad = d.copy_with(crossovers=[buried])
    viol = scaffold_routing_invariants(bad, require_seams=False)
    assert any("clearance" in v for v in viol), viol


def test_checker_passes_crossover_in_extended_ssdna():
    d = _two_helix_scaffold(staple_lo=8, staple_hi=56)
    h0, h1 = d.helices[0], d.helices[1]
    # an end/turn crossover at bp 4 — 4 bp clear of the staple lo edge (8): ssDNA
    ok = Crossover(
        half_a=HalfCrossover(helix_id=h0.id, index=4, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id=h1.id, index=4, strand=Direction.REVERSE),
        process_id="create_near_ends",
    )
    good = d.copy_with(crossovers=[ok])
    assert not scaffold_routing_invariants(good, require_seams=False)


# ── Regression pin: the exact failure mode that shipped on 2026-06-26 ─────────

_BAD_OUTPUT = Path("workspace/Hinge_route_test.nadoc")


@pytest.mark.skipif(not _BAD_OUTPUT.exists(), reason="workspace fixture absent")
def test_gate_would_have_caught_the_hinge_regression():
    """The seamless-raster-as-seamed output that regressed (no seams + crossovers
    buried in staples) MUST be rejected by the gate.  This is the test the original
    feature lacked.  (Skips quietly if the workspace file has been restored to the
    seamed gold — the synthetic unit tests above pin the same failure modes.)"""
    design = Design.model_validate(json.loads(_BAD_OUTPUT.read_text()))
    has_hinge_raster = any(
        (xo.process_id or "").endswith(":hinge") for xo in design.crossovers
    )
    if not has_hinge_raster:
        pytest.skip("workspace file is not the regressed raster output")
    assert scaffold_routing_invariants(design, require_seams=True)
