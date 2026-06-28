"""Tests for the hinge weave realizer (backend/core/hinge_weave_router.py).

The realizer turns the abstract single-strand hinge weave into a concrete bp-level
``Design`` by driving the proven seamed-router placement primitives.  It is
self-gated: returns ``None`` unless the result is exactly one scaffold strand,
invariant-clean, validated, with every forced ligation preserved.

The hinge primitive .nadoc fixtures are hand-built under ``workspace/`` (not in the
repo), so each test skips when its fixture is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.core.hinge_weave_router import (
    _analyze_leaves, realize_hinge_weave, realize_hinge_weave_seamless,
)
from backend.core.models import (
    Design, Direction, Domain, ForcedLigation, LatticeType, Strand, StrandType,
)
from backend.core.scaffold_invariants import scaffold_routing_invariants
from backend.core.seamed_router import _is_forward
from backend.core.validator import validate_design

_PRIMITIVES = Path("workspace/Primitives")
_ROUTED = Path("workspace/Scaffold routing")
_HINGES = {
    "2x2": _PRIMITIVES / "2x2_single_hinge_link.nadoc",
    "2x4": _PRIMITIVES / "2x4_double_hinge_link.nadoc",
    "2x6": _PRIMITIVES / "2x6_triple_hinge_link.nadoc",
}


def _load(p: Path) -> Design:
    return Design.model_validate(json.loads(p.read_text()))


def _scaf(design: Design):
    return [s for s in design.strands if s.is_scaffold and not s.is_reference]


def _params():
    return [
        pytest.param(p, id=name, marks=pytest.mark.skipif(
            not p.exists(), reason=f"fixture missing: {p}"))
        for name, p in _HINGES.items()
    ]


def _skip_if_not_primitive(design: Design):
    """A primitive has per-helix scaffold SEEDS and no crossovers; if the workspace
    file was overwritten by a routed design (e.g. saved from the app), skip rather
    than fail on a corrupted fixture."""
    if design.crossovers or len(_scaf(design)) <= 1:
        pytest.skip("fixture is a routed design, not a primitive (workspace file mutated)")


@pytest.mark.parametrize("path", _params())
def test_realizes_single_gate_clean_strand(path: Path):
    design = _load(path)
    _skip_if_not_primitive(design)
    orig_fls = {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in design.forced_ligations
    }
    routed = realize_hinge_weave(design.model_copy(deep=True))
    assert routed is not None
    out, result = routed
    # exactly one scaffold strand covering every helix
    (strand,) = _scaf(out)
    assert {dm.helix_id for dm in strand.domains} == {h.id for h in out.helices}
    # real seams, gate clean, structurally valid
    assert result.seam_xovers > 0
    assert not scaffold_routing_invariants(out, require_seams=True)
    assert validate_design(out).passed
    # forced ligations preserved verbatim
    assert {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in out.forced_ligations
    } == orig_fls


@pytest.mark.skipif(not _HINGES["2x6"].exists(), reason="fixture missing")
def test_declines_non_rung_forced_ligation():
    """An FL between lattice-adjacent helices (a manual anchor, not a gap rung) →
    the realizer declines so the classic preserve pipeline handles it."""
    design = _load(_HINGES["2x6"])
    design.forced_ligations.append(ForcedLigation(
        three_prime_helix_id="h_XY_0_0", three_prime_bp=39,
        three_prime_direction=Direction.FORWARD,
        five_prime_helix_id="h_XY_0_1", five_prime_bp=39,
        five_prime_direction=Direction.REVERSE,
    ))
    assert realize_hinge_weave(design.model_copy(deep=True)) is None


def test_declines_non_hinge_bundle():
    """A plain contiguous bundle (no gap) is not a hinge → analysis returns None."""
    from backend.core.lattice import make_bundle_design
    from backend.core.seamed_router import _scaffold_coverage
    design = make_bundle_design(
        [(0, 0), (0, 1), (1, 0), (1, 1)], length_bp=64,
        lattice_type=LatticeType.SQUARE)
    assert _analyze_leaves(design, set(_scaffold_coverage(design))) is None
    assert realize_hinge_weave(design) is None


# ── k=3+ coverage via the hand-routed reference designs ──────────────────────
# These thicker-leaf hinges (3-helix leaves) have no primitive fixture, so we
# reconstruct a routable input from each reference by stripping its scaffold route
# back to per-helix duplex seeds + 2-domain gap-bridge seeds carrying the FLs, and
# assert the realizer re-routes it to one gate-clean strand.

def _strip_to_primitive(routed: Design) -> Design:
    gp = {h.id: tuple(h.grid_pos) for h in routed.helices}
    id_of = {v: k for k, v in gp.items()}
    ext: dict[str, tuple[int, int]] = {}
    for s in routed.strands:
        if s.strand_type != StrandType.STAPLE or s.is_reference:
            continue
        for dm in s.domains:
            lo, hi = min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp)
            cur = ext.get(dm.helix_id)
            ext[dm.helix_id] = (min(cur[0], lo), max(cur[1], hi)) if cur else (lo, hi)
    rows = sorted({r for r, _ in gp.values()})
    cols = sorted({c for _, c in gp.values()})
    gi = next(i for i in range(len(rows) - 1) if rows[i + 1] - rows[i] > 1)
    rail_a, rail_b = rows[gi], rows[gi + 1]
    fl_by_pair = {
        frozenset([gp[f.three_prime_helix_id], gp[f.five_prime_helix_id]]): f
        for f in routed.forced_ligations
    }
    keep = [s for s in routed.strands
            if s.strand_type != StrandType.SCAFFOLD or s.is_reference]
    seeds, bridged = [], set()

    def _dom(g, end_bp, is_tp):
        hid = id_of[g]
        lo, hi = ext[hid]
        d = Direction.FORWARD if _is_forward(*g) else Direction.REVERSE
        if is_tp:  # end_bp is the 3' end
            s = lo if d == Direction.FORWARD else hi
            return Domain(helix_id=hid, start_bp=s, end_bp=end_bp, direction=d)
        e = hi if d == Direction.FORWARD else lo  # end_bp is the 5' start
        return Domain(helix_id=hid, start_bp=end_bp, end_bp=e, direction=d)

    for c in cols:
        ga, gb = (rail_a, c), (rail_b, c)
        fl = fl_by_pair.get(frozenset([ga, gb]))
        if not fl or id_of[ga] not in ext or id_of[gb] not in ext:
            continue
        seeds.append(Strand(
            id=f"seed_bridge_{c}",
            domains=[_dom(gp[fl.three_prime_helix_id], fl.three_prime_bp, True),
                     _dom(gp[fl.five_prime_helix_id], fl.five_prime_bp, False)],
            strand_type=StrandType.SCAFFOLD))
        bridged |= {ga, gb}
    for hid, g in gp.items():
        if g in bridged or hid not in ext:
            continue
        lo, hi = ext[hid]
        d = Direction.FORWARD if _is_forward(*g) else Direction.REVERSE
        dm = (Domain(helix_id=hid, start_bp=lo, end_bp=hi, direction=d)
              if d == Direction.FORWARD
              else Domain(helix_id=hid, start_bp=hi, end_bp=lo, direction=d))
        seeds.append(Strand(id=f"seed_{g[0]}_{g[1]}", domains=[dm],
                            strand_type=StrandType.SCAFFOLD))
    return routed.model_copy(update={"strands": keep + seeds, "crossovers": []})


@pytest.mark.parametrize("fname,k", [
    ("3x2_hinge_routed.nadoc", 3),
    ("3x4_hinge_routed.nadoc", 3),
])
def test_thick_leaf_hinge_routes(fname, k):
    """3-helix-leaf hinges (k=3) route to one gate-clean validated strand, FLs
    preserved — the realizer generalizes past the 2-row leaf."""
    path = _ROUTED / fname
    if not path.exists():
        pytest.skip(f"reference missing: {path}")
    routed = Design.model_validate(json.loads(path.read_text()))
    inp = _strip_to_primitive(routed)
    orig_fls = {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in inp.forced_ligations
    }
    result = realize_hinge_weave(inp)
    assert result is not None
    out, res = result
    (strand,) = _scaf(out)
    assert {dm.helix_id for dm in strand.domains} == {h.id for h in out.helices}
    assert res.seam_xovers > 0
    assert not scaffold_routing_invariants(out, require_seams=True)
    assert validate_design(out).passed
    assert {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in out.forced_ligations
    } == orig_fls


# ── seamless (single-pass) hinge routing ─────────────────────────────────────

@pytest.mark.parametrize("fname,k,n", [
    ("3x2_hinge_routed.nadoc", 3, 2),
    ("3x4_hinge_routed.nadoc", 3, 4),
])
def test_seamless_routes_thick_leaf(fname, k, n):
    """Reconstructed k=3 hinges route to one SEAMLESS strand (single-pass, no seams),
    gate-clean at require_seams=False, validated, FLs preserved."""
    path = _ROUTED / fname
    if not path.exists():
        pytest.skip(f"reference missing: {path}")
    routed = Design.model_validate(json.loads(path.read_text()))
    inp = _strip_to_primitive(routed)
    orig = {(f.three_prime_helix_id, f.three_prime_bp,
             f.five_prime_helix_id, f.five_prime_bp) for f in inp.forced_ligations}
    result = realize_hinge_weave_seamless(inp)
    assert result is not None
    out, _ = result
    (strand,) = _scaf(out)
    assert {dm.helix_id for dm in strand.domains} == {h.id for h in out.helices}
    # seamless ⇒ NO seams (the require_seams=True gate must REPORT the absence)
    assert scaffold_routing_invariants(out, require_seams=True)
    assert not scaffold_routing_invariants(out, require_seams=False)
    assert validate_design(out).passed
    assert {(f.three_prime_helix_id, f.three_prime_bp,
             f.five_prime_helix_id, f.five_prime_bp)
            for f in out.forced_ligations} == orig


def test_seamless_decodes_user_reference():
    """The hand-routed seamless 3x2 reference re-routes to one seamless strand when
    stripped and fed back through the realizer (the structure it was decoded from)."""
    path = Path("workspace/3x2_hinge_seamless.nadoc")
    if not path.exists():
        pytest.skip(f"reference missing: {path}")
    routed = Design.model_validate(json.loads(path.read_text()))
    inp = _strip_to_primitive(routed)
    result = realize_hinge_weave_seamless(inp)
    assert result is not None
    out, _ = result
    assert len(_scaf(out)) == 1
    assert not scaffold_routing_invariants(out, require_seams=False)
    assert validate_design(out).passed
