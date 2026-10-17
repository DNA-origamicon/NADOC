"""Characterize current terminal-tail pose disagreement, not desired semantics.

The native recipe and both render builds stay in memory. No candidate placement,
production geometry, numerical pin or golden is changed here. Full and atomistic
tail behavior are deliberately asserted separately: they currently do not share
the same response to a saved pose of the terminal nucleotide.
"""

from dataclasses import fields
from math import sqrt
from uuid import UUID

import numpy as np
import pytest

from backend.api import crud
from backend.core import models as m
from backend.core.atomistic import Atom, build_atomistic_model
from backend.core.base_keys import atom_base_key
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_history_contract import create_empty_part
from tests.test_part_deformation_preview import _append
from tests.test_part_transform_inputs import pose
from tests.test_part_transform_preview import snapshot


_ROTATION = np.array([[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]])
_PIVOT = np.array([0.75, -0.5, 0.25])
_TRANSLATION = np.array([2.0, -1.0, 3.0])
_ATOM_IDENTITY_FIELDS = tuple(field.name for field in fields(Atom)
                              if field.name not in {"x", "y", "z"})


def terminal_tail_recipe(end, direction):
    """One real native 8-bp duplex, with selected/control sequence-only tails."""
    source = snapshot(
        create_empty_part("Terminal pose characterization", "HONEYCOMB"),
        "bundle-create",
        crud.BundleRequest(cells=[[0, 0]], length_bp=8, ligate_adjacent=False,
                           history_seed=UUID(int=16001)).model_dump(mode="json"),
        "native-bundle",
    )
    selected = next(strand for strand in source.strands
                    if strand.domains[0].direction == direction)
    control = next(strand for strand in source.strands if strand.id != selected.id)
    entries = [{"create": True, "extension": {
        "id": identity, "strand_id": strand.id, "end": end,
        "sequence": "AC", "modification": None, "label": identity,
    }} for identity, strand in (("selected-tail", selected), ("control-tail", control))]
    source = _append(source, m.SnapshotLogEntry(
        id="native-tails", op_kind="extension-upsert", label="Native terminal tails",
        params={"_proof_version": 2, "entries": entries}, evicted=True,
        design_snapshot_gz_b64="unusable-recovery", post_state_gz_b64="unusable-recovery",
    ))
    domain = selected.domains[0] if end == "five_prime" else selected.domains[-1]
    bp = domain.start_bp if end == "five_prime" else domain.end_bp
    target = domain.helix_id, bp, domain.direction.value, 0
    return source, target


def _nucleotide_key(value):
    return value["helix_id"], value["bp_index"], value["direction"], value.get("copy_k", 0)


def _xyz(atom):
    return np.array([atom.x, atom.y, atom.z])


def _expected_point(point):
    # Independent explicit 90-degree rotation, not the production quaternion helper.
    return _PIVOT + _ROTATION @ (np.asarray(point) - _PIVOT) + _TRANSLATION


@pytest.mark.parametrize("end", ["five_prime", "three_prime"], ids=["5p", "3p"])
@pytest.mark.parametrize("direction", [m.Direction.FORWARD, m.Direction.REVERSE],
                         ids=["forward", "reverse"])
def test_saved_terminal_pose_moves_atomistic_tail_but_leaves_full_tail_at_old_anchor(
    end, direction, record_property,
):
    source, target = terminal_tail_recipe(end, direction)
    before_source = source.model_dump_json()
    changed = snapshot(source, "nucleotide-transform", {
        **pose(helix_id=target[0], bp_index=target[1], direction=target[2],
               rotation=[0.0, 0.0, sqrt(0.5), sqrt(0.5)],
               translation=_TRANSLATION.tolist(), pivot=_PIVOT.tolist()),
        "history_seed": str(UUID(int=16002)),
    }, "terminal-residue-pose")
    before_changed = changed.model_dump_json()
    assert source.recipe_root.kind == "empty" and changed.recipe_root == source.recipe_root
    assert [entry.op_kind for entry in source.feature_log] == ["bundle-create", "extension-upsert"]
    assert changed.feature_log[-1].op_kind == "nucleotide-transform"
    assert changed.extensions == source.extensions
    assert changed.strands == source.strands and changed.helices == source.helices
    assert len(changed.nucleotide_transforms) == 1

    full_before = _geometry_for_design(source)
    full_after = _geometry_for_design(changed)
    assert [_nucleotide_key(value) for value in full_before] == [
        _nucleotide_key(value) for value in full_after]
    assert len({_nucleotide_key(value) for value in full_before}) == len(full_before)
    by_key = {_nucleotide_key(value): value for value in full_after}
    assert target in by_key
    full_tail_displacements = []
    unselected_records = 0
    for before in full_before:
        after = by_key[_nucleotide_key(before)]
        if _nucleotide_key(before) == target:
            for field in ("backbone_position", "base_position", "slab_position"):
                np.testing.assert_allclose(after[field], _expected_point(before[field]), rtol=0, atol=2e-12)
            for field in ("base_normal", "axis_tangent"):
                np.testing.assert_allclose(after[field], _ROTATION @ before[field], rtol=0, atol=2e-12)
            assert after["backbone_position"] != before["backbone_position"]
        else:
            # Includes every selected tail bead and the opposite strand/tail.
            assert after == before
            unselected_records += 1
        if before.get("extension_id") == "selected-tail":
            full_tail_displacements.append(float(np.linalg.norm(
                np.asarray(after["backbone_position"]) - before["backbone_position"])))
    assert len(full_tail_displacements) == 2 and max(full_tail_displacements) == 0.0
    assert unselected_records > len(full_tail_displacements)
    assert sum(value.get("extension_id") == "control-tail" for value in full_before) == 2

    # Fast bridge construction is the existing display path, not a new solver or
    # a simulation/export. Do not compare tail atoms to the different CG arc.
    atoms_before = build_atomistic_model(source, fast_bridges=True)
    atoms_after = build_atomistic_model(changed, fast_bridges=True)
    assert atoms_after.bonds == atoms_before.bonds
    assert [tuple(getattr(atom, field) for field in _ATOM_IDENTITY_FIELDS)
            for atom in atoms_after.atoms] == [
                tuple(getattr(atom, field) for field in _ATOM_IDENTITY_FIELDS)
                for atom in atoms_before.atoms]
    terminal_key = f"{target[0]}:{target[1]}:{target[2]}"
    moved_terminal, moved_tail, unchanged_control_tail = 0, [], 0
    for before, after in zip(atoms_before.atoms, atoms_after.atoms, strict=True):
        is_terminal = atom_base_key(before) == terminal_key
        is_tail = before.extension_id == "selected-tail"
        if is_terminal or is_tail:
            np.testing.assert_allclose(_xyz(after), _expected_point(_xyz(before)), rtol=0, atol=2e-11)
            assert np.linalg.norm(_xyz(after) - _xyz(before)) > 1.0
            moved_terminal += int(is_terminal)
            if is_tail:
                moved_tail.append(float(np.linalg.norm(_xyz(after) - _xyz(before))))
        else:
            np.testing.assert_array_equal(_xyz(after), _xyz(before))
            unchanged_control_tail += int(before.extension_id == "control-tail")
    assert moved_terminal > 0 and moved_tail and unchanged_control_tail > 0
    record_property("full_selected_tail_max_displacement_nm", max(full_tail_displacements))
    record_property("atomistic_selected_tail_max_displacement_nm", max(moved_tail))
    record_property("selected_terminal_atom_count", moved_terminal)
    record_property("selected_tail_atom_count", len(moved_tail))
    print(f"terminal-tail {end}/{direction.value}: Full tail max=0 nm; "
          f"atomistic tail min/max={min(moved_tail):.6g}/{max(moved_tail):.6g} nm; "
          f"terminal/tail atoms={moved_terminal}/{len(moved_tail)}")

    # This test freezes observed disagreement for review. It does not authorize
    # carrying tails with a new group motion, nor prefer either current behavior.
    assert source.model_dump_json() == before_source
    assert changed.model_dump_json() == before_changed
