"""Finite group dissolution preserves native placement or refuses atomically.

Pure command tests: no sessions, files, stored-recovery decoding or solvers.
"""

from importlib import import_module

import pytest

from backend.core import models as m
from backend.core.part_command_errors import CommandContractError, ReferenceResolutionError


def native():
    return import_module("backend.core.part_group_dissolve")


def source():
    helices = [m.Helix(id=f"h{i}", axis_start=m.Vec3(x=3 * i, y=0, z=0),
        axis_end=m.Vec3(x=3 * i, y=0, z=1.7), length_bp=6) for i in range(2)]
    strands = [m.Strand(id=f"s{i}", domains=[m.Domain(helix_id=h.id,
        start_bp=0, end_bp=5, direction=m.Direction.FORWARD)]) for i, h in enumerate(helices)]
    return m.Design(helices=helices, strands=strands, cluster_transforms=[
        m.ClusterRigidTransform(id="group-a", name="First", helix_ids=["h0"]),
        m.ClusterRigidTransform(id="group-b", name="Second", helix_ids=["h1"]),
    ])


def request(*ids):
    return {"_proof_version": 1, "cluster_ids": list(ids or ("group-a",))}


def rejected(design, params=None):
    before = design.model_dump(mode="json")
    with pytest.raises(CommandContractError) as error:
        native().build(design, params if params is not None else request())
    assert design.model_dump(mode="json") == before
    return error.value.as_issue()


def test_atomic_batch_preserves_source_unrelated_order_and_all_authoring():
    design = source()
    overlap = m.ClusterRigidTransform(id="overlap", helix_ids=["h0"])
    design = design.copy_with(cluster_transforms=[*design.cluster_transforms, overlap])
    before = design.model_dump(mode="json")
    result = native().build(design, request("overlap", "group-a"))
    assert native().KIND == "cluster-dissolve"
    assert [group.id for group in result.cluster_transforms] == ["group-b"]
    assert result.cluster_transforms[0] is design.cluster_transforms[1]
    expected = {**before, "cluster_transforms": [before["cluster_transforms"][1]]}
    assert result.model_dump(mode="json") == expected
    assert design.model_dump(mode="json") == before


def test_identity_dissolution_matches_native_nucleotide_and_axes_geometry():
    from backend.core.deformation import deformed_helix_axes, deformed_nucleotide_arrays
    import numpy as np

    design = source()
    before = [deformed_nucleotide_arrays(helix, design) for helix in design.helices]
    axes = deformed_helix_axes(design)
    result = native().build(design, request())
    after = [deformed_nucleotide_arrays(helix, result) for helix in result.helices]
    for old, new in zip(before, after, strict=True):
        for field in ("positions", "base_positions", "base_normals", "axis_tangents"):
            np.testing.assert_allclose(old[field], new[field], rtol=0, atol=1e-12)
    assert deformed_helix_axes(result) == axes


@pytest.mark.parametrize("params", [
    {}, {"cluster_ids": ["group-a"]}, request("group-a", "group-a"),
    {"_proof_version": True, "cluster_ids": ["group-a"]},
    {"_proof_version": 2, "cluster_ids": ["group-a"]},
    {"_proof_version": 1, "cluster_ids": []},
    {"_proof_version": 1, "cluster_ids": "group-a"},
    {"_proof_version": 1, "cluster_ids": [None]},
    {"_proof_version": 1, "cluster_ids": ["g" * 513]},
    {"_proof_version": 1, "cluster_ids": [str(i) for i in range(129)]},
    {**request(), "candidate": {}},
    {**request(), "_generated_scope": {}},
])
def test_closed_command_refuses_malformed_or_unbounded_inputs(params):
    rejected(source(), params)


@pytest.mark.parametrize("case", ["missing", "ambiguous", "batch-one-missing"])
def test_missing_and_ambiguous_targets_are_typed_atomic_failures(case):
    design = source()
    params = request("missing") if case == "missing" else request()
    if case == "ambiguous":
        design = design.copy_with(cluster_transforms=[*design.cluster_transforms,
            design.cluster_transforms[0].model_copy(deep=True)])
    elif case == "batch-one-missing":
        params = request("group-a", "missing")
    issue = rejected(design, params)
    assert issue["code"] == ("invalid_selection" if case == "ambiguous" else "missing_reference")
    assert issue["references"][0]["kind"] == "cluster"
    assert issue["references"][0]["parameter_path"][0] == "cluster_ids"


def _incoming(design, family):
    target = "group-a"
    if family == "frame":
        from backend.core.lattice_frame_model import LatticeFrame
        frame = LatticeFrame(id="frame", placement_cluster_id=target)
        return design.copy_with(lattice_frames=[frame]), "lattice_frames"
    if family == "child":
        child = design.cluster_transforms[1].model_copy(update={"parent_cluster_id": target})
        return design.copy_with(cluster_transforms=[design.cluster_transforms[0], child]), "cluster_transforms"
    if family == "joint":
        return design.copy_with(cluster_joints=[m.ClusterJoint(id="joint", cluster_id=target)]), "cluster_joints"
    if family == "join":
        endpoint = m.JoinEndpoint(helix_id="h0", bp_index=1, direction=m.Direction.FORWARD)
        attachment = m.JoinAttachment(cluster_id=target, source=endpoint, target=endpoint)
        return design.copy_with(cluster_join_constraints=[m.ClusterJoinConstraint(
            id="join", first=attachment, second=attachment, reach_nm=1)]), "cluster_join_constraints"
    if family == "flexible":
        anchor = m.FlexibleAnchor(strand_id="s0", domain_index=0, bp_index=1,
            direction=m.Direction.FORWARD)
        connection = m.FlexibleConnection(id="flex", cluster_a_id=target,
            cluster_b_id="group-b", anchor_a=anchor, anchor_b=anchor,
            n_ss_bases=1, contour_length_nm=1)
        return design.copy_with(flexible_connections=[connection]), "flexible_connections"
    op = m.DeformationOp(id="bend", type="bend", plane_a_bp=0, plane_b_bp=5,
        affected_helix_ids=["h1"], params=m.BendParams(curvature_deg_per_bp=1))
    op = op.model_copy(update={"cluster_ids": [target]} if family == "deformation-id" else {
        "targets": [{"kind": "cluster", "id": target}]})
    return design.copy_with(deformations=[op]), "deformations"


@pytest.mark.parametrize("family", ["frame", "child", "joint", "join", "flexible", "deformation-id", "deformation-target"])
def test_each_live_incoming_family_reports_typed_owner_and_model_path(family):
    design, field = _incoming(source(), family)
    issue = rejected(design)
    assert issue["code"] == "invalid_selection"
    refs = issue["references"]
    assert any(ref["kind"] == "cluster" and ref["identity"] == "group-a"
        and ref["model_path"][0] == field and ref["owner"]["kind"] for ref in refs)


@pytest.mark.parametrize("change", [
    {"translation": [1, 0, 0]}, {"rotation": [0, 0, 0.1, 0.995]},
    {"pivot": [float("nan"), 0, 0]}, {"rotation": [0, 0, 0, 0]},
    {"pivot": [1, 0, 0]}, {"pivot": [1e308, 0, 0]},
    {"parent_cluster_id": "group-b"}, {"overhang_duplex_driver_id": "driver"},
])
def test_pose_or_special_owner_refuses_without_baking_or_replacement_group(change):
    design = source()
    design = design.copy_with(cluster_transforms=[
        design.cluster_transforms[0].model_copy(update=change), design.cluster_transforms[1]])
    # Nonfinite malformed sources cannot be compared through JSON's NaN equality.
    original = design.cluster_transforms[0]
    with pytest.raises(CommandContractError):
        native().build(design, request())
    assert design.cluster_transforms[0] is original and len(design.cluster_transforms) == 2


@pytest.mark.parametrize("affected", [[], ["h0"]])
def test_implicit_deformation_arm_dependency_refuses_even_identity_group(affected):
    design = source().copy_with(deformations=[m.DeformationOp(type="twist", plane_a_bp=0,
        plane_b_bp=5, affected_helix_ids=affected, params=m.TwistParams(total_degrees=20))])
    rejected(design)


def test_unaffected_deformation_and_disjoint_remaining_pose_are_preserved():
    design = source()
    design = design.copy_with(deformations=[m.DeformationOp(type="twist", plane_a_bp=0,
        plane_b_bp=5, affected_helix_ids=["h1"], params=m.TwistParams(total_degrees=20))],
        cluster_transforms=[design.cluster_transforms[0],
            design.cluster_transforms[1].model_copy(update={"translation": [1, 0, 0]})])
    result = native().build(design, request())
    assert result.deformations is design.deformations
    assert result.cluster_transforms == [design.cluster_transforms[1]]


def test_remaining_posed_group_on_same_helix_refuses_first_group_branch_change():
    design = source()
    design = design.copy_with(cluster_transforms=[design.cluster_transforms[0],
        design.cluster_transforms[1].model_copy(update={"helix_ids": ["h0"], "translation": [1, 0, 0]})])
    rejected(design)


def test_empty_identity_group_and_negative_identity_quaternion_are_supported():
    design = source()
    design = design.copy_with(cluster_transforms=[design.cluster_transforms[0].model_copy(update={
        "helix_ids": [], "rotation": [0, 0, 0, -1], "pivot": [10, 20, 30]}),
        design.cluster_transforms[1]])
    result = native().build(design, request())
    assert [group.id for group in result.cluster_transforms] == ["group-b"]


def test_presentation_and_historical_strings_are_not_live_references():
    design = source().copy_with(
        annotations=[m.Annotation(text="group-a", refs=[{"kind": "cluster", "id": "group-a"}])],
        visibility_state=m.VisibilityState(hidden_cluster_ids=["group-a"]))
    result = native().build(design, request())
    assert result.annotations is design.annotations
    assert result.visibility_state is design.visibility_state


def test_no_history_physical_atoms_or_geometry_access(monkeypatch):
    from backend.core import deformation

    class NeverIterated(list):
        def __iter__(self):
            raise AssertionError("Unrelated materialization must not be traversed")

    design = source().model_copy(update={"feature_log": NeverIterated([object()]),
        "atomistic_reference": object()})
    monkeypatch.setattr(deformation, "deformed_nucleotide_arrays", lambda *_a, **_k: pytest.fail("no geometry"))
    result = native().build(design, request())
    assert result.feature_log is design.feature_log
    assert result.atomistic_reference is design.atomistic_reference


def test_source_collection_overflow_refuses_before_iteration():
    class NeverIterated(list):
        def __iter__(self):
            raise AssertionError("Collection count must be admitted before scan")

    design = source().model_copy(update={"cluster_joints": NeverIterated([None] * 30_001)})
    with pytest.raises(CommandContractError):
        native().build(design, request())


def test_saved_topology_unknown_fields_refuse_instead_of_becoming_no_reference():
    duplex = m.Duplex(id="duplex", left=m.DuplexEnd(overhang_id="left", start_bp=0, end_bp=1),
        right=m.DuplexEnd(overhang_id="right", start_bp=0, end_bp=1),
        prior_driven_topology={"future_cluster_owner": "group-a"})
    rejected(source().copy_with(duplexes=[duplex]))


def test_schema_evolution_cannot_add_an_unseen_cluster_reference(monkeypatch):
    from dataclasses import replace
    from backend.core import part_scope_references

    schema = part_scope_references.SCHEMAS[m.ClusterRigidTransform]
    monkeypatch.setitem(part_scope_references.SCHEMAS, m.ClusterRigidTransform,
        replace(schema, refs={**schema.refs, "name": "cluster"}, plain=schema.plain - {"name"}))
    design = source()
    design = design.copy_with(cluster_transforms=[design.cluster_transforms[0],
        design.cluster_transforms[1].model_copy(update={"name": "group-a"})])
    with pytest.raises(CommandContractError):
        native().build(design, request())


def test_failure_has_native_reference_error_type():
    with pytest.raises(ReferenceResolutionError):
        native().build(source(), request("missing"))


def test_omitted_collection_cannot_gain_nested_known_cluster_owner(monkeypatch):
    from copy import copy

    # Protein attachments are deliberately omitted from the group-owner walk.
    # A future typed target reaching an already-known JoinAttachment must force
    # contract review even though no NEW direct cluster-reference class exists.
    field = copy(m.ProteinAttachment.model_fields["target"])
    field.annotation = m.JoinAttachment
    monkeypatch.setitem(m.ProteinAttachment.model_fields, "target", field)
    with pytest.raises(CommandContractError):
        native().build(source(), request())


def test_new_authoring_collection_requires_reference_contract_review(monkeypatch):
    design = source()
    module = native()
    monkeypatch.setitem(m.Design.model_fields, "future_owners", m.Design.model_fields["cluster_transforms"])
    monkeypatch.setattr(module, "FIELD_ROLES", {**module.FIELD_ROLES, "future_owners": "authoring"})
    with pytest.raises(CommandContractError):
        module.build(design, request())


def test_existing_external_protein_target_has_no_part_group_reference():
    attachment = m.ProteinAttachment(asset_id="asset", target=m.ProteinTargetAssembly(
        instance_id="group-a", interface_label="group-a", overhang_id="group-a"))
    design = source().copy_with(protein_attachments=[attachment])
    result = native().build(design, request())
    assert [group.id for group in result.cluster_transforms] == ["group-b"]
    assert result.protein_attachments[0] is attachment


def test_external_leaf_cannot_gain_nested_cluster_owner(monkeypatch):
    from copy import copy

    field = copy(m.ProteinTargetAssembly.model_fields["interface_label"])
    field.annotation = m.JoinAttachment
    monkeypatch.setitem(m.ProteinTargetAssembly.model_fields, "interface_label", field)
    with pytest.raises(CommandContractError):
        native().build(source(), request())


def test_deformation_target_kind_is_bounded_before_classification():
    op = m.DeformationOp(type="twist", plane_a_bp=0, plane_b_bp=5,
        affected_helix_ids=["h1"], params=m.TwistParams(total_degrees=20))
    op = op.model_copy(update={"targets": [{"kind": "x" * 513, "id": "unrelated"}]})
    issue = rejected(source().copy_with(deformations=[op]))
    assert issue["code"] == "group_dissolve_limit"


def test_remaining_repivoted_group_on_same_scope_is_not_assumed_ineffective():
    design = source()
    design = design.copy_with(cluster_transforms=[design.cluster_transforms[0],
        design.cluster_transforms[1].model_copy(update={"helix_ids": ["h0"], "pivot": [1, 0, 0]})])
    rejected(design)
