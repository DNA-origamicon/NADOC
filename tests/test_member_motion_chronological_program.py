"""Several native residue events share one chronological fixed-world motion."""
from copy import deepcopy

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.atomistic import build_atomistic_model
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Direction
from tests.test_part_member_motion_order import N, M, _nucleotide, _source, _target, _rigid
from tests.test_part_transform_preview import snapshot
from tools.member_motion_ordering_program import (
    ChronologicalProgram, _key, compile_chronological_program,
)


@pytest.mark.parametrize("direction", list(Direction))
@pytest.mark.parametrize("other_selected", [False, True])
def test_mixed_event_sequence_retains_order_and_component_lifetimes(direction, other_selected, monkeypatch):
    base = _source()
    _, first = _target(base, direction)
    second = dict(first)
    second["bp_index"] += 1
    if not other_selected:
        second["helix_id"] = next(h.id for h in base.helices if h.id != first["helix_id"])
    prefix = _nucleotide(base, first, N, "prior-first")
    prefix = _nucleotide(prefix, second, N, "prior-second")
    rotations = [{"rotation": Rotation.from_euler(axis, angle, degrees=True).as_quat().tolist(),
                  "pivot": [1.2, -.7, .9], "translation": [.4, .1, -.3]}
                 for axis, angle in (("x", 37), ("y", -61), ("z", 23))]
    operations = [(first, "compose", rotations[0]), (second, "compose", rotations[1]),
                  (first, "replace", rotations[2]), (first, "reset", None),
                  (first, "replace", rotations[1]), (first, "compose", rotations[0])]
    current, entries, controls = prefix, [], []
    for index, (target, action, pose) in enumerate(operations):
        if action == "reset":
            existing = next(p for p in current.nucleotide_transforms
                            if (p.helix_id, p.bp_index, p.direction.value, p.copy_k) == _key(target))
            current = snapshot(current, "nucleotide-transform-delete", {"transform_id": existing.id}, f"event-{index}")
        else:
            current = _nucleotide(current, target, pose, f"event-{index}", compose=action == "compose")
        entries.append(current.feature_log[-1])
        controls.append((_geometry_for_design(current), build_atomistic_model(current, fast_bridges=True)))
    captured = prefix.model_dump_json()
    program = compile_chronological_program(prefix, entries, [first["helix_id"]])
    before_full, bare_full = _geometry_for_design(prefix), _geometry_for_design(base)
    paths = {_key(row): ([M] if row["helix_id"] == first["helix_id"] else []) for row in before_full}
    cleared = set()
    before_atoms = build_atomistic_model(prefix, fast_bridges=True)
    bare_atoms = build_atomistic_model(base, fast_bridges=True)
    # Independent point arrays keep the native pre-pose geometry separate from
    # the authored current pose, so replacement/reset cannot mimic inverse undo.
    expected = np.array([[a.x, a.y, a.z] for a in before_atoms.atoms])
    bare = np.array([[a.x, a.y, a.z] for a in bare_atoms.atoms])
    selected = np.array([a.helix_id == first["helix_id"] for a in before_atoms.atoms])
    expected[selected] = _rigid(expected[selected], M)
    bare[selected] = _rigid(bare[selected], M)

    def forbidden(*args, **kwargs):
        raise AssertionError("Evaluating a compiled sequence replayed history or rebuilt geometry")
    monkeypatch.setattr("tools.member_motion_ordering_program.commands.execute", forbidden)
    monkeypatch.setattr("tools.member_motion_ordering_program._geometry_for_design", forbidden)
    monkeypatch.setattr("tools.member_motion_ordering_program.build_atomistic_model", forbidden)
    for index, (target, action, pose) in enumerate(operations):
        mask = np.array([_key(atom) == _key(target) for atom in before_atoms.atoms])
        assert mask.any()
        if action != "compose":
            expected[mask] = bare[mask]
            cleared.add(_key(target))
            paths[_key(target)] = [M] if target["helix_id"] == first["helix_id"] else []
        if pose is not None:
            expected[mask] = _rigid(expected[mask], pose)
            paths[_key(target)].append(pose)
        stage = ChronologicalProgram(program.steps[:index + 1])
        full, atoms, trace = stage.evaluate()
        assert [event["feature_id"] for event in trace] == ["diagnostic-world-M", *[e.id for e in entries[:index + 1]]]
        np.testing.assert_allclose([[a.x, a.y, a.z] for a in atoms.atoms], expected, rtol=0, atol=1e-10)
        assert atoms.bonds == before_atoms.bonds
        assert stage.evaluate(motion_enabled=False)[:2] == controls[index]
        for before, bare_row, actual in zip(before_full, bare_full, full, strict=True):
            key = _key(before)
            baseline = bare_row if key in cleared else before
            rotation = Rotation.identity()
            for transform in paths[key]:
                rotation = Rotation.from_quat(transform["rotation"]) * rotation
            for field in ("backbone_position", "base_position", "slab_position"):
                point = baseline[field]
                for transform in paths[key]:
                    point = _rigid(point, transform)
                np.testing.assert_allclose(actual[field], point, rtol=0, atol=1e-10)
            for field in ("base_normal", "axis_tangent"):
                np.testing.assert_allclose(actual[field], rotation.apply(baseline[field]), rtol=0, atol=1e-10)
            np.testing.assert_allclose(Rotation.from_quat(actual["slab_quaternion"]).as_matrix(),
                                       rotation.as_matrix() @ Rotation.from_quat(baseline["slab_quaternion"]).as_matrix(),
                                       rtol=0, atol=1e-10)
            site, base_site = actual["helical_site"], baseline["helical_site"]
            point = base_site["axis_point"]
            for transform in paths[key]:
                point = _rigid(point, transform)
            np.testing.assert_allclose(site["axis_point"], point, rtol=0, atol=1e-10)
            np.testing.assert_allclose(site["radial_hat"], rotation.apply(base_site["radial_hat"]), rtol=0, atol=1e-10)
        # Unselected rows and atom metadata remain exact native outputs.
        for actual, native in zip(full, controls[index][0], strict=True):
            if actual["helix_id"] != first["helix_id"]:
                assert actual == native
        for actual, native in zip(atoms.atoms, controls[index][1].atoms, strict=True):
            if actual.helix_id != first["helix_id"]:
                assert actual == native
    original = program.evaluate()
    expected_result = deepcopy(original)
    original[0][0]["base_position"][0] += 100
    original[1].atoms[0].x += 100
    assert program.evaluate() == expected_result
    assert prefix.model_dump_json() == captured


def test_chronological_program_refuses_unbounded_or_duplicate_event_sequences():
    source = _source()
    _, target = _target(source, Direction.FORWARD)
    later = _nucleotide(source, target, N, "event")
    entry = later.feature_log[-1]
    for entries in ([], [entry] * 17):
        with pytest.raises(ValueError, match="1–16"):
            compile_chronological_program(source, entries, [target["helix_id"]])
    with pytest.raises(ValueError, match="identities must be unique"):
        compile_chronological_program(source, [entry, entry], [target["helix_id"]])

    suppressed = entry.model_copy(update={"suppressed": True})
    with pytest.raises(ValueError, match="Suppressed suffix"):
        compile_chronological_program(source, [suppressed], [target["helix_id"]])
