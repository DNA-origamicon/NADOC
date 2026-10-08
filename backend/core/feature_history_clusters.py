"""Restore native cluster-creation entries before replaying their pose deltas."""

from backend.core.models import ClusterRigidTransform


def restore_cluster_creations(design, position):
    entries = design.feature_log
    creations = {
        e.cluster_id: (i, e)
        for i, e in enumerate(entries)
        if e.feature_type == "cluster_create"
    }
    end = len(entries) - 1 if position == -1 else position
    active = {cid: e for cid, (i, e) in creations.items() if i <= end}
    clusters = [
        c for c in design.cluster_transforms if c.id not in creations or c.id in active
    ]
    existing = {c.id for c in clusters}
    helix_ids = {h.id for h in design.helices}
    for cid, entry in active.items():
        if cid not in existing and any(h in helix_ids for h in entry.helix_ids):
            clusters.append(
                entry.cluster_snapshot
                or ClusterRigidTransform(
                    id=cid,
                    name=entry.name,
                    helix_ids=[h for h in entry.helix_ids if h in helix_ids],
                    domain_ids=entry.domain_ids,
                )
            )
    return design.copy_with(cluster_transforms=clusters)
