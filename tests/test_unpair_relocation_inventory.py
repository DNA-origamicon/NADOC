"""Scaffold retains its address regardless of which partner the user moves."""
from uuid import UUID

import pytest

from backend.core.models import Direction, LoopSkip, StrandType
from tests.test_part_member_motion_order import _source, _target, _nucleotide, D
from tools.unpair_topology_probe import staple_relocation_inventory

SEED = str(UUID(int=31001))


@pytest.mark.parametrize("moved_direction", list(Direction))
def test_relocation_role_does_not_follow_which_partner_was_moved(moved_direction):
    source = _source()
    _, target = _target(source, moved_direction)
    source = _nucleotide(source, target, D, "move")
    before = source.model_dump_json()
    selected = (target["helix_id"], 3, moved_direction.value, 0)
    report = staple_relocation_inventory(source, [selected], identity_seed=SEED)
    [row] = report["relocations"]
    assert row["scaffold"]["identity"]["strand_type"] == "scaffold"
    assert row["staple"]["identity"]["strand_type"] == "staple"
    assert row["scaffold"]["key"][0] == target["helix_id"]
    assert row["new_staple_key"][0] != target["helix_id"]
    assert row["new_staple_key"][1:] == row["staple"]["key"][1:]
    assert source.model_dump_json() == before


def test_copy_identity_and_register_survive_deterministic_relocation_inventory():
    source = _source()
    helix = source.helices[0]
    source = source.copy_with(helices=[
        h.model_copy(update={"loop_skips": [LoopSkip(bp_index=3, delta=1)]})
        if h.id == helix.id else h for h in source.helices
    ])
    keys = [(helix.id, bp, "FORWARD", copy) for bp, copy in [(2, 0), (3, 0), (3, 1)]]
    first = staple_relocation_inventory(source, keys, identity_seed=SEED)
    second = staple_relocation_inventory(source, list(reversed(keys)), identity_seed=SEED)
    assert first == second
    assert len(first["relocations"]) == 3
    assert len({r["new_staple_key"][0] for r in first["relocations"]}) == 1
    assert {(r["new_staple_key"][1], r["new_staple_key"][3])
            for r in first["relocations"]} == {(2, 0), (3, 0), (3, 1)}


@pytest.mark.parametrize("role", [StrandType.SCAFFOLD, StrandType.STAPLE,
                                 StrandType.LINKER, StrandType.OH_BINDER])
def test_ambiguous_or_special_pair_roles_refuse_instead_of_guessing(role):
    source = _source()
    hid = source.helices[0].id
    source = source.copy_with(strands=[s.model_copy(update={"strand_type": role})
                                      for s in source.strands])
    before = source.model_dump_json()
    with pytest.raises(ValueError, match="one scaffold and one staple"):
        staple_relocation_inventory(source, [(hid, 3, "FORWARD", 0)], identity_seed=SEED)
    assert source.model_dump_json() == before
