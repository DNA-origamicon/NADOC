"""Display follows native frozen intervals after later topology/group changes."""

from copy import deepcopy

import pytest

from backend.api.part_proof_commands import execute
from backend.core import deformation, design_geometry
from backend.core.models import BendParams, DeformationOp, DeformationRange, Direction
from backend.core.part_command_errors import CommandContractError
from backend.core.part_dna_comparison import project, project_for_deformation_preview
from backend.core.part_dna_comparison_codec import unpack_records
from backend.core.part_dna_comparison_contract import check_scope, inventory
from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup
from tests.test_group_lineage_resize_pipeline import prefix, resize
from tests.test_part_dna_comparison import small, forbid_geometry


def retained_tail():
    source, sid, hid = prefix()
    op = DeformationOp(id="tail-bend", type="bend", plane_a_bp=0, plane_b_bp=24,
        targets=[{"kind": "part_group", "id": "tail"}],
        params=BendParams(curvature_deg_per_bp=0.5))
    before = execute("deformation", source, {**op.model_dump(mode="json"), "_proof_version": 1})
    after = execute("strand-end-resize", before, {**resize(sid, hid, -6), "_proof_version": 1})
    assert after.deformations == before.deformations
    assert next(g for g in after.group_organization.groups if g.id == "tail").domain_ids == []
    return before, after


@pytest.mark.parametrize("stage", ["selected", "later-trim"])
@pytest.mark.parametrize("preview", [False, True])
def test_complete_native_display_retains_groups_and_historical_ranges(stage, preview):
    before, after = retained_tail()
    design = before if stage == "selected" else after
    original = design.model_dump_json()
    projected = (project_for_deformation_preview if preview else project)(design)
    assert projected["component_version"] == (2 if preview else 3)
    assert projected["display_topology"]["group_organization"] == design.group_organization.model_dump(mode="json")
    assert projected["display_topology"]["deformations"][0]["target_ranges"] == before.deformations[0].model_dump(mode="json")["target_ranges"]
    records = design_geometry._geometry_for_design(design)
    axes = deformation._apply_ovhg_rotations_to_axes(design, deformation.deformed_helix_axes(design), records)
    assert unpack_records(projected["nucleotides"]) == records
    assert projected["helix_axes"] == axes
    assert design.model_dump_json() == original
    projected["display_topology"]["group_organization"]["groups"].clear()
    assert design.model_dump_json() == original


def test_historical_primitive_address_is_not_a_live_domain_reference():
    design = small("bend")
    op = design.deformations[0]
    design.deformations = [op.model_copy(update={
        "targets": [{"kind": "domain", "strand_id": "earlier-strand", "domain_index": 9}],
        "target_ranges": [DeformationRange(helix_id="h0", direction=Direction.FORWARD,
            start_bp=0, end_bp=11, strand_id="earlier-strand", domain_index=9)]})]
    result = project(design)
    assert unpack_records(result["nucleotides"]) == design_geometry._geometry_for_design(design)
    assert result["display_topology"]["deformations"][0]["target_ranges"][0]["strand_id"] == "earlier-strand"


@pytest.mark.parametrize("invalid", ["missing-group", "live-domain", "group-version", "duplicate-group", "style", "too-many-members", "range-pair", "range-direction", "range-order", "range-helix", "range-address"])
def test_live_members_and_frozen_interval_grammar_still_refuse_before_geometry(invalid, monkeypatch):
    design, _ = retained_tail()
    design = deepcopy(design)
    group = next(g for g in design.group_organization.groups if g.id == "tail")
    if invalid == "missing-group":
        design.group_organization.groups.remove(group)
    elif invalid == "live-domain":
        group.domain_ids = [GroupDomainRef(strand_id="missing", domain_index=0)]
    elif invalid == "group-version":
        design.group_organization.version = True
    elif invalid == "duplicate-group":
        design.group_organization.groups.append(group)
    elif invalid == "style":
        group.opacity = float("nan")
    elif invalid == "too-many-members":
        group.helix_ids *= 513
    else:
        target = design.deformations[0].target_ranges[0]
        if invalid == "range-pair": target.domain_index = None
        elif invalid == "range-direction": target.direction = "FORWARD"
        elif invalid == "range-order": target.start_bp = target.end_bp + 1
        elif invalid == "range-helix": target.helix_id = "missing"
        else: target.start_bp = -(10**9)
    forbid_geometry(monkeypatch)
    with pytest.raises(CommandContractError):
        project(design)


def test_organization_and_numerical_placement_namespaces_stay_distinct():
    design = small("cluster")
    design.group_organization = GroupOrganization(groups=[PartGroup(id="parent", name="Selection", helix_ids=["h0"])])
    result = inventory(design)
    assert result.indices["cluster_transforms"]["parent"].translation == [3, 2, -1]
    assert result.indices["group_organization"]["parent"].name == "Selection"
    display = project(design)["display_topology"]
    assert display["group_organization"]["groups"][0]["id"] == display["cluster_transforms"][0]["id"]


def test_lock_owned_scope_preflight_does_not_serialize_group_metadata(monkeypatch):
    design = small("cluster")
    design.group_organization = GroupOrganization(groups=[PartGroup(id="selection", helix_ids=["h0"])])
    monkeypatch.setattr(GroupOrganization, "model_dump", lambda *_a, **_k: pytest.fail("Serialization under capture lock"))
    assert check_scope(design)["group_organization"]["selection"].helix_ids == ["h0"]


def test_group_identity_retains_its_schema_limit_without_widening_other_resources():
    design = small("cluster")
    identity = "g" * 512
    design.group_organization = GroupOrganization(groups=[PartGroup(id=identity, helix_ids=["h0"])])
    assert project(design)["display_topology"]["group_organization"]["groups"][0]["id"] == identity
