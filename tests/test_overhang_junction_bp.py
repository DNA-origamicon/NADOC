"""Tests for `_overhang_junction_bp` chain-link disambiguation parameter.

The helper is internal to `backend.core.lattice` and reads `design.crossovers`
to find the bp index where an extrude-OH helix joins its parent. Today
production extrude-OHs only ever produce one such crossover, but Phase 2 of
the chain-link rollout will introduce extrude-OH helices with TWO crossovers
(parent-side junction + child-side junction). This file pins the behavior of
the new optional ``exclude_helix_id`` parameter that callers can pass to
disambiguate, plus the unchanged default (``None``) behavior.

These tests construct synthetic Designs by hand-crafting the ``crossovers``
list directly — they do NOT depend on the chain-link OverhangSpec builder
(Phase 2, blocked) or on any other lattice topology builder.
"""

from __future__ import annotations

from backend.core.lattice import _overhang_junction_bp
from backend.core.models import Crossover, Design, Direction, HalfCrossover


def _make_xover(helix_a: str, helix_b: str, index: int) -> Crossover:
    """Build a Crossover between (helix_a, helix_b) at the given bp index."""
    return Crossover(
        half_a=HalfCrossover(helix_id=helix_a, index=index, strand=Direction.FORWARD),
        half_b=HalfCrossover(helix_id=helix_b, index=index, strand=Direction.REVERSE),
    )


# ---------------------------------------------------------------------------
# Single-junction (current production shape)
# ---------------------------------------------------------------------------


def test_single_junction_default_returns_match() -> None:
    """One crossover on the OH helix; default call returns its bp index."""
    design = Design(crossovers=[_make_xover("OH1", "parent", index=12)])

    assert _overhang_junction_bp(design, "OH1") == 12


def test_single_junction_with_non_matching_exclude_returns_match() -> None:
    """``exclude_helix_id`` set to a helix not in this junction → same as default."""
    design = Design(crossovers=[_make_xover("OH1", "parent", index=12)])

    # The single crossover's other half is "parent", not "unrelated", so the
    # filter doesn't fire; helper returns the same bp the default call would.
    assert _overhang_junction_bp(design, "OH1", exclude_helix_id="unrelated") == 12


# ---------------------------------------------------------------------------
# Two-junction synthetic design (chain-link disambiguation)
# ---------------------------------------------------------------------------


def _two_junction_design() -> Design:
    """Hand-crafted Design with two crossovers on OH1: one to parent, one to child_OH2.

    crossovers[0]: OH1 ↔ parent       at bp 5  (parent-side junction)
    crossovers[1]: OH1 ↔ child_OH2    at bp 25 (child-side junction)
    """
    return Design(
        crossovers=[
            _make_xover("OH1", "parent", index=5),
            _make_xover("OH1", "child_OH2", index=25),
        ]
    )


def test_two_junction_exclude_parent_returns_child_side() -> None:
    """Excluding the parent helix yields the child-side (chain-link) junction."""
    design = _two_junction_design()

    assert _overhang_junction_bp(design, "OH1", exclude_helix_id="parent") == 25


def test_two_junction_exclude_child_returns_parent_side() -> None:
    """Excluding the child helix yields the parent-side junction."""
    design = _two_junction_design()

    assert _overhang_junction_bp(design, "OH1", exclude_helix_id="child_OH2") == 5


def test_two_junction_default_returns_first_match_backwards_compat() -> None:
    """Default call (no ``exclude_helix_id``) preserves today's first-match behavior.

    crossovers[0] is the OH1↔parent link at bp 5, so the helper returns 5.
    This pins the backward-compatibility guarantee: existing callers see no
    behavior change.
    """
    design = _two_junction_design()

    assert _overhang_junction_bp(design, "OH1") == 5


# ---------------------------------------------------------------------------
# None case
# ---------------------------------------------------------------------------


def test_helix_not_in_any_crossover_returns_none() -> None:
    """Helix that doesn't appear in any crossover → helper returns ``None``."""
    design = Design(crossovers=[_make_xover("A", "B", index=7)])

    assert _overhang_junction_bp(design, "OH_missing") is None
    # And the default-vs-exclude paths agree on the empty case:
    assert _overhang_junction_bp(design, "OH_missing", exclude_helix_id="B") is None
