"""Authored grouping responses must format the exact accepted candidate.

Legacy GET/bootstrap inference remains compatible, but it must not run after
an owned group transaction and silently publish a second, inferred design.
"""

import pytest

from backend.api import crud, routes_clusters as routes, state
from tests.test_geometry_group_history import document as document


def _rootless(document, *, empty=False):
    assert len(document.cluster_transforms) == 1
    group = document.cluster_transforms[0].model_copy(update={
        "auto_created": True,
        "is_default": True,
        "helix_ids": [] if empty else [helix.id for helix in document.helices],
        "domain_ids": [],
        "translation": [7.0, 0.0, 0.0],
    })
    source = document.copy_with(
        recipe_root=None, feature_log=[], cluster_transforms=[group])
    state.load_design(source)
    return source, group


def _no_inference(*_args, **_kwargs):
    raise AssertionError("Owned group responses must not infer or persist legacy membership")


def _assert_publication(source, original, depth, revision, response):
    candidate = state.get_or_404()
    assert candidate is not source
    assert source.model_dump(mode="json") == original
    assert candidate.recipe_root is None
    assert len(candidate.feature_log) == len(source.feature_log) + 1
    assert state.undo_depth() == depth + 1
    assert state.revision() == revision + 1 == response["revision"]
    assert response["design"]["cluster_transforms"] == candidate.model_dump(mode="json")["cluster_transforms"]
    assert response["design"]["feature_log"] == candidate.model_dump(mode="json")["feature_log"]
    assert state.get_or_404() is candidate
    return candidate


def test_rootless_membership_clear_returns_exact_committed_geometry_and_one_revision(document):
    source, group = _rootless(document)
    original = source.model_dump(mode="json")
    depth, revision = state.undo_depth(), state.revision()

    response = routes.update_cluster(group.id, routes.PatchClusterBody(helix_ids=[]))

    candidate = _assert_publication(source, original, depth, revision, response)
    assert [cluster.id for cluster in candidate.cluster_transforms] == [group.id]
    assert candidate.cluster_transforms[0].helix_ids == []
    assert candidate.feature_log[-1].authored_fields["helix_ids"] == []
    expected = crud._geometry_for_design(
        candidate,
        measured_positioning=crud.measured_display_placement(crud.requested_measured_positioning()),
        junction_balance=True,
    )
    assert response["nucleotides"] == expected
    undone, _ = state.undo()
    assert undone.model_dump(mode="json") == original


def test_rootless_empty_auto_group_rename_never_enters_default_inference(document, monkeypatch):
    source, group = _rootless(document, empty=True)
    original = source.model_dump(mode="json")
    depth, revision = state.undo_depth(), state.revision()
    monkeypatch.setattr(crud, "_ensure_default_cluster", _no_inference)

    response = routes.update_cluster(group.id, routes.PatchClusterBody(name="Intentionally empty"))

    candidate = _assert_publication(source, original, depth, revision, response)
    assert candidate.cluster_transforms[0].helix_ids == []
    assert candidate.cluster_transforms[0].name == "Intentionally empty"
    assert "nucleotides" not in response


def test_rootless_group_creation_never_enters_response_default_inference(document, monkeypatch):
    source, group = _rootless(document)
    original = source.model_dump(mode="json")
    depth, revision = state.undo_depth(), state.revision()
    monkeypatch.setattr(crud, "_ensure_default_cluster", _no_inference)

    response = routes.add_cluster(routes.AddClusterBody(
        name="New authored group", helix_ids=[source.helices[0].id]))

    candidate = _assert_publication(source, original, depth, revision, response)
    assert candidate.cluster_transforms[0].id == group.id
    assert candidate.cluster_transforms[-1].name == "New authored group"
    assert candidate.feature_log[-1].proof_version == 2


def test_rootless_membership_skip_geometry_still_opts_out_of_inference(document, monkeypatch):
    source, group = _rootless(document)
    original = source.model_dump(mode="json")
    depth, revision = state.undo_depth(), state.revision()
    monkeypatch.setattr(crud, "should_skip_geometry", lambda: True)
    monkeypatch.setattr(crud, "_ensure_default_cluster", _no_inference)
    monkeypatch.setattr(crud, "_geometry_for_design", _no_inference)

    response = routes.update_cluster(group.id, routes.PatchClusterBody(helix_ids=[]))

    candidate = _assert_publication(source, original, depth, revision, response)
    assert candidate.cluster_transforms[0].helix_ids == []
    assert not {"nucleotides", "helix_axes", "nucleotides_compact"} & response.keys()


@pytest.mark.parametrize("mode", ["full", "compact", "partial", "skip"])
def test_geometry_helper_forwards_explicit_no_inference_in_every_response_branch(
        document, monkeypatch, mode):
    source, _ = _rootless(document, empty=True)
    original = source.model_dump(mode="json")
    revision, depth = state.revision(), state.undo_depth()
    report = state.validate_design(source)
    monkeypatch.setattr(crud, "_ensure_default_cluster", _no_inference)
    monkeypatch.setattr(crud, "should_skip_geometry", lambda: mode == "skip")

    response = crud._design_response_with_geometry(
        source, report,
        [source.helices[0].id] if mode == "partial" else None,
        compact_deformed=mode == "compact", normalize_legacy=False,
    )

    assert response["design"]["cluster_transforms"] == original["cluster_transforms"]
    assert state.get_or_404() is source
    assert source.model_dump(mode="json") == original
    assert state.revision() == revision and state.undo_depth() == depth


def test_geometry_helper_retains_existing_legacy_inference_default(document, monkeypatch):
    source, _ = _rootless(document, empty=True)
    original = source.model_dump(mode="json")
    revision, depth = state.revision(), state.undo_depth()
    monkeypatch.setattr(crud, "should_skip_geometry", lambda: True)

    response = crud._design_response_with_geometry(source, state.validate_design(source))

    current = state.get_or_404()
    assert current is not source
    assert any(group.helix_ids or group.domain_ids for group in current.cluster_transforms)
    assert response["design"]["cluster_transforms"] == current.model_dump(mode="json")["cluster_transforms"]
    assert source.model_dump(mode="json") == original
    assert state.revision() == revision + 1
    assert state.undo_depth() == depth
