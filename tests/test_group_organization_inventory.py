"""Independent organization identities must never alias numerical placement."""

from copy import deepcopy

import pytest


def source():
    from backend.core import models as m
    from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup

    return m.Design(
        helices=[m.Helix(id="h", axis_start=m.Vec3(x=0, y=0, z=0),
                        axis_end=m.Vec3(x=0, y=0, z=2), length_bp=6)],
        strands=[m.Strand(id="s", domains=[m.Domain(
            helix_id="h", start_bp=0, end_bp=5, direction=m.Direction.FORWARD)])],
        cluster_transforms=[m.ClusterRigidTransform(id="same", name="Placement",
            helix_ids=["h"], translation=[3, 2, 1], pivot=[1, 0, 0])],
        group_organization=GroupOrganization(version=1, groups=[PartGroup(
            id="same", name="Organization", helix_ids=["h"],
            domain_ids=[GroupDomainRef(strand_id="s", domain_index=0)])]),
    )


def test_organization_is_complete_authoring_and_capture_is_independently_owned():
    from backend.core.part_history_contract import FIELD_ROLES
    from backend.core.part_history_proof import AUTHORING_FIELDS
    from backend.core.part_verification_capture import capture

    design = source()
    assert FIELD_ROLES["group_organization"] == "authoring"
    assert "group_organization" in AUTHORING_FIELDS
    captured = capture(design, seconds=10)
    assert captured.group_organization == design.group_organization
    captured.group_organization.groups[0].helix_ids.append("private")
    assert design.group_organization.groups[0].helix_ids == ["h"]


def test_same_text_group_and_placement_have_distinct_typed_identities_and_owners():
    from backend.core.part_scope_references import identity_index

    design = source()
    records, owners = identity_index(design)
    assert records["cluster", "same"] is design.cluster_transforms[0]
    assert records["part_group", "same"] is design.group_organization.groups[0]
    assert owners["part_group", "same"] == ("part_group", "same")


def test_group_and_wrapper_references_are_declared_not_opaque_metadata():
    from backend.core.part_scope_references import referenced_resources

    design = source()
    expected = frozenset({("helix", "h"), ("strand", "s")})
    assert referenced_resources(design.group_organization.groups[0]) == expected
    assert referenced_resources(design.group_organization) == expected


def test_duplicate_group_ids_fail_without_confusing_the_placement_namespace():
    from backend.core.part_command_errors import ReferenceResolutionError
    from backend.core.part_scope_references import identity_index

    design = source()
    design.group_organization.groups.append(design.group_organization.groups[0].model_copy(deep=True))
    with pytest.raises(ReferenceResolutionError) as caught:
        identity_index(design)
    assert caught.value.as_issue()["references"][0]["kind"] == "part_group"


def test_remap_carries_version_members_and_independent_group_identity_without_pose_alias():
    from backend.core.part_scope_references import remap_design

    design = source()
    before = deepcopy(design)
    mapped = remap_design(design, {("part_group", "same"): "selected",
                                  ("helix", "h"): "h2", ("strand", "s"): "s2"})
    assert mapped.group_organization.version == 1
    group = mapped.group_organization.groups[0]
    assert group.id == "selected" and group.helix_ids == ["h2"]
    assert group.domain_ids[0].strand_id == "s2"
    assert mapped.cluster_transforms[0].id == "same"
    assert mapped.cluster_transforms[0].translation == [3, 2, 1]
    assert mapped.cluster_transforms[0].helix_ids == ["h2"]
    group.helix_ids.append("isolated")
    assert design == before


@pytest.mark.parametrize("version", [True, 2])
def test_unreviewed_organization_version_fails_before_identity_or_remap(version):
    from backend.core.part_scope_references import identity_index, remap_design

    design = source()
    design.group_organization = design.group_organization.model_copy(update={"version": version})
    for function in (identity_index, lambda value: remap_design(value, {})):
        with pytest.raises(NotImplementedError, match="organization"):
            function(design)


def test_legacy_none_keeps_existing_structure_shape_and_does_not_walk_strands():
    from backend.core.part_structure import assess_structure

    class Untouched(list):
        def __iter__(self):
            raise AssertionError("Legacy structure must not acquire a new strand walk")

    design = source().model_copy(update={"group_organization": None, "strands": Untouched()})
    report = assess_structure(design)
    assert report["status"] == "valid"
    assert report["checked_counts"] == {"clusters": 1, "frames": 0, "helices": 1}


def test_structure_checks_new_members_without_serializing_or_placing(monkeypatch):
    from backend.core.models import Design
    from backend.core.part_group_model import GroupOrganization, PartGroup
    from backend.core.part_structure import assess_structure

    design = source()
    before = deepcopy(design)

    def forbidden(*args, **kwargs):
        raise AssertionError("Structure is a bounded reference check, not geometry or serialization")

    for model in (Design, GroupOrganization, PartGroup):
        monkeypatch.setattr(model, "model_dump", forbidden)
        monkeypatch.setattr(model, "model_validate", forbidden)
    monkeypatch.setattr("backend.core.geometry.nucleotide_positions_arrays", forbidden)
    report = assess_structure(design)
    assert report["status"] == "valid" and report["complete"]
    assert not report["scientific_integrity_checked"]
    assert report["checked_counts"]["part_groups"] == 1
    assert design == before


@pytest.mark.parametrize("target", ["helix", "strand", "domain"])
def test_structural_missing_group_members_are_typed_and_gate_publication(target):
    from backend.core.part_structure import assess_structure
    from backend.core.part_structure_gate import PartStructureError, require_valid_structure

    design = source()
    group = design.group_organization.groups[0]
    if target == "helix":
        group.helix_ids[:] = ["gone"]
    elif target == "strand":
        group.domain_ids[0] = group.domain_ids[0].model_copy(update={"strand_id": "gone"})
    else:
        group.domain_ids[0] = group.domain_ids[0].model_copy(update={"domain_index": 9})
    report = assess_structure(design)
    assert report["status"] == "invalid" and report["complete"]
    assert any(issue["resource"] == {"kind": "part_group", "identity": "same"}
               and issue.get("reference", {}).get("kind") == target
               for issue in report["issues"])
    with pytest.raises(PartStructureError):
        require_valid_structure(design)


def test_duplicate_strand_cannot_satisfy_an_ordinal_group_domain_reference():
    from backend.core.part_structure import assess_structure

    design = source()
    design.strands.append(design.strands[0].model_copy(deep=True))
    report = assess_structure(design)
    assert report["status"] == "invalid"
    assert any(issue["code"] == "ambiguous_reference"
               and issue.get("reference") == {"kind": "strand", "identity": "s"}
               for issue in report["issues"])


def test_group_reference_allowance_refuses_before_member_iteration():
    from backend.core.part_structure import assess_structure

    class Untouched(list):
        def __iter__(self):
            raise AssertionError("Over-budget member list must not be traversed")

    design = source()
    design.group_organization.groups[0].helix_ids = Untouched(["h"] * 8)
    report = assess_structure(design, max_items=4)
    assert report["status"] == "incomplete" and not report["complete"]
    assert report["issues"] == []


def test_structure_unknown_regime_is_incomplete_and_cancellation_propagates():
    from backend.core.part_structure import assess_structure

    design = source()
    unsupported = design.model_copy(update={"group_organization": {"version": 1, "groups": []}})
    assert assess_structure(unsupported)["status"] == "incomplete"
    calls = []

    def cancel():
        calls.append(True)
        if len(calls) == 5:
            raise ValueError("cancelled")

    with pytest.raises(ValueError, match="cancelled"):
        assess_structure(design, checkpoint=cancel)


def test_unbounded_domain_ordinal_is_not_formatted_into_a_diagnostic():
    from backend.core.part_structure import assess_structure

    design = source()
    group = design.group_organization.groups[0]
    group.domain_ids[0] = group.domain_ids[0].model_copy(update={"domain_index": 1 << 128})
    report = assess_structure(design)
    assert report["status"] == "incomplete"
    assert report["limit"]["code"] == "structure_identity_limit"
    assert str(1 << 128) not in repr(report)


def test_legacy_group_dissolve_refuses_separate_organization_before_inventory(monkeypatch):
    from backend.core import part_group_dissolve as dissolve
    from backend.core.part_command_errors import CommandContractError

    def forbidden():
        raise AssertionError("Legacy dissolution must refuse before its metadata inventory")

    monkeypatch.setattr(dissolve, "_check_inventory_contract", forbidden)
    with pytest.raises(CommandContractError, match="organization"):
        dissolve.build(source(), {"_proof_version": 1, "cluster_ids": ["same"]})


def test_unadapted_protein_removal_refuses_separate_organization_before_reference_walk(monkeypatch):
    from backend.api import part_protein_conjugate_lifecycle as lifecycle
    from backend.core.part_command_errors import CommandContractError
    from backend.core import part_scope_references as scope

    def forbidden(*args):
        raise AssertionError("Unreviewed removal must not skip organization references")

    monkeypatch.setattr(scope, "referenced_resources", forbidden)
    with pytest.raises(CommandContractError, match="organization"):
        lifecycle._delete_closure(source(), None, None)


@pytest.mark.parametrize("entry", ["execute", "selection"])
def test_generated_scope_refuses_new_regime_before_inventory_or_builder(monkeypatch, entry):
    from backend.api import generated_native_scope as scope

    def forbidden(*args, **kwargs):
        raise AssertionError("Unsupported organization must refuse before generated work")

    design = source()
    monkeypatch.setattr(scope, "identity_index", forbidden)
    with pytest.raises(NotImplementedError, match="organization"):
        if entry == "execute":
            scope.execute("group-update", design, {}, forbidden)
        else:
            scope._selection(design, "owner", [])


@pytest.mark.parametrize("which", ["destination", "before", "after"])
def test_generated_merge_never_drops_or_implicitly_composes_new_regime(monkeypatch, which):
    from backend.api import generated_native_scope as scope

    design = source()
    legacy = design.model_copy(update={"group_organization": None})
    arguments = dict.fromkeys(("destination", "before", "after"), legacy)
    arguments[which] = design
    before = deepcopy(design)
    with pytest.raises(NotImplementedError, match="organization"):
        scope.merge_changes(**arguments)
    assert design == before
