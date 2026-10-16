"""Native staging and metadata-work boundaries, independent of public rollout."""

import pytest

from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import ClusterRigidTransform
from backend.core.part_command_errors import CommandContractError
from backend.core.part_group_organization import build
from tests.test_group_organization_commands import converted, organize, source


def test_organization_execution_does_not_place_reconcile_or_scan_residues(monkeypatch):
    design = source()
    design.helices[0].length_bp = 1_000_000

    def forbidden(*args, **kwargs):
        raise AssertionError("Organization must only inspect bounded membership metadata")

    monkeypatch.setattr("backend.core.cluster_reconcile.reconcile_cluster_membership", forbidden)
    monkeypatch.setattr("backend.core.lattice.retry_pending_ligations", forbidden)
    monkeypatch.setattr("backend.core.design_geometry._geometry_for_design", forbidden)
    monkeypatch.setattr("backend.core.deformation.deformed_helix_axes", forbidden)
    result = execute("group-organize", design, organize(design))
    assert result.group_organization is not None
    assert result.cluster_transforms == design.cluster_transforms
    assert design.group_organization is None


def test_oversized_source_index_refuses_before_traversal():
    class Unvisited(list):
        def __iter__(self):
            raise AssertionError("The item bound must precede iteration")

    design = source().copy_with(helices=Unvisited([None] * 30_001))
    with pytest.raises(CommandContractError) as error:
        build("group-organize", design, organize(design))
    assert error.value.code == "group_organization_limit"


def test_conversion_bounds_nested_source_before_dump_or_member_walk(monkeypatch):
    design = source().copy_with(cluster_transforms=[ClusterRigidTransform(
        id=f"group-{index}", helix_ids=["h0"] * 15_000) for index in range(3)])

    def forbidden(*args, **kwargs):
        raise AssertionError("Source admission must precede model serialization")

    monkeypatch.setattr(ClusterRigidTransform, "model_dump", forbidden)
    with pytest.raises(CommandContractError) as error:
        build("group-organize", design, organize(design))
    assert error.value.code == "group_organization_limit"


def test_shared_member_lists_are_charged_for_each_serialized_group(monkeypatch):
    from backend.core.part_group_model import GroupOrganization, PartGroup

    original = source()
    helices = [original.helices[0].model_copy(update={"id": f"h{index}"}) for index in range(1000)]
    shared = [helix.id for helix in helices]
    groups = [PartGroup(id=f"g{index}").model_copy(update={"helix_ids": shared}) for index in range(100)]
    organization = GroupOrganization(groups=groups)
    assert organization.groups[0].helix_ids is organization.groups[-1].helix_ids
    design = original.copy_with(helices=helices, group_organization=organization)

    def forbidden(*args, **kwargs):
        raise AssertionError("Aliased containers must be charged before expanding them in JSON")

    monkeypatch.setattr(GroupOrganization, "model_dump", forbidden)
    with pytest.raises(CommandContractError) as error:
        build("group-update", design, {"_proof_version": 1, "group_id": "g0", "fields": {"name": "New"}})
    assert error.value.code == "group_organization_limit"


def test_shared_domain_records_cannot_hide_serialized_bytes(monkeypatch):
    from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup

    member = GroupDomainRef(strand_id="s" * 512, domain_index=0)
    organization = GroupOrganization(groups=[PartGroup(id="g", domain_ids=[member] * 1500)])
    design = source().copy_with(group_organization=organization)

    def forbidden(*args, **kwargs):
        raise AssertionError("Repeated domain records must not bypass the byte budget")

    monkeypatch.setattr(GroupOrganization, "model_dump", forbidden)
    with pytest.raises(CommandContractError) as error:
        build("group-update", design, {"_proof_version": 1, "group_id": "g", "fields": {"name": "New"}})
    assert error.value.code == "group_organization_limit"


@pytest.mark.parametrize("extra", [
    {"helix_ids": ["h1"]}, {"domain_ids": []}, {"name": "New"}, {"color": "#abcdef"},
])
def test_legacy_combined_group_patch_cannot_reinterpret_new_organization(monkeypatch, extra):
    design = converted()
    before = design.model_dump(mode="json")

    def forbidden(*args, **kwargs):
        raise AssertionError("Refuse unadapted authoring before the legacy builder")

    monkeypatch.setattr("backend.core.part_overlay_commands.build", forbidden)
    with pytest.raises(CommandContractError) as error:
        execute("cluster_op", design, {"_proof_version": 1, "cluster_id": "placed", **extra})
    assert error.value.code == "unsupported_group_organization_command"
    assert design.model_dump(mode="json") == before


def test_unadapted_legacy_creation_and_generated_conversion_cannot_get_native_proof():
    design = converted()
    with pytest.raises(CommandContractError) as error:
        execute("cluster_create", design, {"_proof_version": 2,
            "cluster": ClusterRigidTransform(id="new", helix_ids=["h0"]).model_dump(mode="json")})
    assert error.value.code == "unsupported_group_organization_command"
    assert not dependencies("group-organize", {**organize(source()), "_generated_scope": {}}).known


def test_attribution_does_not_become_organization_input_or_placement():
    design = source()
    params = {**organize(design), "_generator": {"label": "Native author"}}
    assert dependencies("group-organize", params).known
    attributed = execute("group-organize", design, params)
    assert attributed == build("group-organize", design, organize(design))
