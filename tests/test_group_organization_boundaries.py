"""Closed archive eligibility and durable command identity for organization."""

from copy import deepcopy

import pytest


def _archive_source():
    from backend.core.models import Design, DesignMetadata, SnapshotLogEntry

    return Design(id="archive", metadata=DesignMetadata(name="Legacy", tags=["kept"]),
        feature_log=[SnapshotLogEntry(id="old", op_kind="bundle-create", label="Old",
            params={"retained": [1, 2]}, design_snapshot_gz_b64="opaque recovery",
            post_state_gz_b64="opaque post")])


def test_legacy_none_keeps_exact_owned_archive_after_schema_extension(monkeypatch):
    from backend.core import oxdna_preparation_inputs as capture

    # This tests schema/ownership semantics, not capture latency qualification.
    monkeypatch.setattr(capture, "CAPTURE_SECONDS", 10.0)
    source = _archive_source()
    expected = source.model_dump(mode="json")
    assert capture.source_reason(source) is None
    owned = capture.capture_archive(source)
    assert owned.model_dump(mode="json") == expected
    assert owned.group_organization is None
    owned.metadata.tags.append("private")
    owned.feature_log[0].params["retained"].append(3)
    assert source.model_dump(mode="json") == expected


@pytest.mark.parametrize("has_groups", [False, True])
def test_active_organization_is_explicitly_unsupported_before_archive_copy(monkeypatch, has_groups):
    from backend.core import oxdna_preparation_inputs as capture
    from backend.core.part_group_model import GroupOrganization, PartGroup

    source = _archive_source().copy_with(group_organization=GroupOrganization(
        groups=[PartGroup(id="empty", name="Selected")] if has_groups else []))
    expected = deepcopy(source)

    def forbidden(*args, **kwargs):
        raise AssertionError("Unsupported organization must not enter archive copying or serialization")

    monkeypatch.setattr(capture, "deepcopy", forbidden)
    monkeypatch.setattr(GroupOrganization, "model_dump", forbidden)
    reason = capture.source_reason(source)
    assert "group organization" in reason.lower()
    with pytest.raises(capture.UnsupportedPreparation) as error:
        capture.capture_archive(source)
    assert error.value.code == "oxdna_preparation_unsupported"
    assert "group organization" in str(error.value).lower()
    assert source == expected


def test_group_create_preserves_only_nested_output_identity_and_existing_version():
    from backend.core.part_edit_identity import preserve_proof_identity

    previous = {"_proof_version": 1, "group": {"id": "owned", "name": "Old", "helix_ids": ["h1"]}}
    updated = {"_proof_version": 99, "group": {"id": "replaced", "name": "New", "helix_ids": ["h2"]}}
    before = deepcopy((previous, updated))
    result = preserve_proof_identity(previous, updated, kind="group-create")
    assert result == {"_proof_version": 1, "group": {"id": "owned", "name": "New", "helix_ids": ["h2"]}}
    assert (previous, updated) == before
    assert result["group"] is not updated["group"]


def test_conversion_keeps_complete_ordered_output_namespace():
    from backend.core.part_edit_identity import preserve_proof_identity

    previous = {"_proof_version": 1, "expected_placement_ids": ["second", "first"]}
    updated = {"_proof_version": 99, "expected_placement_ids": ["replacement"]}
    assert preserve_proof_identity(previous, updated, kind="group-organize") == previous


@pytest.mark.parametrize("kind,field,old,new", [
    ("group-update", "group_id", "old", "new"),
    ("group-dissolve", "group_ids", ["old"], ["new"]),
])
def test_group_consumers_keep_reference_inputs_editable(kind, field, old, new):
    from backend.core.part_edit_identity import preserve_proof_identity

    previous = {"_proof_version": 1, field: old}
    updated = {"_proof_version": 99, field: new}
    assert preserve_proof_identity(previous, updated, kind=kind) == {"_proof_version": 1, field: new}


@pytest.mark.parametrize("kind,updated", [
    ("group-organize", {"expected_placement_ids": []}),
    ("group-create", {"group": {"name": "Incomplete"}}),
    ("group-update", {"group_id": "selected"}),
    ("group-dissolve", {"group_ids": ["selected"]}),
])
def test_identity_policy_does_not_invent_contract_or_output_slots(kind, updated):
    from backend.core.part_edit_identity import preserve_proof_identity

    assert preserve_proof_identity({}, updated, kind=kind) == updated


def test_malformed_group_replacement_is_not_silently_repaired_by_identity_policy():
    from backend.core.part_edit_identity import preserve_proof_identity

    previous = {"_proof_version": 1, "group": {"id": "owned", "name": "Old"}}
    result = preserve_proof_identity(previous, {"group": "invalid"}, kind="group-create")
    assert result == {"_proof_version": 1, "group": "invalid"}


@pytest.mark.parametrize("kind,params,path,replacement", [
    ("group-create", {"_proof_version": 1, "group": {"id": "owned", "name": "Group"}},
     ["group", "id"], "forged"),
    ("group-organize", {"_proof_version": 1, "expected_placement_ids": ["owned"]},
     ["expected_placement_ids"], ["forged"]),
])
def test_repair_planner_rejects_organization_output_identity_replacement(kind, params, path, replacement):
    from backend.core.models import SnapshotLogEntry
    from backend.core.part_history_contract import create_empty_part
    from backend.core.part_repair_inputs import SetInput
    from backend.core.part_repair_planning import RepairInputError, plan_actions

    entry = SnapshotLogEntry(id="feature", op_kind=kind, label="Organization", params=params)
    source = create_empty_part("Planning", "HONEYCOMB").copy_with(feature_log=[entry])
    old = params
    for token in path:
        old = old[token]
    action = SetInput.model_validate({"action": "set_input", "feature_id": entry.id,
        "parameter_path": path, "expected_old": old, "value": replacement})
    with pytest.raises(RepairInputError) as error:
        plan_actions(source, [action])
    assert error.value.code == "protected_recipe_identity"
    assert entry.params == params
