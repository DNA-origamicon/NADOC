"""Residue commands must not expand a posed owner on a shared helix."""
from uuid import UUID

import pytest
from fastapi.testclient import TestClient

from backend.api import part_proof_commands as commands, state
from backend.api.main import app
from backend.core.atomistic import build_atomistic_model
from backend.core.base_keys import atom_base_key
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import Direction
from tests.test_part_member_motion_order import _source, _owner, _target, D
from tests.test_part_transform_preview import snapshot


def source(direction):
    design = _source()
    design = snapshot(design, "nick", {
        "helix_id": design.helices[0].id, "bp_index": 3,
        "direction": direction.value,
    }, "partial-nick")
    _, target = _target(design, direction)
    member = next(r for r in _geometry_for_design(design) if
        r["helix_id"] == target["helix_id"] and r["bp_index"] == 3
        and r["direction"] == direction.value)
    design = _owner(design, design.find_strand(member["strand_id"]))
    return design, target


def assert_unselected_exact(before, after, target):
    assert before.cluster_transforms == after.cluster_transforms
    assert before.strands == after.strands
    assert before.crossovers == after.crossovers
    selected = target["helix_id"], target["bp_index"], target["direction"]
    for a, b in zip(_geometry_for_design(before), _geometry_for_design(after), strict=True):
        if (a["helix_id"], a["bp_index"], a["direction"]) != selected:
            assert a == b
    old_atoms, new_atoms = (build_atomistic_model(d, fast_bridges=True) for d in (before, after))
    assert old_atoms.bonds == new_atoms.bonds
    key = f"{selected[0]}:{selected[1]}:{selected[2]}"
    for a, b in zip(old_atoms.atoms, new_atoms.atoms, strict=True):
        assert atom_base_key(a) == atom_base_key(b)
        if atom_base_key(a) != key:
            assert a == b


@pytest.mark.parametrize("direction", list(Direction))
@pytest.mark.parametrize("kind", ["nucleotide-transform", "nucleotide-transform-batch", "nucleotide-transform-delete"])
def test_native_pose_commands_preserve_every_non_pose_field(direction, kind):
    from backend.api.part_annotation_commands import build
    design, target = source(direction)
    body = {**target, **D, "compose": True}
    params = {**body, "history_seed": str(UUID(int=26009))}
    if kind.endswith("-batch"):
        params = {"transforms": [body], "history_seed": params["history_seed"]}
    elif kind.endswith("-delete"):
        design = build("nucleotide-transform", design, params)
        params = {"transform_id": design.nucleotide_transforms[0].id}
    captured = design.model_dump_json()
    result = commands.execute(kind, design, {**params, "_proof_version": 1})
    assert result.model_dump(exclude={"nucleotide_transforms"}) == design.model_dump(exclude={"nucleotide_transforms"})
    assert_unselected_exact(design, result, target)
    assert design.model_dump_json() == captured


@pytest.mark.parametrize("direction", list(Direction))
@pytest.mark.parametrize("batch", [False, True])
def test_recorded_pose_replace_delete_and_undo_preserve_partial_owner(direction, batch):
    design, target = source(direction)
    state.set_design(design)
    client = TestClient(app)
    body = {**target, **D, "compose": True}
    endpoint = "/api/design/nucleotide-transforms" if batch else "/api/design/nucleotide-transform"
    def put(value):
        response = client.put(endpoint, json={"transforms": [value]} if batch else value)
        assert response.status_code == 200, response.text
        return state.get_or_404().model_copy(deep=True)
    first = put(body)
    assert_unselected_exact(design, first, target)
    replaced = put({**body, "compose": False, "translation": [-1, .5, 2]})
    assert_unselected_exact(first, replaced, target)
    identity = replaced.nucleotide_transforms[0].id
    response = client.delete(f"/api/design/nucleotide-transform/{identity}")
    assert response.status_code == 200, response.text
    deleted = state.get_or_404().model_copy(deep=True)
    assert_unselected_exact(replaced, deleted, target)
    assert not deleted.nucleotide_transforms
    assert _geometry_for_design(deleted) == _geometry_for_design(design)
    from backend.core.part_history_contract import assess_part_history
    proof = assess_part_history(deleted, execute=commands.execute, dependencies=commands.dependencies)
    assert proof["status"] == "verified" and proof["native_editable"], proof
    response = client.post("/api/design/undo")
    assert response.status_code == 200, response.text
    restored = state.get_or_404()
    assert restored.nucleotide_transforms == replaced.nucleotide_transforms
    assert_unselected_exact(replaced, restored, target)
