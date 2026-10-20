"""Executable chronological candidate stays detached and respects native suffixes."""
from copy import deepcopy

import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Direction
from tests.test_part_member_motion_order import D, M, N, _key, _nucleotide, _rigid, _source, _target
from tools.member_motion_ordering_program import compile_ordered_probe


def recipe(direction):
    source = _source()
    _, target = _target(source, direction)
    prefix = _nucleotide(source, target, N, "prior-residue")
    later = _nucleotide(prefix, target, D, "later-world-delta", compose=True)
    return prefix, later, target


@pytest.mark.parametrize("direction", list(Direction))
def test_chronological_program_preserves_later_world_delta_and_exact_disabled_control(direction):
    prefix, later, target = recipe(direction)
    original = prefix.model_dump_json()
    helix_id = target["helix_id"]
    program = compile_ordered_probe(prefix, later.feature_log[-1], [helix_id, helix_id])
    assert program.selected_helix_ids == (helix_id,)
    records, atoms, trace = program.evaluate()
    before = next(r for r in _geometry_for_design(prefix) if (
        r["helix_id"], r["bp_index"], r["direction"], r.get("copy_k", 0)) == _key(target))
    actual = next(r for r in records if (r["helix_id"], r["bp_index"], r["direction"], r.get("copy_k", 0)) == _key(target))
    for name in ("backbone_position", "base_position", "slab_position"):
        expected = _rigid(_rigid(before[name], M), D)
        naive = _rigid(_rigid(before[name], D), M)
        np.testing.assert_allclose(actual[name], expected, rtol=0, atol=1e-10)
        np.testing.assert_allclose(np.asarray(actual[name]) - naive, [1, -5, 0], rtol=0, atol=1e-10)
    prior_atoms = build_atomistic_model(prefix, fast_bridges=True)
    for before_atom, actual_atom in zip(prior_atoms.atoms, atoms.atoms, strict=True):
        key = before_atom.helix_id, before_atom.bp_index, before_atom.direction, before_atom.copy_k or 0
        point = [before_atom.x, before_atom.y, before_atom.z]
        expected = _rigid(point, M) if before_atom.helix_id == helix_id else point
        if key == _key(target):
            expected = _rigid(expected, D)
        np.testing.assert_allclose([actual_atom.x, actual_atom.y, actual_atom.z], expected, rtol=0, atol=1e-10)
    assert [e["feature_id"] for e in trace] == ["diagnostic-world-M", "later-world-delta"]
    disabled_records, disabled_atoms, disabled_trace = program.evaluate(motion_enabled=False)
    assert disabled_records == _geometry_for_design(later)
    assert disabled_atoms == build_atomistic_model(later, fast_bridges=True)
    assert disabled_trace[0]["native_output_exact"]
    records[0]["backbone_position"][0] += 100
    atoms.atoms[0].x += 100
    fresh_records, fresh_atoms, _ = program.evaluate()
    assert fresh_records != records and fresh_atoms != atoms
    assert prefix.model_dump_json() == original


def test_native_suffix_on_unselected_helix_keeps_its_exact_native_output():
    prefix, later, target = recipe(Direction.FORWARD)
    other = next(h.id for h in prefix.helices if h.id != target["helix_id"])
    program = compile_ordered_probe(prefix, later.feature_log[-1], [other])
    records, atoms, _ = program.evaluate()
    native_records = _geometry_for_design(later)
    assert [r for r in records if r["helix_id"] == target["helix_id"]] == [
        r for r in native_records if r["helix_id"] == target["helix_id"]]
    native_atoms = build_atomistic_model(later, fast_bridges=True)
    assert [a for a in atoms.atoms if a.helix_id == target["helix_id"]] == [
        a for a in native_atoms.atoms if a.helix_id == target["helix_id"]]


@pytest.mark.parametrize("change", [{"compose": False}, {"rotation": [0, 0, 1, 0]}])
def test_unsettled_suffix_roles_are_not_silently_interpreted(change):
    prefix, later, target = recipe(Direction.FORWARD)
    entry = deepcopy(later.feature_log[-1])
    entry.params.update(change)
    with pytest.raises(ValueError, match="replacement/reset/rotation remain unresolved"):
        compile_ordered_probe(prefix, entry, [target["helix_id"]])


def test_named_union_intersects_actual_material_without_unoccupied_partner_or_overlap():
    from backend.core.part_group_model import PartGroup
    from tests.test_part_group_selection import source
    from tools.member_motion_ordering_program import existing_material_union

    design = source()
    design.group_organization.groups.append(PartGroup(id="overlap", helix_ids=["h0"]))
    captured = design.model_dump_json()
    actual = existing_material_union(design, [
        {"kind": "part_group", "id": "same"}, {"kind": "part_group", "id": "overlap"},
        {"kind": "part_group", "id": "domain"}])
    expected = {("h0", bp, direction, 0)
                for direction, count in (("FORWARD", 6), ("REVERSE", 12)) for bp in range(count)}
    assert len(actual) == len(set(actual)) == 18
    assert set(actual) == expected
    # Equal-text owner selects the other helix, with no occupied reverse strand.
    owner = existing_material_union(design, [{"kind": "cluster", "id": "same"}])
    assert set(owner) == {("h1", bp, "FORWARD", 0) for bp in range(12)}
    # Domain-backed group's helix_ids must not widen its actual native domain.
    domain = existing_material_union(design, [{"kind": "part_group", "id": "domain"}])
    assert set(domain) == {("h0", bp, "FORWARD", 0) for bp in range(6)}
    assert design.model_dump_json() == captured


def test_compiled_named_overlap_matches_one_whole_motion_and_owns_its_references():
    from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup

    prefix, later, target = recipe(Direction.FORWARD)
    entry, selected = later.feature_log[-1], target["helix_id"]
    prefix = prefix.copy_with(group_organization=GroupOrganization(groups=[
        PartGroup(id="a", helix_ids=[selected]), PartGroup(id="b", helix_ids=[selected]),
        PartGroup(id="partial", domain_ids=[GroupDomainRef(
            strand_id=next(r["strand_id"] for r in _geometry_for_design(prefix) if _key(r) == _key(target)),
            domain_index=0)]),
    ]))
    references = [{"kind": "part_group", "id": "a"}, {"kind": "part_group", "id": "b"}]
    program = compile_ordered_probe(prefix, entry, [selected], named_targets=references)
    reference = compile_ordered_probe(prefix, entry, [selected])
    actual_full, actual_atoms, trace = program.evaluate()
    expected_full, expected_atoms, _ = reference.evaluate()
    assert actual_full == expected_full and actual_atoms == expected_atoms
    references[0]["id"] = "changed-after-compile"
    assert trace[0]["named_targets"] == [{"kind": "part_group", "id": "a"}, {"kind": "part_group", "id": "b"}]
    assert program.evaluate()[2][0]["named_targets"] == trace[0]["named_targets"]
    with pytest.raises(ValueError, match="partial frames"):
        compile_ordered_probe(prefix, entry, [selected], named_targets=[{"kind": "part_group", "id": "partial"}])


@pytest.mark.parametrize("kind", ["bend", "twist", "sweep"])
@pytest.mark.parametrize("direction", list(Direction))
def test_prior_native_deformation_frames_remain_in_chronological_rigid_candidate(kind, direction):
    from backend.core.models import DeformationLogEntry, DeformationOp
    from tests.test_part_deformation_preview import _append

    if kind == "sweep":
        from backend.core.part_history_contract import create_empty_part
        from backend.core.sweep import SweepRequest
        from tests.test_part_transform_preview import snapshot
        source = snapshot(create_empty_part("Prior curved Sweep", "HONEYCOMB"), "sweep",
                          SweepRequest(sweep_id="bbf3fdbe-92a7-476e-8d77-4578091ed5df",
                                       cells=[(0, 0), (0, 1)], points_nm=[(0, 0, 0), (0, 0, 5), (2, 0, 10)],
                                       ligate_adjacent=False).model_dump(mode="json"), "prior-sweep")
    else:
        source = _source()
        op = DeformationOp(id="prior-shape", type=kind, plane_a_bp=0, plane_b_bp=7,
                           affected_helix_ids=[source.helices[0].id],
                           params={"kind": kind, **({"curvature_deg_per_bp": 2, "direction_deg": 25}
                                                   if kind == "bend" else {"total_degrees": 30})})
        source = _append(source, DeformationLogEntry(
            id="prior-shape-feature", deformation_id=op.id, op_snapshot=op, proof_version=1))
    _, target = _target(source, direction)
    prefix = _nucleotide(source, target, N, "prior-residue")
    later = _nucleotide(prefix, target, D, "later-delta", compose=True)
    if kind == "sweep":
        from backend.core.part_group_model import GroupOrganization, PartGroup
        from tools.member_motion_ordering_program import existing_material_union
        grouped = prefix.copy_with(group_organization=GroupOrganization(groups=[
            PartGroup(id="sweep-members", helix_ids=[target["helix_id"]])]))
        keys = existing_material_union(grouped, [{"kind": "part_group", "id": "sweep-members"}])
        assert len([key for key in keys if key[3] == 1]) == 4
        assert set(keys) == {_key(row) for row in _geometry_for_design(prefix)
                             if row["helix_id"] == target["helix_id"]}
        assert any(change.delta == -1 for h in prefix.helices for change in h.loop_skips)
    locked = prefix.model_dump_json()
    program = compile_ordered_probe(prefix, later.feature_log[-1], [target["helix_id"]])
    control_records, control_atoms, _ = program.evaluate(motion_enabled=False)
    assert control_records == _geometry_for_design(later)
    assert control_atoms == build_atomistic_model(later, fast_bridges=True)
    records, atoms, _ = program.evaluate()
    for before, after in zip(_geometry_for_design(prefix), records, strict=True):
        if before["helix_id"] != target["helix_id"]:
            assert before == after
            continue
        for field in ("backbone_position", "base_position", "slab_position"):
            expected = _rigid(before[field], M)
            if _key(before) == _key(target):
                expected = _rigid(expected, D)
            np.testing.assert_allclose(after[field], expected, atol=1e-10, rtol=0)
    for before, after in zip(build_atomistic_model(prefix, fast_bridges=True).atoms, atoms.atoms, strict=True):
        xyz = [before.x, before.y, before.z]
        if before.helix_id == target["helix_id"]:
            xyz = _rigid(xyz, M)
            if (before.helix_id, before.bp_index, before.direction, before.copy_k or 0) == _key(target):
                xyz = _rigid(xyz, D)
        np.testing.assert_allclose([after.x, after.y, after.z], xyz, atol=1e-10, rtol=0)
    assert prefix.model_dump_json() == locked
