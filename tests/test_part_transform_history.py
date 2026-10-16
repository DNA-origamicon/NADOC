"""Real recipe edits keep transform targets, suffixes and publication coherent."""

from copy import deepcopy

import pytest
from fastapi import HTTPException

from backend.api import state
from backend.api.crud import EditFeatureBody, edit_feature
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_history_verification import verify_current_part
from backend.core import models as m
from backend.core.part_overlay_commands import command_input
from tests.test_part_deformation_preview import _append, authoring
from tests.test_part_transform_preview import FEATURE, snapshot, source_recipe


@pytest.fixture(autouse=True)
def document():
    token = set_current_doc("transform-history-checkpoint")
    try:
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def install(source):
    state.set_design(source)
    state.clear_history()
    return next(i for i, row in enumerate(source.feature_log) if row.id == FEATURE)


@pytest.mark.parametrize("kind", ["cluster_op", "nucleotide-transform", "nucleotide-transform-batch"])
def test_complete_native_edit_rebuilds_suffix_and_survives_undo_reload_without_recovery(kind, monkeypatch):
    source = source_recipe(kind)
    index = install(source)
    ids = [row.id for row in source.feature_log]
    selected = source.feature_log[index]
    patch = {"translation": [8, -3, 2], "pivot": [1, 2, 3], "rotation": [0, 0, 1, 0]}
    if kind.endswith("-batch"):
        patch = {"transforms": [{**selected.params["transforms"][0], **patch}]}
    before = authoring(source)
    with monkeypatch.context() as checks:
        checks.setattr(state, "decode_design_snapshot", lambda *_: pytest.fail("read poisoned recovery"))
        edit_feature(index, EditFeatureBody(params=patch))
    candidate = state.get_or_404()
    assert [row.id for row in candidate.feature_log] == ids
    assert len(candidate.helices) == len(source.helices)
    assert state.undo_depth() == 1
    assert verify_current_part()["status"] == "verified"
    assert authoring(candidate) != before
    restored = m.Design.model_validate_json(candidate.model_dump_json())
    assert authoring(restored) == authoring(candidate)
    state.undo()
    assert authoring(state.get_or_404()) == before
    state.redo()
    assert authoring(state.get_or_404()) == authoring(candidate)
    assert verify_current_part()["status"] == "verified"


@pytest.mark.parametrize("kind,patch,code", [
    ("cluster_op", {"unknown": 4}, "unsupported_transform_scope"),
    ("cluster_op", {"translation": [True, 0, 0]}, "invalid_transform_input"),
    ("nucleotide-transform", {"compose": "false"}, "invalid_transform_input"),
    ("nucleotide-transform-batch", {"transforms": []}, "invalid_transform_input"),
])
def test_malformed_history_inputs_refuse_before_publication_and_keep_undo(kind, patch, code):
    source = source_recipe(kind)
    index = install(source)
    original = source.model_dump_json()
    revision = state.get_design_with_revision()[1]
    with pytest.raises(HTTPException) as caught:
        edit_feature(index, EditFeatureBody(params=patch))
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == code
    assert state.get_or_404() is source
    assert state.get_or_404().model_dump_json() == original
    assert state.get_design_with_revision()[1] == revision and state.undo_depth() == 0


def test_reset_retarget_receipt_comes_from_exact_selected_prefix():
    source = source_recipe("nucleotide-transform", suffix=False)
    first = source.nucleotide_transforms[0]
    body = {**source.feature_log[-1].params, "bp_index": 5}
    source = snapshot(source, "nucleotide-transform", body, "second-pose")
    second = next(t for t in source.nucleotide_transforms if t.id != first.id)
    reset = m.SnapshotLogEntry(id="reset", op_kind="nucleotide-transform-delete", label="Reset",
        params={"_proof_version": 1, "transform_id": first.id, "target": list(first.target_key())})
    source = _append(source, reset)
    state.set_design(source)
    state.clear_history()
    edit_feature(len(source.feature_log) - 1, EditFeatureBody(params={"transform_id": second.id}))
    candidate = state.get_or_404()
    assert [t.id for t in candidate.nucleotide_transforms] == [first.id]
    assert candidate.feature_log[-1].params == {
        "_proof_version": 1, "transform_id": second.id, "target": list(second.target_key())}
    assert verify_current_part()["status"] == "verified"


def test_selected_missing_target_is_actionable_and_atomic():
    source = source_recipe("nucleotide-transform")
    index = install(source)
    before = deepcopy(source.model_dump(mode="json"))
    with pytest.raises(HTTPException) as caught:
        edit_feature(index, EditFeatureBody(params={"helix_id": "removed"}))
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "missing_reference"
    assert caught.value.detail["feature_id"] == FEATURE
    assert caught.value.detail["references"] == [{
        "kind": "helix", "identity": "removed", "parameter_path": ["helix_id"]}]
    assert state.get_or_404().model_dump(mode="json") == before and state.undo_depth() == 0


def test_earlier_target_change_exposes_later_reset_dependency_without_publishing():
    source = source_recipe("nucleotide-transform", suffix=False)
    moved = source.nucleotide_transforms[0]
    source = snapshot(source, "nucleotide-transform-delete", {
        "transform_id": moved.id, "target": list(moved.target_key())}, "later-reset")
    index = install(source)
    original = source.model_dump_json()
    with pytest.raises(HTTPException) as caught:
        edit_feature(index, EditFeatureBody(params={"bp_index": 5}))
    assert caught.value.status_code == 409
    assert caught.value.detail["feature_id"] == "later-reset"
    assert caught.value.detail["code"] == "missing_reference"
    assert caught.value.detail["references"] == [{
        "kind": "nucleotide_transform", "identity": moved.id, "parameter_path": ["transform_id"]}]
    assert state.get_or_404().model_dump_json() == original and state.undo_depth() == 0


def test_placement_reference_retarget_changes_the_selected_owner_and_keeps_row_metadata():
    source = source_recipe(suffix=False)
    row = source.feature_log[-1]
    # Rebuild the actual native prefix without decoding any recovery snapshot.
    from backend.api.part_recipe_edit import regenerate
    prefix = regenerate(source, source.feature_log[:-1], lambda: None)
    other = m.ClusterRigidTransform(id="other-owner", name="Other", helix_ids=[prefix.helices[0].id])
    prefix = _append(prefix, m.ClusterCreateLogEntry(cluster_id=other.id,
        name=other.name, helix_ids=other.helix_ids, cluster_snapshot=other, proof_version=2))
    source = _append(prefix, row)
    index = install(source)
    patch = {"cluster_id": other.id, "helix_ids": list(other.helix_ids), "translation": [9, 0, 0]}
    edit_feature(index, EditFeatureBody(params=patch))
    candidate = state.get_or_404()
    changed = candidate.feature_log[index]
    assert changed.id == row.id and changed.source == row.source
    assert changed.cluster_id == other.id
    assert command_input(changed)[1]["translation"] == [9, 0, 0]
    assert next(c for c in candidate.cluster_transforms if c.id == other.id).translation == [9, 0, 0]
    assert verify_current_part()["status"] == "verified"
