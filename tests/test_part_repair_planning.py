"""Shared repair planning: explicit expected inputs/errors, without replay."""

from copy import deepcopy

import pytest

from backend.api import part_recipe_repair as worker
from backend.core.models import MinorMutationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry
from backend.core.part_command_errors import CommandContractError
from backend.core.part_dependencies import Dependencies
from backend.core.part_history_contract import create_empty_part
from backend.core.part_repair_inputs import RepairRequest
from backend.core.part_repair_planning import (
    RepairInputError, check_numerical_expectations, plan_actions, validate_target,
)
from backend.core.part_repair_proposal import DraftInputError, proposed_inputs


def source():
    design = create_empty_part("Repair planning", "HONEYCOMB")
    design.id = "part"
    params = {"_proof_version": 1, "history_seed": "fixed", "selector": "missing",
              "nested": {"items": [1, 2.0], "enabled": True}}
    design.feature_log = [SnapshotLogEntry(id="feature", op_kind="nanoparticle-patch", label="Feature", params=params),
        RoutingClusterLogEntry(id="group", children=[MinorMutationLogEntry(id="child", op_subtype="nick", label="Child",
            params={"_proof_version": 1, "helix_id": "missing"})])]
    return design


def action(**extra):
    return {"action": "set_input", "feature_id": "feature", "parameter_path": ["selector"],
            "expected_old": "missing", "value": "replacement", **extra}


def parsed(actions):
    return RepairRequest.model_validate({"repair_version": 1, "expected_design_id": "part", "expected_revision": 1,
                                         "actions": actions})


def known(_kind, _params):
    return Dependencies()


def test_planning_preserves_action_order_and_clones_only_changed_input_definitions():
    design = source()
    before = design.model_dump_json()
    request = parsed([action(feature_id="group", child_id="child", parameter_path=["helix_id"]),
        action(parameter_path=["nested", "items", 0], expected_old=1, value=3),
        action(parameter_path=["nested", "enabled"], expected_old=True, value=False)])
    targets = plan_actions(design, request.actions, dependencies=known)
    assert list(targets) == ["child", "feature"]
    assert targets["child"].params == {"_proof_version": 1, "helix_id": "replacement"}
    assert targets["feature"].params == {"_proof_version": 1, "history_seed": "fixed", "selector": "missing",
                                          "nested": {"items": [3, 2.0], "enabled": False}}
    targets["feature"].params["nested"]["items"][1] = 500
    assert design.model_dump_json() == before
    assert request.actions[1].value == 3


@pytest.mark.parametrize("actions,code,failed_index", [
    ([action(expected_old="stale")], "repair_conflict", 0),
    ([action(parameter_path=["nested", "items", 0], expected_old=True)], "repair_conflict", 0),
    ([action(parameter_path=["nested", "items", 1], expected_old=2)], "repair_conflict", 0),
    ([action(feature_id="gone")], "missing_feature", 0),
    ([action(feature_id="group", child_id="gone")], "missing_feature", 0),
    ([action(child_id="child")], "invalid_repair_target", 0),
    ([action(feature_id="group")], "unsupported_repair_target", 0),
    ([action(parameter_path=["absent"])], "invalid_parameter_path", 0),
    ([action(parameter_path=["nested", "items", 9])], "invalid_parameter_path", 0),
    ([action(), action()], "overlapping_repair_paths", 1),
    ([action(parameter_path=["nested"], expected_old={"items": [1, 2.0], "enabled": True}, value={}),
      action(parameter_path=["nested", "enabled"], expected_old=True, value=False)], "overlapping_repair_paths", 1),
    ([action(parameter_path=["history_seed"], expected_old="fixed", value="replaced")], "protected_recipe_identity", 0),
])
def test_action_failures_identify_the_exact_target_and_path(actions, code, failed_index):
    design = source()
    before = design.model_dump_json()
    with pytest.raises(RepairInputError) as error:
        plan_actions(design, parsed(actions).actions, dependencies=known)
    issue, failed = error.value.as_issue(), actions[failed_index]
    assert issue["code"] == code and error.value.status == "failed"
    assert issue["feature_id"] == failed["feature_id"]
    assert issue.get("child_id") == failed.get("child_id")
    assert issue["parameter_path"] == failed["parameter_path"]
    assert design.model_dump_json() == before


def test_unknown_contract_keeps_worker_unverified_error_identity():
    with pytest.raises(CommandContractError) as error:
        plan_actions(source(), parsed([action()]).actions, dependencies=lambda *_: Dependencies(known=False))
    assert type(error.value) is CommandContractError and error.value.status == "unverified"
    assert error.value.as_issue() == {"code": "missing_proof_contract",
        "detail": "Repair cannot promote a legacy or unknown command contract"}


def test_invalid_final_contract_retains_worker_error_and_draft_target_diagnostic():
    design = source()
    request = parsed([action()])
    target = plan_actions(design, request.actions, dependencies=known)["feature"]
    with pytest.raises(RepairInputError) as error:
        validate_target(target, lambda *_: Dependencies(known=False))
    assert error.value.as_issue() == {"code": "invalid_repaired_contract",
        "detail": "Patched inputs do not satisfy the registered native command schema"}
    with pytest.raises(DraftInputError) as draft_error:
        proposed_inputs(design, request.actions, dependencies=lambda _k, p: Dependencies(known=p["selector"] == "missing"))
    assert draft_error.value.as_issue()["feature_id"] == "feature"
    assert "parameter_path" not in draft_error.value.as_issue()


@pytest.mark.parametrize("duplicate,code", [(False, "empty_routing_cluster"), (True, "ambiguous_feature_identity")])
def test_ambiguous_identity_precedes_empty_group_admission(duplicate, code):
    design = source()
    design.feature_log.append(RoutingClusterLogEntry(id="feature" if duplicate else "empty", children=[]))
    with pytest.raises(CommandContractError) as error:
        plan_actions(design, parsed([action()]).actions, dependencies=known)
    assert error.value.code == code


def test_capture_discovery_never_hashes_or_calls_admission_and_keeps_original_expectations(monkeypatch):
    design = source()
    request = parsed([action(expected_old="stale", value="source-selection")])
    monkeypatch.setattr("backend.core.part_repair_planning.same_input", lambda *_: pytest.fail("Discovery hashed inputs"))
    targets = plan_actions(design, request.actions, check_expectations=False,
                           dependencies=lambda *_: pytest.fail("Discovery admitted commands"))
    assert targets["feature"].params["selector"] == "source-selection"
    assert request.actions[0].expected_old == "stale"
    assert design.feature_log[0].params["selector"] == "missing"


def numerical():
    design = source()
    params = {"_proof_version": 1, "relaxation_version": 1, "source": {"kind": "native"},
        "engine": {"id": "nadoc.duplex-relax-native.v1", "implementation_sha256": "a" * 64, "runtime_sha256": "b" * 64}}
    design.feature_log = [SnapshotLogEntry(id="numerical", op_kind="duplex-relax", label="Relax", params=params)]
    upgrade = {"action": "upgrade_numerical_contract", "feature_id": "numerical", "expected_engine": deepcopy(params["engine"])}
    return design, upgrade


def test_planning_records_upgrade_intent_without_selecting_or_mutating_pins():
    design, upgrade = numerical()
    before = design.model_dump_json()
    target = plan_actions(design, parsed([upgrade]).actions, dependencies=known)["numerical"]
    assert target.upgrade.expected_engine == design.feature_log[0].params["engine"]
    check_numerical_expectations(target.params, target.upgrade)
    assert target.params == design.feature_log[0].params
    assert design.model_dump_json() == before


def test_stale_numerical_expectation_fails_in_the_explicit_check_phase():
    design, upgrade = numerical()
    upgrade["expected_engine"]["runtime_sha256"] = "c" * 64
    target = plan_actions(design, parsed([upgrade]).actions, dependencies=known)["numerical"]
    with pytest.raises(RepairInputError) as error:
        check_numerical_expectations(target.params, target.upgrade)
    assert error.value.as_issue() == {"code": "repair_conflict", "feature_id": "numerical",
        "detail": "The numerical contract changed after this repair was prepared"}


def test_a_definition_can_request_only_one_numerical_upgrade():
    design, upgrade = numerical()
    with pytest.raises(RepairInputError) as error:
        plan_actions(design, parsed([upgrade, deepcopy(upgrade)]).actions, dependencies=known)
    assert error.value.code == "duplicate_numerical_upgrade"


def test_worker_compatibility_alias_and_planned_log_keep_existing_error_and_metadata_contract():
    assert worker.RepairInputError is RepairInputError
    design = source()
    before = design.model_dump_json()
    log, upgrades = worker._definitions(design, parsed([action()]), known,
        lambda *_: pytest.fail("A nonnumerical repair selected numerical pins"))
    assert upgrades == [] and log[0].params["selector"] == "replacement"
    assert log[0].id == "feature" and log[0].label == "Feature"
    assert log[1] == design.feature_log[1]
    assert design.model_dump_json() == before
