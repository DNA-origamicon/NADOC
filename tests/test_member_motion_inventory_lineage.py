"""Existing-material inventory consumes established native lineage, not a new policy.

These checks resolve selection at the supplied edited prefix. They do not
reinterpret a motion that happened earlier or assign frames to later births.
"""
import pytest

from backend.core.constants import BDNA_RISE_PER_BP as RISE
from backend.core.models import ClusterRigidTransform, Direction
from backend.core.part_command_errors import ReferenceResolutionError
from tests.test_part_group_lineage import (
    api, finish, grouped, native_nick, source, strand_at,
)
from tools.member_motion_ordering_program import existing_material_union


def selected(design, *identities):
    return existing_material_union(design, [
        {"kind": "part_group", "id": identity} for identity in identities])


@pytest.mark.parametrize("end", ["start", "end"])
@pytest.mark.parametrize("detach", [False, True])
def test_sweep_prefix_selects_old_material_after_native_domain_ordinal_changes(end, detach):
    from backend.core.sweep import SweepRequest, build_sweep

    design = source()
    strand = strand_at(design, Direction.FORWARD)
    design = grouped(design, [[(strand.id, 0)], [(strand.id, 0)]], whole=True)
    old = selected(design, "g0", "g1")
    captured = design.model_dump_json()
    sign = 1 if end == "end" else -1
    body = SweepRequest(cells=[(0, 0)], points_nm=[(0, 0, 0), (0, 0, sign * 7 * RISE)],
                        source_helix_id=design.helices[0].id, source_end=end,
                        detach_source=detach, ligate_adjacent=False)
    plan = api().prepare_lineage(design, "sweep", body.model_dump(mode="json"))
    result = api().apply_lineage(plan, finish(design, build_sweep(design, body)))
    actual = selected(result, "g0", "g1")
    fresh_helices = {h.id for h in result.helices} - {h.id for h in design.helices}
    assert fresh_helices
    assert len(actual) == len(set(actual)) == 21
    assert set(actual) == set(old)
    assert not fresh_helices.intersection(key[0] for key in actual)
    assert design.model_dump_json() == captured


@pytest.mark.parametrize("direction", list(Direction))
def test_nick_prefix_preserves_exact_selected_material_across_native_children(direction):
    design = source()
    strand = strand_at(design, direction)
    design = grouped(design, [[(strand.id, 0)], [(strand.id, 0)]])
    old = selected(design, "g0", "g1")
    plan = api().prepare_lineage(design, "nick", {
        "helix_id": design.helices[0].id, "bp_index": 8, "direction": direction.value})
    result = api().apply_lineage(plan, finish(design, native_nick(design, direction)))
    assert len(result.group_organization.groups[0].domain_ids) == 2
    actual = selected(result, "g0", "g1")
    assert len(actual) == len(set(actual)) == 21
    assert set(actual) == set(old)


@pytest.mark.parametrize("direction", list(Direction))
def test_merge_prefix_uses_native_whole_descendant_membership_once(direction):
    from backend.api.crud import NickRequest
    from backend.api.part_ligation_commands import ligate

    design = native_nick(source(), direction)
    pieces = [s for s in design.strands if s.domains[0].direction == direction]
    design = grouped(design, [[(pieces[0].id, 0)], [(pieces[1].id, 0)]])
    old = selected(design, "g0")
    assert len(old) < 21
    body = NickRequest(helix_id=design.helices[0].id, bp_index=8, direction=direction)
    plan = api().prepare_lineage(design, "ligate", body.model_dump(mode="json"))
    result = api().apply_lineage(plan, finish(design, ligate(design, body)))
    first, second, union = selected(result, "g0"), selected(result, "g1"), selected(result, "g0", "g1")
    assert first == second == union and len(union) == 21
    assert set(old) < set(union)  # Current membership, not retroactive motion of this new material.


@pytest.mark.parametrize("missing", [False, True], ids=["empty", "dissolved"])
def test_empty_or_dissolved_named_reference_never_falls_back_to_equal_text_owner(missing):
    design = grouped(source(), [[]])
    design.group_organization.groups[0].helix_ids = []
    design.cluster_transforms.append(ClusterRigidTransform(id="g0", helix_ids=[design.helices[0].id]))
    if missing:
        design.group_organization.groups = []
    captured = design.model_dump_json()
    with pytest.raises(ReferenceResolutionError):
        selected(design, "g0")
    assert design.model_dump_json() == captured
