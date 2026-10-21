"""Named ordinary motion never inherits terminal extension atoms by anchor."""
import numpy as np
import pytest

from backend.core.atomistic import build_atomistic_model
from backend.core.base_keys import atom_base_key
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Direction
from backend.core.part_group_model import GroupOrganization, PartGroup
from tests.test_part_member_motion_order import N, D, M, _nucleotide, _rigid
from tools.member_motion_ordering_program import compile_ordered_probe
from tools.member_motion_tail_audit import tail_source


@pytest.mark.parametrize("direction", list(Direction))
@pytest.mark.parametrize("end", ["five_prime", "three_prime"])
@pytest.mark.parametrize("phase", [0, 43])
def test_named_helix_motion_keeps_unselected_existing_tails_exact(direction, end, phase, monkeypatch):
    source, address = tail_source(end, direction, phase)
    target = dict(zip(("helix_id", "bp_index", "direction", "copy_k"), address, strict=True))
    target["kind"] = "base"
    source = source.copy_with(group_organization=GroupOrganization(groups=[
        PartGroup(id="ordinary", helix_ids=[address[0]])]))
    prefix = _nucleotide(source, target, N, "prior-anchor")
    later = _nucleotide(prefix, target, D, "later-anchor", compose=True)
    captured = prefix.model_dump_json()
    program = compile_ordered_probe(prefix, later.feature_log[-1], [address[0]],
                                    named_targets=[{"kind": "part_group", "id": "ordinary"}])
    assert all(key[0] == address[0] for key in program.selected_material_keys)
    before_full, before_atoms = _geometry_for_design(prefix), build_atomistic_model(prefix, fast_bridges=True)
    native_full, native_atoms = _geometry_for_design(later), build_atomistic_model(later, fast_bridges=True)
    assert program.evaluate(motion_enabled=False)[:2] == (native_full, native_atoms)

    def forbidden(*args, **kwargs):
        raise AssertionError("Evaluation replayed native history or rebuilt geometry")
    monkeypatch.setattr("tools.member_motion_ordering_program.commands.execute", forbidden)
    monkeypatch.setattr("tools.member_motion_ordering_program._geometry_for_design", forbidden)
    monkeypatch.setattr("tools.member_motion_ordering_program.build_atomistic_model", forbidden)
    full, atoms, _ = program.evaluate()
    assert atoms.bonds == before_atoms.bonds
    target_key = f"{address[0]}:{address[1]}:{address[2]}"
    tail_atoms = tail_records = 0
    for before, actual in zip(before_full, full, strict=True):
        if before["helix_id"] != address[0]:
            assert actual == before
            tail_records += bool(before.get("extension_id"))
            continue
        for field in ("backbone_position", "base_position", "slab_position"):
            expected = _rigid(before[field], M)
            if (before["bp_index"], before["direction"]) == (address[1], address[2]):
                expected = _rigid(expected, D)
            np.testing.assert_allclose(actual[field], expected, rtol=0, atol=1e-10)
    for before, actual in zip(before_atoms.atoms, atoms.atoms, strict=True):
        key = atom_base_key(before)
        if before.extension_id or before.helix_id != address[0]:
            assert actual == before
            tail_atoms += bool(before.extension_id)
            continue
        expected = _rigid([before.x, before.y, before.z], M)
        if key == target_key:
            expected = _rigid(expected, D)
        np.testing.assert_allclose([actual.x, actual.y, actual.z], expected, rtol=0, atol=1e-10)
    assert tail_atoms > 0 and tail_records == 4
    assert prefix.model_dump_json() == captured
