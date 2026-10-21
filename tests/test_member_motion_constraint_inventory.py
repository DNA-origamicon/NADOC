"""Named membership is not authorization to move native constrained companions."""
import pytest

from backend.core.flexible_segments import all_cluster_gates
from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup
from tests.test_part_transform_constraint_history import constraint_recipe
from tests.test_part_member_motion_order import D, _nucleotide
from tools.member_motion_ordering_program import compile_ordered_probe, existing_material_union


@pytest.mark.parametrize("kind", ["flexible", "joint"])
def test_named_members_remain_distinct_from_native_linked_and_fixed_owners(kind):
    source, ids = constraint_recipe(kind, suffix=False)
    owners = {owner.id: owner for owner in source.cluster_transforms}
    primary = owners[ids["primary"]]
    source = source.copy_with(group_organization=GroupOrganization(groups=[PartGroup(
        id=primary.id, helix_ids=primary.helix_ids,
        domain_ids=[GroupDomainRef(strand_id=ref.strand_id, domain_index=ref.domain_index)
                    for ref in primary.domain_ids])]))
    captured = source.model_dump_json()
    selected = existing_material_union(source, [{"kind": "part_group", "id": primary.id}])
    owner_selected = existing_material_union(source, [{"kind": "cluster", "id": primary.id}])
    assert selected == owner_selected and selected
    for role in ("auxiliary", "fixed"):
        companion = existing_material_union(source, [{"kind": "cluster", "id": ids[role]}])
        assert companion and not set(companion).intersection(selected)
    assert all_cluster_gates(source)[primary.id]["gate"]
    assert {frozenset((edge.cluster_a_id, edge.cluster_b_id)) for edge in source.flexible_connections} == {
        frozenset((primary.id, ids["auxiliary"])), frozenset((ids["auxiliary"], ids["fixed"]))}
    definition = source.feature_log[-1].params
    assert definition["selected_cluster_ids"] == [primary.id]
    assert {pose["cluster_id"] for pose in definition["poses"]} == {primary.id, ids["auxiliary"]}
    assert definition["authoring"]["fixed_cluster_ids"] == [ids["fixed"]]
    # Native owner gestures explicitly carry the auxiliary pose. An equal-member
    # named selection has no such authored constraint contract yet; do not infer it.
    helix, bp, direction, copy = selected[0]
    target = {"kind": "base", "helix_id": helix, "bp_index": bp, "direction": direction, "copy_k": copy}
    later = _nucleotide(source, target, D, "later-residue", compose=True)
    with pytest.raises(ValueError, match="Companion, constraint and birth policy"):
        compile_ordered_probe(source, later.feature_log[-1], primary.helix_ids,
                              named_targets=[{"kind": "part_group", "id": primary.id}])
    assert source.model_dump_json() == captured
