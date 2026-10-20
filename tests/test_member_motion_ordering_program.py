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
