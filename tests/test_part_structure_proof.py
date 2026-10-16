"""A reproducible recipe is not necessarily a structurally valid part."""

import pytest
from fastapi import HTTPException

from backend.api import part_proof_commands
from backend.api.part_recipe_edit import prepare_change
from backend.api.part_recipe_repair import prepare_repair
from backend.core.models import ClusterCreateLogEntry, ClusterRigidTransform
from backend.core.part_history_contract import assess_part_history
from tests.test_part_deformation_preview import _append, native_source


def grouped_source(*, all_members=True):
    source = native_source()
    source = source.copy_with(feature_log=source.feature_log[:-1], deformations=[])
    members = [helix.id for helix in source.helices]
    group = ClusterRigidTransform(id="530058ac-9d73-41fd-9d61-3b51098c64ec", name="Arm",
                                  helix_ids=members if all_members else members[:1])
    return _append(source, ClusterCreateLogEntry(id="group-feature", cluster_id=group.id,
        name=group.name, helix_ids=group.helix_ids, cluster_snapshot=group, proof_version=1))


def assess(source):
    return assess_part_history(source, execute=part_proof_commands.execute,
                               dependencies=part_proof_commands.dependencies)


def test_exact_v1_reproduction_reports_invalid_structure_and_responsible_group():
    source = grouped_source()
    original = source.model_dump_json()
    result = assess(source)
    assert result["status"] == "failed", result
    assert result["reproducibility_status"] == "verified"
    assert not result["native_editable"] and not result["integrity_checked"]
    assert result["structure"]["status"] == "invalid"
    issue = next(item for item in result["issues"] if item["code"] == "invalid_structure")
    assert issue["feature_id"] == "group-feature"
    assert issue["possible_dependents"] == []
    assert issue["structure"]["issues"][0]["reference"] == {
        "kind": "cluster", "identity": source.lattice_frames[0].placement_cluster_id}
    assert "parameter_path" not in issue["structure"]["issues"][0]
    assert source.model_dump_json() == original


def test_valid_reproduction_retains_verified_status_with_separate_structural_scope():
    result = assess(grouped_source(all_members=False))
    assert result["status"] == result["reproducibility_status"] == "verified"
    assert result["native_editable"] and result["structure"]["status"] == "valid"
    assert not result["integrity_checked"]


def test_historical_group_edit_cannot_return_an_invalid_regenerated_candidate():
    source = grouped_source(all_members=False)
    original = source.model_dump_json()
    with pytest.raises(HTTPException) as caught:
        prepare_change(source, source.model_copy(deep=True), len(source.feature_log) - 1,
                       lambda: None, params={"helix_ids": [helix.id for helix in source.helices]})
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "invalid_structure"
    assert source.model_dump_json() == original


def test_repair_completion_refuses_reproduced_invalid_structure_without_candidate():
    source = grouped_source()
    original = source.model_dump_json()
    first = source.feature_log[0]
    body = {"repair_version": 1, "expected_design_id": source.id, "expected_revision": 7,
        "actions": [{"action": "set_input", "feature_id": first.id,
            "parameter_path": ["length_bp"], "expected_old": first.params["length_bp"],
            "value": first.params["length_bp"]}]}
    result = prepare_repair(source, body, source_revision=7,
        executor=part_proof_commands.execute, dependency_resolver=part_proof_commands.dependencies)
    assert result["status"] == "failed", result
    assert result["issues"][0]["code"] == "invalid_structure"
    assert result["repair"]["phase"] == "validation"
    assert "candidate" not in result
    assert source.model_dump_json() == original
