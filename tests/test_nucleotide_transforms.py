"""Independent residue poses shared by atomistic display and NAMD builds."""

import math

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from backend.core.atomistic import Atom, apply_nucleotide_transforms
from backend.core.design_geometry import apply_nucleotide_transforms_to_geometry
from backend.core.models import ClusterRigidTransform, Design, Direction, NucleotideTransform
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
        "display_slab_offset": [0.1, 0.2, 0.3],
        "display_slab_rotation": [0, 0, 0, 1],
    }
    first = client.put("/api/design/nucleotide-transform", json=body)
    assert first.status_code == 200
    stored = first.json()["design"]["nucleotide_transforms"]
    assert len(stored) == 1 and stored[0]["translation"] == [1, 0, 0]
    assert first.json()["design"]["feature_log"][-1]["op_kind"] == "nucleotide-transform"

    second = client.put("/api/design/nucleotide-transform", json={
        **body, "translation": [0, 2, 0], "compose": True,
    })
    assert second.status_code == 200
    stored2 = second.json()["design"]["nucleotide_transforms"]
    assert len(stored2) == 1
    assert stored2[0]["id"] == stored[0]["id"]
    assert stored2[0]["translation"] == pytest.approx([1, 2, 0])
    assert stored2[0]["display_slab_offset"] == [0.1, 0.2, 0.3]

    undo = client.post("/api/design/undo")
    assert undo.status_code == 200
    assert undo.json()["design"]["nucleotide_transforms"][0]["translation"] == [1, 0, 0]
    assert len(undo.json()["design"]["feature_log"]) == 1

    redo = client.post("/api/design/redo")
    assert redo.status_code == 200
    assert redo.json()["design"]["nucleotide_transforms"][0]["translation"] == pytest.approx([1, 2, 0])
    assert [e["op_kind"] for e in redo.json()["design"]["feature_log"]] == [
        "nucleotide-transform", "nucleotide-transform",
    ]


def test_delete_transform_records_pose_reset_in_feature_log():
    design_state.set_design(make_minimal_design())
    client = TestClient(app)
    created = client.put("/api/design/nucleotide-transform", json={
        "kind": "base", "helix_id": "h0", "bp_index": 4, "direction": "FORWARD",
        "copy_k": 0, "pivot": [0, 0, 0], "translation": [1, 0, 0],
        "rotation": [0, 0, 0, 1],
    }).json()
    transform_id = created["design"]["nucleotide_transforms"][0]["id"]
    deleted = client.delete(f"/api/design/nucleotide-transform/{transform_id}")
    assert deleted.status_code == 200
    assert deleted.json()["design"]["feature_log"][-1]["op_kind"] == "nucleotide-transform-delete"
    undone = client.post("/api/design/undo")
    assert len(undone.json()["design"]["nucleotide_transforms"]) == 1
    assert undone.json()["design"]["feature_log"][-1]["op_kind"] == "nucleotide-transform"
    redone = client.post("/api/design/redo")
    assert redone.json()["design"]["nucleotide_transforms"] == []
    assert redone.json()["design"]["feature_log"][-1]["op_kind"] == "nucleotide-transform-delete"


def test_put_route_embeds_the_requested_display_projection():
    """Apply must not replace measured display geometry with legacy geometry."""
    design_state.set_design(make_minimal_design())
    client = TestClient(app)
    body = {
        "kind": "base", "helix_id": "h0", "bp_index": 4, "direction": "FORWARD",
        "copy_k": 0, "pivot": [0, 0, 0], "translation": [1, 0, 0],
        "rotation": [0, 0, 0, 1],
    }
    measured = client.put(
        "/api/design/nucleotide-transform", json=body,
        headers={"X-NADOC-Measured-Positioning": "true"},
    )
    assert measured.status_code == 200

    # The mutation response and canonical measured GET must agree for every
    # untouched residue (the transformed residue intentionally differs).
    loaded = client.get("/api/design/geometry?measured_positioning=true")
    assert loaded.status_code == 200
    response_nucs = {
        (n["helix_id"], n["bp_index"], n["direction"], n.get("copy_k", 0)): n
        for n in measured.json()["nucleotides"]
    }
    loaded_nucs = {
        (n["helix_id"], n["bp_index"], n["direction"], n.get("copy_k", 0)): n
        for n in loaded.json()["nucleotides"]
    }
    for key, after in response_nucs.items():
        if key == ("h0", 4, "FORWARD", 0):
            continue
        assert after["backbone_position"] == pytest.approx(loaded_nucs[key]["backbone_position"])
        assert after["base_position"] == pytest.approx(loaded_nucs[key]["base_position"])


def test_committed_cluster_move_round_trips_through_undo_redo_without_log_drift():
    design = make_minimal_design()
    cluster = ClusterRigidTransform(id="move-me", name="Move me", helix_ids=["h0"])
    design_state.set_design(design.copy_with(cluster_transforms=[cluster]))
    client = TestClient(app)

    moved = client.patch("/api/design/cluster/move-me", json={
        "translation": [2, 3, 4], "commit": True,
    })
    assert moved.status_code == 200
    assert moved.json()["design"]["cluster_transforms"][0]["translation"] == [2, 3, 4]
    assert moved.json()["design"]["feature_log"][-1]["feature_type"] == "cluster_op"

    undone = client.post("/api/design/undo")
    assert undone.status_code == 200
    assert undone.json()["design"]["cluster_transforms"][0]["translation"] == [0, 0, 0]
    assert undone.json()["design"]["feature_log"] == []

    redone = client.post("/api/design/redo")
    assert redone.status_code == 200
    assert redone.json()["design"]["cluster_transforms"][0]["translation"] == [2, 3, 4]
    assert len(redone.json()["design"]["feature_log"]) == 1


def test_put_route_rejects_a_stale_target():
    design_state.set_design(make_minimal_design())
    response = TestClient(app).put("/api/design/nucleotide-transform", json={
        "kind": "extra_base", "crossover_id": "gone", "extra_base_k": 0,
        "pivot": [0, 0, 0], "translation": [1, 0, 0], "rotation": [0, 0, 0, 1],
    })
    assert response.status_code == 404
