"""Headless hinge-primitive builder — backend/api/headless_hinge_build.py (AF-33 P1).

``build_hinge_primitive`` recreates a standard hinge primitive from scratch by
replaying its construction (bundle-create → duplex shift → gap-bridge resize +
forced ligation) through the shipped ``headless_build`` wrappers.  The pass
criterion is golden-equality: the code-built hinge is byte-for-byte the validated
hand-built ``workspace/Primitives/<name>.nadoc`` — pinned by
``assert_matches_primitive`` (canonical topology + FL endpoint set + round-trip +
validator).

The golden ``.nadoc`` files are hand-built and may be absent in a clean checkout,
so the golden-equality test skips when its fixture is missing.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.api import headless_build as hb
from backend.api import state as design_state
from backend.api.headless_hinge_build import build_hinge, build_hinge_primitive
from backend.core.models import Design
from backend.core.scaffold_invariants import scaffold_routing_invariants
from backend.core.validator import validate_design
from tests.automation_harness import (
    assert_matches_primitive,
    assert_scaffold_routing_compliant,
)

_PRIMITIVES = Path("workspace/Primitives")
_GOLDEN_2X2 = _PRIMITIVES / "2x2_single_hinge_link.nadoc"
_GOLDEN_2X4 = _PRIMITIVES / "2x4_double_hinge_link.nadoc"
_GOLDEN_2X6 = _PRIMITIVES / "2x6_triple_hinge_link.nadoc"


def test_build_2x2_has_the_hinge_shape():
    """The built 2x2 hinge is a well-formed two-leaf bundle with one link (2 FLs).

    Structure-only checks that hold without the golden file present: 8 helices
    (two 2×2 SQUARE leaves), 14 strands (16 from the bundle minus the 2 merged by
    the FL links), exactly 2 forced ligations, and a passing validator.
    """
    d = build_hinge_primitive()
    assert len(d.helices) == 8
    assert len(d.strands) == 14
    assert len(d.forced_ligations) == 2
    # the two leaves: rows {0,1} and {4,5}, cols {0,1}
    assert {h.grid_pos for h in d.helices} == {
        (0, 0), (0, 1), (1, 0), (1, 1), (4, 0), (4, 1), (5, 0), (5, 1)
    }
    assert validate_design(d).passed


def test_build_2x2_carries_a_replayable_feature_log():
    """The build is a real replay (bundle-create + fine-routing ops), not a load.

    A ``from_json`` of the golden would carry the golden's snapshot log; a genuine
    headless build carries a ``bundle-create`` entry from ``create_bundle`` — proof
    the hinge was *constructed* from base ops, the whole point of AF-33.
    """
    d = build_hinge_primitive()
    op_kinds = [getattr(fe, "op_kind", None) for fe in d.feature_log]
    assert any(k == "bundle-create" for k in op_kinds), (
        f"no bundle-create in the built feature log: {op_kinds}"
    )


def test_build_is_isolated_from_active_design():
    """A one-shot build runs in a scratch session and leaves the active doc alone."""
    design_state.set_design(Design())
    before = design_state.get_or_404().model_copy(deep=True)
    build_hinge_primitive()
    after = design_state.get_or_404()
    assert len(after.helices) == len(before.helices) == 0


def test_unknown_primitive_name_raises():
    """An unsupported name fails loudly, not silently (2x2/2x4/2x6 are supported)."""
    with pytest.raises(KeyError, match="unknown hinge primitive"):
        build_hinge_primitive("9x9_nonexistent_hinge")


def test_build_2x4_has_the_hinge_shape():
    """The built 2x4 hinge: two 2×4 SQUARE leaves, two links (4 reciprocal FLs).

    Structure-only checks (no golden needed): 16 helices (rows {0,1,4,5} × cols
    {0..3}), 28 strands (32 from the bundle minus the 4 merged by the FL links),
    exactly 4 forced ligations, passing validator.
    """
    d = build_hinge_primitive("2x4_double_hinge_link")
    assert len(d.helices) == 16
    assert len(d.strands) == 28
    assert len(d.forced_ligations) == 4
    assert {h.grid_pos for h in d.helices} == {
        (r, c) for r in (0, 1, 4, 5) for c in range(4)
    }
    assert validate_design(d).passed


def test_build_2x6_has_the_hinge_shape():
    """The built 2x6 hinge: two 2×6 SQUARE leaves, three links (6 reciprocal FLs)."""
    d = build_hinge_primitive("2x6_triple_hinge_link")
    assert len(d.helices) == 24
    assert len(d.strands) == 42
    assert len(d.forced_ligations) == 6
    assert {h.grid_pos for h in d.helices} == {
        (r, c) for r in (0, 1, 4, 5) for c in range(6)
    }
    assert validate_design(d).passed


def test_build_2x2_autoscaffolds_compliantly():
    """AF-34 end-to-end: a from-scratch 2x2 hinge routes to ONE compliant scaffold.

    ``build_hinge_primitive`` (no golden file needed) → ``hb.auto_scaffold`` (the
    seamed entry dispatches to the hinge router on the design's ``forced_ligations``)
    → the output is a single seamed, invariant-clean scaffold strand that validates.
    This is the first fully-headless build→route→validate win of the hinge chain, and
    pins it against the LESSONS H8 regression (a seamless raster with buried
    crossovers) via the reusable ``assert_scaffold_routing_compliant`` oracle.
    """
    d = build_hinge_primitive("2x2_single_hinge_link")
    design_state.set_design(d)
    out = hb.auto_scaffold()
    scaffolds = assert_scaffold_routing_compliant(out, require_seams=True)
    assert len(scaffolds) == 1
    assert validate_design(out).passed


@pytest.mark.parametrize("k,n", [
    (2, 2), (2, 4), (2, 6),   # 2-row leaves (single / double / triple link)
    (3, 2), (3, 4), (3, 6),   # 3-row leaves
    (4, 4),                   # 4-row leaves
])
def test_build_kxn_hinge_routes_compliantly(k, n):
    """FULL PIPELINE, arbitrary k×N: ``build_hinge(k, n)`` (from scratch, no golden)
    → ``hb.auto_scaffold`` → exactly one seamed, invariant-clean, validated scaffold
    strand covering every helix, with every forced-ligation rung preserved."""
    d = build_hinge(k, n)
    assert len(d.forced_ligations) == n  # one rung per column
    orig_fls = {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in d.forced_ligations
    }
    design_state.set_design(d)
    out = hb.auto_scaffold()
    scaffolds = assert_scaffold_routing_compliant(out, require_seams=True)
    assert len(scaffolds) == 1
    assert validate_design(out).passed
    assert {dm.helix_id for dm in scaffolds[0].domains} == {h.id for h in out.helices}
    assert {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in out.forced_ligations
    } == orig_fls


@pytest.mark.parametrize("k,n", [
    (2, 2), (2, 4), (2, 6),
    (3, 2), (3, 4), (3, 6),
    (4, 4),
])
def test_build_kxn_hinge_routes_seamless(k, n):
    """FULL PIPELINE (seamless), arbitrary k×N: ``build_hinge`` → seamless route →
    one single-pass scaffold strand (no seams), invariant-clean (require_seams=False),
    validated, full coverage, every rung preserved."""
    from backend.core.seamless_router import auto_scaffold_seamless
    d = build_hinge(k, n)
    orig_fls = {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in d.forced_ligations
    }
    out, _ = auto_scaffold_seamless(d.model_copy(deep=True))
    scaf = [s for s in out.strands if s.is_scaffold and not s.is_reference]
    assert len(scaf) == 1
    assert not scaffold_routing_invariants(out, require_seams=False)
    assert validate_design(out).passed
    assert {dm.helix_id for dm in scaf[0].domains} == {h.id for h in out.helices}
    # closed cycle reopened with a BURIED nick: 5'/3' on the same helix, interior
    # (not dangling at a face / on a crossover) — the seamed router's nick quality.
    strand = scaf[0]
    first, last = strand.domains[0], strand.domains[-1]
    assert first.helix_id == last.helix_id
    h = next(hx for hx in out.helices if hx.id == first.helix_id)
    lo, hi = h.bp_start, h.bp_start + h.length_bp - 1
    for bp in (first.start_bp, last.end_bp):
        assert lo + 2 <= bp <= hi - 2  # nick is mid-helix, not at an end/crossover
    assert {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in out.forced_ligations
    } == orig_fls


@pytest.mark.parametrize("k,n", [(1, 4), (2, 3), (3, 0)])
def test_build_hinge_rejects_bad_dimensions(k, n):
    with pytest.raises(ValueError):
        build_hinge(k, n)


# ── Overhang / staple-level FLs must not derail scaffold routing ──────────────
# Regression for workspace/3x6_hinge_bound_end_to_root.nadoc: an in-app "bound end
# to root" overhang binding emits a forced ligation whose endpoint helix carries
# only staples (no scaffold).  Scaffold routing owns only both-endpoints-scaffold
# FLs; a staple-only helix and a staple FL must be ignored by routing (and the FL
# preserved verbatim), not break the hinge realizer into the fragmenting fallback.


def test_scaffold_fls_filter_excludes_staple_only_endpoint_fl():
    """``_scaffold_fls`` keeps the scaffold rungs and drops a staple-level FL whose
    endpoint helix is not scaffold-covered."""
    from backend.core.models import Direction, ForcedLigation
    from backend.core.hinge_weave_router import _scaffold_fls
    from backend.core.seamed_router import _scaffold_coverage

    d = build_hinge(3, 6)
    cov = _scaffold_coverage(d)
    rail = next(h for h in d.helices if h.grid_pos == (2, 0))
    staple_fl = ForcedLigation(
        three_prime_helix_id=rail.id, three_prime_bp=rail.bp_start + 10,
        three_prime_direction=Direction.REVERSE,
        five_prime_helix_id="h_staple_only", five_prime_bp=0,
        five_prime_direction=Direction.FORWARD,
    )
    fls = list(d.forced_ligations) + [staple_fl]
    kept = _scaffold_fls(fls, cov)
    assert staple_fl not in kept                 # staple FL excluded
    assert len(kept) == len(d.forced_ligations)  # all 6 rungs kept


def test_hinge_with_staple_only_helix_still_routes_to_one_strand():
    """A staple-only helix in the gap (the 'root' of a bound-end-to-root binding)
    must not break the hinge realizer's rectangular-leaf analysis.  Before the fix
    the extra helix made ``_analyze_leaves`` decline → classic fallback fragmented
    the scaffold; now it is excluded and the hinge routes to one seamed strand."""
    from backend.core.models import Direction, Domain, Strand, StrandType

    d = build_hinge(3, 6)
    rung_fls = {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in d.forced_ligations
    }
    base = d.helices[0]
    root = base.model_copy(update={"id": "h_root", "grid_pos": (3, 0)})  # gap row
    root_stpl = Strand(
        id="stpl_root",
        domains=[Domain(helix_id="h_root", start_bp=base.bp_start,
                        end_bp=base.bp_start + 3, direction=Direction.FORWARD)],
        strand_type=StrandType.STAPLE,
    )
    d = d.model_copy(update={
        "helices": list(d.helices) + [root],
        "strands": list(d.strands) + [root_stpl],
    })

    design_state.set_design(d)
    out = hb.auto_scaffold()
    scaffolds = assert_scaffold_routing_compliant(out, require_seams=True)
    assert len(scaffolds) == 1
    assert validate_design(out).passed
    # every scaffold helix (not the staple-only root) is in the single strand
    scaf_helix_ids = {h.id for h in out.helices if h.id != "h_root"}
    assert {dm.helix_id for dm in scaffolds[0].domains} == scaf_helix_ids
    assert {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in out.forced_ligations
    } == rung_fls  # rungs preserved


def test_real_bound_end_to_root_design_routes_and_preserves_all_fls():
    """End-to-end on the reported file: a 3x6 hinge with a 'bound end to root'
    overhang binding (2 staple-level FLs + 1 staple-only helix on top of the 6
    scaffold rungs) routes to ONE scaffold strand with ALL 8 forced ligations
    preserved verbatim.  The .nadoc is not git-tracked → skip if absent."""
    import json

    fixture = Path("workspace/3x6_hinge_bound_end_to_root.nadoc")
    if not fixture.exists():
        pytest.skip(f"{fixture} not present in this checkout")
    d = Design.model_validate(json.loads(fixture.read_text()))
    orig_fls = {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in d.forced_ligations
    }
    assert len(orig_fls) == 8

    design_state.set_design(d)
    out = hb.auto_scaffold()
    scaffolds = assert_scaffold_routing_compliant(out, require_seams=True)
    assert len(scaffolds) == 1
    assert validate_design(out).passed
    assert {
        (f.three_prime_helix_id, f.three_prime_bp,
         f.five_prime_helix_id, f.five_prime_bp)
        for f in out.forced_ligations
    } == orig_fls  # both the 6 rungs AND the 2 root-binding FLs preserved


@pytest.mark.skipif(
    not _GOLDEN_2X2.exists(),
    reason=f"hinge primitive golden missing: {_GOLDEN_2X2} (hand-built, not in repo)",
)
def test_build_2x2_matches_golden():
    """The load-bearing pin: the code-built 2x2 hinge == the hand-built golden.

    Equal canonical topology AND forced-ligation endpoint set AND round-trip
    stable AND validator-passing — so a builder that drifted (wrong duplex shift,
    a dropped/mis-wired link, an altered leaf) would fail here.
    """
    d = build_hinge_primitive("2x2_single_hinge_link")
    assert_matches_primitive(d, "2x2_single_hinge_link", primitives_dir=_PRIMITIVES)


@pytest.mark.skipif(
    not _GOLDEN_2X4.exists(),
    reason=f"hinge primitive golden missing: {_GOLDEN_2X4} (hand-built, not in repo)",
)
def test_build_2x4_matches_golden():
    """AF-33 P2 load-bearing pin: the code-built 2x4 == the hand-built golden.

    The 2x4 golden carries ASYMMETRIC hand-authored gap trims (``3p −16`` / ``5p −2``
    by column parity) replayed verbatim from its feature log — so a drifted trim, a
    dropped/mis-wired link, or a wrong leaf would fail on canonical topology and/or
    the forced-ligation endpoint set (``canonical_topology`` is blind to FL records).
    """
    d = build_hinge_primitive("2x4_double_hinge_link")
    assert_matches_primitive(d, "2x4_double_hinge_link", primitives_dir=_PRIMITIVES)


@pytest.mark.skipif(
    not _GOLDEN_2X6.exists(),
    reason=f"hinge primitive golden missing: {_GOLDEN_2X6} (hand-built, not in repo)",
)
def test_build_2x6_matches_golden():
    """AF-33 P2 load-bearing pin: the code-built 2x6 == the golden (3 links, no trims)."""
    d = build_hinge_primitive("2x6_triple_hinge_link")
    assert_matches_primitive(d, "2x6_triple_hinge_link", primitives_dir=_PRIMITIVES)
