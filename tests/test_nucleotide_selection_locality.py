"""A residue pose must not reconstruct or transform unselected residues."""

import numpy as np
import pytest

from backend.core.atomistic import apply_nucleotide_transforms, build_atomistic_model
from backend.core.base_keys import atom_base_key
from backend.core.models import Design, NucleotideTransform
from backend.core.design_geometry import _geometry_for_design
from tests.test_namd_extra_bases import _design
from tests.test_nucleotide_transforms import _atom
from tests.test_overhang_connections import _seed_ds_linker_design
from tests.test_part_motion_native_characterization import terminal_tail_recipe
from backend.core.models import Direction
from backend.api.routes_nucleotide_transforms import _target_exists
from tests.test_part_transform_preview import snapshot
from tests.test_part_transform_inputs import pose as pose_input


@pytest.mark.parametrize("end", ["five_prime", "three_prime"])
@pytest.mark.parametrize("direction", [Direction.FORWARD, Direction.REVERSE])
@pytest.mark.parametrize("selected_count", [1, 2])
def test_explicit_tail_selection_moves_only_selected_tail_residues(end, direction, selected_count):
    design, _ = terminal_tail_recipe(end, direction)
    pose = NucleotideTransform(kind="base", helix_id="__ext_selected-tail", bp_index=0,
                              direction=direction, translation=[0.4, -0.2, 0.7])
    assert _target_exists(design, pose)
    assert not _target_exists(design, pose.model_copy(update={"bp_index": 2}))
    assert not _target_exists(design, pose.model_copy(update={"copy_k": 1}))
    wrong = Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD
    assert not _target_exists(design, pose.model_copy(update={"direction": wrong}))
    changed = snapshot(design, "nucleotide-transform-batch", {
        "transforms": [pose_input(helix_id=pose.helix_id, bp_index=i,
            direction=direction.value, translation=pose.translation) for i in range(selected_count)],
        "history_seed": "00000000-0000-0000-0000-000000016003",
    }, "selected-tail-pose")
    before = build_atomistic_model(design, fast_bridges=True)
    after = build_atomistic_model(changed, fast_bridges=True)
    assert before.bonds == after.bonds
    count = 0
    for a, b in zip(before.atoms, after.atoms, strict=True):
        if a.extension_id == "selected-tail" and a.ext_k < selected_count:
            count += 1
            np.testing.assert_allclose([b.x, b.y, b.z],
                np.asarray([a.x, a.y, a.z]) + pose.translation, rtol=0, atol=1e-12)
        else:
            assert (a.x, a.y, a.z) == (b.x, b.y, b.z)
    assert count > 0
    full_before = _geometry_for_design(design)
    full_after = _geometry_for_design(changed)
    for a, b in zip(full_before, full_after, strict=True):
        if a["helix_id"] == pose.helix_id and a["bp_index"] < selected_count:
            np.testing.assert_allclose(b["backbone_position"],
                np.asarray(a["backbone_position"]) + pose.translation, rtol=0, atol=1e-12)
        else:
            assert a == b


@pytest.mark.parametrize("rotate", [False, True], ids=["move", "rotate"])
def test_ds_bridge_anchor_pose_preserves_all_unselected_full_records(rotate):
    design = _seed_ds_linker_design()
    pose = NucleotideTransform(kind="base", helix_id="oh_helix_a", bp_index=0,
        direction="REVERSE", translation=[0.4, -0.2, 0.7], pivot=[0.75, -0.5, 0.25],
        rotation=[0, 0, 2**-0.5, 2**-0.5] if rotate else [0, 0, 0, 1])
    rotation = np.array([[0, -1, 0], [1, 0, 0], [0, 0, 1]]) if rotate else np.eye(3)
    def expected_point(point):
        return np.asarray(pose.pivot) + rotation @ (np.asarray(point) - pose.pivot) + pose.translation
    before = _geometry_for_design(design)
    after = _geometry_for_design(design.model_copy(update={"nucleotide_transforms": [pose]}))
    assert any(n["helix_id"].startswith("__lnk__") for n in before)
    for a, b in zip(before, after, strict=True):
        key = (a["helix_id"], a["bp_index"], a["direction"])
        assert key == (b["helix_id"], b["bp_index"], b["direction"])
        if key == (pose.helix_id, pose.bp_index, pose.direction.value):
            np.testing.assert_allclose(b["backbone_position"],
                expected_point(a["backbone_position"]), rtol=0, atol=1e-12)
            for field in ["base_normal", "axis_tangent"]:
                np.testing.assert_allclose(b[field], rotation @ a[field], rtol=0, atol=1e-12)
        else:
            assert a == b, f"Unselected Full record changed: {key}"
    atoms_before = build_atomistic_model(design, fast_bridges=True)
    atoms_after = build_atomistic_model(
        design.model_copy(update={"nucleotide_transforms": [pose]}), fast_bridges=True)
    assert atoms_before.bonds == atoms_after.bonds
    for a, b in zip(atoms_before.atoms, atoms_after.atoms, strict=True):
        assert atom_base_key(a) == atom_base_key(b)
        if atom_base_key(a) == "oh_helix_a:0:REVERSE":
            np.testing.assert_allclose([b.x, b.y, b.z],
                expected_point([a.x, a.y, a.z]), rtol=0, atol=1e-12)
        else:
            assert (a.x, a.y, a.z) == (b.x, b.y, b.z)


@pytest.mark.parametrize("selected", ["anchor", "tail"])
def test_tail_and_anchor_have_independent_pose_identity(selected):
    atoms = [_atom(), _atom(extension_id="tail", ext_k=0),
             _atom(extension_id="tail", ext_k=1), _atom(copy_k=1),
             _atom(crossover_id="xo", extra_base_k=0)]
    target = ("h1", 4) if selected == "anchor" else ("__ext_tail", 0)
    transform = NucleotideTransform(kind="base", helix_id=target[0],
        bp_index=target[1], direction="FORWARD", translation=[0, 3, 0])
    apply_nucleotide_transforms(atoms, Design(nucleotide_transforms=[transform]))
    assert [a.y for a in atoms] == ([3, 0, 0, 0, 0] if selected == "anchor" else [0, 3, 0, 0, 0])


@pytest.mark.parametrize("sequence", ["T", "TT"])
@pytest.mark.parametrize("endpoint", ["half_a", "half_b"])
@pytest.mark.parametrize("fast_bridges", [True, False], ids=["display", "default-build"])
def test_crossover_endpoint_pose_preserves_every_unselected_atom(sequence, endpoint, fast_bridges):
    design = _design(sequence)
    half = getattr(design.crossovers[0], endpoint)
    pose = NucleotideTransform(kind="base", helix_id=half.helix_id,
        bp_index=half.index, direction=half.strand, translation=[0.4, -0.2, 0.7])
    before = build_atomistic_model(design, fast_bridges=fast_bridges)
    after = build_atomistic_model(design.model_copy(update={"nucleotide_transforms": [pose]}),
                                  fast_bridges=fast_bridges)
    assert before.bonds == after.bonds
    selected = f"{half.helix_id}:{half.index}:{half.strand.value}"
    for a, b in zip(before.atoms, after.atoms, strict=True):
        assert atom_base_key(a) == atom_base_key(b)
        expected = np.array([a.x, a.y, a.z])
        if atom_base_key(a) == selected:
            expected += pose.translation
            np.testing.assert_allclose([b.x, b.y, b.z], expected, rtol=0, atol=1e-12)
        else:
            np.testing.assert_array_equal([b.x, b.y, b.z], expected,
                                          err_msg=f"Unselected {atom_base_key(a)} {a.name}")
