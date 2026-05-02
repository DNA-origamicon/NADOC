"""Unit tests for backend.core.cluster_reconcile."""

from __future__ import annotations

import pytest

from backend.core.cluster_reconcile import (
    EMPTY_REPORT,
    MutationReport,
    reconcile_cluster_membership,
)
from backend.core.models import (
    ClusterRigidTransform,
    Design,
    Direction,
    Domain,
    DomainRef,
    Helix,
    Strand,
    StrandType,
    Vec3,
)


# ── Helpers ───────────────────────────────────────────────────────────────────


def _helix(hid: str, row: int = 0, col: int = 0, length_bp: int = 100) -> Helix:
    return Helix(
        id=hid,
        axis_start=Vec3(x=col * 2.5, y=row * 2.5, z=0.0),
        axis_end=Vec3(x=col * 2.5, y=row * 2.5, z=length_bp * 0.34),
        length_bp=length_bp,
        grid_pos=(row, col),
    )


def _strand(
    sid: str,
    domains: list[Domain],
    strand_type: StrandType = StrandType.STAPLE,
) -> Strand:
    return Strand(id=sid, domains=domains, strand_type=strand_type)


def _dom(hid: str, lo: int, hi: int, direction: Direction = Direction.FORWARD) -> Domain:
    return Domain(helix_id=hid, start_bp=lo, end_bp=hi, direction=direction)


def _cluster(
    cid: str,
    helix_ids: list[str],
    domain_refs: list[DomainRef] | None = None,
    translation: list[float] | None = None,
    rotation: list[float] | None = None,
    pivot: list[float] | None = None,
) -> ClusterRigidTransform:
    return ClusterRigidTransform(
        id=cid,
        name=f"Cluster {cid}",
        helix_ids=helix_ids,
        domain_ids=domain_refs or [],
        translation=translation or [0.0, 0.0, 0.0],
        rotation=rotation or [0.0, 0.0, 0.0, 1.0],
        pivot=pivot or [0.0, 0.0, 0.0],
    )


# ── No-change baseline ────────────────────────────────────────────────────────


def test_no_change_returns_equivalent_design():
    h0 = _helix("h0", 0, 0)
    s0 = _strand("s0", [_dom("h0", 0, 99)])
    cluster = _cluster("c0", ["h0"], translation=[1.0, 2.0, 3.0])
    design = Design(helices=[h0], strands=[s0], cluster_transforms=[cluster])

    result = reconcile_cluster_membership(design, design)

    assert len(result.cluster_transforms) == 1
    assert result.cluster_transforms[0].helix_ids == ["h0"]
    assert result.cluster_transforms[0].translation == [1.0, 2.0, 3.0]


def test_design_with_no_clusters_is_passthrough():
    design = Design(helices=[_helix("h0")], strands=[])
    result = reconcile_cluster_membership(design, design)
    assert result.cluster_transforms == []


def test_design_before_none_is_passthrough():
    h0 = _helix("h0")
    cluster = _cluster("c0", ["h0"])
    design = Design(helices=[h0], cluster_transforms=[cluster])
    result = reconcile_cluster_membership(None, design)
    assert result.cluster_transforms[0].helix_ids == ["h0"]


# ── New domain on existing helix ──────────────────────────────────────────────


def test_new_domain_on_existing_helix_inherits_helix_level_cluster():
    """Helix-level cluster: new domain on cluster's helix gets transform automatically.

    Helix-level clusters store no DomainRefs; the deformation code applies the
    transform to every nucleotide on a clustered helix. So adding a new strand
    on that helix needs no membership change — but the reconciler must not
    accidentally promote the cluster to domain-level.
    """
    h0 = _helix("h0", length_bp=100)
    s0 = _strand("s0", [_dom("h0", 0, 49)])
    cluster_before = _cluster("c0", ["h0"])
    design_before = Design(helices=[h0], strands=[s0], cluster_transforms=[cluster_before])

    s1 = _strand("s1", [_dom("h0", 50, 99, Direction.REVERSE)])
    design_after = Design(
        helices=[h0],
        strands=[s0, s1],
        cluster_transforms=[cluster_before],
    )

    result = reconcile_cluster_membership(design_before, design_after)
    c = result.cluster_transforms[0]
    assert c.helix_ids == ["h0"]
    assert c.domain_ids == []  # stayed helix-level


def test_new_domain_on_existing_helix_added_to_domain_level_cluster():
    """Domain-level cluster: new domain falling within cluster's bp coverage
    must get a DomainRef added so its nucleotides are transformed."""
    h0 = _helix("h0", length_bp=100)
    s0 = _strand("s0", [_dom("h0", 0, 99)])
    cluster_before = _cluster(
        "c0",
        ["h0"],
        domain_refs=[DomainRef(strand_id="s0", domain_index=0)],
    )
    design_before = Design(helices=[h0], strands=[s0], cluster_transforms=[cluster_before])

    s1 = _strand("s1", [_dom("h0", 0, 99, Direction.REVERSE)])
    design_after = Design(
        helices=[h0],
        strands=[s0, s1],
        cluster_transforms=[cluster_before],
    )

    result = reconcile_cluster_membership(design_before, design_after)
    c = result.cluster_transforms[0]
    refs = sorted((r.strand_id, r.domain_index) for r in c.domain_ids)
    assert ("s0", 0) in refs
    assert ("s1", 0) in refs


# ── BP-range majority among competing clusters ────────────────────────────────


def test_bp_range_majority_wins_for_two_domain_clusters_on_one_helix():
    """Two domain-level clusters share helix h0. Each claims half the bp range.
    A new domain in cluster B's range should join cluster B."""
    h0 = _helix("h0", length_bp=100)
    s_a = _strand("s_a", [_dom("h0", 0, 49)])
    s_b = _strand("s_b", [_dom("h0", 50, 99)])
    cluster_a = _cluster("c_a", ["h0"], domain_refs=[DomainRef(strand_id="s_a", domain_index=0)])
    cluster_b = _cluster("c_b", ["h0"], domain_refs=[DomainRef(strand_id="s_b", domain_index=0)])
    design_before = Design(
        helices=[h0],
        strands=[s_a, s_b],
        cluster_transforms=[cluster_a, cluster_b],
    )

    s_new = _strand("s_new", [_dom("h0", 60, 80)])  # entirely within cluster_b
    design_after = Design(
        helices=[h0],
        strands=[s_a, s_b, s_new],
        cluster_transforms=[cluster_a, cluster_b],
    )

    result = reconcile_cluster_membership(design_before, design_after)
    c_a_after = next(c for c in result.cluster_transforms if c.id == "c_a")
    c_b_after = next(c for c in result.cluster_transforms if c.id == "c_b")
    assert all(r.strand_id != "s_new" for r in c_a_after.domain_ids)
    assert any(r.strand_id == "s_new" for r in c_b_after.domain_ids)


# ── New helix membership ──────────────────────────────────────────────────────


def test_new_helix_inherits_via_report_origin():
    h0 = _helix("h0", 0, 0)
    s0 = _strand("s0", [_dom("h0", 0, 99)])
    cluster = _cluster("c0", ["h0"], translation=[5.0, 0.0, 0.0])
    design_before = Design(helices=[h0], strands=[s0], cluster_transforms=[cluster])

    h_new = _helix("h_new", 5, 5)  # far from h0 by lattice distance
    design_after = Design(
        helices=[h0, h_new],
        strands=[s0],
        cluster_transforms=[cluster],
    )

    report = MutationReport(new_helix_origins={"h_new": "h0"})
    result = reconcile_cluster_membership(design_before, design_after, report)

    c = result.cluster_transforms[0]
    assert "h_new" in c.helix_ids


def test_new_helix_inherits_via_lattice_neighbor_majority():
    """No report — fall back to grid_pos proximity."""
    h0 = _helix("h0", 0, 0)
    h1 = _helix("h1", 0, 1)  # adjacent
    s0 = _strand("s0", [_dom("h0", 0, 99)])
    s1 = _strand("s1", [_dom("h1", 0, 99)])
    cluster = _cluster("c0", ["h0", "h1"])
    design_before = Design(
        helices=[h0, h1],
        strands=[s0, s1],
        cluster_transforms=[cluster],
    )

    h_new = _helix("h_new", 0, 2)  # adjacent to h1
    design_after = Design(
        helices=[h0, h1, h_new],
        strands=[s0, s1],
        cluster_transforms=[cluster],
    )

    result = reconcile_cluster_membership(design_before, design_after)
    c = result.cluster_transforms[0]
    assert "h_new" in c.helix_ids


def test_new_helix_with_orphan_neighbor_stays_orphaned():
    """If parent helix is orphan (in no cluster), new helix inherits orphan state."""
    h0 = _helix("h0", 0, 0)  # in cluster
    h_orphan = _helix("h_orphan", 5, 5)  # not in any cluster
    s0 = _strand("s0", [_dom("h0", 0, 99)])
    s_orphan = _strand("s_orphan", [_dom("h_orphan", 0, 99)])
    cluster = _cluster("c0", ["h0"])
    design_before = Design(
        helices=[h0, h_orphan],
        strands=[s0, s_orphan],
        cluster_transforms=[cluster],
    )

    h_new = _helix("h_new", 5, 6)  # adjacent to orphan
    design_after = Design(
        helices=[h0, h_orphan, h_new],
        strands=[s0, s_orphan],
        cluster_transforms=[cluster],
    )

    report = MutationReport(new_helix_origins={"h_new": "h_orphan"})
    result = reconcile_cluster_membership(design_before, design_after, report)
    c = result.cluster_transforms[0]
    assert "h_new" not in c.helix_ids


def test_new_helix_inherits_all_clusters_of_parent():
    """If parent is in multiple clusters (scaffold + geometry layered),
    new helix joins all of them."""
    h0 = _helix("h0", 0, 0)
    s0 = _strand("s0", [_dom("h0", 0, 99)])
    scaffold_cluster = _cluster("c_scaffold", ["h0"])
    geometry_cluster = _cluster("c_geometry", ["h0"])
    design_before = Design(
        helices=[h0],
        strands=[s0],
        cluster_transforms=[scaffold_cluster, geometry_cluster],
    )

    h_new = _helix("h_new", 0, 1)
    design_after = Design(
        helices=[h0, h_new],
        strands=[s0],
        cluster_transforms=[scaffold_cluster, geometry_cluster],
    )

    report = MutationReport(new_helix_origins={"h_new": "h0"})
    result = reconcile_cluster_membership(design_before, design_after, report)
    for c in result.cluster_transforms:
        assert "h_new" in c.helix_ids


# ── Strand id renames / strand splits handled by bp-overlap ───────────────────


def test_strand_split_distributes_domain_refs_by_bp_range():
    """Strand A at bp 0..99 splits into A (0..49) and A_r (50..99) after a nick.
    The reconciler rebuilds DomainRefs via bp overlap — no rename map needed."""
    h0 = _helix("h0", 0, 0, length_bp=100)
    s_a_before = _strand("s_a", [_dom("h0", 0, 99)])
    cluster_before = _cluster(
        "c0",
        ["h0"],
        domain_refs=[DomainRef(strand_id="s_a", domain_index=0)],
    )
    design_before = Design(helices=[h0], strands=[s_a_before], cluster_transforms=[cluster_before])

    s_a_after = _strand("s_a", [_dom("h0", 0, 49)])
    s_a_r = _strand("s_a_r", [_dom("h0", 50, 99)])
    design_after = Design(
        helices=[h0],
        strands=[s_a_after, s_a_r],
        cluster_transforms=[cluster_before],
    )

    result = reconcile_cluster_membership(design_before, design_after)
    refs = {(r.strand_id, r.domain_index) for r in result.cluster_transforms[0].domain_ids}
    assert ("s_a", 0) in refs
    assert ("s_a_r", 0) in refs


def test_stale_domain_ref_dropped_when_strand_gone():
    h0 = _helix("h0", 0, 0)
    s0 = _strand("s0", [_dom("h0", 0, 49)])
    s1 = _strand("s1", [_dom("h0", 50, 99)])
    cluster_before = _cluster(
        "c0",
        ["h0"],
        domain_refs=[
            DomainRef(strand_id="s0", domain_index=0),
            DomainRef(strand_id="s1", domain_index=0),
        ],
    )
    design_before = Design(helices=[h0], strands=[s0, s1], cluster_transforms=[cluster_before])

    design_after = Design(
        helices=[h0],
        strands=[s0],  # s1 deleted
        cluster_transforms=[cluster_before],
    )

    result = reconcile_cluster_membership(design_before, design_after)
    refs = {(r.strand_id, r.domain_index) for r in result.cluster_transforms[0].domain_ids}
    assert refs == {("s0", 0)}


def test_stale_domain_ref_dropped_when_index_out_of_range():
    h0 = _helix("h0", 0, 0)
    s0_before = _strand("s0", [_dom("h0", 0, 49), _dom("h0", 50, 99, Direction.REVERSE)])
    cluster_before = _cluster(
        "c0",
        ["h0"],
        domain_refs=[
            DomainRef(strand_id="s0", domain_index=0),
            DomainRef(strand_id="s0", domain_index=1),
        ],
    )
    design_before = Design(helices=[h0], strands=[s0_before], cluster_transforms=[cluster_before])

    s0_after = _strand("s0", [_dom("h0", 0, 49)])  # second domain merged/removed
    design_after = Design(helices=[h0], strands=[s0_after], cluster_transforms=[cluster_before])

    result = reconcile_cluster_membership(design_before, design_after)
    refs = {(r.strand_id, r.domain_index) for r in result.cluster_transforms[0].domain_ids}
    assert refs == {("s0", 0)}


# ── Invariants ────────────────────────────────────────────────────────────────


def test_never_modifies_translation_rotation_pivot():
    h0 = _helix("h0", 0, 0)
    s0 = _strand("s0", [_dom("h0", 0, 99)])
    original = _cluster(
        "c0",
        ["h0"],
        translation=[1.5, 2.5, 3.5],
        rotation=[0.1, 0.2, 0.3, 0.9],
        pivot=[4.0, 5.0, 6.0],
    )
    design_before = Design(helices=[h0], strands=[s0], cluster_transforms=[original])

    h_new = _helix("h_new", 0, 1)
    design_after = Design(
        helices=[h0, h_new],
        strands=[s0],
        cluster_transforms=[original],
    )

    result = reconcile_cluster_membership(
        design_before,
        design_after,
        MutationReport(new_helix_origins={"h_new": "h0"}),
    )
    c = result.cluster_transforms[0]
    assert c.translation == [1.5, 2.5, 3.5]
    assert c.rotation == [0.1, 0.2, 0.3, 0.9]
    assert c.pivot == [4.0, 5.0, 6.0]


def test_never_merges_clusters():
    """Two adjacent clusters sharing a lattice edge stay separate after a no-op mutation."""
    h0 = _helix("h0", 0, 0)
    h1 = _helix("h1", 0, 1)
    s0 = _strand("s0", [_dom("h0", 0, 99)])
    s1 = _strand("s1", [_dom("h1", 0, 99)])
    cluster_a = _cluster("c_a", ["h0"])
    cluster_b = _cluster("c_b", ["h1"])
    design = Design(
        helices=[h0, h1],
        strands=[s0, s1],
        cluster_transforms=[cluster_a, cluster_b],
    )

    result = reconcile_cluster_membership(design, design)
    assert len(result.cluster_transforms) == 2
    a = next(c for c in result.cluster_transforms if c.id == "c_a")
    b = next(c for c in result.cluster_transforms if c.id == "c_b")
    assert a.helix_ids == ["h0"]
    assert b.helix_ids == ["h1"]


def test_never_splits_existing_cluster():
    """If h1 was in cluster A (before), it stays in A (after) regardless of bp coverage."""
    h0 = _helix("h0", 0, 0)
    h1 = _helix("h1", 0, 1)
    s0 = _strand("s0", [_dom("h0", 0, 99)])
    s1 = _strand("s1", [_dom("h1", 0, 99)])
    cluster_a = _cluster("c_a", ["h0", "h1"])  # both helices in A
    design_before = Design(
        helices=[h0, h1],
        strands=[s0, s1],
        cluster_transforms=[cluster_a],
    )

    s_new = _strand("s_new", [_dom("h1", 0, 99, Direction.REVERSE)])
    design_after = Design(
        helices=[h0, h1],
        strands=[s0, s1, s_new],
        cluster_transforms=[cluster_a],
    )

    result = reconcile_cluster_membership(design_before, design_after)
    c = result.cluster_transforms[0]
    assert "h1" in c.helix_ids  # h1 stays in c_a


def test_loop_skip_change_does_not_disturb_membership():
    """Loop/skip mutations don't change Domain.start_bp/end_bp, so reconciliation is a no-op."""
    h0 = _helix("h0", 0, 0)
    s0 = _strand("s0", [_dom("h0", 0, 99)])
    cluster_before = _cluster(
        "c0",
        ["h0"],
        domain_refs=[DomainRef(strand_id="s0", domain_index=0)],
    )
    design_before = Design(helices=[h0], strands=[s0], cluster_transforms=[cluster_before])

    from backend.core.models import LoopSkip
    h0_after = h0.model_copy(update={"loop_skips": [LoopSkip(bp_index=10, delta=1)]})
    design_after = Design(helices=[h0_after], strands=[s0], cluster_transforms=[cluster_before])

    result = reconcile_cluster_membership(design_before, design_after)
    c = result.cluster_transforms[0]
    refs = {(r.strand_id, r.domain_index) for r in c.domain_ids}
    assert refs == {("s0", 0)}


def test_helix_deletion_drops_helix_from_clusters():
    h0 = _helix("h0", 0, 0)
    h1 = _helix("h1", 0, 1)
    s0 = _strand("s0", [_dom("h0", 0, 99)])
    s1 = _strand("s1", [_dom("h1", 0, 99)])
    cluster_before = _cluster("c0", ["h0", "h1"])
    design_before = Design(
        helices=[h0, h1],
        strands=[s0, s1],
        cluster_transforms=[cluster_before],
    )

    design_after = Design(
        helices=[h0],
        strands=[s0],
        cluster_transforms=[cluster_before],
    )

    result = reconcile_cluster_membership(design_before, design_after)
    assert result.cluster_transforms[0].helix_ids == ["h0"]


# ── Mixed cluster (helix-level + domain-level) preserved ──────────────────────


def test_exclusive_helix_in_mixed_cluster_preserved():
    """Scaffold-cluster pattern: helix h0 is exclusive (whole), helix h1 is bridge
    (specific DomainRefs). Adding a new domain to h0 doesn't add a DomainRef."""
    h0 = _helix("h0", 0, 0)
    h1 = _helix("h1", 0, 1)
    s_scaf = _strand("s_scaf", [_dom("h1", 0, 99)], strand_type=StrandType.SCAFFOLD)
    s_stap = _strand("s_stap", [_dom("h0", 0, 99, Direction.REVERSE)])
    cluster_before = _cluster(
        "c0",
        ["h0", "h1"],
        domain_refs=[DomainRef(strand_id="s_scaf", domain_index=0)],
    )
    design_before = Design(
        helices=[h0, h1],
        strands=[s_scaf, s_stap],
        cluster_transforms=[cluster_before],
    )

    s_new = _strand("s_new", [_dom("h0", 0, 49)])
    design_after = Design(
        helices=[h0, h1],
        strands=[s_scaf, s_stap, s_new],
        cluster_transforms=[cluster_before],
    )

    result = reconcile_cluster_membership(design_before, design_after)
    c = result.cluster_transforms[0]
    # helix_ids unchanged (no new helices)
    assert set(c.helix_ids) == {"h0", "h1"}
    # h0 is exclusive (whole) → no DomainRefs for s_new on h0
    refs = {(r.strand_id, r.domain_index) for r in c.domain_ids}
    assert ("s_new", 0) not in refs
    # s_scaf still claimed
    assert ("s_scaf", 0) in refs


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
