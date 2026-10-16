"""Named organization consumers retain editable inputs without placement aliases."""

import pytest

from backend.api.part_proof_commands import dependencies, execute
from backend.core import models as m
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_dependencies import Resource
from backend.core.part_group_organization import build
from backend.core.part_structure import assess_structure
from tests.test_group_organization_commands import converted
from tests.test_group_organization_history import _append, _edit, _verified, history


def operation(identity="regrouped", *, kind="twist", cluster_ids=()):
    return m.DeformationOp(id="group-deformation", type=kind, plane_a_bp=1, plane_b_bp=9,
        targets=[{"kind": "part_group", "id": identity}], cluster_ids=list(cluster_ids),
        params={"kind": kind, **({"total_degrees": 8} if kind == "twist" else
                                 {"curvature_deg_per_bp": .25, "direction_deg": 20})})


def append_deformation(design, op):
    result = _append(design, m.DeformationLogEntry(id="group-deformation-row",
        deformation_id=op.id, op_snapshot=op, proof_version=1))
    result.feature_log[-1] = result.feature_log[-1].model_copy(
        update={"op_snapshot": result.deformations[-1]})
    return result


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_named_selection_rebuilds_after_upstream_membership_edit_and_cold_reload(kind):
    design, _ = history()
    current = append_deformation(design, operation(kind=kind))
    original = current.model_dump(mode="json")
    before_ranges = current.deformations[-1].target_ranges
    _verified(current)
    other = design.strands[1]
    changed = _edit(current, 6, {"fields": {"helix_ids": [], "domain_ids": [
        {"strand_id": other.id, "domain_index": 0}]}})
    op = changed.deformations[-1]
    assert op.targets == [{"kind": "part_group", "id": "regrouped"}]
    assert op.cluster_ids == []
    assert op.target_ranges != before_ranges
    assert {r.strand_id for r in op.target_ranges} == {other.id}
    assert changed.cluster_transforms == current.cluster_transforms
    _verified(m.Design.model_validate_json(changed.model_dump_json()))
    assert current.model_dump(mode="json") == original


def test_dissolve_reports_named_deformation_consumer_before_changing_organization():
    design = converted()
    op = operation("placed", cluster_ids=["placed"])
    current = execute("deformation", design, {**op.model_dump(mode="json"), "_proof_version": 1})
    before = current.model_dump(mode="json")
    with pytest.raises(ReferenceResolutionError) as error:
        build("group-dissolve", current, {"_proof_version": 1, "group_ids": ["placed"]})
    assert error.value.code == "invalid_selection"
    assert any(r["kind"] == "part_group" and r["identity"] == "placed"
               for r in error.value.references)
    assert current.model_dump(mode="json") == before
    # Removing the named consumer leaves the independent placement reference.
    fixed = current.copy_with(deformations=[current.deformations[-1].model_copy(
        update={"targets": None})])
    removed = build("group-dissolve", fixed, {"_proof_version": 1, "group_ids": ["placed"]})
    assert removed.cluster_transforms == fixed.cluster_transforms
    assert removed.deformations == fixed.deformations


def test_structure_reports_missing_named_group_independently_of_equal_placement_id():
    design = converted().copy_with(deformations=[operation("placed")])
    assert assess_structure(design)["status"] == "valid"
    organization = design.group_organization.model_copy(update={"groups": [
        g for g in design.group_organization.groups if g.id != "placed"]})
    report = assess_structure(design.copy_with(group_organization=organization))
    assert report["status"] == "invalid"
    assert any(i.get("reference") == {"kind": "part_group", "identity": "placed"}
               for i in report["issues"])


def test_group_reference_dependencies_are_separate_from_placement_context():
    op = operation("placed", cluster_ids=["placed"])
    contract = dependencies("deformation", {**op.model_dump(mode="json"), "_proof_version": 1})
    assert contract.known and contract.barrier
    assert {Resource("part_group", "placed"), Resource("cluster", "placed")} <= contract.reads


def test_partial_named_selection_refuses_loop_realization_before_native_work(monkeypatch):
    from backend.api.part_loop_commands import plan

    design, _ = history()
    current = append_deformation(design, operation())

    def forbidden(*args, **kwargs):
        raise AssertionError("Partial organization scope must refuse before native loop planning")

    monkeypatch.setattr("backend.core.loop_skip_calculator.clear_loop_skips", forbidden)
    with pytest.raises(CommandContractError) as error:
        plan(current)
    assert error.value.code == "unsupported_partial_group_realization"


def test_named_consumer_scan_is_bounded_before_target_iteration():
    class Unvisited(list):
        def __iter__(self):
            raise AssertionError("Target count must be admitted before iteration")

    design = converted()
    op = operation("placed").model_copy(update={"targets": Unvisited([None] * 30_001)})
    with pytest.raises(CommandContractError) as error:
        build("group-dissolve", design.copy_with(deformations=[op]),
              {"_proof_version": 1, "group_ids": ["placed"]})
    assert error.value.code == "group_consumer_limit"


@pytest.mark.parametrize("target", [
    {"kind": "domain", "strandId": "s0", "domain_index": 0},
    {"kind": "domain", "strand_id": "s0", "domainIndex": False, "ui_label": "Legacy"},
])
def test_legacy_selector_grammar_is_unchanged_after_organization_conversion(target):
    op = operation("placed").model_copy(update={"targets": [target]})
    params = {**op.model_dump(mode="json"), "_proof_version": 1}
    assert dependencies("deformation", params).known
    design = execute("deformation", converted(), params)
    assert assess_structure(design)["status"] == "valid"
    result = build("group-dissolve", design, {"_proof_version": 1, "group_ids": ["placed"]})
    assert result.deformations == design.deformations


def test_whole_helix_realization_bounds_derived_affected_ids_before_set_construction():
    from backend.core.part_group_consumers import require_whole_helix_realization

    class Unvisited(list):
        def __iter__(self):
            raise AssertionError("Affected count must precede set construction")

    design = converted()
    op = operation("placed")
    design = execute("deformation", design, {**op.model_dump(mode="json"), "_proof_version": 1})
    op = design.deformations[-1].model_copy(update={"affected_helix_ids": Unvisited(["h0"] * 30_001)})
    with pytest.raises(CommandContractError) as error:
        require_whole_helix_realization(design.copy_with(deformations=[op]))
    assert error.value.code == "group_consumer_limit"


@pytest.mark.parametrize("placements", ["placed", [True], [""], ["p"] * 30_001])
def test_named_dependency_placement_context_is_typed_and_bounded(placements):
    params = {**operation("placed").model_dump(mode="json"), "_proof_version": 1,
              "cluster_ids": placements}
    assert dependencies("deformation", params).known is False


def test_later_group_and_topology_edits_keep_already_evaluated_ranges_frozen():
    design, _ = history()
    current = append_deformation(design, operation())
    frozen = current.deformations[-1].model_dump(mode="json")
    params = {"_proof_version": 1, "helix_id": current.helices[0].id,
              "bp_index": 5, "direction": "FORWARD"}
    current = execute("nick", current, params)
    assert current.deformations[-1].model_dump(mode="json") == frozen
    current = execute("ligate", current, params)
    assert current.deformations[-1].model_dump(mode="json") == frozen
    current = build("group-update", current, {"_proof_version": 1, "group_id": "regrouped",
        "fields": {"helix_ids": [current.helices[1].id], "domain_ids": []}})
    assert current.deformations[-1].model_dump(mode="json") == frozen
