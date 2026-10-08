from backend.core.feature_history_clusters import restore_cluster_creations
from backend.core.models import ClusterCreateLogEntry, ClusterRigidTransform, DomainRef
from backend.core.lattice import make_bundle_design


def test_native_cluster_creation_preserves_duplex_parent_and_ownership():
    design = make_bundle_design([(0, 0)], 21)
    helix = design.helices[0]
    child = ClusterRigidTransform(
        id="child",
        name="Duplex",
        helix_ids=[helix.id],
        domain_ids=[DomainRef(strand_id=design.strands[0].id, domain_index=0)],
        parent_cluster_id="parent",
        overhang_duplex_driver_id="overhang",
        auto_created=True,
    )
    entry = ClusterCreateLogEntry(
        cluster_id=child.id,
        name=child.name,
        helix_ids=child.helix_ids,
        domain_ids=child.domain_ids,
        cluster_snapshot=child,
    )
    design = design.copy_with(feature_log=[entry])
    assert restore_cluster_creations(design, 0).cluster_transforms == [child]
    assert (
        restore_cluster_creations(
            design.copy_with(cluster_transforms=[child]), -2
        ).cluster_transforms
        == []
    )


def test_native_generation_restores_clusters_before_original_particle_edits():
    from backend.api.crud import _topology_substitute
    from backend.core.models import SnapshotLogEntry

    original = make_bundle_design([(0, 0)], 21)
    original_cluster = ClusterRigidTransform(
        id="original", name="Original group", helix_ids=[original.helices[0].id]
    )
    original = original.copy_with(cluster_transforms=[original_cluster])
    later = original.copy_with(
        cluster_transforms=[original_cluster.model_copy(update={"id": "gen_new"})],
        feature_log=[
            SnapshotLogEntry(
                op_kind="extrude-segment",
                label="Extrude segment",
                params={"_generator": {"version": 2, "cluster_ids": ["gen_new"]}},
            )
        ],
    )
    assert _topology_substitute(later, original).cluster_transforms == [
        original_cluster
    ]
