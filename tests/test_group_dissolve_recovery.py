"""Chronological group membership survives repeated recovery seeks.

All snapshots are tiny in-memory strings. Recovery is not a proof oracle: the
ordinary native-route case separately verifies input replay with poisoned
recovery payloads. No files, solver or worker lifecycle is used here.
"""

import pytest

from backend.api import crud, routes_clusters as routes, state
from backend.core import feature_history_clusters as history
from backend.core.lattice import make_bundle_design
from backend.core.models import ClusterCreateLogEntry, ClusterOpLogEntry, ClusterRigidTransform, Design, SnapshotLogEntry
from tests.test_geometry_group_history import _create, _verified
from tests.test_geometry_group_history import document as document


def _clusters(design):
    return [group.model_dump(mode="json") for group in design.cluster_transforms]


def _entry(before, after, kind="cluster-dissolve", params=None):
    pre, pre_size = state.encode_design_snapshot(before)
    post, post_size = state.encode_design_snapshot(after)
    return SnapshotLogEntry(op_kind=kind, label=kind,
        params=params if params is not None else {"_proof_version": 1, "cluster_ids": ["target"]},
        design_snapshot_gz_b64=pre, snapshot_size_bytes=pre_size,
        post_state_gz_b64=post, post_state_size_bytes=post_size)


def _rootless():
    design = make_bundle_design([(0, 0), (0, 1)], length_bp=6)
    return design.copy_with(cluster_transforms=[
        ClusterRigidTransform(id="left", name="Left", helix_ids=[design.helices[0].id]),
        ClusterRigidTransform(id="empty", name="Imported empty", color="#abcdef"),
        ClusterRigidTransform(id="target", name="Imported member", helix_ids=[design.helices[1].id]),
        ClusterRigidTransform(id="right", name="Right"),
    ])


def _removed(design, *identities):
    selected = set(identities)
    return design.copy_with(cluster_transforms=[group for group in design.cluster_transforms if group.id not in selected])


def _creation(group, version=2):
    return ClusterCreateLogEntry(proof_version=version, cluster_id=group.id, name=group.name,
        helix_ids=group.helix_ids, domain_ids=group.domain_ids, cluster_snapshot=group)


def _padding(design, count):
    group = design.cluster_transforms[0]
    return [ClusterOpLogEntry(proof_version=1, cluster_id=group.id, translation=list(group.translation),
        rotation=list(group.rotation), pivot=list(group.pivot)) for _ in range(count)]


def test_snapshot_restores_only_dissolution_targets_in_original_order_without_decode(monkeypatch):
    before = _rootless()
    after = _removed(before, "empty", "target")
    row = _entry(before, after, params={"_proof_version": 1, "cluster_ids": ["empty", "target"]})
    left = after.cluster_transforms[0].model_copy(update={"name": "Current unaffected label"})
    live = after.copy_with(cluster_transforms=[left, after.cluster_transforms[1]], feature_log=[row])
    original = live.model_dump(mode="json")
    snapshot = before.model_dump(mode="json")

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Selected field restoration must not decode another snapshot")

    monkeypatch.setattr(state, "decode_design_snapshot", unexpected)
    result = history.restore_dissolve_fields(live, before)
    assert [group.id for group in result.cluster_transforms] == ["left", "empty", "target", "right"]
    assert result.cluster_transforms[0] is left
    assert result.cluster_transforms[1:3] == before.cluster_transforms[1:3]
    assert result.cluster_transforms[-1] is live.cluster_transforms[-1]
    assert result.helices is live.helices and result.strands is live.strands
    assert live.model_dump(mode="json") == original
    assert before.model_dump(mode="json") == snapshot
    assert _clusters(history.restore_dissolve_fields(result, after)) == _clusters(live)


@pytest.mark.parametrize("optimized,padding", [(False, 0), (True, 34)], ids=["ordinary", "optimized-34"])
def test_imported_and_empty_groups_roundtrip_repeated_backward_forward_seek(optimized, padding):
    before = _rootless()
    after = _removed(before, "empty", "target")
    row = _entry(before, after, params={"_proof_version": 1, "cluster_ids": ["empty", "target"]})
    live = after.copy_with(feature_log=[*_padding(before, padding), row])
    stored = live.model_dump_json()
    for position, expected in [(-2, before), (-1, after), (padding - 1 if padding else -2, before),
                               (-1, after), (-2, before), (-1, after)]:
        live = crud._seek_feature_log(live, position, optimized=optimized)
        assert _clusters(live) == _clusters(expected)
        live = Design.from_json(live.model_dump_json())
        assert _clusters(live) == _clusters(expected)
    assert len(live.feature_log) == padding + 1
    assert live.recipe_root is None
    assert stored == after.copy_with(feature_log=live.feature_log).model_dump_json()


@pytest.mark.parametrize("optimized", [False, True])
def test_ordinary_native_create_dissolve_seek_and_cold_replay(document, optimized):
    grouped, group, _ = _create(document)
    before = _clusters(grouped)
    routes.delete_cluster(group.id)
    live = state.get_or_404()
    assert live.feature_log[-1].op_kind == "cluster-dissolve"
    assert live.feature_log[-1].params == {"_proof_version": 1, "cluster_ids": [group.id]}
    after = _clusters(live)
    _verified(live)
    for position, expected in [(1, before), (-1, after), (1, before), (-1, after)]:
        live = crud._seek_feature_log(live, position, optimized=optimized)
        assert _clusters(live) == expected
        live = Design.from_json(live.model_dump_json())
    _verified(live)


@pytest.mark.parametrize("version", [1, 2])
def test_creation_restorer_never_resurrects_an_active_dissolution(version):
    before = _rootless()
    group = before.cluster_transforms[2]
    after = _removed(before, "target")
    live = after.copy_with(feature_log=[_creation(group, version), _entry(before, after)])
    assert "target" not in {c.id for c in history.restore_cluster_creations(live, -1).cluster_transforms}
    restored = history.restore_cluster_creations(live, 0)
    assert next(c for c in restored.cluster_transforms if c.id == "target") == group


def test_later_same_identity_creation_clears_tombstone_and_uses_active_definition():
    before = _rootless()
    first = before.cluster_transforms[2]
    second = first.model_copy(update={"name": "Recreated group", "color": "#123456", "helix_ids": []})
    after = _removed(before, "target")
    live = after.copy_with(feature_log=[_creation(first), _entry(before, after), _creation(second)])
    for position, expected in [(0, first), (1, None), (-1, second), (0, first), (-1, second)]:
        live = history.restore_cluster_creations(live, position)
        live = history.apply_cluster_dissolutions(live, position)
        found = [c for c in live.cluster_transforms if c.id == "target"]
        assert found == ([] if expected is None else [expected])


@pytest.mark.parametrize("producer", ["create", "linear-pattern", "cluster-join"])
@pytest.mark.parametrize("optimized,padding", [(False, 0), (True, 34)], ids=["ordinary", "optimized-34"])
def test_later_overlay_restorers_cannot_resurrect_dissolved_group(producer, optimized, padding):
    before = _rootless()
    target = before.cluster_transforms[2]
    without = _removed(before, "target")
    if producer == "create":
        creation = _creation(target)
    else:
        creation = _entry(without if producer == "linear-pattern" else before, before,
            kind=producer, params={"second": {"cluster_id": "target"}} if producer == "cluster-join" else {})
    prefix = _padding(before, padding)
    live = without.copy_with(feature_log=[*prefix, creation, _entry(before, without)])
    for position, visible in [(-1, False), (padding, True), (-1, False), (padding, True), (-1, False)]:
        live = crud._seek_feature_log(live, position, optimized=optimized)
        assert ("target" in {c.id for c in live.cluster_transforms}) is visible
    assert live.cluster_transforms == without.cluster_transforms


def test_final_tombstone_filter_is_nondeleting_before_history_and_payload_independent(monkeypatch):
    design = _rootless()
    row = SnapshotLogEntry(op_kind="cluster-dissolve", label="Dissolve",
        params={"_proof_version": 1, "cluster_ids": ["target"]},
        design_snapshot_gz_b64="not decoded", post_state_gz_b64="not decoded")
    design = design.copy_with(feature_log=[row])

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Lifecycle input scan must not decode recovery payloads")

    monkeypatch.setattr(state, "decode_design_snapshot", unexpected)
    assert history.apply_cluster_dissolutions(design, -2) is design
    assert history.apply_cluster_dissolutions(design, -1).cluster_transforms == _removed(design, "target").cluster_transforms


def test_unrelated_history_preserves_existing_fast_noop_path():
    design = _rootless().copy_with(feature_log=[])
    assert history.restore_dissolve_fields(design, _removed(design, "target")) is design
    assert history.apply_cluster_dissolutions(design, -1) is design


def test_long_unrelated_history_retains_legacy_recovery_without_new_inventory_admission(monkeypatch):
    design = _rootless()
    target = design.cluster_transforms[2]
    entries = [*_padding(design, 2_001), _creation(target)]
    design = _removed(design, "target").copy_with(feature_log=entries)

    def unexpected(*_args, **_kwargs):
        raise AssertionError("Unrelated histories must not enter dissolution inventory admission")

    monkeypatch.setattr(history, "_lifecycle", unexpected)
    monkeypatch.setattr(history, "_records", unexpected)
    assert history.restore_dissolve_fields(design, _rootless()) is design
    assert history.apply_cluster_dissolutions(design, -1) is design
    restored = history.restore_cluster_creations(design, -1)
    assert restored.cluster_transforms == [*design.cluster_transforms, target]
    assert history.restore_cluster_creations(restored, -2).cluster_transforms == design.cluster_transforms


def test_generator_annotation_does_not_change_dissolution_recovery_inputs():
    design = _rootless()
    after = _removed(design, "target")
    row = _entry(design, after, params={"_proof_version": 1, "cluster_ids": ["target"],
                                      "_generator": {"version": 2, "label": "Attribution only"}})
    live = after.copy_with(feature_log=[row])
    restored = history.restore_dissolve_fields(live, design)
    assert _clusters(restored) == _clusters(design)
    assert _clusters(history.apply_cluster_dissolutions(restored, -1)) == _clusters(after)


def test_lifecycle_record_limit_refuses_before_reading_payloads(monkeypatch):
    design = _rootless()
    row = SnapshotLogEntry(op_kind="cluster-dissolve", label="Dissolve",
        params={"_proof_version": 1, "cluster_ids": ["target"]})
    design = design.copy_with(feature_log=[row, row.model_copy(update={"id": "second-row"})])
    monkeypatch.setattr(history, "MAX_HISTORY_ENTRIES", 1, raising=False)
    with pytest.raises(ValueError, match="limit|allowance|budget"):
        history.apply_cluster_dissolutions(design, -1)


@pytest.mark.parametrize("params", [
    {"_proof_version": True, "cluster_ids": ["target"]},
    {"_proof_version": 2, "cluster_ids": ["target"]},
    {"_proof_version": 1, "cluster_ids": ["target"], "candidate": {}},
    {"_proof_version": 1, "cluster_ids": ["target"], "_generated_scope": {}},
], ids=["boolean-version", "future-version", "unknown-input", "generated-scope"])
def test_malformed_dissolution_refuses_even_when_future_instead_of_silently_ignoring(params):
    design = _rootless()
    design = design.copy_with(feature_log=[SnapshotLogEntry(
        op_kind="cluster-dissolve", label="Malformed", params=params)])
    before = design.model_dump(mode="json")
    with pytest.raises(ValueError):
        history.apply_cluster_dissolutions(design, -2)
    assert design.model_dump(mode="json") == before


def test_snapshot_merge_preserves_all_untouched_order_and_extra_groups():
    before = _rootless()
    after = _removed(before, "empty", "target")
    extra = ClusterRigidTransform(id="extra", name="Unrelated current group")
    row = _entry(before, after, params={"_proof_version": 1, "cluster_ids": ["empty", "target"]})
    live = after.copy_with(cluster_transforms=[after.cluster_transforms[1], extra, after.cluster_transforms[0]],
                           feature_log=[row])
    result = history.restore_dissolve_fields(live, before)
    assert [c.id for c in result.cluster_transforms] == ["empty", "target", "right", "extra", "left"]
    assert [c for c in result.cluster_transforms if c.id not in {"empty", "target"}] == live.cluster_transforms
    assert len({c.id for c in result.cluster_transforms}) == len(result.cluster_transforms)


def _replace_group(design, group):
    return design.copy_with(cluster_transforms=[group if c.id == group.id else c for c in design.cluster_transforms])


def _move(group):
    return ClusterOpLogEntry(proof_version=1, cluster_id=group.id, translation=list(group.translation),
                             rotation=list(group.rotation), pivot=list(group.pivot))


@pytest.mark.parametrize("optimized,padding", [(False, 0), (True, 34)], ids=["ordinary", "optimized-34"])
def test_native_recreated_identity_keeps_new_pose_across_full_seek_reload_and_replay(document, optimized, padding):
    from backend.api.part_proof_commands import execute
    from backend.core.part_overlay_commands import command_input

    grouped, first, _ = _create(document)
    routes.update_cluster(first.id, routes.PatchClusterBody(translation=[2, 3, 4], commit=True))
    routes.update_cluster(first.id, routes.PatchClusterBody(translation=[0, 0, 0], commit=True))
    reset = state.get_or_404()
    routes.delete_cluster(first.id)
    dissolved = state.get_or_404()
    second = first.model_copy(update={"name": "Recreated", "translation": [7.0, 8.0, 9.0],
                                      "rotation": [0.0, 0.0, 1.0, 0.0], "pivot": [1.0, 2.0, 3.0]})
    recreate = _creation(second)
    kind, params = command_input(recreate)
    recreated = execute(kind, dissolved, params)
    # The public creator allocates a fresh ID. This is a real saved native input
    # reusing an explicitly dissolved identity, with no UUID monkeypatch.
    prefix = list(dissolved.feature_log)
    before_recreation = len(prefix) - 1
    prefix.extend(_padding(dissolved, padding))
    recreation_index = len(prefix)
    recreated = recreated.copy_with(feature_log=[*prefix, recreate])
    moved_group = second.model_copy(update={"translation": [-3.0, 2.0, 1.0]})
    moved_row = _move(moved_group)
    kind, params = command_input(moved_row)
    moved = execute(kind, recreated, params)
    live = moved.copy_with(feature_log=[*recreated.feature_log, moved_row])
    _verified(live)
    expected_recreated, expected_moved = _clusters(recreated), _clusters(live)
    for position, expected in [
        (recreation_index, expected_recreated), (-1, expected_moved),
        (before_recreation, _clusters(dissolved)), (recreation_index, expected_recreated),
        (len(grouped.feature_log) + 1, _clusters(reset)), (-1, expected_moved),
    ]:
        live = crud._seek_feature_log(live, position, optimized=optimized)
        assert _clusters(live) == expected
        live = Design.from_json(live.model_dump_json())
    _verified(live)


@pytest.mark.parametrize("optimized,padding", [(False, 0), (True, 34)], ids=["ordinary", "optimized-34"])
@pytest.mark.parametrize("old_move", [False, True], ids=["join-only", "join-and-reset"])
def test_recreated_identity_cannot_inherit_old_join_pose_or_future_join_baseline(optimized, padding, old_move):
    before = _rootless()
    first = before.cluster_transforms[2]
    joined_first = first.model_copy(update={"translation": [4.0, 5.0, 6.0], "pivot": [2.0, 1.0, 0.0]})
    joined = _replace_group(before, joined_first)
    reset = _replace_group(joined, first)
    absent = _removed(reset, "target")
    second = first.model_copy(update={"name": "New lifetime", "translation": [12.0, 13.0, 14.0],
                                      "rotation": [0.0, 0.0, 1.0, 0.0], "pivot": [3.0, 2.0, 1.0]})
    recreated = absent.copy_with(cluster_transforms=[*absent.cluster_transforms, second])
    joined_second = second.model_copy(update={"translation": [-8.0, -7.0, -6.0]})
    rejoined = _replace_group(recreated, joined_second)
    entries = [*_padding(before, padding), _creation(first),
               _entry(before, joined, kind="cluster-join", params={"second": {"cluster_id": "target"}})]
    old_join_index = len(entries) - 1
    if old_move:
        entries.append(_move(first))
    entries.append(_entry(reset if old_move else joined, absent))
    dissolve_index = len(entries) - 1
    entries.append(_creation(second))
    recreate_index = len(entries) - 1
    entries.append(_entry(recreated, rejoined, kind="cluster-join", params={"second": {"cluster_id": "target"}}))
    live = rejoined.copy_with(feature_log=entries)
    for position, expected in [
        (recreate_index, second), (-1, joined_second), (old_join_index, joined_first),
        (dissolve_index, None), (recreate_index, second), (-1, joined_second),
    ]:
        live = crud._seek_feature_log(live, position, optimized=optimized)
        selected = [c for c in live.cluster_transforms if c.id == "target"]
        assert selected == ([] if expected is None else [expected])
        assert [c for c in live.cluster_transforms if c.id != "target"] == absent.cluster_transforms
        live = Design.from_json(live.model_dump_json())


@pytest.mark.parametrize("optimized,padding", [(False, 0), (True, 34)], ids=["ordinary", "optimized-34"])
def test_pattern_created_pose_survives_seek_before_reset_and_dissolution(optimized, padding):
    from backend.core.circular_pattern import pattern_history_overlays

    source = _rootless()
    original = source.cluster_transforms[2]
    before = _removed(source, "target")
    patterned_group = original.model_copy(update={"translation": [11.0, 12.0, 13.0],
                                                "rotation": [0.0, 0.0, 1.0, 0.0], "pivot": [2.0, 3.0, 4.0]})
    patterned = before.copy_with(cluster_transforms=[*before.cluster_transforms, patterned_group])
    reset_group = patterned_group.model_copy(update={"translation": [0.0, 0.0, 0.0],
                                                    "rotation": [0.0, 0.0, 0.0, 1.0]})
    reset = _replace_group(patterned, reset_group)
    entries = [*_padding(before, padding),
               _entry(before, patterned, kind="linear-pattern", params={}),
               _move(reset_group), _entry(reset, before)]
    live = before.copy_with(feature_log=entries)
    for position, expected in [(padding, patterned), (padding + 1, reset), (-1, before),
                               (padding, patterned), (-1, before), (padding + 1, reset)]:
        live = crud._seek_feature_log(live, position, optimized=optimized)
        assert _clusters(live) == _clusters(expected)
        live = Design.from_json(live.model_dump_json())

    # Once explicitly recreated, the old pattern must no longer own either the
    # selected group's reset baseline or its position in the group collection.
    recreated_group = original.model_copy(update={"name": "Recreated after pattern", "translation": [21.0, 22.0, 23.0]})
    recreated = before.copy_with(cluster_transforms=[*before.cluster_transforms, recreated_group],
                                 feature_log=[*entries, _creation(recreated_group)])
    windows = history.group_pose_windows(recreated, -1)
    groups, _, baselines = pattern_history_overlays(recreated, state.decode_design_snapshot, pose_windows=windows)
    assert groups == recreated.cluster_transforms
    assert "target" not in baselines
    live = live.copy_with(feature_log=recreated.feature_log)
    for position, expected in [(-1, recreated), (padding, patterned), (-1, recreated)]:
        live = crud._seek_feature_log(live, position, optimized=optimized)
        assert _clusters(live) == _clusters(expected)


@pytest.mark.parametrize("optimized,padding", [(False, 0), (True, 34)], ids=["ordinary", "optimized-34"])
def test_imported_incarnation_is_not_erased_by_future_same_id_creation(optimized, padding):
    before = _rootless()
    first = before.cluster_transforms[2]
    absent = _removed(before, "target")
    second = first.model_copy(update={"name": "Recreated imported identity", "translation": [5.0, 6.0, 7.0],
                                      "pivot": [3.0, 2.0, 1.0]})
    recreated = absent.copy_with(cluster_transforms=[*absent.cluster_transforms, second])
    live = recreated.copy_with(feature_log=[*_padding(before, padding), _entry(before, absent), _creation(second)])
    for position, expected in [(-2, before), (-1, recreated), (padding, absent),
                               (-2, before), (-1, recreated), (padding, absent)]:
        live = crud._seek_feature_log(live, position, optimized=optimized)
        assert _clusters(live) == _clusters(expected)
        live = Design.from_json(live.model_dump_json())
