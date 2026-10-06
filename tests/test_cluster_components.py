"""Disconnected extrusion / additive repair contract, independent of user files."""

from backend.core.cluster_components import (
    cluster_unassigned_components,
    lattice_cluster_graph,
    lattice_components,
)
from backend.core.cluster_reconcile import MutationReport, reconcile_cluster_membership
from backend.core.models import ClusterRigidTransform, Design, Helix, LatticeType, Vec3


def helix(hid, row, col, frame=None):
    return Helix(
        id=hid,
        grid_pos=(row, col),
        lattice_frame_id=frame,
        axis_start=Vec3(x=col * 2.5, y=row * 2.5, z=0),
        axis_end=Vec3(x=col * 2.5, y=row * 2.5, z=10),
        length_bp=30,
    )


def test_exact_neighbors_frames_and_singletons():
    d = Design(
        lattice_type=LatticeType.SQUARE,
        helices=[
            helix("a", 0, 0),
            helix("b", 0, 1),
            helix("diagonal", 1, 2),
            helix("far", 0, 3),
        ],
    )
    graph = lattice_cluster_graph(d)
    assert graph["a"] == {"b"}
    assert lattice_components(graph, set(graph)) == [["a", "b"], ["diagonal"], ["far"]]
    # Reusing grid cells in a different explicit frame cannot join the first frame.
    framed = d.model_copy(
        update={"helices": [d.helices[0], helix("other", 0, 1, "other-frame")]}
    )
    assert lattice_cluster_graph(framed) == {"a": set(), "other": set()}


def test_disconnected_extrusion_preserves_existing_pose_and_old_orphans():
    old = ClusterRigidTransform(
        id="existing", name="Cluster 1", helix_ids=["a"], translation=[5, 6, 7]
    )
    before = Design(
        lattice_type=LatticeType.SQUARE,
        helices=[helix("a", 0, 0), helix("orphan", 20, 0)],
        cluster_transforms=[old],
    )
    after = before.model_copy(
        update={
            "helices": before.helices
            + [
                helix("b", 0, 1),
                helix("c", 0, 2),
                helix("d", 10, 0),
                helix("e", 10, 1),
                helix("single", 30, 0),
                helix("__lnk__x", 40, 0),
            ]
        }
    )
    result = reconcile_cluster_membership(
        before, after, MutationReport(cluster_disconnected=True)
    )
    assert result.cluster_transforms[0].helix_ids == ["a", "b", "c"]
    assert result.cluster_transforms[0].translation == old.translation
    assert [c.helix_ids for c in result.cluster_transforms[1:]] == [
        ["d", "e"],
        ["single"],
    ]
    assert old.helix_ids == ["a"]
    assert [
        c.id
        for c in reconcile_cluster_membership(
            before, after, MutationReport(cluster_disconnected=True)
        ).cluster_transforms
    ] == [c.id for c in result.cluster_transforms]


def test_explicit_orphans_and_parents_are_authoritative():
    c = ClusterRigidTransform(id="c", helix_ids=["a"])
    before = Design(
        lattice_type=LatticeType.SQUARE,
        helices=[helix("a", 0, 0)],
        cluster_transforms=[c],
    )
    after = before.model_copy(
        update={
            "helices": before.helices + [helix("orphan", 0, 1), helix("child", 9, 0)]
        }
    )
    result = reconcile_cluster_membership(
        before,
        after,
        MutationReport(
            cluster_disconnected=True, new_helix_origins={"orphan": None, "child": "a"}
        ),
    )
    assert len(result.cluster_transforms) == 1
    assert result.cluster_transforms[0].helix_ids == ["a", "child"]


def test_repair_additive_idempotent_and_works_without_existing_clusters():
    c = ClusterRigidTransform(
        id="c",
        name="Cluster 1",
        helix_ids=["a"],
        pivot=[1, 2, 3],
        translation=[4, 5, 6],
    )
    d = Design(
        lattice_type=LatticeType.SQUARE,
        helices=[helix("a", 0, 0), helix("b", 8, 0), helix("c", 8, 1)],
        cluster_transforms=[c],
    )
    result = cluster_unassigned_components(d)
    assert result.cluster_transforms[0] == c
    assert result.cluster_transforms[1].helix_ids == ["b", "c"]
    assert cluster_unassigned_components(result) is result
    empty = d.model_copy(update={"cluster_transforms": []})
    assert [
        c.helix_ids for c in cluster_unassigned_components(empty).cluster_transforms
    ] == [["a"], ["b", "c"]]


def test_repair_excludes_reference_and_domain_only_membership():
    from backend.core.models import Domain, DomainRef, Strand, Direction

    ref = Strand(
        id="ref",
        is_reference=True,
        domains=[
            Domain(
                helix_id="reference", start_bp=0, end_bp=10, direction=Direction.FORWARD
            )
        ],
    )
    active = Strand(
        id="active",
        domains=[
            Domain(
                helix_id="claimed", start_bp=0, end_bp=10, direction=Direction.FORWARD
            )
        ],
    )
    c = ClusterRigidTransform(
        id="domain-only", domain_ids=[DomainRef(strand_id="active", domain_index=0)]
    )
    d = Design(
        lattice_type=LatticeType.SQUARE,
        helices=[
            helix("reference", 0, 0),
            helix("claimed", 0, 1),
            helix("__lnk__bridge", 5, 0),
            helix("new", 9, 0),
        ],
        strands=[ref, active],
        cluster_transforms=[c],
    )
    result = cluster_unassigned_components(d)
    assert [c.helix_ids for c in result.cluster_transforms] == [[], ["new"]]
    assert result.cluster_transforms[0] == c


def test_multi_scaffold_detection_keeps_disconnected_unscaffolded_component():
    from backend.core.cluster_autodetect import _geometry_clusters_multi_scaffold
    from backend.core.models import Domain, Strand, StrandType, Direction

    hs = (
        [helix(f"h{i}", 0, i) for i in range(3)]
        + [helix(f"h{i}", 10, i) for i in range(3, 6)]
        + [helix("orphan", 30, 0)]
    )
    strands = [
        Strand(
            id=f"s{j}",
            strand_type=StrandType.SCAFFOLD,
            domains=[
                Domain(
                    helix_id=f"h{i}", start_bp=0, end_bp=10, direction=Direction.FORWARD
                )
                for i in range(j * 3, j * 3 + 3)
            ],
        )
        for j in range(2)
    ]
    d = Design(lattice_type=LatticeType.SQUARE, helices=hs, strands=strands)
    clusters = _geometry_clusters_multi_scaffold(d).cluster_transforms
    assert [c.helix_ids for c in clusters] == [
        ["h0", "h1", "h2"],
        ["h3", "h4", "h5"],
        ["orphan"],
    ]


def test_component_inherits_through_new_explicit_parent():
    old = ClusterRigidTransform(id="old", helix_ids=["a"])
    before = Design(
        lattice_type=LatticeType.SQUARE,
        helices=[helix("a", 0, 0)],
        cluster_transforms=[old],
    )
    after = before.copy_with(
        helices=before.helices + [helix("continuation", 0, 0), helix("neighbor", 0, 1)]
    )
    # The report remains authoritative even with no direct old adjacency.
    after.helices[0] = helix("a", 20, 20)
    result = reconcile_cluster_membership(
        before,
        after,
        MutationReport(
            cluster_disconnected=True, new_helix_origins={"continuation": "a"}
        ),
    )
    assert len(result.cluster_transforms) == 1
    assert result.cluster_transforms[0].helix_ids == ["a", "continuation", "neighbor"]


def test_history_repair_only_reconstructs_removed_identity_auto_groups():
    from backend.core.cluster_components import repair_removed_auto_cluster_membership

    c = ClusterRigidTransform(id="removed", auto_created=True, helix_ids=["a", "b"])
    before = Design(
        lattice_type=LatticeType.SQUARE,
        helices=[helix("a", 0, 0), helix("b", 0, 1)],
        cluster_transforms=[c],
    )
    after = before.copy_with(helices=[before.helices[1]], cluster_transforms=[])
    repaired = repair_removed_auto_cluster_membership(before, after, {"a", "removed"})
    assert repaired.cluster_transforms[0].helix_ids == ["b"]
    posed = before.copy_with(
        cluster_transforms=[c.model_copy(update={"translation": [10, 0, 0]})]
    )
    assert (
        repair_removed_auto_cluster_membership(posed, after, {"a", "removed"}) is after
    )


def test_claimed_neighbor_wins_over_unassigned_neighbor_without_merging():
    c = ClusterRigidTransform(id="c", helix_ids=["z-claimed"])
    before = Design(
        lattice_type=LatticeType.SQUARE,
        helices=[helix("a-orphan", 0, 0), helix("z-claimed", 0, 2)],
        cluster_transforms=[c],
    )
    after = before.copy_with(helices=before.helices + [helix("new", 0, 1)])
    result = reconcile_cluster_membership(
        before, after, MutationReport(cluster_disconnected=True)
    )
    assert len(result.cluster_transforms) == 1
    assert result.cluster_transforms[0].helix_ids == ["z-claimed", "new"]
