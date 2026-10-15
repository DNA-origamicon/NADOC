"""Portable repair proposals remain bounded input data, never saved results."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.core.part_repair_draft import RepairBaseFingerprint, RepairDraft
from backend.core.part_repair_inputs import RepairRequest, SetInput, UpgradeNumericalContract


def action():
    return {"action": "set_input", "feature_id": "group", "child_id": "child",
            "parameter_path": ["helix_ids", 0], "expected_old": "missing", "value": "replacement"}


def draft():
    return {"version": 1, "draft_id": "draft-one", "generation": 0, "base_design_id": "part-one",
            "base": {"version": 1, "root_sha256": "a" * 64, "commands_sha256": "b" * 64,
                     "sources_sha256": "c" * 64}, "repair_version": 1, "actions": [action()]}


def test_draft_json_roundtrip_preserves_expectations_without_runtime_state():
    data = draft()
    data["actions"].append({"action": "upgrade_numerical_contract", "feature_id": "relax", "child_id": None,
        "expected_engine": {"id": "engine", "implementation_sha256": "d" * 64}, "expected_template": None})
    before = deepcopy(data)
    proposal = RepairDraft.model_validate(data)
    loaded = RepairDraft.model_validate_json(proposal.model_dump_json())
    assert loaded == proposal and loaded.model_dump(mode="json") == before
    assert isinstance(loaded.actions[0], SetInput)
    assert isinstance(loaded.actions[1], UpgradeNumericalContract)
    assert data == before


def test_shared_request_remains_the_api_compatibility_type():
    from backend.api import part_recipe_repair as repair

    assert repair.RepairRequest is RepairRequest
    assert repair.SetInput is SetInput
    assert repair.UpgradeNumericalContract is UpgradeNumericalContract
    assert repair.MAX_REPAIR_ACTIONS == 64
    body = {"repair_version": 1, "expected_design_id": "part-one", "expected_revision": 18,
            "actions": [action()]}
    assert RepairRequest.model_validate(body).model_dump(mode="json") == body


@pytest.mark.parametrize("field", ["expected_revision", "source_revision", "job_id", "status", "result",
                                  "candidate", "geometry", "recovery", "native_editable", "recipe_root"])
def test_draft_cannot_persist_runtime_or_output_fields(field):
    data = draft()
    data[field] = {}
    with pytest.raises(ValidationError):
        RepairDraft.model_validate(data)


@pytest.mark.parametrize("path,value", [
    (("version",), True), (("version",), 2), (("repair_version",), "1"),
    (("generation",), -1), (("generation",), True), (("base_design_id",), ""),
    (("base", "version"), 2), (("base", "root_sha256"), "A" * 64),
    (("actions", 0, "parameter_path"), [True]),
    (("actions", 0, "parameter_path"), ["x"] * 17),
    (("actions", 0, "action"), "replace_geometry"),
])
def test_draft_schema_is_strict_and_versioned(path, value):
    data = draft()
    target = data
    for token in path[:-1]:
        target = target[token]
    target[path[-1]] = value
    with pytest.raises(ValidationError):
        RepairDraft.model_validate(data)


@pytest.mark.parametrize("count", [0, 65])
def test_draft_action_count_is_bounded(count):
    data = draft()
    data["actions"] = [action() for _ in range(count)]
    with pytest.raises(ValidationError):
        RepairDraft.model_validate(data)


def test_sixty_four_actions_remain_admitted():
    data = draft()
    data["actions"] = [action() for _ in range(64)]
    assert len(RepairDraft.model_validate(data).actions) == 64


@pytest.mark.parametrize("field,value", [
    ("expected_old", "x" * 64_000), ("value", "x" * 64_000),
    ("value", [0] * 10_000), ("value", float("inf")),
])
def test_entire_draft_charges_old_values_and_proposed_values_before_acceptance(field, value):
    data = draft()
    data["actions"][0][field] = value
    with pytest.raises(ValidationError, match="budget|finite"):
        RepairDraft.model_validate(data)


def test_fingerprint_is_only_strict_hashes_and_has_no_saved_certificate():
    data = draft()["base"]
    fingerprint = RepairBaseFingerprint.model_validate(data)
    assert fingerprint.model_dump(mode="json") == data
    with pytest.raises(ValidationError):
        RepairBaseFingerprint.model_validate({**data, "verified": True})
