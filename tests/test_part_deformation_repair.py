"""Named-group repair uses typed inputs and the actual native feature prefix."""

from copy import deepcopy

import pytest

from backend.api import part_repair_input_metadata as metadata
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_recipe_repair import prepare_repair
from backend.api.part_repair_selection import prepare_selection
from backend.core import models as m
from backend.core.part_history_contract import assess_part_history
from backend.core.part_repair_capture import capture_draft_inputs
from backend.core.part_repair_draft import RepairDraft
from backend.core.part_repair_draft_evaluation import compile_draft_evaluation
from backend.core.part_repair_draft_host import parse_draft_request, prepare_draft
from backend.core.part_repair_inputs import RepairRequest
from backend.core.part_repair_planning import RepairInputError, plan_actions
from tests.test_part_deformation_preview import _append, native_source


def source(kind="twist", *, broken=True):
    original = native_source(kind)
    entry = original.feature_log[-1]
    design = original.copy_with(deformations=[], feature_log=original.feature_log[:-1])
    design = _append(design, m.SnapshotLogEntry(id="organize", op_kind="group-organize", label="Organize",
        params={"_proof_version": 1,
                "expected_placement_ids": [group.id for group in design.cluster_transforms]}))
    strand = design.strands[0]
    for identity, refs in [("replacement", [{"strand_id": strand.id, "domain_index": 0}]), ("empty", [])]:
        design = _append(design, m.SnapshotLogEntry(id=f"create-{identity}", op_kind="group-create", label=identity,
            params={"_proof_version": 1, "group": {"id": identity, "domain_ids": refs}}))
    domain = strand.domains[0]
    design = _append(design, m.SnapshotLogEntry(id="nick", op_kind="nick", label="Nick", params={
        "_proof_version": 1, "helix_id": domain.helix_id, "direction": domain.direction.value,
        "bp_index": 20}))
    operation = entry.op_snapshot.model_copy(update={"targets": [{"kind": "part_group", "id": "replacement"}],
        "cluster_ids": [], "target_ranges": None})
    entry = entry.model_copy(update={"op_snapshot": operation})
    design = _append(design, entry)
    entry = entry.model_copy(update={"op_snapshot": design.deformations[-1].model_copy(deep=True)})
    if broken:
        entry.op_snapshot.targets[0]["id"] = "missing"
    design.feature_log[-1] = entry
    design = _append(design, m.SnapshotLogEntry(id="later-group", op_kind="group-create", label="Future group", params={
        "_proof_version": 1, "group": {"id": "future", "helix_ids": [design.helices[0].id]}}))
    return design


def action(**changes):
    return {"action": "set_input", "feature_id": "edited-feature", "child_id": None,
            "parameter_path": ["targets", 0, "id"], "expected_old": "missing",
            "value": "replacement", **changes}


def request(design, *actions):
    return RepairRequest.model_validate({"repair_version": 1, "expected_design_id": design.id,
        "expected_revision": 7, "actions": list(actions) or [action()]})


def select(design, **changes):
    body = {"selection_version": 1, "expected_design_id": design.id, "expected_revision": 7,
            "feature_id": "edited-feature", "parameter_path": ["targets", 0, "id"],
            "expected_old": "missing", **changes}
    return prepare_selection(design, body, source_revision=7, executor=execute, dependency_resolver=dependencies)


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_native_control_includes_topology_split_and_independent_cold_proof(kind):
    design = source(kind, broken=False)
    group = next(group for group in design.group_organization.groups if group.id == "replacement")
    assert len(group.domain_ids) == 2
    assert assess_part_history(design, execute=execute, dependencies=dependencies)["status"] == "verified"


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_missing_group_selection_rebuilds_prefix_then_repair_reconstructs_typed_row(kind):
    design = source(kind)
    before = design.model_dump_json()
    result = select(design)
    assert result["status"] == "preview", result
    choices = result["selection"]["candidates"]
    assert {choice["identity"] for choice in choices} >= {"replacement"}
    assert not {"empty", "future", "missing"}.intersection(choice["identity"] for choice in choices)
    assert all(choice["kind"] == "part_group" for choice in choices)
    assert result["selection"]["completed_prefix"][-1] == "nick"
    assert result["selection"]["not_evaluated"] == ["edited-feature", "later-group"]
    assert result["selection"]["whole_recipe_validated"] is False
    repaired = prepare_repair(design, request(design), source_revision=7,
        executor=execute, dependency_resolver=dependencies)
    assert repaired["status"] == "ready", repaired
    candidate = repaired["candidate"]
    old = design.feature_log[-2]
    row = candidate.feature_log[-2]
    assert type(row) is m.DeformationLogEntry and row.id == old.id
    assert row.deformation_id == old.deformation_id and row.proof_version == old.proof_version
    assert row.op_snapshot.targets == [{"kind": "part_group", "id": "replacement"}]
    assert "params" not in row.__dict__
    assert len(candidate.deformations[-1].target_ranges) == 2
    assert candidate.cluster_transforms == design.cluster_transforms
    loaded = m.Design.model_validate_json(candidate.model_dump_json())
    for entry in loaded.feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned"
    assert assess_part_history(loaded, execute=execute, dependencies=dependencies)["status"] == "verified"
    assert design.model_dump_json() == before


def test_metadata_exposes_only_named_id_and_capture_does_not_serialize(monkeypatch):
    design = source()
    selection = metadata.RepairInputSelection(expected_design_id=design.id, expected_revision=7,
        feature_id="edited-feature")
    with monkeypatch.context() as patch:
        patch.setattr(m.DeformationOp, "model_dump", lambda *_a, **_k: pytest.fail("Serialized under capture lock"))
        kind, captured = metadata._capture(design, selection)
        captured_draft = capture_draft_inputs(design, source_revision=7,
            proposed_actions=request(design).actions, seconds=1)
    assert kind == "deformation" and captured is not design.feature_log[-2]
    assert captured_draft.feature_log[-2] is not design.feature_log[-2]
    catalog = metadata.describe_inputs(kind, captured)
    assert catalog["definition_supported"] is True
    assert [(field["parameter_path"], field["expected_old"], field["input_type"])
            for field in catalog["fields"]] == [(["targets", 0, "id"], "missing", "reference")]
    assert catalog["fields"][0]["reference_selection"]["resource_kind"] == "part_group"


def test_draft_roundtrip_compilation_and_rebase_keep_exact_expected_reference():
    design = source()
    actions = request(design).actions
    captured = capture_draft_inputs(design, source_revision=7, proposed_actions=actions, seconds=1)
    body = parse_draft_request({"draft_version": 1, "operation": "create",
        "expected_design_id": design.id, "expected_revision": 7,
        "expected_draft_id": None, "expected_generation": None,
        "actions": [item.model_dump(mode="json") for item in actions]})
    draft = prepare_draft(captured, body, dependencies=dependencies, new_draft_id="named-repair")
    draft = RepairDraft.model_validate_json(draft.model_dump_json())
    compiled = compile_draft_evaluation(capture_draft_inputs(design, source_revision=7, draft=draft, seconds=1), {
        "draft_version": 1, "expected_design_id": design.id, "expected_revision": 7,
        "expected_draft_id": draft.draft_id, "expected_generation": draft.generation})
    assert compiled.actions == actions
    design.feature_log[-2].op_snapshot.targets[0]["id"] = "new-old"
    rebase = {"draft_version": 1, "operation": "rebase", "expected_design_id": design.id,
        "expected_revision": 8, "expected_draft_id": draft.draft_id,
        "expected_generation": draft.generation}
    with pytest.raises(RepairInputError) as caught:
        prepare_draft(capture_draft_inputs(design, source_revision=8, draft=draft, seconds=1),
            rebase, dependencies=dependencies)
    assert caught.value.code == "repair_conflict"
    assert draft.actions[0].expected_old == "missing"


@pytest.mark.parametrize("path", [["id"], ["type"], ["_proof_version"], ["affected_helix_ids", 0],
    ["target_ranges", 0, "start_bp"], ["cluster_ids"], ["targets"], ["targets", 0, "kind"],
    ["params", "total_degrees"], ["targets", 1, "id"]])
def test_other_overlay_and_derived_input_paths_remain_protected(path):
    design = source()
    before = design.model_dump_json()
    with pytest.raises(RepairInputError) as caught:
        plan_actions(design, request(design, action(parameter_path=path)).actions, dependencies=dependencies)
    assert caught.value.code == "protected_recipe_identity"
    assert design.model_dump_json() == before


@pytest.mark.parametrize("change", ["old", "duplicate", "empty", "namespace", "version", "operation-id",
                                    "empty-operation-id", "parameter-family"])
def test_exact_expectations_and_recognized_typed_definitions_are_required(change):
    design = source()
    row = design.feature_log[-2]
    actions = [action()]
    if change == "old":
        actions = [action(expected_old="stale")]
    elif change == "duplicate":
        actions *= 2
    elif change == "empty":
        row.op_snapshot.targets = []
    elif change == "namespace":
        row.op_snapshot.targets = [{"kind": "cluster", "id": "missing"}]
    elif change == "version":
        row.proof_version = True
    elif change == "empty-operation-id":
        row.deformation_id = row.op_snapshot.id = ""
    elif change == "parameter-family":
        row.op_snapshot.params = m.BendParams(curvature_deg_per_bp=.1, direction_deg=0)
    else:
        row.deformation_id = "different"
    before = deepcopy(design)
    with pytest.raises(RepairInputError):
        plan_actions(design, request(design, *actions).actions, dependencies=dependencies)
    assert design == before


@pytest.mark.parametrize("identity", ["missing-again", "empty", "placement-only"])
def test_invalid_replacement_fails_native_replay_without_alias_or_candidate(identity):
    design = source()
    design.cluster_transforms.append(m.ClusterRigidTransform(id="placement-only", helix_ids=[design.helices[0].id]))
    result = prepare_repair(design, request(design, action(value=identity)), source_revision=7,
        executor=execute, dependency_resolver=dependencies)
    assert result["status"] == "failed" and "candidate" not in result
    assert result["issues"][0]["code"] in {"missing_reference", "invalid_selection"}
    assert result["issues"][0]["feature_id"] == "edited-feature"
    assert result["repair"]["not_evaluated"] == ["later-group"]


def test_stale_reference_picker_refuses_before_prefix_execution(monkeypatch):
    monkeypatch.setattr("backend.api.part_recipe_edit.regenerate", lambda *_a, **_k: pytest.fail("Stale replay"))
    result = select(source(), expected_old="stale")
    assert result["issues"][0]["code"] == "selection_conflict"


def test_multiple_named_slots_can_swap_but_cannot_finish_with_duplicate_selection():
    design = source()
    row = design.feature_log[-2]
    row.op_snapshot.targets = [{"kind": "part_group", "id": "left"}, {"kind": "part_group", "id": "right"}]
    first = action(expected_old="left", value="right")
    second = action(parameter_path=["targets", 1, "id"], expected_old="right", value="left")
    planned = plan_actions(design, request(design, first, second).actions, dependencies=dependencies)
    assert planned[row.id].definition_replacement.op_snapshot.targets == list(reversed(row.op_snapshot.targets))
    with pytest.raises(RepairInputError) as caught:
        plan_actions(design, request(design, first).actions, dependencies=dependencies)
    assert caught.value.code == "invalid_repaired_contract"


def test_group_candidate_inventory_refuses_ambiguity_and_excludes_invalid_or_already_selected_members():
    from backend.core.part_deformation_repair import group_candidates
    from backend.api.part_repair_selection import SelectionRequest
    from backend.core.part_command_errors import ReferenceResolutionError
    from backend.core.part_overlay_commands import command_input

    design = source()
    row = design.feature_log[-2]
    row.op_snapshot.targets.append({"kind": "part_group", "id": "future"})
    body = SelectionRequest(selection_version=1, expected_design_id=design.id, expected_revision=7,
        feature_id=row.id, parameter_path=["targets", 0, "id"], expected_old="missing")
    params = command_input(row)[1]
    candidates, _ = group_candidates(design, params, body, lambda: None)
    assert {candidate["identity"] for candidate in candidates}.isdisjoint({"future", "empty"})
    replacement = next(group for group in design.group_organization.groups if group.id == "replacement")
    replacement.domain_ids[0].strand_id = "gone"
    candidates, _ = group_candidates(design, params, body, lambda: None)
    assert "replacement" not in {candidate["identity"] for candidate in candidates}
    design.group_organization.groups.append(replacement.model_copy(deep=True))
    with pytest.raises(ReferenceResolutionError) as caught:
        group_candidates(design, params, body, lambda: None)
    assert caught.value.code == "invalid_selection"


def test_capture_accepts_only_native_direction_enum_not_arbitrary_string_enums():
    from enum import Enum
    from backend.core.part_repair_capture import _Copier

    class Other(str, Enum):
        FORWARD = "FORWARD"

    assert _Copier(20, 1000, 1).clone(m.Direction.FORWARD) is m.Direction.FORWARD
    with pytest.raises(ValueError, match="typed definitions"):
        _Copier(20, 1000, 1).clone(Other.FORWARD)
