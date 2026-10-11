"""Replay Join's absolute poses alongside ordinary cluster move history."""

from collections.abc import Callable

from backend.core.models import ClusterRigidTransform, Design


def _pose(cluster):
    return {key: getattr(cluster, key) for key in ("translation", "rotation", "pivot")}


def restore_join_history_poses(
    design: Design,
    clusters: list[ClusterRigidTransform],
    active_count: int,
    decode_snapshot: Callable[[str], Design],
) -> list[ClusterRigidTransform]:
    """Restore Join poses without replaying a routing mutation.

    Snapshot seek owns topology; ordinary ``cluster_op`` replay owns most poses.
    Join is both. Its POST pose must win over earlier moves and lose to later
    moves. Before the first Join, retain its imported PRE pose unless an earlier
    manual move already owns the cluster's baseline/reset semantics. Copy only
    pose fields so the topology-selected cluster membership and display metadata
    remain authoritative.

    ``active_count == 0`` means seek before all features. Missing/evicted payloads
    are ignored just as in the general snapshot history evaluator.
    """
    log = design.feature_log
    baselines = {}
    joins = {}
    for index, entry in enumerate(log):
        if (
            getattr(entry, "op_kind", None) != "cluster-join"
            or entry.evicted
            or not entry.design_snapshot_gz_b64
            or not entry.post_state_gz_b64
        ):
            continue
        before = decode_snapshot(entry.design_snapshot_gz_b64)
        after = decode_snapshot(entry.post_state_gz_b64)
        previous = {c.id: c for c in before.cluster_transforms}
        # Comparing poses also supports saved joins whose request envelope differs
        # from the current API. Unchanged clusters do not acquire Join ownership.
        changed = {
            c.id: c for c in after.cluster_transforms
            if c.id in previous and _pose(c) != _pose(previous[c.id])
        }
        requested = entry.params.get("second", {}).get("cluster_id")
        if requested in previous:
            donor = next((c for c in after.cluster_transforms if c.id == requested), None)
            if donor is not None:
                changed[requested] = donor
        for cid in changed:
            baselines.setdefault(cid, (index, previous[cid]))
        joins[index] = changed

    if not baselines:
        return clusters

    poses = {}
    for cid, (first_join_index, baseline) in baselines.items():
        earlier_move = any(
            entry.feature_type == "cluster_op" and entry.cluster_id == cid
            for entry in log[:first_join_index]
        )
        if not earlier_move:
            poses[cid] = baseline
    for index, entry in enumerate(log[:active_count]):
        poses.update(joins.get(index, {}))
        if entry.feature_type == "cluster_op" and entry.cluster_id in baselines:
            poses[entry.cluster_id] = entry

    return [
        cluster.model_copy(update=_pose(poses[cluster.id]))
        if cluster.id in poses else cluster
        for cluster in clusters
    ]


def rebase_join_snapshots_after_move_delete(
    entries, cluster_id, baseline, decode_snapshot, encode_snapshot
):
    """Remove a deleted move from the PRE states of surviving Joins.

    A Join retains its authored absolute destination pose. Its PRE snapshot must
    nevertheless describe the surviving history, so reverting that Join cannot
    resurrect an earlier move whose log entry the user has deleted.
    """
    pose = baseline
    result = []
    for entry in entries:
        if entry.feature_type == "cluster_op" and entry.cluster_id == cluster_id:
            pose = entry
        if (
            getattr(entry, "op_kind", None) != "cluster-join"
            or entry.evicted
            or not entry.design_snapshot_gz_b64
            or not entry.post_state_gz_b64
        ):
            result.append(entry)
            continue
        before = decode_snapshot(entry.design_snapshot_gz_b64)
        after = decode_snapshot(entry.post_state_gz_b64)
        pre_pose = next((c for c in before.cluster_transforms if c.id == cluster_id), None)
        post_pose = next((c for c in after.cluster_transforms if c.id == cluster_id), None)
        if pre_pose is None or post_pose is None:
            result.append(entry)
            continue
        moves_cluster = (
            _pose(pre_pose) != _pose(post_pose)
            or entry.params.get("second", {}).get("cluster_id") == cluster_id
        )
        before = before.copy_with(cluster_transforms=[
            c.model_copy(update=_pose(pose)) if c.id == cluster_id else c
            for c in before.cluster_transforms
        ])
        if moves_cluster:
            pose = post_pose
        else:
            after = after.copy_with(cluster_transforms=[
                c.model_copy(update=_pose(pose)) if c.id == cluster_id else c
                for c in after.cluster_transforms
            ])
        pre, pre_size = encode_snapshot(before)
        post, post_size = encode_snapshot(after)
        result.append(entry.model_copy(update={
            "design_snapshot_gz_b64": pre, "snapshot_size_bytes": pre_size,
            "post_state_gz_b64": post, "post_state_size_bytes": post_size,
        }))
    return result
