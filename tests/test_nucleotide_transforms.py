"""Independent residue poses shared by atomistic display and NAMD builds."""

import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.core.atomistic import Atom, apply_nucleotide_transforms
from backend.core.design_geometry import apply_nucleotide_transforms_to_geometry
from backend.core.models import Design, Direction, NucleotideTransform
from backend.api import state as design_state
from backend.api.main import app
from tests.conftest import make_minimal_design


def _atom(**overrides):
    data = dict(
        serial=0, name="P", element="P", residue="DT", chain_id="A", seq_num=1,
        x=1.0, y=0.0, z=0.0, strand_id="s1", helix_id="h1", bp_index=4,
        direction="FORWARD",
    )
    data.update(overrides)
    return Atom(**data)


def test_regular_nucleotide_transform_moves_only_matching_residue_atoms():
    qz90 = [0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4)]
    transform = NucleotideTransform(
        kind="base", helix_id="h1", bp_index=4, direction=Direction.FORWARD,
        pivot=[0, 0, 0], translation=[2, 0, 0], rotation=qz90,
    )
    matching = [_atom(name="P"), _atom(serial=1, name="C1'", x=0, y=1)]
    other = _atom(serial=2, bp_index=5, x=9)
    matched = apply_nucleotide_transforms(matching + [other], Design(nucleotide_transforms=[transform]))
    assert matched == {transform.id}
    assert [matching[0].x, matching[0].y, matching[0].z] == pytest.approx([2, 1, 0])
    assert [matching[1].x, matching[1].y, matching[1].z] == pytest.approx([1, 0, 0])
    assert other.x == 9


def test_regular_nucleotide_transform_drives_abstract_geometry_with_same_pose():
    qz90 = [0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4)]
    transform = NucleotideTransform(
        kind="base", helix_id="h1", bp_index=4, direction=Direction.FORWARD,
        pivot=[0, 0, 0], translation=[2, 0, 0], rotation=qz90,
    )
    nuc = {
        "helix_id": "h1", "bp_index": 4, "direction": "FORWARD",
        "backbone_position": [1, 0, 0], "base_position": [0, 1, 0],
        "base_normal": [1, 0, 0], "axis_tangent": [0, 0, 1],
    }
    matched = apply_nucleotide_transforms_to_geometry(
        [nuc], Design(nucleotide_transforms=[transform]))
    assert matched == {transform.id}
    assert nuc["backbone_position"] == pytest.approx([2, 1, 0])
    assert nuc["base_position"] == pytest.approx([1, 0, 0])
    assert nuc["base_normal"] == pytest.approx([0, 1, 0])
    assert nuc["axis_tangent"] == pytest.approx([0, 0, 1])


def test_extra_base_transform_uses_crossover_identity_not_source_helix_identity():
    transform = NucleotideTransform(
        kind="extra_base", crossover_id="xo-1", extra_base_k=1,
        pivot=[0, 0, 0], translation=[0, 3, 0], rotation=[0, 0, 0, 1],
    )
    insert = _atom(crossover_id="xo-1", extra_base_k=1)
    source_base = _atom(serial=1)
    apply_nucleotide_transforms([insert, source_base], Design(nucleotide_transforms=[transform]))
    assert [insert.x, insert.y, insert.z] == pytest.approx([1, 3, 0])
    assert [source_base.x, source_base.y, source_base.z] == pytest.approx([1, 0, 0])


def test_transform_round_trips_in_design_json_and_normalizes_quaternion():
    transform = NucleotideTransform(
        kind="base", helix_id="h1", bp_index=2, direction="REVERSE",
        pivot=[1, 2, 3], translation=[4, 5, 6], rotation=[0, 0, 0, 2],
    )
    restored = Design.model_validate_json(Design(nucleotide_transforms=[transform]).model_dump_json())
    assert restored.nucleotide_transforms[0].target_key() == ("base", "h1", 2, "REVERSE", 0)
    assert restored.nucleotide_transforms[0].rotation == [0, 0, 0, 1]


@pytest.mark.parametrize("kwargs", [
    {"kind": "base", "helix_id": "h1", "bp_index": 1},
    {"kind": "extra_base", "crossover_id": "xo"},
    {"kind": "base", "helix_id": "h1", "bp_index": 1, "direction": "FORWARD", "rotation": [0, 0, 0, 0]},
])
def test_invalid_or_incomplete_transform_is_rejected(kwargs):
    with pytest.raises(ValidationError):
        NucleotideTransform(**kwargs)


def test_put_route_persists_one_undoable_pose_and_composes_followup_delta():
    design_state.set_design(make_minimal_design())
    client = TestClient(app)
    body = {
        "kind": "base", "helix_id": "h0", "bp_index": 4, "direction": "FORWARD",
        "copy_k": 0, "pivot": [0, 0, 0], "translation": [1, 0, 0],
        "rotation": [0, 0, 0, 1],
    }
    first = client.put("/api/design/nucleotide-transform", json=body)
    assert first.status_code == 200
    stored = first.json()["design"]["nucleotide_transforms"]
    assert len(stored) == 1 and stored[0]["translation"] == [1, 0, 0]

    second = client.put("/api/design/nucleotide-transform", json={
        **body, "translation": [0, 2, 0], "compose": True,
    })
    assert second.status_code == 200
    stored2 = second.json()["design"]["nucleotide_transforms"]
    assert len(stored2) == 1
    assert stored2[0]["id"] == stored[0]["id"]
    assert stored2[0]["translation"] == pytest.approx([1, 2, 0])

    undo = client.post("/api/design/undo")
    assert undo.status_code == 200
    assert undo.json()["design"]["nucleotide_transforms"][0]["translation"] == [1, 0, 0]


def test_put_route_rejects_a_stale_target():
    design_state.set_design(make_minimal_design())
    response = TestClient(app).put("/api/design/nucleotide-transform", json={
        "kind": "extra_base", "crossover_id": "gone", "extra_base_k": 0,
        "pivot": [0, 0, 0], "translation": [1, 0, 0], "rotation": [0, 0, 0, 1],
    })
    assert response.status_code == 404
