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


@pytest.mark.parametrize("change", [{"copy_k": 1}, {"kind": "extension"}])
def test_unsettled_suffix_roles_are_not_silently_interpreted(change):
    prefix, later, target = recipe(Direction.FORWARD)
    entry = deepcopy(later.feature_log[-1])
    entry.params.update(change)
    with pytest.raises(ValueError, match="Only ordinary base pose components"):
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
    partial = compile_ordered_probe(prefix, entry, [selected],
                                   named_targets=[{"kind": "part_group", "id": "partial"}])
    assert set(partial.selected_material_keys) < set(program.selected_material_keys)
    partial_full, partial_atoms, _ = partial.evaluate()
    native_full, native_atoms, _ = partial.evaluate(motion_enabled=False)
    keys = set(partial.selected_material_keys)
    assert [row for row in partial_full if _key(row) not in keys] == [
        row for row in native_full if _key(row) not in keys]
    def atom_key(atom):
        return atom.helix_id, atom.bp_index, atom.direction, atom.copy_k or 0
    assert [atom for atom in partial_atoms.atoms if atom_key(atom) not in keys] == [
        atom for atom in native_atoms.atoms if atom_key(atom) not in keys]


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


@pytest.mark.parametrize("direction", list(Direction))
@pytest.mark.parametrize("suffix_selected", [False, True])
@pytest.mark.parametrize("rotate_suffix", [False, True])
def test_partial_named_motion_preserves_shared_frame_neighbors_and_native_suffix(direction, suffix_selected, rotate_suffix, monkeypatch):
    from scipy.spatial.transform import Rotation
    from backend.core.deformation import deformed_helix_axes
    from backend.core.part_group_model import GroupDomainRef, GroupOrganization, PartGroup
    from tests.test_part_group_lineage import native_nick

    source = native_nick(_source(), direction, bp=3)
    _, target = _target(source, direction)
    prefix = _nucleotide(source, target, N, "prior-residue")
    member = next(row for row in _geometry_for_design(prefix) if _key(row) == _key(target))
    domain = GroupDomainRef(strand_id=member["strand_id"], domain_index=member["domain_index"])
    prefix = prefix.copy_with(group_organization=GroupOrganization(groups=[
        PartGroup(id=name, helix_ids=[target["helix_id"]], domain_ids=[domain])
        for name in ("partial-a", "partial-b")]))
    suffix_target = dict(target)
    if not suffix_selected:
        suffix_target["direction"] = "REVERSE" if direction == Direction.FORWARD else "FORWARD"
    delta = {"rotation": Rotation.from_euler("y", 37, degrees=True).as_quat().tolist(),
             "pivot": [-2, 3, .7], "translation": [1, 2, -.5]} if rotate_suffix else D
    later = _nucleotide(prefix, suffix_target, delta, "later-delta", compose=True)
    captured, axes = prefix.model_dump_json(), deformed_helix_axes(prefix)
    program = compile_ordered_probe(prefix, later.feature_log[-1], [target["helix_id"]],
        named_targets=[{"kind": "part_group", "id": name} for name in ("partial-a", "partial-b")])
    keys = set(program.selected_material_keys)
    # Native nick polarity puts bp 3 on the low forward / high reverse child.
    expected_bps = range(4) if direction == Direction.FORWARD else range(3, 8)
    assert keys == {(target["helix_id"], bp, direction.value, 0) for bp in expected_bps}
    assert len(keys) == len(program.selected_material_keys)
    assert _key(target) in keys
    full, atoms, trace = program.evaluate()
    assert trace[0]["shared_helix_frame_policy"].startswith("unresolved")
    native_full, native_atoms, _ = program.evaluate(motion_enabled=False)
    assert native_full == _geometry_for_design(later)
    assert native_atoms == build_atomistic_model(later, fast_bridges=True)
    prior_full = _geometry_for_design(prefix)
    for before, actual, native in zip(prior_full, full, native_full, strict=True):
        if _key(before) not in keys:
            assert actual == native
            continue
        for field in ("backbone_position", "base_position", "slab_position"):
            expected = _rigid(before[field], M)
            if _key(before) == _key(suffix_target):
                expected = _rigid(expected, delta)
            np.testing.assert_allclose(actual[field], expected, rtol=0, atol=1e-10)
        rotation = Rotation.from_quat(M["rotation"])
        if _key(before) == _key(suffix_target):
            rotation = Rotation.from_quat(delta["rotation"]) * rotation
        for field in ("base_normal", "axis_tangent"):
            np.testing.assert_allclose(actual[field], rotation.apply(before[field]), rtol=0, atol=1e-10)
        np.testing.assert_allclose(Rotation.from_quat(actual["slab_quaternion"]).as_matrix(),
                                   rotation.as_matrix() @ Rotation.from_quat(before["slab_quaternion"]).as_matrix(),
                                   rtol=0, atol=1e-10)
        site, prior_site = actual["helical_site"], before["helical_site"]
        expected_axis = _rigid(prior_site["axis_point"], M)
        if _key(before) == _key(suffix_target):
            expected_axis = _rigid(expected_axis, delta)
        np.testing.assert_allclose(site["axis_point"], expected_axis, rtol=0, atol=1e-10)
        np.testing.assert_allclose(site["radial_hat"], rotation.apply(prior_site["radial_hat"]), rtol=0, atol=1e-10)
        for field in ("azimuth_rad", "groove_offset_rad", "phase_roll_rad"):
            assert site[field] == prior_site[field]
    prior_atoms = build_atomistic_model(prefix, fast_bridges=True)
    assert atoms.bonds == prior_atoms.bonds == native_atoms.bonds
    for before, actual, native in zip(prior_atoms.atoms, atoms.atoms, native_atoms.atoms, strict=True):
        key = before.helix_id, before.bp_index, before.direction, before.copy_k or 0
        if key not in keys:
            assert actual == native
            continue
        expected = _rigid([before.x, before.y, before.z], M)
        if key == _key(suffix_target):
            expected = _rigid(expected, delta)
        np.testing.assert_allclose([actual.x, actual.y, actual.z], expected, rtol=0, atol=1e-10)
    assert prefix.model_dump_json() == captured
    assert deformed_helix_axes(prefix) == axes

    def forbidden(*args, **kwargs):
        raise AssertionError("Evaluation rebuilt native geometry or replayed history")
    with monkeypatch.context() as scoped:
        scoped.setattr("tools.member_motion_ordering_program.commands.execute", forbidden)
        scoped.setattr("tools.member_motion_ordering_program._geometry_for_design", forbidden)
        scoped.setattr("tools.member_motion_ordering_program.build_atomistic_model", forbidden)
        repeated_full, repeated_atoms, repeated_trace = program.evaluate()
    assert (repeated_full, repeated_atoms, repeated_trace) == (full, atoms, trace)


@pytest.mark.parametrize("direction", list(Direction))
def test_compiled_samples_follow_multiple_native_owners_without_replay(direction, monkeypatch):
    from scipy.spatial.transform import Rotation
    from tools.member_motion_birth_audit import phase_source
    from tests.test_part_member_motion_order import _owner
    from tests.test_part_group_lineage import native_nick

    source = native_nick(phase_source(43), direction, bp=3)
    strand, target = _target(source, direction)
    source = _owner(source, strand)
    prefix = _nucleotide(source, target, N, "prior-residue")
    delta = {"rotation": Rotation.from_euler("y", 37, degrees=True).as_quat().tolist(),
             "pivot": [-2, 3, .7], "translation": [1, 2, -.5]}
    later = _nucleotide(prefix, target, delta, "later-rotation", compose=True)
    captured = prefix.model_dump_json()
    prior_full = _geometry_for_design(prefix)
    prior_atoms = build_atomistic_model(prefix, fast_bridges=True)
    program = compile_ordered_probe(prefix, later.feature_log[-1], [target["helix_id"]])
    assert len(prefix.cluster_transforms) >= 2

    def forbidden(*args, **kwargs):
        raise AssertionError("Slider sample replayed history or rebuilt native geometry")
    with monkeypatch.context() as scoped:
        scoped.setattr("tools.member_motion_ordering_program.commands.execute", forbidden)
        scoped.setattr("tools.member_motion_ordering_program._geometry_for_design", forbidden)
        scoped.setattr("tools.member_motion_ordering_program.build_atomistic_model", forbidden)
        for angle in (-63, 22, 115):
            motion = {"rotation": Rotation.from_euler("x", angle, degrees=True).as_quat().tolist(),
                      "pivot": [3, -2, .5], "translation": [.3, -.7, 1.4]}
            full, atoms, trace = program.evaluate(motion=motion)
            assert trace[0]["pose"] == motion
            assert atoms.bonds == prior_atoms.bonds
            for before, actual in zip(prior_full, full, strict=True):
                if before["helix_id"] != target["helix_id"]:
                    assert actual == before
                    continue
                for field in ("backbone_position", "base_position", "slab_position"):
                    expected = _rigid(before[field], motion)
                    if _key(before) == _key(target):
                        expected = _rigid(expected, delta)
                    np.testing.assert_allclose(actual[field], expected, rtol=0, atol=1e-10)
            for before, actual in zip(prior_atoms.atoms, atoms.atoms, strict=True):
                key = before.helix_id, before.bp_index, before.direction, before.copy_k or 0
                expected = [before.x, before.y, before.z]
                if before.helix_id == target["helix_id"]:
                    expected = _rigid(expected, motion)
                    if key == _key(target):
                        expected = _rigid(expected, delta)
                np.testing.assert_allclose([actual.x, actual.y, actual.z], expected, rtol=0, atol=1e-10)
    assert prefix.model_dump_json() == captured
