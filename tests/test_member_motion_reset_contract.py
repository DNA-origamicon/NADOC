"""Native component contracts and isolated fixed-world-motion reset/replacement."""
from copy import deepcopy

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.api import part_proof_commands as commands
from backend.core.atomistic import build_atomistic_model
from backend.core.base_keys import atom_base_key
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Direction
from tests.test_part_member_motion_order import _source, _target, _nucleotide, _owner, _rigid, N, M
from tests.test_part_transform_preview import snapshot


@pytest.mark.parametrize("direction", list(Direction))
@pytest.mark.parametrize("reset", [False, True])
def test_native_component_edit_preserves_later_owner_and_exact_no_pose_baseline(direction, reset):
    base = _source()
    strand, target = _target(base, direction)
    prior = _nucleotide(base, target, N, "prior-residue")
    placed = _owner(prior, strand)
    no_pose = _owner(base, strand)
    existing_id = placed.nucleotide_transforms[0].id
    replacement = {"rotation": Rotation.from_euler("y", 37, degrees=True).as_quat().tolist(),
                   "pivot": [-2, 3, .7], "translation": [1, 2, -.5]}
    if reset:
        actual = snapshot(placed, "nucleotide-transform-delete", {"transform_id": existing_id}, "reset")
        expected = no_pose
        assert not actual.nucleotide_transforms
    else:
        actual = _nucleotide(placed, target, replacement, "replace", compose=False)
        expected = _nucleotide(no_pose, target, replacement, "replacement-baseline", compose=False)
        assert actual.nucleotide_transforms[0].id == existing_id
    assert actual.cluster_transforms == placed.cluster_transforms
    assert actual.strands == placed.strands and actual.crossovers == placed.crossovers
    assert _geometry_for_design(actual) == _geometry_for_design(expected)
    atoms = build_atomistic_model(actual, fast_bridges=True)
    assert atoms == build_atomistic_model(expected, fast_bridges=True)
    old_atoms = build_atomistic_model(placed, fast_bridges=True)
    assert atoms.bonds == old_atoms.bonds
    key = f'{target["helix_id"]}:{target["bp_index"]}:{target["direction"]}'
    for old, new in zip(old_atoms.atoms, atoms.atoms, strict=True):
        if atom_base_key(old) != key:
            assert new == old
    # Replay the exact native command independently with no proposed world event.
    entry = actual.feature_log[-1]
    captured = placed.model_dump_json()
    replayed = commands.execute(entry.op_kind, placed.model_copy(deep=True), deepcopy(entry.params))
    assert _geometry_for_design(replayed) == _geometry_for_design(actual)
    assert build_atomistic_model(replayed, fast_bridges=True) == atoms
    assert placed.model_dump_json() == captured

    # An inverse gesture on current world coordinates is not component deletion.
    # Both agree without M, so a no-M control alone cannot catch that mistake.
    # The isolated fixed-world M contract retains its authored matrix on deletion.
    points = np.asarray([[a.x, a.y, a.z] for a in build_atomistic_model(base, fast_bridges=True).atoms
                         if atom_base_key(a) == key])
    n_inverse = Rotation.from_quat(N["rotation"]).inv()
    def undo_n(value):
        return n_inverse.apply(value - np.asarray(N["pivot"]) - np.asarray(N["translation"])) + N["pivot"]
    keep_motion = _rigid(points, M)
    undo_in_world = undo_n(_rigid(_rigid(points, N), M))
    native_control = points
    world_control = undo_n(_rigid(points, N))
    if not reset:
        keep_motion, undo_in_world = (_rigid(p, replacement) for p in (keep_motion, undo_in_world))
        native_control, world_control = (_rigid(p, replacement) for p in (native_control, world_control))
    np.testing.assert_allclose(world_control, native_control, rtol=0, atol=1e-12)
    assert np.max(np.linalg.norm(keep_motion - undo_in_world, axis=1)) > 1


@pytest.mark.parametrize("direction", list(Direction))
@pytest.mark.parametrize("reset", [False, True])
@pytest.mark.parametrize("suffix_selected", [False, True])
def test_component_edit_retains_fixed_world_motion(direction, reset, suffix_selected, monkeypatch):
    from tests.test_part_member_motion_order import D, _key
    from tools.member_motion_ordering_program import compile_ordered_probe

    base = _source()
    strand, target = _target(base, direction)
    base = _owner(base, strand)
    prefix = _nucleotide(base, target, N, "first-component")
    prefix = _nucleotide(prefix, target, D, "composed-component", compose=True)
    pose_id = prefix.nucleotide_transforms[0].id
    replacement = {"rotation": Rotation.from_euler("y", 37, degrees=True).as_quat().tolist(),
                   "pivot": [-2, 3, .7], "translation": [1, 2, -.5]}
    later = (snapshot(prefix, "nucleotide-transform-delete", {"transform_id": pose_id}, "reset") if reset
             else _nucleotide(prefix, target, replacement, "replace", compose=False))
    selected = target["helix_id"] if suffix_selected else next(h.id for h in base.helices if h.id != target["helix_id"])
    captured = prefix.model_dump_json()
    program = compile_ordered_probe(prefix, later.feature_log[-1], [selected])
    native_full, native_atoms = _geometry_for_design(later), build_atomistic_model(later, fast_bridges=True)
    assert program.evaluate(motion_enabled=False)[:2] == (native_full, native_atoms)
    base_full, base_atoms = _geometry_for_design(base), build_atomistic_model(base, fast_bridges=True)
    prior_full, prior_atoms = _geometry_for_design(prefix), build_atomistic_model(prefix, fast_bridges=True)

    def forbidden(*args, **kwargs):
        raise AssertionError("Sample rebuilt native geometry or replayed history")
    monkeypatch.setattr("tools.member_motion_ordering_program.commands.execute", forbidden)
    monkeypatch.setattr("tools.member_motion_ordering_program._geometry_for_design", forbidden)
    monkeypatch.setattr("tools.member_motion_ordering_program.build_atomistic_model", forbidden)
    for angle in (-63, 115):
        motion = {"rotation": Rotation.from_euler("x", angle, degrees=True).as_quat().tolist(),
                  "pivot": [3, -2, .5], "translation": [.3, -.7, 1.4]}
        full, atoms, trace = program.evaluate(motion=motion)
        assert trace[-1]["replaced_pose_id"] == pose_id
        assert trace[-1]["kind"] == ("native-reset-component" if reset else "native-replace-component")
        assert atoms.bonds == prior_atoms.bonds == native_atoms.bonds
        for before, bare, actual, native in zip(prior_full, base_full, full, native_full, strict=True):
            if before["helix_id"] != selected:
                assert actual == native
                continue
            is_target = _key(before) == _key(target)
            source = bare if is_target else before
            rotation = Rotation.from_quat(motion["rotation"])
            if is_target and not reset:
                rotation = Rotation.from_quat(replacement["rotation"]) * rotation
            for field in ("backbone_position", "base_position", "slab_position"):
                expected = _rigid(source[field], motion)
                if is_target and not reset:
                    expected = _rigid(expected, replacement)
                np.testing.assert_allclose(actual[field], expected, rtol=0, atol=1e-10)
            for field in ("base_normal", "axis_tangent"):
                np.testing.assert_allclose(actual[field], rotation.apply(source[field]), rtol=0, atol=1e-10)
            np.testing.assert_allclose(Rotation.from_quat(actual["slab_quaternion"]).as_matrix(),
                                       rotation.as_matrix() @ Rotation.from_quat(source["slab_quaternion"]).as_matrix(),
                                       rtol=0, atol=1e-10)
        for before, bare, actual, native in zip(prior_atoms.atoms, base_atoms.atoms, atoms.atoms, native_atoms.atoms, strict=True):
            if before.helix_id != selected:
                assert actual == native
                continue
            is_target = (before.helix_id, before.bp_index, before.direction, before.copy_k or 0) == _key(target)
            source = bare if is_target else before
            expected = _rigid([source.x, source.y, source.z], motion)
            if is_target and not reset:
                expected = _rigid(expected, replacement)
            np.testing.assert_allclose([actual.x, actual.y, actual.z], expected, rtol=0, atol=1e-10)
    assert prefix.model_dump_json() == captured


def test_reset_recreated_component_does_not_resurrect_old_lifetime():
    from tools.member_motion_ordering_program import compile_ordered_probe
    from tests.test_part_member_motion_order import D, _key

    base = _source()
    _, target = _target(base, Direction.FORWARD)
    first = _nucleotide(base, target, N, "first")
    deleted = snapshot(first, "nucleotide-transform-delete", {"transform_id": first.nucleotide_transforms[0].id}, "delete-first")
    recreated = _nucleotide(deleted, target, D, "recreated")
    reset = snapshot(recreated, "nucleotide-transform-delete", {"transform_id": recreated.nucleotide_transforms[0].id}, "reset-current")
    program = compile_ordered_probe(recreated, reset.feature_log[-1], [target["helix_id"]])
    full, _, _ = program.evaluate()
    for before, actual in zip(_geometry_for_design(base), full, strict=True):
        if _key(before) == _key(target):
            np.testing.assert_allclose(actual["base_position"], _rigid(before["base_position"], M), rtol=0, atol=1e-10)
    with pytest.raises(ValueError, match="current saved pose lifetime"):
        compile_ordered_probe(deleted, reset.feature_log[-1], [target["helix_id"]])
