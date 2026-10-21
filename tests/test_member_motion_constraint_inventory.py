"""Named membership is not authorization to move native constrained companions."""
from copy import deepcopy

import numpy as np
import pytest

from backend.api import part_proof_commands as commands
from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.flexible_segments import all_cluster_gates
from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup
from tests.test_part_transform_constraint_history import constraint_recipe
from tests.test_part_member_motion_order import D, _nucleotide, _rigid
from tools.member_motion_ordering_program import _key, compile_ordered_probe, existing_material_union


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


@pytest.mark.parametrize("include_auxiliary", [False, True])
def test_native_authored_poses_move_only_explicit_owners_not_constraint_neighbors(include_auxiliary):
    """Command replay consumes poses, not the tether graph or a constraint solver.

    These deliberately authored poses characterize the command boundary; their
    existence does not prove mechanical feasibility or qualify a drag gesture.
    """
    source, ids = constraint_recipe("flexible", suffix=False)
    captured = source.model_dump_json()
    definition = deepcopy(source.feature_log[-1].params)
    poses = {pose["cluster_id"]: pose for pose in definition["poses"]}
    poses[ids["primary"]].update(translation=[.2, -.4, .7], pivot=[1, -2, .5],
                               rotation=[0, 0, 2**-.5, 2**-.5])
    poses[ids["auxiliary"]].update(translation=[-.3, .6, -.1], pivot=[-1, 2, .3],
                                 rotation=[2**-.5, 0, 0, 2**-.5])
    if not include_auxiliary:
        poses.pop(ids["auxiliary"])
    definition["poses"] = list(poses.values())
    roles = {role: set(existing_material_union(source, [{"kind": "cluster", "id": identity}]))
             for role, identity in ids.items()}
    result = commands.execute("placement-poses", source.model_copy(deep=True), definition)
    before_full, after_full = _geometry_for_design(source), _geometry_for_design(result)
    before_atoms, after_atoms = (build_atomistic_model(value, fast_bridges=True) for value in (source, result))
    assert before_atoms.bonds == after_atoms.bonds
    for before, actual in zip(before_full, after_full, strict=True):
        role = next(role for role, keys in roles.items() if _key(before) in keys)
        pose = poses.get(ids[role])
        if pose is None:
            assert actual == before
        else:
            for field in ("backbone_position", "base_position", "slab_position"):
                np.testing.assert_allclose(actual[field], _rigid(before[field], pose), rtol=0, atol=1e-10)
    for before, actual in zip(before_atoms.atoms, after_atoms.atoms, strict=True):
        role = next(role for role, keys in roles.items() if _key(before) in keys)
        pose = poses.get(ids[role])
        if pose is None:
            assert actual == before
        else:
            np.testing.assert_allclose([actual.x, actual.y, actual.z],
                                      _rigid([before.x, before.y, before.z], pose), rtol=0, atol=1e-10)
    assert source.model_dump_json() == captured
