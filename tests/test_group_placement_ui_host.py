"""The separate UI commits explicit placements atomically and saves display only."""

from copy import deepcopy

import pytest
from fastapi import HTTPException

from backend.api import part_group_organization_recording as host, state
from backend.core.models import Design
from backend.core.design_geometry import _geometry_for_design
from tests.test_group_organization_history import _verified
from tests.test_group_organization_recording import document as _document_fixture, apply, before, unchanged


document = _document_fixture


def moves(session):
    return {"placements": [{"placement_id": item.id, "fields": {
        "translation": [i + 5, 2, -3]}} for i, item in enumerate(session.design.cluster_transforms)]}


def test_multi_placement_commit_is_one_revision_undo_and_cold_replay(document):
    apply(document)
    source = document.design
    revision, depth = document.revision, len(document.history)
    candidate, _, last = apply(document, "placements-update", moves(document))
    assert len(source.cluster_transforms) >= 2
    assert document.revision == revision + 1 and len(document.history) == depth + 1
    assert candidate.group_organization is source.group_organization
    assert [p.id for p in candidate.cluster_transforms] == [p.id for p in source.cluster_transforms]
    assert len(candidate.feature_log) == len(source.feature_log) + len(source.cluster_transforms)
    assert last is candidate.feature_log[-1]
    _verified(Design.model_validate_json(candidate.model_dump_json()))
    expected = _geometry_for_design(candidate)
    restored, _ = state.undo()
    assert restored.cluster_transforms == source.cluster_transforms
    restored, _ = state.redo()
    assert _geometry_for_design(restored) == expected


@pytest.mark.parametrize("failure", ["missing-last", "duplicate", "bad-pose", "too-many", "empty"])
def test_whole_move_refuses_without_partial_history(document, failure):
    apply(document)
    inputs = moves(document)
    if failure == "missing-last":
        inputs["placements"][-1]["placement_id"] = "missing"
    elif failure == "duplicate":
        inputs["placements"].append(deepcopy(inputs["placements"][0]))
    elif failure == "bad-pose":
        inputs["placements"][-1]["fields"]["rotation"] = [0, 0, 0, 0]
    elif failure == "too-many":
        inputs["placements"] *= 65
    else:
        inputs["placements"] = []
    saved = before(document)
    with pytest.raises(HTTPException):
        apply(document, "placements-update", inputs)
    unchanged(document, saved)


def test_noop_members_do_not_create_rows_and_all_noop_retains_source(document):
    apply(document)
    inputs = {"placements": [{"placement_id": c.id, "fields": {
        "translation": list(c.translation)}} for c in document.design.cluster_transforms]}
    saved = before(document)
    assert apply(document, "placements-update", inputs)[2] is None
    unchanged(document, saved)
    inputs["placements"][-1]["fields"]["translation"] = [9, 8, 7]
    candidate, _, last = apply(document, "placements-update", inputs)
    assert len(candidate.feature_log) == len(saved[0].feature_log) + 1
    assert last.cluster_id == inputs["placements"][-1]["placement_id"]


def test_visibility_preserves_authoring_and_roundtrips_without_new_feature(document):
    apply(document)
    source = document.design
    inputs = {"visibility_state": {"hidden_base_keys": ["h:0:FORWARD"] * 2,
        "shown_base_keys": [], "hidden_cluster_ids": ["placement"]}}
    candidate, _, entry = apply(document, "visibility-update", inputs)
    assert entry is None and candidate.feature_log is source.feature_log
    assert candidate.model_dump(exclude={"visibility_state"}) == source.model_dump(exclude={"visibility_state"})
    assert candidate.visibility_state.hidden_base_keys == ["h:0:FORWARD"]
    assert not source.visibility_state.hidden_base_keys
    loaded = Design.model_validate_json(candidate.model_dump_json())
    assert loaded.visibility_state == candidate.visibility_state
    _verified(loaded)
    saved = before(document)
    assert apply(document, "visibility-update", inputs)[0] is candidate
    unchanged(document, saved)


@pytest.mark.parametrize("patch", [
    {"hidden_group_ids": ["placement"]}, {"hidden_base_keys": [1]},
    {"hidden_cluster_ids": "placement"}, {"translation": [1, 2, 3]},
])
def test_visibility_cannot_smuggle_authoring_or_new_address_grammar(document, patch):
    apply(document)
    value = {"hidden_base_keys": [], "shown_base_keys": [], "hidden_cluster_ids": [], **patch}
    saved = before(document)
    with pytest.raises(HTTPException):
        apply(document, "visibility-update", {"visibility_state": value})
    unchanged(document, saved)


@pytest.mark.parametrize("kind", ["placements-update", "visibility-update"])
def test_new_adapters_recheck_source_and_rollback_publication(document, monkeypatch, kind):
    apply(document)
    inputs = moves(document) if kind == "placements-update" else {"visibility_state": {
        "hidden_base_keys": ["h:0:FORWARD"], "shown_base_keys": [], "hidden_cluster_ids": []}}
    saved = before(document)
    def fail(_session):
        raise RuntimeError("publication failure")
    monkeypatch.setattr(state, "_bump_revision", fail)
    with pytest.raises(RuntimeError, match="publication failure"):
        apply(document, kind, inputs)
    unchanged(document, saved)


def test_multi_move_history_cap_charges_all_rows(document, monkeypatch):
    apply(document)
    monkeypatch.setattr(host, "MAX_HISTORY_ROWS", len(document.design.feature_log) + 1)
    saved = before(document)
    with pytest.raises(HTTPException) as error:
        apply(document, "placements-update", moves(document))
    assert error.value.detail["code"] == "group_capture_limit"
    unchanged(document, saved)


def test_batch_row_limit_counts_routing_children_and_visibility_reserves_no_row(document, monkeypatch):
    from backend.core.models import MinorMutationLogEntry, RoutingClusterLogEntry

    apply(document)
    # Definition-only admission fixture: the children are never evaluated here.
    document.design.feature_log.append(RoutingClusterLogEntry(children=[
        MinorMutationLogEntry(op_subtype="nick", label="Child", params={}) for _ in range(2)]))
    rows = len(document.design.feature_log) + 2
    monkeypatch.setattr(host, "MAX_HISTORY_ROWS", rows)
    saved = before(document)
    with pytest.raises(HTTPException) as error:
        apply(document, "placements-update", moves(document))
    assert error.value.detail["code"] == "group_capture_limit"
    unchanged(document, saved)
    value = {"hidden_base_keys": ["h:0:FORWARD"], "shown_base_keys": [], "hidden_cluster_ids": []}
    candidate, _, entry = apply(document, "visibility-update", {"visibility_state": value})
    assert entry is None and len(candidate.feature_log) + 2 == rows
