"""Join snapshot poses must remain synchronized with native feature history."""

import pytest

from backend.api import state
from backend.api.crud import _seek_feature_log
from backend.core.lattice import make_bundle_design
from backend.core.models import ClusterOpLogEntry, ClusterRigidTransform, SnapshotLogEntry


def posed(design, cid, xyz):
    return design.copy_with(cluster_transforms=[
        c.model_copy(update={"translation": list(xyz)}) if c.id == cid else c
        for c in design.cluster_transforms
    ])


def pose(design, cid):
    return next(c for c in design.cluster_transforms if c.id == cid).translation


def baseline():
    design = make_bundle_design([(0, 0), (0, 1), (0, 2)], 24)
    return design.copy_with(cluster_transforms=[
        ClusterRigidTransform(id=f"part{i}", helix_ids=[h.id],
                              translation=[32.0 * i, 4.0 * i, 0.0],
                              pivot=[1.0, 2.0, 3.0])
        for i, h in enumerate(design.helices)
    ])


def join_entry(before, after, cid="part1"):
    pre, pre_size = state.encode_design_snapshot(before)
    post, post_size = state.encode_design_snapshot(after)
    return SnapshotLogEntry(op_kind="cluster-join", label="Join",
                            params={"second": {"cluster_id": cid}},
                            design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
                            post_state_gz_b64=post, post_state_size_bytes=post_size)


def move_entry(design, cid="part1"):
    cluster = next(c for c in design.cluster_transforms if c.id == cid)
    return ClusterOpLogEntry(cluster_id=cid, translation=cluster.translation,
                             rotation=cluster.rotation, pivot=cluster.pivot)


@pytest.mark.parametrize("optimized", [False, True])
def test_join_seek_retains_imported_pre_pose_and_later_manual_pose(optimized):
    before = baseline()
    joined = posed(before, "part1", [2.0, 3.0, 4.0])
    moved = posed(joined, "part1", [-5.0, 7.0, 6.0])
    log = [join_entry(before, joined), move_entry(moved)]
    live = moved.copy_with(feature_log=log)
    # These are destructive successive seeks, not fresh independent copies.
    for position, expected in [(0, joined), (-2, before), (-1, moved), (0, joined), (-1, moved)]:
        live = _seek_feature_log(live, position, optimized=optimized)
        assert live.cluster_transforms == expected.cluster_transforms


@pytest.mark.parametrize("optimized,padding", [(False, 0), (True, 34)])
def test_join_pose_wins_over_earlier_move_and_loses_to_later_move(optimized, padding):
    initial = posed(baseline(), "part1", [0.0, 0.0, 0.0])
    before = posed(initial, "part1", [17.0, 12.0, 0.0])
    joined = posed(before, "part1", [3.0, 6.0, 9.0])
    moved = posed(joined, "part1", [-2.0, -4.0, 6.0])
    prefix = [move_entry(initial, "part0") for _ in range(padding)]
    log = [*prefix, move_entry(before), join_entry(before, joined), move_entry(moved)]
    live = moved.copy_with(feature_log=log)
    for position, expected in [(-1, moved), (padding + 1, joined), (padding, before),
                               (-2, initial), (padding + 1, joined), (-1, moved)]:
        live = _seek_feature_log(live, position, optimized=optimized)
        assert live.cluster_transforms == expected.cluster_transforms


def test_repeated_join_replays_each_donor_pose_chronologically():
    original = baseline()
    first = posed(original, "part1", [2.0, 3.0, 4.0])
    second = posed(first, "part2", [8.0, 9.0, 10.0])
    third = posed(second, "part1", [11.0, 12.0, 13.0])
    log = [join_entry(original, first), join_entry(first, second, "part2"),
           join_entry(second, third)]
    live = third.copy_with(feature_log=log)
    for position, expected in [(0, first), (1, second), (-1, third), (-2, original), (1, second)]:
        live = _seek_feature_log(live, position)
        assert live.cluster_transforms == expected.cluster_transforms


def test_later_topology_snapshot_does_not_discard_join_pose():
    original = baseline()
    joined = posed(original, "part1", [4.0, 5.0, 6.0])
    routed = joined.model_copy(deep=True)
    routed.strands[0].name = "manual fine edit"
    later = join_entry(joined, routed).model_copy(update={"op_kind": "auto-staple", "params": {}})
    live = routed.copy_with(feature_log=[join_entry(original, joined), later])
    live = _seek_feature_log(live, -2)
    assert live.cluster_transforms == original.cluster_transforms
    live = _seek_feature_log(live, -1)
    assert live.cluster_transforms == joined.cluster_transforms
    assert live.strands[0].name == "manual fine edit"
