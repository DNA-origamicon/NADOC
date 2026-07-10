"""Unit tests for backend.core.cluster_copy (cluster copy/paste).

The load-bearing invariant, asserted by ``test_every_pasted_crossover_stays_legal``:

    an even-parity grid shift with Δbp == 0 preserves every copied helix's
    FORWARD/REVERSE polarity AND lands every copied crossover on a legal bp phase.

Everything else here defends that, or defends the truncation bookkeeping.
"""

from __future__ import annotations

import json
import pathlib

import pytest

from backend.core.cluster_copy import (
    cluster_closure,
    extract_cluster_subdesign,
    graft_cluster_subdesign,
    paste_clusters,
)
from backend.core.cluster_reconcile import MutationReport, reconcile_cluster_membership
from backend.core.crossover_positions import crossover_neighbor
from backend.core.models import (
    ClusterRigidTransform,
    Crossover,
    Design,
    Direction,
    Domain,
    DomainRef,
    ForcedLigation,
    HalfCrossover,
    Helix,
    LatticeType,
    Strand,
    StrandType,
    Vec3,
)
from backend.core.validator import validate_design

EXAMPLES = pathlib.Path(__file__).resolve().parent.parent / "Examples"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _helix(hid: str, row: int, col: int, length_bp: int = 100) -> Helix:
    return Helix(
        id=hid,
        axis_start=Vec3(x=col * 2.5, y=row * 2.5, z=0.0),
        axis_end=Vec3(x=col * 2.5, y=row * 2.5, z=length_bp * 0.34),
        length_bp=length_bp,
        grid_pos=(row, col),
    )


def _dom(hid: str, lo: int, hi: int, direction: Direction = Direction.FORWARD) -> Domain:
    return Domain(helix_id=hid, start_bp=lo, end_bp=hi, direction=direction)


def _cluster(cid: str, helix_ids: list[str], **kw) -> ClusterRigidTransform:
    return ClusterRigidTransform(id=cid, name=f"Cluster {cid}", helix_ids=helix_ids, **kw)


def _load(stem: str) -> Design:
    return Design.model_validate(json.loads((EXAMPLES / f"{stem}.nadoc").read_text()))


@pytest.fixture
def two_cluster_design() -> Design:
    """Two 1-helix clusters side by side, plus a staple straddling the boundary.

    Cells (0,0) and (0,2) are both even parity, so a (0,+4) paste is legal.
    """
    return Design(
        lattice_type=LatticeType.HONEYCOMB,
        helices=[_helix("hA", 0, 0), _helix("hB", 0, 2)],
        strands=[
            Strand(id="sA", domains=[_dom("hA", 0, 20)], strand_type=StrandType.STAPLE),
            # straddles the boundary: hA -> hB -> hA
            Strand(
                id="sSpan",
                domains=[_dom("hA", 30, 40), _dom("hB", 30, 40), _dom("hA", 50, 60)],
                strand_type=StrandType.STAPLE,
                sequence="A" * 33,
            ),
        ],
        crossovers=[
            Crossover(
                id="xInternal",
                half_a=HalfCrossover(helix_id="hA", index=10, strand=Direction.FORWARD),
                half_b=HalfCrossover(helix_id="hA", index=10, strand=Direction.REVERSE),
            ),
            Crossover(
                id="xBoundary",
                half_a=HalfCrossover(helix_id="hA", index=30, strand=Direction.FORWARD),
                half_b=HalfCrossover(helix_id="hB", index=30, strand=Direction.REVERSE),
            ),
        ],
        forced_ligations=[
            ForcedLigation(
                id="flInternal",
                three_prime_helix_id="hA",
                three_prime_bp=5,
                three_prime_direction=Direction.FORWARD,
                five_prime_helix_id="hA",
                five_prime_bp=6,
                five_prime_direction=Direction.FORWARD,
            ),
            ForcedLigation(
                id="flBoundary",
                three_prime_helix_id="hA",
                three_prime_bp=70,
                three_prime_direction=Direction.FORWARD,
                five_prime_helix_id="hB",
                five_prime_bp=70,
                five_prime_direction=Direction.REVERSE,
            ),
        ],
        cluster_transforms=[_cluster("cA", ["hA"]), _cluster("cB", ["hB"])],
    )


# ── Closure ───────────────────────────────────────────────────────────────────


def test_closure_pulls_in_parent_when_child_selected():
    clusters = [_cluster("parent", ["h1"]), _cluster("child", ["h1"], parent_cluster_id="parent")]
    closure, added = cluster_closure(["child"], clusters)
    assert set(closure) == {"parent", "child"}
    assert added == ["parent"]


def test_closure_pulls_in_child_when_parent_selected():
    clusters = [_cluster("parent", ["h1"]), _cluster("child", ["h1"], parent_cluster_id="parent")]
    closure, added = cluster_closure(["parent"], clusters)
    assert set(closure) == {"parent", "child"}
    assert added == ["child"]


def test_closure_is_transitive_and_reports_nothing_extra_when_complete():
    clusters = [
        _cluster("a", ["h1"]),
        _cluster("b", ["h1"], parent_cluster_id="a"),
        _cluster("c", ["h1"], parent_cluster_id="b"),
    ]
    closure, added = cluster_closure(["c"], clusters)
    assert set(closure) == {"a", "b", "c"}
    closure2, added2 = cluster_closure(["a", "b", "c"], clusters)
    assert added2 == []


def test_closure_rejects_unknown_cluster_id():
    with pytest.raises(ValueError, match="unknown cluster id"):
        cluster_closure(["nope"], [_cluster("a", ["h1"])])


# ── Extract: truncation ───────────────────────────────────────────────────────


def test_boundary_strand_truncates_into_two_fragments(two_cluster_design):
    sub, report = extract_cluster_subdesign(two_cluster_design, ["cA"])

    # sA survives whole; sSpan (hA, hB, hA) loses its middle domain -> 2 fragments.
    assert len(sub.strands) == 3
    assert report.truncated_strand_count == 1
    frag_sizes = sorted(len(s.domains) for s in sub.strands)
    assert frag_sizes == [1, 1, 1]
    assert all(dm.helix_id == "hA" for s in sub.strands for dm in s.domains)


def test_truncation_renumbers_domain_index_for_domain_level_clusters():
    """A DomainRef at index 2 must follow its domain into the fragment at index 0."""
    design = Design(
        lattice_type=LatticeType.HONEYCOMB,
        helices=[_helix("hA", 0, 0), _helix("hB", 0, 2)],
        strands=[
            Strand(
                id="s1",
                # index:   0            1            2
                domains=[_dom("hB", 0, 5), _dom("hB", 6, 9), _dom("hA", 10, 20)],
            )
        ],
        cluster_transforms=[
            _cluster("cA", ["hA"], domain_ids=[DomainRef(strand_id="s1", domain_index=2)]),
        ],
    )
    sub, _ = extract_cluster_subdesign(design, ["cA"])

    assert len(sub.strands) == 1
    frag = sub.strands[0]
    assert len(frag.domains) == 1
    ref = sub.cluster_transforms[0].domain_ids[0]
    assert ref.strand_id == frag.id      # points at the fragment, not the original
    assert ref.domain_index == 0         # renumbered from 2 -> 0


def test_domain_refs_to_dropped_domains_are_dropped():
    design = Design(
        lattice_type=LatticeType.HONEYCOMB,
        helices=[_helix("hA", 0, 0), _helix("hB", 0, 2)],
        strands=[Strand(id="s1", domains=[_dom("hA", 0, 5), _dom("hB", 6, 9)])],
        cluster_transforms=[
            _cluster(
                "cA",
                ["hA"],
                domain_ids=[
                    DomainRef(strand_id="s1", domain_index=0),  # survives
                    DomainRef(strand_id="s1", domain_index=1),  # on hB -> dropped
                ],
            ),
        ],
    )
    sub, _ = extract_cluster_subdesign(design, ["cA"])
    assert len(sub.cluster_transforms[0].domain_ids) == 1
    assert sub.cluster_transforms[0].domain_ids[0].domain_index == 0


def test_sequences_are_not_copied(two_cluster_design):
    sub, _ = extract_cluster_subdesign(two_cluster_design, ["cA"])
    assert all(s.sequence is None for s in sub.strands)


def test_boundary_crossovers_and_ligations_are_dropped(two_cluster_design):
    sub, report = extract_cluster_subdesign(two_cluster_design, ["cA"])
    assert [x.id for x in sub.crossovers] == ["xInternal"]
    assert [f.id for f in sub.forced_ligations] == ["flInternal"]
    assert report.dropped_boundary_crossovers == 1
    assert report.dropped_boundary_fls == 1


def test_copied_cluster_is_never_the_default(two_cluster_design):
    two_cluster_design.cluster_transforms[0].is_default = True
    sub, _ = extract_cluster_subdesign(two_cluster_design, ["cA"])
    assert sub.cluster_transforms[0].is_default is False


def test_extract_refuses_empty_selection(two_cluster_design):
    with pytest.raises(ValueError, match="no clusters selected"):
        extract_cluster_subdesign(two_cluster_design, [])


def test_extract_refuses_overhangs_rather_than_dropping_them():
    """Silently dropping an OverhangSpec would leave a dangling Domain.overhang_id."""
    design = _load("hingeV4")
    assert design.overhangs, "fixture must carry overhangs for this test to mean anything"
    cid = design.cluster_transforms[0].id
    with pytest.raises(ValueError, match="overhang"):
        extract_cluster_subdesign(design, [cid])


# ── Graft: the parity guard ───────────────────────────────────────────────────


@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
@pytest.mark.parametrize("delta", [(0, 1), (1, 0), (1, 2), (-1, 0)])
def test_odd_parity_paste_raises(two_cluster_design, lattice, delta):
    """SQUARE is the case the inherited footprint guard misses — its positions are
    linear, so an odd shift distorts nothing but silently inverts every polarity."""
    two_cluster_design.lattice_type = lattice
    sub, _ = extract_cluster_subdesign(two_cluster_design, ["cA"])
    sub.lattice_type = lattice
    with pytest.raises(ValueError, match="odd parity"):
        graft_cluster_subdesign(two_cluster_design, sub, grid_delta=delta)


@pytest.mark.parametrize("lattice", [LatticeType.HONEYCOMB, LatticeType.SQUARE])
def test_even_parity_paste_succeeds(two_cluster_design, lattice):
    two_cluster_design.lattice_type = lattice
    sub, _ = extract_cluster_subdesign(two_cluster_design, ["cA"])
    sub.lattice_type = lattice
    out, pasted = graft_cluster_subdesign(two_cluster_design, sub, grid_delta=(0, 4))
    assert len(pasted) == 1
    assert len(out.helices) == 3


def test_zero_delta_paste_raises(two_cluster_design):
    sub, _ = extract_cluster_subdesign(two_cluster_design, ["cA"])
    with pytest.raises(ValueError, match="zero"):
        graft_cluster_subdesign(two_cluster_design, sub, grid_delta=(0, 0))


def test_paste_onto_occupied_cell_raises(two_cluster_design):
    sub, _ = extract_cluster_subdesign(two_cluster_design, ["cA"])
    # hA is at (0,0); hB occupies (0,2). Δ=(0,+2) lands hA' on top of hB.
    with pytest.raises(ValueError, match="collides"):
        graft_cluster_subdesign(two_cluster_design, sub, grid_delta=(0, 2))


def test_paste_into_mismatched_lattice_raises(two_cluster_design):
    sub, _ = extract_cluster_subdesign(two_cluster_design, ["cA"])
    sub.lattice_type = LatticeType.SQUARE
    with pytest.raises(ValueError, match="cannot paste"):
        graft_cluster_subdesign(two_cluster_design, sub, grid_delta=(0, 4))


# ── Graft: content preservation ───────────────────────────────────────────────


def test_bp_indices_are_untouched(two_cluster_design):
    """Δbp is always 0 — the whole crossover-phase argument rests on this."""
    before_h = {h.id: (h.bp_start, h.length_bp) for h in two_cluster_design.helices}
    out, pasted, _ = paste_clusters(two_cluster_design, ["cA"], (0, 4))

    new_helices = [h for h in out.helices if h.id in set(pasted)]
    assert len(new_helices) == 1
    assert (new_helices[0].bp_start, new_helices[0].length_bp) == before_h["hA"]

    src_doms = sorted(
        (d.start_bp, d.end_bp)
        for s in two_cluster_design.strands
        for d in s.domains
        if d.helix_id == "hA"
    )
    new_doms = sorted(
        (d.start_bp, d.end_bp)
        for s in out.strands
        for d in s.domains
        if d.helix_id in set(pasted)
    )
    assert src_doms == new_doms

    new_xo = [x for x in out.crossovers if x.half_a.helix_id in set(pasted)]
    assert [x.half_a.index for x in new_xo] == [10]


def test_posed_cluster_copies_pose_and_shifts_pivot(two_cluster_design):
    two_cluster_design.cluster_transforms[0].translation = [1.0, 2.0, 3.0]
    two_cluster_design.cluster_transforms[0].rotation = [0.0, 0.0, 0.7071, 0.7071]
    two_cluster_design.cluster_transforms[0].pivot = [10.0, 20.0, 30.0]

    out, _, _ = paste_clusters(two_cluster_design, ["cA"], (0, 4))
    new = out.cluster_transforms[-1]

    assert new.translation == [1.0, 2.0, 3.0]
    assert new.rotation == pytest.approx([0.0, 0.0, 0.7071, 0.7071])
    # XY plane -> pivot shifts in x,y by the same world vector as the helices; z fixed.
    assert new.pivot[2] == 30.0
    assert new.pivot[0] != 10.0
    src_h = next(h for h in two_cluster_design.helices if h.id == "hA")
    new_h = next(h for h in out.helices if h.id in set(new.helix_ids))
    assert new.pivot[0] - 10.0 == pytest.approx(new_h.axis_start.x - src_h.axis_start.x)
    assert new.pivot[1] - 20.0 == pytest.approx(new_h.axis_start.y - src_h.axis_start.y)


def test_paste_is_additive_and_ids_are_unique(two_cluster_design):
    out, pasted, _ = paste_clusters(two_cluster_design, ["cA"], (0, 4))

    for attr in ("helices", "strands", "crossovers", "forced_ligations", "cluster_transforms"):
        ids = [o.id for o in getattr(out, attr)]
        assert len(ids) == len(set(ids)), f"duplicate ids in {attr}"

    # host content survives untouched
    assert {"hA", "hB"} <= {h.id for h in out.helices}
    assert {"xInternal", "xBoundary"} <= {x.id for x in out.crossovers}
    assert set(pasted).isdisjoint({"hA", "hB"})


def test_pasted_helix_keeps_polarity_parity(two_cluster_design):
    out, pasted, _ = paste_clusters(two_cluster_design, ["cA"], (0, 4))
    src = next(h for h in two_cluster_design.helices if h.id == "hA")
    new = next(h for h in out.helices if h.id in set(pasted))
    assert sum(src.grid_pos) % 2 == sum(new.grid_pos) % 2


def test_child_cluster_reparents_onto_the_copied_parent():
    design = Design(
        lattice_type=LatticeType.HONEYCOMB,
        helices=[_helix("hA", 0, 0)],
        strands=[Strand(id="s1", domains=[_dom("hA", 0, 20)])],
        cluster_transforms=[
            _cluster("parent", ["hA"]),
            _cluster(
                "child",
                ["hA"],
                parent_cluster_id="parent",
                domain_ids=[DomainRef(strand_id="s1", domain_index=0)],
            ),
        ],
    )
    out, _, report = paste_clusters(design, ["child"], (0, 4))
    assert report.auto_added_cluster_ids == ["parent"]

    new_parent, new_child = out.cluster_transforms[-2], out.cluster_transforms[-1]
    assert new_child.parent_cluster_id == new_parent.id
    assert new_parent.id not in ("parent", "child")


# ── The load-bearing invariant ────────────────────────────────────────────────


def _crossover_legal_flags(design: Design, xo: Crossover) -> set[bool]:
    """Which is_scaffold interpretations make this crossover a legal lattice site."""
    hmap = {h.id: h for h in design.helices}
    a, b = hmap[xo.half_a.helix_id], hmap[xo.half_b.helix_id]
    flags = set()
    for is_scaffold in (False, True):
        nb = crossover_neighbor(
            design.lattice_type,
            a.grid_pos[0],
            a.grid_pos[1],
            xo.half_a.index,
            is_scaffold=is_scaffold,
        )
        if nb is not None and nb == b.grid_pos:
            flags.add(is_scaffold)
    return flags


def test_every_pasted_crossover_stays_legal():
    """THE invariant. Even-parity Δ + Δbp=0 ⇒ every copied crossover site is still
    a legal lattice crossover, with the same scaffold/staple character."""
    design = _load("2hb_xover_val")
    assert design.crossovers, "fixture must carry crossovers"
    cid = design.cluster_transforms[0].id

    src_flags = [_crossover_legal_flags(design, x) for x in design.crossovers]
    assert all(f for f in src_flags), "fixture's own crossovers must be legal to begin with"

    out, pasted, _ = paste_clusters(design, [cid], (0, 4))
    pasted_set = set(pasted)
    new_xo = [x for x in out.crossovers if x.half_a.helix_id in pasted_set]
    assert len(new_xo) == len(design.crossovers)

    new_flags = [_crossover_legal_flags(out, x) for x in new_xo]
    assert all(f for f in new_flags), "a pasted crossover landed on an illegal site"
    assert sorted(map(sorted, new_flags)) == sorted(map(sorted, src_flags))


def test_paste_of_real_design_validates_clean():
    design = _load("2hb_xover_val")
    cid = design.cluster_transforms[0].id
    out, _, _ = paste_clusters(design, [cid], (0, 4))

    def _failures(rep):
        return [r for r in rep.results if not r.ok]

    before = _failures(validate_design(design))
    after = _failures(validate_design(out))
    assert len(after) == len(before), (
        f"paste introduced validation failures: {[str(r) for r in after]}"
    )


# ── Trap 1: the reconciler must not steal the pasted helices ──────────────────
#
# `reconcile_cluster_membership` assigns a NEW helix to a pre-existing cluster when
# a lattice neighbour within Manhattan distance 2 belongs to one.  A paste that
# lands close to its source therefore gets swept into the SOURCE's membership
# unless the mutation reports the pasted helices as explicit orphans.


@pytest.fixture
def adjacent_paste_design() -> Design:
    """One helix at (0,0); a Δ=(0,+2) paste lands at Manhattan distance 2 — inside
    the reconciler's neighbour radius, which is exactly when theft happens."""
    return Design(
        lattice_type=LatticeType.HONEYCOMB,
        helices=[_helix("hA", 0, 0)],
        strands=[Strand(id="sA", domains=[_dom("hA", 0, 20)])],
        cluster_transforms=[_cluster("cA", ["hA"])],
    )


def test_reconcile_without_orphan_hint_steals_pasted_helices(adjacent_paste_design):
    """Pins WHY the hint is needed — this is the bug, reproduced."""
    before = adjacent_paste_design.model_copy(deep=True)
    out, pasted, _ = paste_clusters(adjacent_paste_design, ["cA"], (0, 2))

    reconciled = reconcile_cluster_membership(before, out, None)  # no hint
    by_id = {c.id: c for c in reconciled.cluster_transforms}
    assert set(by_id["cA"].helix_ids) == {"hA", *pasted}, (
        "expected the source cluster to absorb the pasted helix without a hint"
    )


def test_reconcile_with_orphan_hint_leaves_pasted_helices_alone(adjacent_paste_design):
    before = adjacent_paste_design.model_copy(deep=True)
    out, pasted, _ = paste_clusters(adjacent_paste_design, ["cA"], (0, 2))

    report = MutationReport(new_helix_origins={hid: None for hid in pasted})
    reconciled = reconcile_cluster_membership(before, out, report)

    by_id = {c.id: c for c in reconciled.cluster_transforms}
    assert by_id["cA"].helix_ids == ["hA"], "source cluster absorbed the pasted helix"

    new_cluster = reconciled.cluster_transforms[-1]
    assert new_cluster.id != "cA"
    assert set(new_cluster.helix_ids) == set(pasted)
