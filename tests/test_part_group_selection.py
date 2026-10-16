"""Named organization selections remain distinct from native placement owners.

Small owned inputs only: no host publication, disk, worker, or scientific run.
The independent native resolver remains the oracle for existing scope semantics.
"""

from copy import deepcopy
from importlib import import_module

import pytest

from backend.core import models as m
from backend.core.deformation_scope import resolve_deformation_targets as native_targets
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError
from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup
from backend.core.part_overlay_commands import build


def selection():
    return import_module("backend.core.part_group_selection")


def source():
    return m.Design(id="selection-source", helices=[m.Helix(
        id=f"h{i}", length_bp=12, axis_start=m.Vec3(x=3 * i, y=0, z=0),
        axis_end=m.Vec3(x=3 * i, y=0, z=3.74)) for i in range(2)],
        strands=[
            m.Strand(id="s0", domains=[m.Domain(helix_id="h0", start_bp=0,
                end_bp=5, direction=m.Direction.FORWARD)]),
            m.Strand(id="r0", domains=[m.Domain(helix_id="h0", start_bp=0,
                end_bp=11, direction=m.Direction.REVERSE)]),
            m.Strand(id="s1", domains=[m.Domain(helix_id="h1", start_bp=0,
                end_bp=11, direction=m.Direction.FORWARD)]),
        ], cluster_transforms=[m.ClusterRigidTransform(id="same", helix_ids=["h1"],
            translation=[2, 1, 0])],
        group_organization=GroupOrganization(groups=[
            PartGroup(id="same", name="Selection", helix_ids=["h0"]),
            PartGroup(id="domain", helix_ids=["h1"],
                domain_ids=[GroupDomainRef(strand_id="s0", domain_index=0)]),
            PartGroup(id="empty"),
        ]))


def params(targets=None, **changes):
    return {"_proof_version": 1, "id": "twist", "type": "twist",
        "plane_a_bp": 0, "plane_b_bp": 11, "affected_helix_ids": [],
        "cluster_ids": [], "targets": targets if targets is not None else [
            {"kind": "part_group", "id": "same"}], "target_ranges": None,
        "params": {"kind": "twist", "total_degrees": 30, "degrees_per_nm": None},
        **changes}


def ranges(values):
    return [value.model_dump(mode="json") for value in values]


def test_legacy_native_selection_control_includes_unoccupied_partner_and_domain_precedence():
    design = source()
    whole = native_targets(design, [{"kind": "cluster", "id": "same"}])
    assert [(r.helix_id, r.start_bp, r.end_bp, r.direction) for r in whole] == [
        ("h1", 0, 11, m.Direction.FORWARD), ("h1", 0, 11, m.Direction.REVERSE)]
    assert native_targets(design, [{"kind": "domain", "strand_id": "s0",
                                    "domain_index": 0}])[0].end_bp == 5


def test_whole_group_resolves_full_native_span_without_placement_alias_or_source_mutation():
    design = source()
    before = deepcopy(design)
    targets = [{"kind": "part_group", "id": "same"}]
    result = selection().resolve_deformation_targets(design, targets)
    oracle = design.copy_with(cluster_transforms=[m.ClusterRigidTransform(
        id="oracle", helix_ids=["h0"])])
    assert ranges(result) == ranges(native_targets(oracle, [{"kind": "cluster", "id": "oracle"}]))
    assert design == before and targets == [{"kind": "part_group", "id": "same"}]
    result[0].start_bp = 99
    assert design == before


def test_domain_group_uses_native_direction_interval_and_domain_precedence():
    design = source()
    result = selection().resolve_deformation_targets(design, [{"kind": "part_group", "id": "domain"}])
    expected = native_targets(design, [{"kind": "domain", "strand_id": "s0", "domain_index": 0}])
    assert ranges(result) == ranges(expected)
    assert result[0].helix_id == "h0" and result[0].direction == m.Direction.FORWARD


def test_mixed_targets_deduplicate_same_domain_without_losing_opposite_direction():
    design = source()
    result = selection().resolve_deformation_targets(design, [
        {"kind": "part_group", "id": "domain"},
        {"kind": "domain", "strandId": "s0", "domainIndex": 0},
        {"kind": "strand", "id": "r0"},
    ])
    assert ranges(result) == ranges(native_targets(design, [
        {"kind": "domain", "strand_id": "s0", "domain_index": 0},
        {"kind": "strand", "id": "r0"},
    ]))


def test_existing_cluster_and_primitive_selection_delegate_unchanged():
    design = source().copy_with(group_organization=None)
    targets = [{"kind": "cluster", "id": "same"},
               {"kind": "domain", "strandId": "s0", "domainIndex": 0}]
    assert ranges(selection().resolve_deformation_targets(design, targets)) == ranges(native_targets(design, targets))


@pytest.mark.parametrize("state", [None, True, 2])
def test_new_target_requires_explicit_supported_organization(state):
    design = source()
    design.group_organization = (None if state is None else
        design.group_organization.model_copy(update={"version": state}))
    with pytest.raises(CommandContractError):
        selection().resolve_deformation_targets(design, [{"kind": "part_group", "id": "same"}])


@pytest.mark.parametrize("targets", [
    [], [{"kind": "part_group", "id": "same", "placement_id": "same"}],
    [{"kind": "part_group", "id": ""}], [{"kind": "part_group", "id": True}],
    [{"kind": "part_group", "id": "same"}] * 2,
    [{"kind": "part_group", "id": "same"},
     {"kind": "domain", "strand_id": "s0", "domain_index": True}],
    [{"kind": "part_group", "id": "same"},
     {"kind": "domain", "strandId": "s0", "domain_index": 0}],
    [{"kind": "part_group", "id": "same"}, {"kind": "future_group", "id": "same"}],
])
def test_closed_target_grammar_rejects_ambiguous_or_empty_selection(targets):
    with pytest.raises(CommandContractError):
        selection().resolve_deformation_targets(source(), targets)


@pytest.mark.parametrize("failure", ["missing", "empty", "duplicate", "helix", "strand", "domain"])
def test_invalid_named_membership_is_typed_and_never_falls_back_to_placement_or_all(failure):
    design = source()
    target = "same"
    if failure == "missing":
        design.group_organization.groups = [item for item in design.group_organization.groups if item.id != "same"]
    elif failure == "empty":
        target = "empty"
    elif failure == "duplicate":
        design.group_organization.groups.append(design.group_organization.groups[0].model_copy(deep=True))
    elif failure == "helix":
        design.group_organization.groups[0].helix_ids = ["gone"]
    else:
        target = "domain"
        ref = GroupDomainRef(strand_id="gone" if failure == "strand" else "s0",
                             domain_index=50 if failure == "domain" else 0)
        design.group_organization.groups[1].domain_ids = [ref]
    before = deepcopy(design)
    with pytest.raises(ReferenceResolutionError) as caught:
        selection().resolve_deformation_targets(design, [{"kind": "part_group", "id": target}])
    assert caught.value.as_issue()["references"]
    assert design == before


def test_source_item_bound_precedes_inventory_iteration():
    class Unvisited(list):
        def __iter__(self):
            raise AssertionError("Source count must be admitted before traversal")

    design = source().model_copy(update={"helices": Unvisited([None] * 30_001)})
    with pytest.raises(CommandContractError):
        selection().resolve_deformation_targets(design, [{"kind": "part_group", "id": "same"}])


def test_nested_member_budget_precedes_native_resolution_or_geometry(monkeypatch):
    design = source()
    shared = [GroupDomainRef(strand_id="s0", domain_index=0)] * 12_000
    design.group_organization.groups = [PartGroup(id=f"g{i}").model_copy(update={"domain_ids": shared})
                                        for i in range(3)]

    def forbidden(*args, **kwargs):
        raise AssertionError("Expanded membership must be admitted before native resolution")

    monkeypatch.setattr("backend.core.deformation_scope.resolve_deformation_targets", forbidden)
    with pytest.raises(CommandContractError):
        selection().resolve_deformation_targets(design, [{"kind": "part_group", "id": "g0"}])


def test_checkpoint_exception_propagates_without_a_partial_result():
    error = TypeError("selection cancelled")

    def stop():
        raise error

    with pytest.raises(TypeError) as caught:
        selection().resolve_deformation_targets(source(), [{"kind": "part_group", "id": "same"}], checkpoint=stop)
    assert caught.value is error


def test_overlay_preserves_typed_provenance_and_separate_explicit_placement_context():
    design = source()
    arguments = params(cluster_ids=["same"])
    before = deepcopy(design)
    result = build("deformation", design, arguments)
    op = result.deformations[-1]
    assert op.targets == [{"kind": "part_group", "id": "same"}]
    assert op.cluster_ids == ["same"] and op.affected_helix_ids == ["h0"]
    assert {r.helix_id for r in op.target_ranges} == {"h0"}
    assert result.cluster_transforms == design.cluster_transforms
    assert design == before and arguments == params(cluster_ids=["same"])
    implicit = build("deformation", design, params()).deformations[-1]
    assert implicit.cluster_ids == []  # Equal text is never inferred as placement.


def test_replaying_group_membership_change_resolves_current_named_group_and_replaces_saved_ranges():
    from backend.core.part_group_organization import build as edit_group
    from backend.core.part_overlay_commands import command_input

    design = source()
    first = build("deformation", design, params()).deformations[-1]
    entry = m.DeformationLogEntry(id="feature", proof_version=1, deformation_id=first.id, op_snapshot=first)
    edited = edit_group("group-update", design, {"_proof_version": 1,
        "group_id": "same", "fields": {"helix_ids": ["h1"]}})
    kind, arguments = command_input(entry)
    replayed = build(kind, edited, arguments).deformations[-1]
    assert first.affected_helix_ids == ["h0"]
    assert replayed.targets == first.targets and replayed.affected_helix_ids == ["h1"]
    assert {r.helix_id for r in replayed.target_ranges} == {"h1"}
    assert entry.op_snapshot == first and edited.deformations == []


def test_named_group_replay_does_not_validate_obsolete_derived_helix_ids_before_resolution():
    arguments = params(affected_helix_ids=["removed-old-member"], target_ranges=[{
        "helix_id": "removed-old-member", "start_bp": 0, "end_bp": 4,
        "direction": "FORWARD", "strand_id": None, "domain_index": None}])
    result = build("deformation", source(), arguments).deformations[-1]
    assert result.affected_helix_ids == ["h0"]
    assert {item.helix_id for item in result.target_ranges} == {"h0"}


@pytest.mark.parametrize("kind", ["bend", "twist"])
def test_actual_native_arrays_and_axes_match_explicit_equivalent_scope(kind):
    from backend.core.deformation import deformed_helix_axes, deformed_nucleotide_arrays
    import numpy as np

    design = source()
    arguments = params(type=kind, targets=[{"kind": "part_group", "id": "domain"}],
        params=({"kind": "bend", "curvature_deg_per_bp": 1, "direction_deg": 25}
                if kind == "bend" else {"kind": "twist", "total_degrees": 30}))
    actual = build("deformation", design, arguments)
    reference = build("deformation", design, {**arguments,
        "targets": [{"kind": "domain", "strand_id": "s0", "domain_index": 0}]})
    assert deformed_helix_axes(actual) == deformed_helix_axes(reference)
    for helix in design.helices:
        lhs, rhs = deformed_nucleotide_arrays(helix, actual), deformed_nucleotide_arrays(helix, reference)
        for field in ("positions", "base_positions", "base_normals", "axis_tangents"):
            np.testing.assert_array_equal(lhs[field], rhs[field])


def test_reference_inventory_and_remap_distinguish_equal_group_and_placement_ids():
    from backend.core.part_scope_references import referenced_resources, remap_design

    design = source()
    op = m.DeformationOp.model_validate({key: value for key, value in params(cluster_ids=["same"]).items()
                                       if key != "_proof_version"})
    assert {("part_group", "same"), ("cluster", "same")} <= referenced_resources(op)
    design = design.copy_with(deformations=[op])
    mapped = remap_design(design, {("part_group", "same"): "selected"})
    assert mapped.deformations[0].targets == [{"kind": "part_group", "id": "selected"}]
    assert mapped.deformations[0].cluster_ids == ["same"]
    assert mapped.cluster_transforms[0].id == "same"
    assert design.deformations[0].targets[0]["id"] == "same"


def test_source_free_reference_contract_has_closed_distinct_namespaces():
    refs = selection().target_references([{"kind": "part_group", "id": "same"},
        {"kind": "cluster", "id": "same"},
        {"kind": "domain", "strand_id": "s0", "domain_index": 0}])
    assert refs == frozenset({("part_group", "same"), ("cluster", "same"), ("strand", "s0")})
    assert selection().target_references(None) == frozenset()


def test_native_dependencies_include_named_group_and_placement_separately():
    from backend.api.part_proof_commands import dependencies
    from backend.core.part_dependencies import Resource

    contract = dependencies("deformation", params(cluster_ids=["same"]))
    assert contract.known and contract.barrier
    assert {Resource("part_group", "same"), Resource("cluster", "same")} <= contract.reads


def test_registered_native_execution_qualifies_typed_group_selection_without_public_gate():
    from backend.api.part_proof_commands import execute

    result = execute("deformation", source(), params())
    assert result.deformations[-1].targets == [{"kind": "part_group", "id": "same"}]
    assert result.deformations[-1].affected_helix_ids == ["h0"]


def test_named_group_removal_with_a_live_deformation_consumer_is_not_silently_accepted():
    from backend.api.part_proof_commands import execute

    design = build("deformation", source(), params())
    before = deepcopy(design)
    with pytest.raises(ReferenceResolutionError):
        execute("group-dissolve", design, {"_proof_version": 1, "group_ids": ["same"]})
    assert design == before
