"""Recorded Move reclassification remains editable through native history."""
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import part_transform_preview as preview, state
from backend.api.crud import EditFeatureBody, edit_feature
from backend.api.part_transform_preview_dto import prepare_display
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history
from backend.api import part_proof_commands as commands
from tests.test_part_deformation_preview import owned_capture, authoring
from tests.test_part_member_motion_order import _source
from tests.test_part_transform_frontend_contract import assert_frontend
from tests.test_part_transform_preview import snapshot
from tests.test_unpair_move_apply import bodies


def unpair_history(direction="REVERSE", *, prior=False):
    source = _source()
    transforms = bodies(source, (direction,))
    if prior:
        source = snapshot(source, "nucleotide-transform-batch", {
            "transforms": transforms, "history_seed": str(uuid4())}, "prior")
    return snapshot(source, "nucleotide-transform-batch", {
        "transforms": transforms, "history_seed": str(uuid4()),
        "reclassify_unpaired": True}, "unpair")


@pytest.mark.parametrize("direction", ["FORWARD", "REVERSE"])
@pytest.mark.parametrize("prior", [False, True])
def test_relocated_display_keeps_authored_addresses_and_stable_pose_ids(direction, prior):
    source = unpair_history(direction, prior=prior)
    before = source.model_dump_json()
    prepared = preview.prepare_from_capture(owned_capture(source), "unpair")
    evaluated = preview.evaluate(prepared, {})
    packet = prepare_display(prepared.copy_prefix(), evaluated)
    assert packet["control_state"]["inputs"] == source.feature_log[-1].params
    ids = packet["control_state"]["residue_pose_ids"]
    assert ids == [p.id for p in source.nucleotide_transforms]
    assert source.model_dump_json() == before
    assert_frontend(packet)


def test_edit_reclassification_regenerates_later_relocated_move_and_undo_cold_replay():
    source = unpair_history()
    first = source.nucleotide_transforms[0]
    source = snapshot(source, "nucleotide-transform", {
        **first.model_dump(mode="json", exclude={"id"}), "compose": True,
        "translation": [0, 1, 0], "history_seed": str(uuid4())}, "later-move")
    state.set_design(source)
    state.clear_history()
    index = next(i for i, row in enumerate(source.feature_log) if row.id == "unpair")
    row = source.feature_log[index]
    edit_feature(index, EditFeatureBody(params={"transforms": [
        {**body, "translation": [4, 0, 0]} for body in row.params["transforms"]]}))
    candidate = state.get_or_404()
    assert candidate.feature_log[index].params["reclassify_unpaired"] is True
    assert [h.id for h in candidate.helices] == [h.id for h in source.helices]
    assert candidate.nucleotide_transforms[0].translation == [4, 1, 0]
    restored = Design.model_validate_json(candidate.model_dump_json())
    assert assess_part_history(restored, execute=commands.execute,
                               dependencies=commands.dependencies)["status"] == "verified"
    assert state.undo_depth() == 1
    state.undo()
    assert authoring(state.get_or_404()) == authoring(source)
    state.redo()
    assert authoring(state.get_or_404()) == authoring(candidate)


def test_removing_separation_attributes_missing_relocated_target_to_later_move():
    source = unpair_history()
    first = source.nucleotide_transforms[0]
    source = snapshot(source, "nucleotide-transform", {
        **first.model_dump(mode="json", exclude={"id"}), "compose": True,
        "translation": [0, 1, 0], "history_seed": str(uuid4())}, "later-move")
    state.set_design(source)
    state.clear_history()
    original = source.model_dump_json()
    index = next(i for i, row in enumerate(source.feature_log) if row.id == "unpair")
    with pytest.raises(HTTPException) as error:
        edit_feature(index, EditFeatureBody(params={"transforms": [
            {**body, "translation": [0, 0, 0]} for body in source.feature_log[index].params["transforms"]]}))
    assert error.value.detail["feature_id"] == "later-move"
    assert error.value.detail["code"] == "missing_reference"
    assert state.get_or_404().model_dump_json() == original
    assert state.undo_depth() == 0
