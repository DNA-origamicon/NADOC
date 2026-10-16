"""Unavailable dissolve recovery refuses before seeking or publishing any state.

The conservative checkpoint policy requires both bodies for every dissolve row,
even where native input replay could independently reconstruct the design.
Fixtures and recovery strings stay tiny and memory-only; no worker is needed.
"""

import pytest
from fastapi import HTTPException

from backend.api import crud, routes_clusters, routes_feature_log as routes, state
from backend.core import feature_evaluation, feature_history_clusters as history
from backend.core.models import SnapshotLogEntry
from tests.test_geometry_group_history import _create, _verified
from tests.test_geometry_group_history import document as document
from tests.test_group_dissolve_recovery import _entry, _padding, _removed, _rootless
from tests.test_group_edit_recording import _snapshot, _unchanged


def _install(design):
    state.load_design(design)
    # Exercise a real nonempty redo stack; failed seeks must not clear it.
    state.set_design(design.model_copy(deep=True))
    state.undo()
    return state.get_or_404()


def _rootless_history(*, optimized=False, missing="both", later=False, params=None):
    before = _rootless()
    after = _removed(before, "target")
    row = _entry(before, after, params=params)
    if missing in {"both", "pre"}:
        row.design_snapshot_gz_b64 = ""
    if missing in {"both", "post"}:
        row.post_state_gz_b64 = ""
    if missing == "evicted":
        # Even retained strings cannot overrule the explicit eviction flag.
        row.evicted = True
    entries = [*_padding(before, 34 if optimized else 0), row]
    if later:
        entries.append(_entry(after, after, kind="extrude-frame", params={}))
    return after.copy_with(recipe_root=None, feature_log=entries, feature_log_cursor=-1)


@pytest.mark.parametrize("optimized", [False, True], ids=["baseline", "optimized-34"])
@pytest.mark.parametrize("missing", ["both", "pre", "post", "evicted"])
def test_rootless_dissolve_with_missing_recovery_cannot_publish_a_false_earlier_cursor(
        document, monkeypatch, optimized, missing):
    monkeypatch.setattr(feature_evaluation, "optimization_enabled", lambda: optimized)
    _install(_rootless_history(optimized=optimized, missing=missing))
    before = _snapshot()
    with pytest.raises(HTTPException) as caught:
        routes.seek_features(routes.SeekFeaturesBody(position=-2))
    assert caught.value.status_code == 410
    assert caught.value.detail["code"] == "group_recovery_unavailable"
    _unchanged(before)


@pytest.mark.parametrize("optimized", [False, True], ids=["baseline", "optimized-34"])
def test_later_retained_snapshot_does_not_substitute_for_missing_dissolve_baseline(document, monkeypatch, optimized):
    monkeypatch.setattr(feature_evaluation, "optimization_enabled", lambda: optimized)
    live = _install(_rootless_history(optimized=optimized, later=True))
    assert live.feature_log[-1].design_snapshot_gz_b64 and live.feature_log[-1].post_state_gz_b64
    before = _snapshot()
    with pytest.raises(HTTPException) as caught:
        routes.seek_features(routes.SeekFeaturesBody(position=-2))
    assert caught.value.status_code == 410 and caught.value.detail["code"] == "group_recovery_unavailable"
    _unchanged(before)


def test_end_seek_also_refuses_missing_dissolve_bodies_under_the_explicit_conservative_policy(document):
    _install(_rootless_history())
    before = _snapshot()
    with pytest.raises(HTTPException) as caught:
        routes.seek_features(routes.SeekFeaturesBody(position=-1))
    assert caught.value.status_code == 410 and caught.value.detail["code"] == "group_recovery_unavailable"
    _unchanged(before)


@pytest.mark.parametrize("optimized", [False, True], ids=["baseline", "optimized-34"])
def test_implicit_pattern_rebirth_refuses_instead_of_silently_dropping_new_group(document, monkeypatch, optimized):
    monkeypatch.setattr(feature_evaluation, "optimization_enabled", lambda: optimized)
    after = _rootless_history(optimized=optimized, missing=None)
    # A saved pattern can reuse a removed wrapper ID with different members.
    # UUID freshness is not a lifetime contract; only explicit recreation is
    # supported by this compatibility reader.
    target = _rootless().cluster_transforms[2].model_copy(update={
        "name": "New pattern wrapper", "helix_ids": [after.helices[0].id]})
    reborn = after.copy_with(cluster_transforms=[*after.cluster_transforms, target])
    row = _entry(after, reborn, kind="linear-pattern", params={})
    _install(reborn.copy_with(feature_log=[*after.feature_log, row]))
    before = _snapshot()
    with pytest.raises(HTTPException) as caught:
        routes.seek_features(routes.SeekFeaturesBody(position=-1))
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "group_recovery_unsupported"
    _unchanged(before)


@pytest.mark.parametrize("params", [
    {"_proof_version": True, "cluster_ids": ["target"]},
    {"_proof_version": 2, "cluster_ids": ["target"]},
    {"_proof_version": 1, "cluster_ids": ["target"], "candidate": {}},
    {"_proof_version": 1, "cluster_ids": ["target"], "_generated_scope": {}},
], ids=["boolean-version", "future-version", "extra-input", "generated-scope"])
def test_malformed_dissolve_metadata_is_typed_before_any_recovery_decode(document, monkeypatch, params):
    _install(_rootless_history(missing=None, params=params))
    before = _snapshot()

    def unexpected(*_args, **_kwargs):
        pytest.fail("Malformed dissolution metadata must refuse before snapshot decode")

    monkeypatch.setattr(state, "decode_design_snapshot", unexpected)
    with pytest.raises(HTTPException) as caught:
        routes.seek_features(routes.SeekFeaturesBody(position=-2))
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "group_recovery_invalid"
    _unchanged(before)


def test_group_recovery_budget_is_a_typed_atomic_refusal(document, monkeypatch):
    _install(_rootless_history(missing=None))
    before = _snapshot()
    monkeypatch.setattr(history, "MAX_ITEMS", 0)
    monkeypatch.setattr(state, "decode_design_snapshot", lambda *_a: pytest.fail("Budget refusal must precede decode"))
    with pytest.raises(HTTPException) as caught:
        routes.seek_features(routes.SeekFeaturesBody(position=-2))
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "group_recovery_invalid"
    _unchanged(before)


@pytest.mark.parametrize("reader", ["preview", "geometry-batch"])
def test_readonly_seek_consumers_share_the_unavailable_recovery_guard(document, reader):
    _install(_rootless_history())
    before = _snapshot()
    with pytest.raises(HTTPException) as caught:
        if reader == "preview":
            routes.preview_features(routes.SeekFeaturesBody(position=-2))
        else:
            routes.geometry_batch(routes.GeometryBatchBody(positions=[-2]))
    assert caught.value.status_code == 410 and caught.value.detail["code"] == "group_recovery_unavailable"
    _unchanged(before)


@pytest.mark.parametrize("optimized", [False, True], ids=["baseline", "optimized-34"])
def test_plain_evicted_history_retains_legacy_seek_behavior(document, monkeypatch, optimized):
    monkeypatch.setattr(feature_evaluation, "optimization_enabled", lambda: optimized)
    live = _rootless()
    row = SnapshotLogEntry(op_kind="extrude-frame", label="Legacy evicted extrusion", params={}, evicted=True)
    live = _install(live.copy_with(feature_log=[*_padding(live, 34 if optimized else 0), row]))
    before, depth, revision = live.model_dump(mode="json"), state.undo_depth(), state.revision()
    routes.seek_features(routes.SeekFeaturesBody(position=-2))
    result = state.get_or_404()
    assert result.feature_log_cursor == -2
    assert result.cluster_transforms == live.cluster_transforms
    assert state.undo_depth() == depth + 1 and state.revision() == revision + 1
    assert live.model_dump(mode="json") == before


def test_conservative_recovery_refusal_does_not_disable_independent_native_proof(document):
    grouped, group, _ = _create(document)
    routes_clusters.delete_cluster(group.id)
    live = state.get_or_404().model_copy(deep=True)
    row = live.feature_log[-1]
    row.evicted = True
    row.design_snapshot_gz_b64 = row.post_state_gz_b64 = ""
    live = _install(live)
    before = _snapshot()
    with pytest.raises(HTTPException) as caught:
        crud._seek_feature_log(live, -1)
    assert caught.value.status_code == 410
    _verified(live)
    _unchanged(before)
