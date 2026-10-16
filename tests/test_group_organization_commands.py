"""Organization can change without replacing ordered native placement owners.

Tiny, memory-only fixtures derive native coordinates independently. No sampled
geometry is stored in command inputs, and no recovery payload supplies proof.
"""

from importlib import import_module

import pytest

from backend.core import models as m
from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_command_errors import CommandContractError


GROUP_FIELDS = {
    "id", "name", "helix_ids", "domain_ids", "color", "opacity",
    "is_default", "auto_created",
}
CASES = ("posed", "domain", "child", "overlap", "deformation", "frame")


def native():
    return import_module("backend.core.part_group_organization")


def source(case="posed"):
    helices = [m.Helix(id=f"h{i}", length_bp=12,
        axis_start=m.Vec3(x=3 * i, y=0, z=0),
        axis_end=m.Vec3(x=3 * i, y=0, z=3.74)) for i in range(2)]
    strands = [m.Strand(id=f"s{i}", domains=[m.Domain(
        helix_id=helix.id, start_bp=0, end_bp=11, direction=m.Direction.FORWARD)])
        for i, helix in enumerate(helices)]
    placements = [
        m.ClusterRigidTransform(id="default", name="Unassigned", is_default=True,
            auto_created=True, helix_ids=["h1"]),
        m.ClusterRigidTransform(id="placed", name="Arm", helix_ids=["h0"],
            translation=[2, -1, 3], rotation=[0, 0, 0.6, 0.8], pivot=[1, 0, 0],
            color="#123456", opacity=0.4),
    ]
    if case in {"domain", "child"}:
        placements.append(m.ClusterRigidTransform(
            id="local", name="Domain pose", helix_ids=["h0"],
            domain_ids=[m.DomainRef(strand_id="s0", domain_index=0)],
            translation=[0, 2, 1], rotation=[0.6, 0, 0, 0.8], pivot=[0, 1, 0],
            parent_cluster_id="placed" if case == "child" else None))
    if case == "overlap":
        placements.append(m.ClusterRigidTransform(id="overlap", name="Second pose",
            helix_ids=["h0"], translation=[-1, 2, 0], rotation=[0, 0.6, 0, 0.8]))
    design = m.Design(id="organization-fixture", helices=helices, strands=strands,
        cluster_transforms=placements)
    if case == "deformation":
        design = design.copy_with(deformations=[m.DeformationOp(
            id="bend", type="bend", plane_a_bp=1, plane_b_bp=9,
            affected_helix_ids=["h0"], cluster_ids=["placed"],
            params=m.BendParams(curvature_deg_per_bp=1, direction_deg=25))])
    if case == "frame":
        design = design.copy_with(lattice_frames=[m.LatticeFrame(
            id="frame", placement_cluster_id="placed")])
    return design


def organize(design):
    return {"_proof_version": 1,
        "expected_placement_ids": [placement.id for placement in design.cluster_transforms]}


def group(identity="regrouped", **fields):
    return {"id": identity, "name": "Regrouped", "helix_ids": ["h0", "h1"],
        "domain_ids": [], "color": None, "opacity": 1.0,
        "is_default": False, "auto_created": False, **fields}


def converted(case="posed"):
    design = source(case)
    return native().build("group-organize", design, organize(design))


def unchanged_native(before, after):
    # Includes placement order, parent/default roles, retained frame/deformation
    # references, topology, physical state, history and document metadata.
    assert after.model_dump(mode="json", exclude={"group_organization"}) == before.model_dump(
        mode="json", exclude={"group_organization"})
    assert _geometry_for_design(after) == _geometry_for_design(before)
    assert deformed_helix_axes(after) == deformed_helix_axes(before)


def rejected(kind, design, params):
    before = design.model_dump(mode="json")
    with pytest.raises(CommandContractError) as caught:
        native().build(kind, design, params)
    assert design.model_dump(mode="json") == before
    return caught.value.as_issue()


@pytest.mark.parametrize("case", CASES)
def test_reference_fixture_roundtrips_and_has_real_native_pose(case):
    """Independent controls must pass before the new command module exists."""
    design = source(case)
    loaded = m.Design.model_validate_json(design.model_dump_json())
    assert loaded == design
    assert len(_geometry_for_design(design)) == 24
    assert deformed_helix_axes(design)
    rest = design.copy_with(cluster_transforms=[], deformations=[], lattice_frames=[])
    assert _geometry_for_design(design) != _geometry_for_design(rest)


@pytest.mark.parametrize("case", CASES)
def test_conversion_posed_dissolve_regroup_keeps_actual_geometry_and_owners(case):
    original = source(case)
    before = original.model_dump(mode="json")
    current = native().build("group-organize", original, organize(original))
    assert current.group_organization.version == 1
    assert [item.model_dump(mode="json") for item in current.group_organization.groups] == [
        item.model_dump(mode="json", include=GROUP_FIELDS) for item in original.cluster_transforms]
    unchanged_native(original, current)

    # A former wrapper can disappear even when its retained placement has
    # frame/child/deformation consumers. Those consumers still name the owner.
    current = native().build("group-dissolve", current,
        {"_proof_version": 1, "group_ids": ["placed"]})
    assert "placed" not in {item.id for item in current.group_organization.groups}
    assert next(item for item in current.cluster_transforms if item.id == "placed") == original.cluster_transforms[1]
    unchanged_native(original, current)

    current = native().build("group-create", current,
        {"_proof_version": 1, "group": group()})
    assert current.group_organization.groups[-1].model_dump(mode="json") == group()
    unchanged_native(original, current)
    current = native().build("group-update", current,
        {"_proof_version": 1, "group_id": "regrouped", "fields": {
            "name": "Domain selection", "helix_ids": ["h0"],
            "domain_ids": [{"strand_id": "s1", "domain_index": 0}],
            "color": "#abcdef", "opacity": 0.25}})
    selected = current.group_organization.groups[-1]
    assert selected.name == "Domain selection" and selected.opacity == 0.25
    assert selected.helix_ids == ["h0"]
    assert [ref.model_dump() for ref in selected.domain_ids] == [{"strand_id": "s1", "domain_index": 0}]
    unchanged_native(original, current)
    assert m.Design.model_validate_json(current.model_dump_json()) == current
    assert original.model_dump(mode="json") == before


def test_organization_is_explicit_and_empty_state_never_recreates_groups():
    original = source()
    assert original.group_organization is None
    current = native().build("group-organize", original, organize(original))
    current = native().build("group-dissolve", current,
        {"_proof_version": 1, "group_ids": ["default", "placed"]})
    assert current.group_organization.groups == []
    loaded = m.Design.model_validate_json(current.model_dump_json())
    assert loaded.group_organization.groups == []
    unchanged_native(original, loaded)
    rejected("group-organize", loaded, organize(loaded))


@pytest.mark.parametrize("kind,params", [
    ("group-create", {"_proof_version": 1, "group": group()}),
    ("group-update", {"_proof_version": 1, "group_id": "placed", "fields": {"name": "New"}}),
    ("group-dissolve", {"_proof_version": 1, "group_ids": ["placed"]}),
])
def test_legacy_regime_cannot_be_implicitly_converted(kind, params):
    rejected(kind, source(), params)


@pytest.mark.parametrize("ids", [[], ["placed", "default"], ["default"],
    ["default", "placed", "foreign"], ["default", "default"], "default", [True]])
def test_conversion_requires_exact_ordered_placement_selection(ids):
    rejected("group-organize", source(), {"_proof_version": 1, "expected_placement_ids": ids})


@pytest.mark.parametrize("version", [None, True, 2, "1"])
def test_conversion_never_coerces_or_infers_contract_version(version):
    params = organize(source())
    if version is None:
        params.pop("_proof_version")
    else:
        params["_proof_version"] = version
    rejected("group-organize", source(), params)


def test_conversion_refuses_duplicate_placement_identity_without_mutation():
    design = source()
    design = design.copy_with(cluster_transforms=[*design.cluster_transforms, design.cluster_transforms[-1]])
    rejected("group-organize", design, organize(design))


@pytest.mark.parametrize("field,value", [
    ("translation", [1, 2, 3]), ("rotation", [0, 0, 0, 1]),
    ("pivot", [1, 2, 3]), ("parent_cluster_id", "placed"),
    ("overhang_duplex_driver_id", "driver"), ("opacity", float("nan")),
    ("id", ""), ("name", 7), ("color", "red"),
    ("domain_ids", [{"strand_id": "s0", "domain_index": True}]),
])
def test_group_definition_is_closed_metadata_not_a_second_placement(field, value):
    rejected("group-create", converted(),
        {"_proof_version": 1, "group": group(**{field: value})})


@pytest.mark.parametrize("fields", [
    {"translation": [1, 0, 0]}, {"id": "other"}, {"is_default": True},
    {"auto_created": True}, {"name": None}, {"helix_ids": ["h0", "h0"]},
    {"domain_ids": [{"strand_id": "s0", "domain_index": 0}] * 2},
])
def test_update_rejects_pose_identity_role_or_ambiguous_membership(fields):
    rejected("group-update", converted(),
        {"_proof_version": 1, "group_id": "placed", "fields": fields})


@pytest.mark.parametrize("fields,kind,identity,path", [
    ({"helix_ids": ["absent"]}, "helix", "absent", ["fields", "helix_ids", 0]),
    ({"domain_ids": [{"strand_id": "absent", "domain_index": 0}]},
     "strand", "absent", ["fields", "domain_ids", 0]),
    ({"domain_ids": [{"strand_id": "s0", "domain_index": 1}]},
     "strand", "s0", ["fields", "domain_ids", 0]),
])
def test_missing_members_are_typed_actionable_reference_failures(fields, kind, identity, path):
    issue = rejected("group-update", converted(),
        {"_proof_version": 1, "group_id": "placed", "fields": fields})
    assert issue["code"] in {"missing_reference", "invalid_selection"}
    assert {"kind": kind, "identity": identity, "parameter_path": path} in issue["references"]


def test_group_namespace_never_resolves_a_retained_placement_as_organization():
    design = converted()
    design = native().build("group-dissolve", design,
        {"_proof_version": 1, "group_ids": ["placed"]})
    issue = rejected("group-update", design,
        {"_proof_version": 1, "group_id": "placed", "fields": {"name": "Wrong owner"}})
    assert issue["code"] == "missing_reference"
    assert {"kind": "part_group", "identity": "placed", "parameter_path": ["group_id"]} in issue["references"]
    restored = native().build("group-create", design,
        {"_proof_version": 1, "group": group("placed")})
    unchanged_native(design, restored)
    assert restored.group_organization.groups[-1].helix_ids == ["h0", "h1"]


def test_atomic_multi_dissolve_refuses_missing_member_without_partial_result():
    issue = rejected("group-dissolve", converted(),
        {"_proof_version": 1, "group_ids": ["placed", "absent"]})
    assert issue["code"] == "missing_reference"
    assert {"kind": "part_group", "identity": "absent", "parameter_path": ["group_ids", 1]} in issue["references"]


def test_registered_native_recipe_cold_replays_with_poisoned_recovery_and_detects_tamper():
    from backend.api.crud import BundleRequest
    from backend.api.part_proof_commands import dependencies, execute
    from backend.core.part_dependencies import Resource
    from backend.core.part_history_contract import assess_part_history, create_empty_part
    from backend.core.part_overlay_commands import command_input

    def append(design, entry):
        kind, params = command_input(entry)
        result = execute(kind, design, params)
        return result.copy_with(id=design.id, recipe_root=design.recipe_root,
            feature_log=[*design.feature_log, entry])

    design = create_empty_part("Organization proof", "HONEYCOMB")
    params = BundleRequest(cells=[[0, 0], [0, 1]], length_bp=12,
        name="Organization proof", history_seed="feee59bc-a093-4a31-a9ba-d993c8f5eb3a").model_dump(mode="json")
    design = append(design, m.SnapshotLogEntry(op_kind="bundle-create", label="Bundle",
        params={**params, "_proof_version": 1}, design_snapshot_gz_b64="poisoned-before",
        post_state_gz_b64="poisoned-after"))
    placement = m.ClusterRigidTransform(id="placed", name="Arm", helix_ids=[design.helices[0].id])
    design = append(design, m.ClusterCreateLogEntry(cluster_id=placement.id, name=placement.name,
        helix_ids=placement.helix_ids, cluster_snapshot=placement, proof_version=2))
    design = append(design, m.ClusterOpLogEntry(cluster_id=placement.id, proof_version=1,
        translation=[2, -1, 3], rotation=[0, 0, 0.6, 0.8], pivot=[1, 0, 0]))
    original = design
    inputs = [
        ("group-organize", organize(design)),
        ("group-dissolve", {"_proof_version": 1, "group_ids": [placement.id]}),
        ("group-create", {"_proof_version": 1, "group": group(
            helix_ids=[helix.id for helix in design.helices])}),
        ("group-update", {"_proof_version": 1, "group_id": "regrouped",
            "fields": {"name": "Editable organization", "color": "#abcdef"}}),
    ]
    for kind, params in inputs:
        contract = dependencies(kind, params)
        assert contract.known, (kind, contract)
        if kind in {"group-create", "group-update"}:
            assert Resource("part_group", "regrouped") in contract.writes
        design = append(design, m.SnapshotLogEntry(op_kind=kind, label=kind,
            params=params, design_snapshot_gz_b64="poisoned-before", post_state_gz_b64="poisoned-after"))
    assert design.cluster_transforms == original.cluster_transforms
    assert _geometry_for_design(design) == _geometry_for_design(original)
    assert deformed_helix_axes(design) == deformed_helix_axes(original)
    loaded = m.Design.model_validate_json(design.model_dump_json())
    report = assess_part_history(loaded, execute=execute, dependencies=dependencies)
    assert report["status"] == "verified", report
    assert report["checked_commands"] == 7
    assert report["native_editable"] is True
    groups = list(loaded.group_organization.groups)
    groups[-1] = groups[-1].model_copy(update={"name": "Unlogged replacement"})
    tampered = loaded.copy_with(group_organization=loaded.group_organization.model_copy(update={"groups": groups}))
    failed = assess_part_history(tampered, execute=execute, dependencies=dependencies)
    assert failed["status"] != "verified"
    assert any(issue["code"] == "authoring_state_mismatch" for issue in failed["issues"]), failed
