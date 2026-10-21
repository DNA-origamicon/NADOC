"""Existing native out-of-span material is not a deformation-window selection.

The fixture is a static geometry input, not evidence for a current loop producer
or for replaying construction after a named motion.
"""
import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Direction
from backend.core.part_group_model import GroupOrganization, GroupDomainRef, PartGroup
from backend.core.part_group_selection import resolve_deformation_targets
from tests.test_part_member_motion_order import _source, _target, _nucleotide, _rigid, D, M
from tools.member_motion_ordering_program import _key, existing_material_union, compile_ordered_probe


@pytest.mark.parametrize("direction", list(Direction))
@pytest.mark.parametrize("domain_only", [False, True])
def test_existing_out_of_span_members_follow_exact_whole_or_domain_selection(direction, domain_only):
    source = _source().model_copy(deep=True)
    strand, target = _target(source, direction)
    domain = strand.domains[0]
    # Preserve native traversal; only this occupied domain extends at both ends.
    step = 1 if domain.end_bp > domain.start_bp else -1
    domain.start_bp -= 2 * step
    domain.end_bp += 2 * step
    strand.sequence = None
    source.feature_log = []
    source.recipe_root = None
    group = PartGroup(id="selected", helix_ids=[target["helix_id"]],
        domain_ids=[GroupDomainRef(strand_id=strand.id, domain_index=0)] if domain_only else [])
    source = source.copy_with(group_organization=GroupOrganization(groups=[group]))
    refs = [{"kind": "part_group", "id": "selected"}]
    captured = source.model_dump_json()
    full = _geometry_for_design(source)
    expected = {_key(row) for row in full if row["helix_id"] == target["helix_id"]
                and (not domain_only or row["strand_id"] == strand.id)}
    outside = {key for key in expected if key[1] < 0 or key[1] >= 8}
    assert len(outside) == 4
    # Preserve the original deformation contract: whole-helix windows are bounded.
    if not domain_only:
        assert {(r.start_bp, r.end_bp) for r in resolve_deformation_targets(source, refs)} == {(0, 7)}
    assert set(existing_material_union(source, refs)) == expected
    later = _nucleotide(source, target, D, "later-residue", compose=True)
    program = compile_ordered_probe(source, later.feature_log[-1], [target["helix_id"]], named_targets=refs)
    actual_full, actual_atoms, _ = program.evaluate()
    prior_atoms = build_atomistic_model(source, fast_bridges=True)
    assert {_key(atom) for atom in prior_atoms.atoms} >= outside
    assert actual_atoms.bonds == prior_atoms.bonds
    for before, actual in zip(full, actual_full, strict=True):
        if _key(before) not in expected:
            assert actual == before
            continue
        for field in ("backbone_position", "base_position", "slab_position"):
            point = _rigid(before[field], M)
            if _key(before) == _key(target):
                point = _rigid(point, D)
            np.testing.assert_allclose(actual[field], point, rtol=0, atol=1e-10)
    for before, actual in zip(prior_atoms.atoms, actual_atoms.atoms, strict=True):
        if _key(before) not in expected:
            assert actual == before
            continue
        point = _rigid([before.x, before.y, before.z], M)
        if _key(before) == _key(target):
            point = _rigid(point, D)
        np.testing.assert_allclose([actual.x, actual.y, actual.z], point, rtol=0, atol=1e-10)
    assert source.model_dump_json() == captured
