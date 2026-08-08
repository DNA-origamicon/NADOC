"""Tests for the hinge scaffold router (backend/core/hinge_router.py).

A hinge primitive is two rigid leaves bridged across a gap by forced ligations.
``route_hinge`` routes one SEAMED strand through the bridges by reusing the proven
seamed pipeline, and is **self-gated** against ``scaffold_routing_invariants`` so it
can never return a non-compliant routing (the guarantee the 2026-06-26 regression
lacked).  It falls back (``None``) for anything it cannot route compliantly.

Coverage status: the single-link hinge routes compliantly; multi-link hinges
currently fall back (their multi-bridge seeds don't coalesce in-place yet) — pinned
as an xfail so the goal stays visible.  The self-gate guarantee is asserted on ALL.

The primitive .nadoc files live under ``workspace/`` (hand-built, not in the repo),
so each test skips when its fixture is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.hinge_router import route_hinge
from backend.core.models import Design, Direction, ForcedLigation
from backend.core.scaffold_invariants import scaffold_routing_invariants
from backend.core.seamed_router import (
    _build_adj,
    _scaffold_coverage,
    auto_scaffold_seamed,
)
from backend.core.validator import validate_design

_PRIMITIVES = Path("workspace/Primitives")
_HINGES = {
    "single": _PRIMITIVES / "2x2_single_hinge_link.nadoc",
    "double": _PRIMITIVES / "2x4_double_hinge_link.nadoc",
    "triple": _PRIMITIVES / "2x6_triple_hinge_link.nadoc",
}


def _load(path: Path) -> Design:
    return Design.model_validate(json.loads(path.read_text()))


def _params():
    return [
        pytest.param(
            path,
            id=name,
            marks=pytest.mark.skipif(
                not path.exists(),
                reason=f"hinge primitive fixture missing: {path} (hand-built, not in repo)",
            ),
        )
        for name, path in _HINGES.items()
    ]


def _scaffold_strands(design: Design):
    return [s for s in design.strands if s.is_scaffold and not s.is_reference]


@pytest.mark.parametrize("path", _params())
def test_route_hinge_is_never_non_compliant(path: Path):
    """The self-gate guarantee: route_hinge returns either None (fall back) or a
    single, seamed, invariant-clean scaffold strand — NEVER a regressed routing.
    This is the guardrail the first attempt lacked."""
    routed = route_hinge(_load(path).model_copy(deep=True))
    if routed is None:
        return  # legitimate fall-back
    out, _ = routed
    assert len(_scaffold_strands(out)) == 1
    assert not scaffold_routing_invariants(out, require_seams=True)
    assert validate_design(out).passed


@pytest.mark.skipif(not _HINGES["single"].exists(), reason="fixture missing")
def test_single_link_hinge_routes_compliantly():
    """The single-link hinge routes to ONE seamed strand: full coverage, real seams,
    extended ssDNA ends, every cross-gap bridge re-recorded as a forced ligation."""
    design = _load(_HINGES["single"])
    gap_pairs = _gap_pairs(design)
    routed = route_hinge(design.model_copy(deep=True))
    assert routed is not None, "single-link hinge should route, not fall back"
    out, result = routed

    (strand,) = _scaffold_strands(out)
    assert {dm.helix_id for dm in strand.domains} == set(_scaffold_coverage(design))
    assert result.seam_xovers > 0  # real seams (not a raster)
    assert not scaffold_routing_invariants(out, require_seams=True)
    assert validate_design(out).passed

    # every gap bridge is carried by the strand as a re-derived forced ligation
    out_pairs = {
        (
            min(fl.three_prime_helix_id, fl.five_prime_helix_id),
            max(fl.three_prime_helix_id, fl.five_prime_helix_id),
        )
        for fl in out.forced_ligations
    }
    assert out_pairs == gap_pairs
    three = {(dm.helix_id, dm.end_bp) for dm in strand.domains}
    five = {(dm.helix_id, dm.start_bp) for dm in strand.domains}
    for fl in out.forced_ligations:
        assert (fl.three_prime_helix_id, fl.three_prime_bp) in three
        assert (fl.five_prime_helix_id, fl.five_prime_bp) in five


@pytest.mark.skipif(not _HINGES["single"].exists(), reason="fixture missing")
def test_dispatch_through_auto_scaffold_seamed():
    """The public seamed entry routes the single-link hinge compliantly."""
    out, _ = auto_scaffold_seamed(_load(_HINGES["single"]).model_copy(deep=True))
    assert len(_scaffold_strands(out)) == 1
    assert not scaffold_routing_invariants(out, require_seams=True)


@pytest.mark.parametrize("path", [p for p in _params() if p.id != "single"])
def test_multi_link_hinge_routes(path: Path):
    """Multi-link hinges (2x4/2x6) route to ONE seamed, invariant-clean, validated
    scaffold strand via the from-scratch weave realizer, FLs preserved verbatim."""
    design = _load(path)
    if design.crossovers or len(_scaffold_strands(design)) <= 1:
        pytest.skip(
            "fixture is a routed design, not a primitive (workspace file mutated)"
        )
    orig_fls = {
        (
            f.three_prime_helix_id,
            f.three_prime_bp,
            f.five_prime_helix_id,
            f.five_prime_bp,
        )
        for f in design.forced_ligations
    }
    routed = route_hinge(design.model_copy(deep=True))
    assert routed is not None, "multi-link hinge should route, not fall back"
    out, result = routed
    assert len(_scaffold_strands(out)) == 1
    assert result.seam_xovers > 0
    assert not scaffold_routing_invariants(out, require_seams=True)
    assert validate_design(out).passed
    assert {dm.helix_id for dm in _scaffold_strands(out)[0].domains} == set(
        _scaffold_coverage(design)
    )
    new_fls = {
        (
            f.three_prime_helix_id,
            f.three_prime_bp,
            f.five_prime_helix_id,
            f.five_prime_bp,
        )
        for f in out.forced_ligations
    }
    assert new_fls == orig_fls  # forced ligations preserved verbatim


@pytest.mark.skipif(not _HINGES["triple"].exists(), reason="fixture missing")
def test_intra_leaf_forced_ligation_falls_back():
    """An FL between lattice-adjacent helices is a one-off manual anchor, not a
    gap bridge → route_hinge declines so the classic preserve pipeline runs."""
    design = _load(_HINGES["triple"])
    design.forced_ligations.append(
        ForcedLigation(
            three_prime_helix_id="h_XY_0_0",
            three_prime_bp=39,
            three_prime_direction=Direction.FORWARD,
            five_prime_helix_id="h_XY_0_1",
            five_prime_bp=39,
            five_prime_direction=Direction.REVERSE,
        )
    )
    assert route_hinge(design.model_copy(deep=True)) is None


def test_no_forced_ligations_returns_none():
    from backend.core.lattice import make_bundle_design
    from backend.core.models import LatticeType

    design = make_bundle_design(
        [(0, 0), (0, 1), (1, 0), (1, 1)], length_bp=64, lattice_type=LatticeType.SQUARE
    )
    assert not design.forced_ligations
    assert route_hinge(design) is None


def _gap_pairs(design: Design) -> set:
    cov = _scaffold_coverage(design)
    adj = _build_adj(design, cov)
    return {
        (
            min(fl.three_prime_helix_id, fl.five_prime_helix_id),
            max(fl.three_prime_helix_id, fl.five_prime_helix_id),
        )
        for fl in design.forced_ligations
        if fl.five_prime_helix_id not in adj.get(fl.three_prime_helix_id, set())
    }
