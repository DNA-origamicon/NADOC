"""ISSUE-18 — a SCAFFOLD router must never edit a STAPLE / LINKER / OH_BINDER.

The rule: a scaffold router may extend helices and scaffold domains. It must NEVER
create, extend, trim, split or delete a non-scaffold strand.

Two helpers in `seamed_router` scanned EVERY strand with no `strand_type` filter:
  * `_nick_if_needed` → `lattice._find_strand_at`  (unfiltered lookup)
  * `_ligate_xover`   → terminal maps built over all strands
So on any bp where the scaffold does not reach but a LINKER / OH_BINDER / hand-drawn
staple occupies the scaffold-DIRECTION slot, the scaffold router would nick or fuse it.
Reproduced: a linker at [86 → 81] came out of `auto_scaffold_seamed` split into
[86 → 85] + [84 → 81].

Both routers are covered: the seamless router shares `_place_xover`, which is what
calls both helpers.
"""

from __future__ import annotations

import pytest

from backend.core.lattice import make_bundle_design
from backend.core.models import Direction, Domain, Strand, StrandType
from backend.core.seamed_router import (
    auto_scaffold_seamed,
    is_routable_scaffold,
)
from backend.core.seamless_router import auto_scaffold_seamless

CELLS_4HB = [(0, 0), (0, 1), (1, 0), (1, 1)]


def _nonscaffold(d):
    """id -> domain extents, for every strand a scaffold router must not touch."""
    return {
        s.id: [(dm.helix_id, dm.start_bp, dm.end_bp) for dm in s.domains]
        for s in d.strands
        if s.strand_type != StrandType.SCAFFOLD and not s.is_reference
    }


def _with_strand_at(base, grid_pos, lo, hi, direction, strand_type, sid):
    h = next(x for x in base.helices if x.grid_pos == grid_pos)
    start, end = (lo, hi) if direction == Direction.FORWARD else (hi, lo)
    s = Strand(
        id=sid,
        domains=[
            Domain(helix_id=h.id, start_bp=start, end_bp=end, direction=direction)
        ],
        strand_type=strand_type,
    )
    return base.copy_with(strands=list(base.strands) + [s]), h


# ── The repro, as a pin ──────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "router",
    [
        pytest.param(lambda d: auto_scaffold_seamed(d)[0], id="seamed"),
        pytest.param(lambda d: auto_scaffold_seamless(d)[0], id="seamless"),
    ],
)
@pytest.mark.parametrize(
    "strand_type",
    [
        StrandType.LINKER,
        StrandType.STAPLE,
        StrandType.OH_BINDER,
    ],
)
def test_scaffold_router_never_edits_a_non_scaffold_strand(router, strand_type):
    """Plant a non-scaffold strand whose 3' terminus lands ON a scaffold-crossover half
    (bp 81, the seam site on this bundle) in the SCAFFOLD direction — the exact slot the
    unfiltered lookup used to grab. It must come out byte-identical."""
    base = make_bundle_design(CELLS_4HB, length_bp=168)
    d, _ = _with_strand_at(
        base, (0, 1), 81, 86, Direction.REVERSE, strand_type, "victim"
    )

    before = _nonscaffold(d)
    after = _nonscaffold(router(d))

    assert "victim" in after, f"{strand_type} was CONSUMED by the scaffold router"
    assert after["victim"] == before["victim"], (
        f"scaffold router MUTATED a {strand_type}: "
        f"{before['victim']} -> {after['victim']}"
    )
    assert len(after) == len(before), (
        "scaffold router split a non-scaffold strand in two"
    )


def test_scaffold_router_leaves_a_linker_in_the_end_turn_zone_alone():
    """The realistic case: a linker in the region the near-end turn extends INTO
    (bp -9..-4), not overlapping the scaffold's original footprint."""
    base = make_bundle_design(CELLS_4HB, length_bp=168)
    d, _ = _with_strand_at(
        base, (0, 1), -9, -4, Direction.REVERSE, StrandType.LINKER, "endzone"
    )

    before = _nonscaffold(d)
    after = _nonscaffold(auto_scaffold_seamed(d)[0])

    assert after["endzone"] == before["endzone"]


def test_a_clean_bundle_still_routes_to_one_strand():
    """The allowlist must not break the ordinary path: no linkers → unchanged."""
    routed = auto_scaffold_seamed(make_bundle_design(CELLS_4HB, length_bp=168))[0]
    n_scaf = sum(
        1
        for s in routed.strands
        if s.strand_type == StrandType.SCAFFOLD and not s.is_reference
    )
    assert n_scaf == 1


# ── The allowlist itself ─────────────────────────────────────────────────────


def test_allowlist_is_positive_not_a_linker_blocklist():
    """A blocklist ('not LINKER') would still let the router chew on OH_BINDERs and
    hand-drawn staples, and would silently miss any strand type added later."""

    def mk(t, ref=False):
        return Strand(id="x", domains=[], strand_type=t, is_reference=ref)

    assert is_routable_scaffold(mk(StrandType.SCAFFOLD))
    assert not is_routable_scaffold(mk(StrandType.SCAFFOLD, ref=True))  # reference geom
    for t in (StrandType.STAPLE, StrandType.LINKER, StrandType.OH_BINDER):
        assert not is_routable_scaffold(mk(t)), f"{t} must not be routable"


def test_staple_paths_keep_the_unfiltered_lookup():
    """`make_nick` without a predicate must still nick ANY strand — the staple-crossover
    path in crud relies on exactly that, and this fix must not have narrowed it."""
    from backend.core.lattice import make_nick

    base = make_bundle_design(CELLS_4HB, length_bp=168)
    staple = next(s for s in base.strands if s.strand_type == StrandType.STAPLE)
    dom = staple.domains[0]
    mid = (min(dom.start_bp, dom.end_bp) + max(dom.start_bp, dom.end_bp)) // 2

    nicked = make_nick(base, dom.helix_id, mid, dom.direction)  # no predicate

    n_before = sum(1 for s in base.strands if s.strand_type == StrandType.STAPLE)
    n_after = sum(1 for s in nicked.strands if s.strand_type == StrandType.STAPLE)
    assert n_after == n_before + 1, "unfiltered make_nick must still split a staple"
