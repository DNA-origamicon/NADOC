"""Regression tests for single-strand routing of irregular *multi-section* designs
(teeth, dumbbells) — ISSUE-8.

The load-bearing invariant here is **inter-tooth gap emptiness**, captured by a
geometry-independent, per-domain check (``intertooth_gap_extension``): a scaffold
domain end that lands in a *gap* (the bp span between two of its helix's nominal
sections — i.e. physically between two teeth) must sit within a small bound of the
nearest section face.  That is the testable form of the user's design rule:

    a scaffold domain end extends only until it reaches the predetermined crossover
    with a *co-existing* neighbour — never out into the empty span between teeth.

The hand-routed reference (``workspace/Scaffold routing/teeth_seamed_route*.nadoc``)
satisfies it (worst inter-tooth extension 10 bp).  These tests pin the reference as
the proof the checker is correct, and require any router we ship to match it.  This
is a "tests pass but visually wrong" area (see project_dumbbell_autoscaffold.md /
LESSONS.md) — the gap check is the missing feedback that earlier diagnostics lacked.
"""
from __future__ import annotations

from collections import defaultdict
from pathlib import Path

import json

import pytest

from backend.core.models import Design, StrandType
from backend.core.seamed_router import _scaffold_coverage, auto_scaffold_seamed
from backend.core.seamless_router import auto_scaffold_seamless
from backend.core.section_router import route_sections
# Promoted to the shared automation harness (AF-1) so the design-automation loop's
# round-trip oracle and this router test share one definition.
from tests.automation_harness import canonical_topology as _canonical_topology

_ROOT = Path(__file__).resolve().parents[1]
_TEETH = _ROOT / "tests" / "fixtures" / "teeth.nadoc"
_DUMBBELL = _ROOT / "tests" / "fixtures" / "10-6-10hb_seamed.nadoc"
_REF1 = _ROOT / "workspace" / "Scaffold routing" / "teeth_seamed_route1.nadoc"
_REF2 = _ROOT / "workspace" / "Scaffold routing" / "teeth_seamed_route2.nadoc"
_SEAMLESS_REF = _ROOT / "workspace" / "Scaffold routing" / "teeth_seamless_route1.nadoc"

# Bound on how far a scaffold domain end may extend into an inter-tooth gap.  The
# hand-routed reference's worst is 10 bp; 12 gives a hair of slack without admitting
# the per-crossover-period (32 bp on SQ) over-extension the buggy routers produced.
_MAX_GAP_EXT = 12

# Minimum contiguous empty span every inter-tooth gap must retain — the metric that
# actually tracks visual gap-openness (see min_per_gap_clearance).  Reference keeps
# ≥18 bp clear; 15 demands a clearly-open gap without byte-matching the reference.
_MIN_GAP_CLEARANCE = 15


def _load(path: Path) -> Design:
    if not path.exists():
        pytest.skip(f"{path} not available")
    return Design(**json.loads(path.read_text()))


def _segmented_helices(base: Design) -> dict[str, list[dict]]:
    """Helices whose scaffold coverage spans more than one section (the teeth)."""
    cov = _scaffold_coverage(base)
    return {h: sorted(ivs, key=lambda iv: iv["lo"]) for h, ivs in cov.items() if len(ivs) > 1}


def intertooth_gap_extension(routed: Design, base: Design) -> tuple[int, list[tuple[str, int, int]]]:
    """Worst inter-tooth gap extension (bp) + the offending (helix, end_bp, dist) list.

    Only counts domain ends that fall *strictly between* two of a segmented helix's
    nominal sections — the physical inter-tooth gaps.  Ends beyond the outermost
    section (the structure's blunt outer ends) are exempt: a bounded blunt-end
    turn-around there is by design.
    """
    seg = _segmented_helices(base)
    scaf = [s for s in routed.strands if s.is_scaffold and not s.is_reference]
    worst = 0
    viol: list[tuple[str, int, int]] = []
    for s in scaf:
        for dm in s.domains:
            ivs = seg.get(dm.helix_id)
            if ivs is None:
                continue
            for end in (dm.start_bp, dm.end_bp):
                if any(iv["lo"] <= end <= iv["hi"] for iv in ivs):
                    continue  # inside a real section
                left = [iv for iv in ivs if iv["hi"] < end]
                right = [iv for iv in ivs if iv["lo"] > end]
                if not (left and right):
                    continue  # outer blunt end — exempt
                dist = min(end - left[-1]["hi"], right[0]["lo"] - end)
                worst = max(worst, dist)
                if dist > _MAX_GAP_EXT:
                    viol.append((dm.helix_id[-4:], end, dist))
    return worst, viol


def min_per_gap_clearance(routed: Design, base: Design) -> int:
    """Smallest contiguous empty bp run left in ANY inter-tooth gap.

    This is the metric that actually tracks the *visual* "is the gap open" question
    (the per-domain extension bound does not — every tooth helix can turn ≤12 bp into
    a gap and still leave it visually full).  The hand-routed reference keeps ≥18 bp
    of every gap clear by threading some helices straight through the trunk instead of
    turning both ends of every window.  Returns a large sentinel if there are no gaps.
    """
    seg = _segmented_helices(base)
    got: dict[str, set[int]] = defaultdict(set)
    for s in _active_scaffold_strands(routed):
        for dm in s.domains:
            for bp in range(min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp) + 1):
                got[dm.helix_id].add(bp)
    worst = 10 ** 9
    for hid, ivs in seg.items():
        for a, b in zip(ivs, ivs[1:]):
            best = cur = 0
            for bp in range(a["hi"] + 1, b["lo"]):
                if bp in got[hid]:
                    cur = 0
                else:
                    cur += 1
                    best = max(best, cur)
            worst = min(worst, best)
    return worst


def max_teeth_extension_past_any_face(routed: Design, base: Design) -> int:
    """Largest bp any SEGMENTED (tooth) domain extends past any of its nominal faces.

    Teeth are internal features — their faces (including the outermost) must stay
    tight.  The CONTINUOUS trunk is deliberately exempt: its farthest faces carry the
    matched-ends periodic extension (far = near + P) for end-to-end polymerization, so
    a ~one-period outer extension there is intended, not a protrusion.
    """
    cov = _scaffold_coverage(base)
    seg = _segmented_helices(base)
    got: dict[str, set[int]] = defaultdict(set)
    for s in _active_scaffold_strands(routed):
        for dm in s.domains:
            for bp in range(min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp) + 1):
                got[dm.helix_id].add(bp)
    worst = 0
    for hid in seg:
        nlo = min(iv["lo"] for iv in cov[hid])
        nhi = max(iv["hi"] for iv in cov[hid])
        if got[hid]:
            worst = max(worst, nlo - min(got[hid]), max(got[hid]) - nhi)
    return worst


def trunk_matched_translate(routed: Design, base: Design) -> int | None:
    """Period P if the trunk's far end is an exact translate of its near end (far =
    near + P), else None.

    The continuous (trunk) helices carry only the structure's two farthest faces, so
    every ``create_near_ends`` / ``create_far_ends`` crossover on a continuous helix is
    a trunk end.  Matched ends require the sorted far positions to equal the sorted near
    positions shifted by one constant P>0 — the puzzle/periodic relationship that lets
    copy N+1's near face slot into copy N's far face.
    """
    cov = _scaffold_coverage(base)
    cont = {h for h, ivs in cov.items() if len(ivs) == 1}
    near, far = set(), set()
    for xo in routed.crossovers:
        if xo.half_a.helix_id not in cont or xo.half_b.helix_id not in cont:
            continue
        if xo.process_id == "create_near_ends":
            near.add(xo.half_a.index)
        elif xo.process_id == "create_far_ends":
            far.add(xo.half_a.index)
    if not near or len(near) != len(far):
        return None
    near_s, far_s = sorted(near), sorted(far)
    p = far_s[0] - near_s[0]
    if p > 0 and all(f - n == p for n, f in zip(near_s, far_s)):
        return p
    return None


def trunk_tooth_connections_off_midpoint(routed: Design, base: Design) -> list[tuple[int, float]]:
    """For each trunk↔tooth connection crossover, how far its bp sits from the nearest
    tooth (section) midpoint, relative to the tooth half-width.

    Returns ``(bp, off_fraction)`` for connections that land OUTSIDE the central half
    of their tooth (off_fraction > 1.0 means closer to a face than the midpoint).
    """
    cov = _scaffold_coverage(base)
    sections = [(iv["lo"], iv["hi"]) for ivs in cov.values() for iv in ivs if len(ivs) > 1]
    out: list[tuple[int, float]] = []
    for xo in routed.crossovers:
        if xo.process_id != "auto_scaffold_seamed:section":
            continue
        bp = xo.half_a.index
        lo, hi = min(sections, key=lambda s: abs((s[0] + s[1]) / 2 - bp))
        mid = (lo + hi) / 2.0
        half = max((hi - lo) / 2.0, 1.0)
        frac = abs(bp - mid) / half
        if frac > 0.5:  # outside the central half of the tooth
            out.append((bp, round(frac, 2)))
    return out


def nick_is_buried(routed: Design, base: Design, margin: int = 15) -> bool:
    """True if the single scaffold's 5'/3' nick sits mid-bundle, not at an outer face."""
    cov = _scaffold_coverage(base)
    nlo = min(iv["lo"] for ivs in cov.values() for iv in ivs)
    nhi = max(iv["hi"] for ivs in cov.values() for iv in ivs)
    scaf = _active_scaffold_strands(routed)
    if len(scaf) != 1:
        return False
    f, l = scaf[0].domains[0], scaf[0].domains[-1]
    return all(nlo + margin < bp < nhi - margin for bp in (f.start_bp, l.end_bp))


def nick_is_proper(routed: Design) -> bool:
    """True if the 5'/3' form a real nick: same helix, adjacent bp (a circular scaffold
    opened at one phosphate), as in the hand-routed reference (_0_0[125]/[126])."""
    scaf = _active_scaffold_strands(routed)
    if len(scaf) != 1:
        return False
    f, l = scaf[0].domains[0], scaf[0].domains[-1]
    return f.helix_id == l.helix_id and abs(f.start_bp - l.end_bp) == 1


def seam_crossover_count(routed: Design) -> int:
    """Number of seamed-style seam crossovers (mid-helix Holliday junctions).  A fully
    seamless route — like the hand reference — has NONE; they only appear when a helix
    is routed by the seamed raster."""
    return sum(1 for x in routed.crossovers if (x.process_id or "") == "auto_scaffold_seamed:seam")


def _active_scaffold_strands(d: Design):
    return [s for s in d.strands if s.is_scaffold and not s.is_reference]


def _full_coverage_missing(routed: Design, base: Design) -> dict[str, int]:
    """bp of each nominal section left uncovered by the routed scaffold (should be empty)."""
    cov = _scaffold_coverage(base)
    got: dict[str, set[int]] = defaultdict(set)
    for s in _active_scaffold_strands(routed):
        for dm in s.domains:
            for bp in range(min(dm.start_bp, dm.end_bp), max(dm.start_bp, dm.end_bp) + 1):
                got[dm.helix_id].add(bp)
    miss: dict[str, int] = {}
    for hid, ivs in cov.items():
        want: set[int] = set()
        for iv in ivs:
            want |= set(range(iv["lo"], iv["hi"] + 1))
        m = want - got[hid]
        if m:
            miss[hid] = len(m)
    return miss


# ── The checker is correct: the hand-routed reference satisfies the invariant ──────

@pytest.mark.parametrize("ref_path", [_REF1, _REF2])
def test_reference_route_keeps_inter_tooth_gaps_open(ref_path):
    """The hand-routed reference is a single strand that keeps the gaps open.

    The reference is an *existence proof*, not the tightest possible route: against
    the clean fixture faces its worst per-domain dip is 13 bp (our section router does
    9), so we only assert it leaves each gap clearly open (clearance), not the stricter
    ≤12 bp per-domain bound that our router meets.
    """
    base = _load(_TEETH)
    ref = _load(ref_path)
    assert len(_active_scaffold_strands(ref)) == 1
    assert min_per_gap_clearance(ref, base) >= _MIN_GAP_CLEARANCE


# ── The builder reproduces the committed fixture (golden-migration pin) ────────────

def test_teeth_builder_matches_fixture():
    """`make_teeth_design()` reproduces tests/fixtures/teeth.nadoc exactly.

    The builder replays teeth.nadoc's own 6-op feature log through the same core
    bundle/extrude builders the app uses, so it can replace the 63 KB committed
    blob without changing what the routing tests consume.  Two independent proofs:

    1. Canonical topology equality — identical helices (by grid_pos) and strand
       domains.  Because route_sections is a pure function of topology, equal
       fingerprints ⇒ the router cannot tell the two inputs apart.
    2. Belt-and-suspenders: routing both through the seamed AND seamless paths
       yields identical scaffold routes — the user's literal "router treats them
       identically" criterion, checked end-to-end.

    If this ever fails after a change to make_bundle_design /
    make_bundle_continuation, the builder has drifted from the fixture: either the
    construction semantics changed (regenerate the fixture) or the builder is wrong.
    """
    from tests.conftest import make_teeth_design

    built = make_teeth_design()
    fixture = _load(_TEETH)

    assert _canonical_topology(built) == _canonical_topology(fixture)

    for seamless in (False, True):
        rb = route_sections(built.model_copy(deep=True), seamless=seamless)
        rf = route_sections(fixture.model_copy(deep=True), seamless=seamless)
        assert rb is not None and rf is not None
        routed_built, _ = rb
        routed_fixture, _ = rf
        assert _canonical_topology(routed_built) == _canonical_topology(routed_fixture), (
            f"seamless={seamless}: routed output differs between builder and fixture"
        )


def test_18hb_builder_matches_fixture():
    """`make_18hb_design()` reproduces tests/fixtures/18hb_fixture.nadoc.

    Single-op (bundle-create) honeycomb reference — proves the generalized
    builder is faithful beyond the multi-pass teeth special case.
    """
    from tests.conftest import make_18hb_design

    assert _canonical_topology(make_18hb_design()) == _canonical_topology(_load(
        _ROOT / "tests" / "fixtures" / "18hb_fixture.nadoc"))


# ── Structural guarantees the section router already meets ─────────────────────────

@pytest.mark.parametrize("fixture", [_TEETH, _DUMBBELL])
def test_section_router_single_strand_full_coverage(fixture):
    base = _load(fixture)
    result = route_sections(base.model_copy(deep=True))
    assert result is not None, "route_sections fell back to None on a multi-section design"
    routed, _ = result
    assert len(_active_scaffold_strands(routed)) == 1
    assert _full_coverage_missing(routed, base) == {}


# ── The hard requirement under construction (face-based redesign target) ───────────

@pytest.mark.parametrize("fixture", [_TEETH, _DUMBBELL])
def test_section_router_keeps_inter_tooth_gaps_open(fixture):
    base = _load(fixture)
    routed, _ = route_sections(base.model_copy(deep=True))
    clearance = min_per_gap_clearance(routed, base)
    assert clearance >= _MIN_GAP_CLEARANCE, (
        f"a gap is left only {clearance}bp clear (< {_MIN_GAP_CLEARANCE}); "
        "scaffold fills the inter-tooth gaps"
    )


@pytest.mark.parametrize("fixture", [_TEETH, _DUMBBELL])
def test_section_router_bounds_per_domain_gap_extension(fixture):
    base = _load(fixture)
    routed, _ = route_sections(base.model_copy(deep=True))
    worst, viol = intertooth_gap_extension(routed, base)
    assert not viol, f"scaffold extends >{_MAX_GAP_EXT}bp into inter-tooth gaps: worst={worst} {viol}"


@pytest.mark.parametrize("fixture", [_TEETH, _DUMBBELL])
def test_trunk_tooth_connections_near_midpoint(fixture):
    base = _load(fixture)
    routed, _ = route_sections(base.model_copy(deep=True))
    off = trunk_tooth_connections_off_midpoint(routed, base)
    assert not off, f"trunk↔tooth connections sit near a face, not the tooth midpoint: {off}"


# ── The PUBLIC seamed entry point (the in-app Auto-scaffold) must keep gaps clear ──
# auto_scaffold_seamed now routes any multi-section design through the section router
# by default, so the in-app seamed route — not just route_sections — keeps the teeth
# gaps open (the per-helix seamed path bridged a gap: min_clear=0).

def test_seamed_autoscaffold_keeps_teeth_gaps_open():
    base = _load(_TEETH)
    routed, result = auto_scaffold_seamed(base.copy_with(crossovers=[]))
    scaffold = [s for s in routed.strands if s.strand_type == StrandType.SCAFFOLD and not s.is_reference]
    assert len(scaffold) == 1, f"expected 1 scaffold strand, got {len(scaffold)}"
    assert _full_coverage_missing(routed, base) == {}
    worst, viol = intertooth_gap_extension(routed, base)
    assert not viol, f"seamed autoscaffold extends >{_MAX_GAP_EXT}bp into gaps: worst={worst} {viol}"
    clearance = min_per_gap_clearance(routed, base)
    assert clearance >= _MIN_GAP_CLEARANCE, f"seamed autoscaffold leaves a gap only {clearance}bp clear"
    teeth_ext = max_teeth_extension_past_any_face(routed, base)
    assert teeth_ext <= _MAX_GAP_EXT, (
        f"a tooth face sticks out {teeth_ext}bp (> {_MAX_GAP_EXT}); tooth extension not bounded"
    )


def test_seamed_autoscaffold_trunk_ends_matched_for_polymerization():
    """The trunk's two farthest faces are matched (far = near + P) so identical copies
    puzzle-fit end-to-end for periodic-boundary polymerization."""
    base = _load(_TEETH)
    routed, _ = auto_scaffold_seamed(base.copy_with(crossovers=[]))
    p = trunk_matched_translate(routed, base)
    assert p is not None, "trunk far end is not a periodic translate of its near end (not polymerizable)"


# ── Seamless autoscaffold: as robust as seamed, with a buried nick ────────────────
# auto_scaffold_seamless now routes multi-section designs through the section router
# (windows seamless, backbone seamed→circular), so the dumbbell that used to fragment
# into 8 pieces routes to one strand with a buried mid-bundle nick.

@pytest.mark.parametrize("fixture", [_TEETH, _DUMBBELL])
def test_seamless_autoscaffold_single_strand_buried_nick(fixture):
    base = _load(fixture)
    routed, result = auto_scaffold_seamless(base.copy_with(crossovers=[]))
    scaffold = [s for s in routed.strands if s.strand_type == StrandType.SCAFFOLD and not s.is_reference]
    assert len(scaffold) == 1, f"expected 1 scaffold strand, got {len(scaffold)}"
    assert result.warnings == [], result.warnings
    assert _full_coverage_missing(routed, base) == {}
    assert nick_is_buried(routed, base), "seamless nick is not buried mid-bundle"
    teeth_ext = max_teeth_extension_past_any_face(routed, base)
    assert teeth_ext <= _MAX_GAP_EXT, f"a tooth face sticks out {teeth_ext}bp (> {_MAX_GAP_EXT})"
    assert min_per_gap_clearance(routed, base) >= _MIN_GAP_CLEARANCE


# ── The hand-routed seamless reference defines "correct" ──────────────────────────
# workspace/Scaffold routing/teeth_seamless_route1.nadoc: 1 strand, ZERO seams (fully
# seamless — every crossover is an end/bridge, no mid-helix Holliday junction), and a
# PROPER nick (5'/3' on the same helix at adjacent bp — a circular scaffold opened at
# one phosphate), buried mid-bundle.  This is the target the router must match.

def test_reference_seamless_route_is_golden():
    base = _load(_TEETH)
    ref = _load(_SEAMLESS_REF)
    assert len(_active_scaffold_strands(ref)) == 1
    assert seam_crossover_count(ref) == 0, "reference unexpectedly has seam crossovers"
    assert nick_is_proper(ref), "reference nick is not a same-helix adjacent-bp nick"
    assert nick_is_buried(ref, base), "reference nick is not buried"
    assert _full_coverage_missing(ref, base) == {}
    assert min_per_gap_clearance(ref, base) >= _MIN_GAP_CLEARANCE


def test_seamless_autoscaffold_is_fully_seamless_like_reference():
    """The seamless router must produce a fully-seamless route like the reference:
    one strand, a proper buried nick, full coverage, clean gaps, and NO seam crossovers
    anywhere (not even on the backbone)."""
    base = _load(_TEETH)
    routed, result = auto_scaffold_seamless(base.copy_with(crossovers=[]))
    assert len(_active_scaffold_strands(routed)) == 1
    assert _full_coverage_missing(routed, base) == {}
    assert nick_is_proper(routed) and nick_is_buried(routed, base)
    assert min_per_gap_clearance(routed, base) >= _MIN_GAP_CLEARANCE
    assert seam_crossover_count(routed) == 0, (
        f"seamless route has {seam_crossover_count(routed)} seam crossover(s) on the "
        "backbone; the reference is fully seamless"
    )
