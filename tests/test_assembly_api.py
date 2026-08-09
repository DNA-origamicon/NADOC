"""
Phase 2 tests — Assembly CRUD API.

Uses FastAPI TestClient to exercise all assembly endpoints.  Each test resets
both the assembly and design states to prevent cross-contamination.
"""

from __future__ import annotations
from tests._assembly_compat import v1_instances

import math

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.models import (
    Assembly,
    AssemblyJoint,
    ClusterJoint,
    ClusterRigidTransform,
    ConnectionType,
    Design,
    DesignMetadata,
    InterfacePoint,
    PartInstance,
    PartSourceInline,
    Vec3,
)

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset():
    """Clean assembly state before and after every test."""
    assembly_state.close_session()
    yield
    assembly_state.close_session()


def _inline_source_dict() -> dict:
    """Return a minimal PartSource dict with type='inline' and an empty Design."""
    from backend.core.models import Design

    return {"type": "inline", "design": Design().to_dict()}


def _inline_cluster_source_dict() -> dict:
    cluster = ClusterRigidTransform(id="cluster-a", name="Arm", helix_ids=["h1"])
    joint = ClusterJoint(
        id="joint-a",
        cluster_id="cluster-a",
        axis_origin=[0, 0, 0],
        axis_direction=[0, 0, 1],
    )
    design = Design(cluster_transforms=[cluster], cluster_joints=[joint])
    return {"type": "inline", "design": design.to_dict()}


def _inline_overlapping_cluster_source_dict() -> dict:
    scaffold = ClusterRigidTransform(
        id="scaffold", name="Scaffold Cluster", helix_ids=["h1", "h2", "h3"]
    )
    geometry = ClusterRigidTransform(
        id="geometry", name="Geometry Cluster", helix_ids=["h1"]
    )
    joint = ClusterJoint(
        id="joint-g",
        cluster_id="geometry",
        axis_origin=[0, 0, 0],
        axis_direction=[0, 0, 1],
    )
    design = Design(cluster_transforms=[scaffold, geometry], cluster_joints=[joint])
    return {"type": "inline", "design": design.to_dict()}


# ── GET /assembly ─────────────────────────────────────────────────────────────


def test_get_assembly_creates_if_none():
    r = client.get("/api/assembly")
    assert r.status_code == 200
    body = r.json()
    assert "assembly" in body
    assert v1_instances(body) == []
    assert body["assembly"]["joints"] == []


def test_get_assembly_returns_existing():
    a = Assembly(metadata=DesignMetadata(name="Existing"))
    assembly_state.set_assembly(a)
    r = client.get("/api/assembly")
    assert r.status_code == 200
    assert r.json()["assembly"]["metadata"]["name"] == "Existing"


# ── POST /assembly ────────────────────────────────────────────────────────────


def test_create_assembly_returns_201():
    r = client.post("/api/assembly")
    assert r.status_code == 201
    body = r.json()
    assert v1_instances(body) == []
    assert body["assembly"]["joints"] == []


def test_create_assembly_replaces_existing():
    a = Assembly(metadata=DesignMetadata(name="Old"))
    assembly_state.set_assembly(a)

    r = client.post("/api/assembly")
    assert r.status_code == 201
    # New assembly has no name set (default empty string)
    new_id = r.json()["assembly"]["id"]
    assert new_id != a.id


# ── POST /assembly/import ─────────────────────────────────────────────────────


def test_import_assembly_roundtrip():
    a = Assembly(metadata=DesignMetadata(name="Imported"))
    r = client.post("/api/assembly/import", json={"content": a.to_json()})
    assert r.status_code == 200
    body = r.json()
    assert body["assembly"]["metadata"]["name"] == "Imported"
    assert body["assembly"]["id"] == a.id


def test_import_assembly_bad_json_returns_400():
    r = client.post("/api/assembly/import", json={"content": "not-json"})
    assert r.status_code == 400


# ── GET /assembly/export ──────────────────────────────────────────────────────


def test_export_assembly_returns_file():
    a = Assembly(metadata=DesignMetadata(name="My Assembly"))
    assembly_state.set_assembly(a)
    r = client.get("/api/assembly/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert ".nass" in r.headers["content-disposition"]
    # Body parses as valid Assembly JSON
    restored = Assembly.from_json(r.text)
    assert restored.id == a.id


def test_export_assembly_404_when_empty():
    r = client.get("/api/assembly/export")
    assert r.status_code == 404


# ── POST /assembly/instances ──────────────────────────────────────────────────


def test_add_instance_returns_201():
    client.post("/api/assembly")  # create fresh assembly
    r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
            "name": "Part A",
        },
    )
    assert r.status_code == 201
    body = r.json()
    instances = v1_instances(body)
    assert len(instances) == 1
    assert instances[0]["name"] == "Part A"
    assert instances[0]["source"]["type"] == "inline"


def test_add_instance_with_transform():
    client.post("/api/assembly")
    transform = {"values": [1, 0, 0, 5, 0, 1, 0, 3, 0, 0, 1, 0, 0, 0, 0, 1]}
    r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
            "name": "Shifted",
            "transform": transform,
        },
    )
    assert r.status_code == 201
    inst = v1_instances(r.json())[0]
    assert inst["transform"]["values"][3] == pytest.approx(5.0)


def test_add_instance_invalid_source_returns_400():
    client.post("/api/assembly")
    r = client.post(
        "/api/assembly/instances",
        json={
            "source": {"type": "unknown"},
            "name": "Bad",
        },
    )
    assert r.status_code == 400


# ── PATCH /assembly/instances/{id} ───────────────────────────────────────────


def test_patch_instance_name():
    client.post("/api/assembly")
    add_r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
            "name": "Original",
        },
    )
    inst_id = v1_instances(add_r.json())[0]["id"]

    r = client.patch(f"/api/assembly/instances/{inst_id}", json={"name": "Renamed"})
    assert r.status_code == 200
    instances = v1_instances(r.json())
    assert instances[0]["name"] == "Renamed"


def test_patch_instance_visible():
    client.post("/api/assembly")
    add_r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
        },
    )
    inst_id = v1_instances(add_r.json())[0]["id"]

    r = client.patch(f"/api/assembly/instances/{inst_id}", json={"visible": False})
    assert r.status_code == 200
    assert v1_instances(r.json())[0]["visible"] is False


def test_patch_instance_mode():
    client.post("/api/assembly")
    add_r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
        },
    )
    inst_id = v1_instances(add_r.json())[0]["id"]

    r = client.patch(f"/api/assembly/instances/{inst_id}", json={"mode": "rigid"})
    assert r.status_code == 200
    assert v1_instances(r.json())[0]["mode"] == "rigid"


def test_patch_instance_allow_part_joints():
    client.post("/api/assembly")
    add_r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
        },
    )
    inst_id = v1_instances(add_r.json())[0]["id"]

    r = client.patch(
        f"/api/assembly/instances/{inst_id}", json={"allow_part_joints": True}
    )
    assert r.status_code == 200
    assert v1_instances(r.json())[0]["allow_part_joints"] is True


def test_assembly_configuration_restore_ignores_newer_parts():
    client.post("/api/assembly")
    r_a = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
            "name": "A",
            "transform": {"values": [1, 0, 0, 1, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
        },
    )
    a_id = v1_instances(r_a.json())[0]["id"]
    cfg_r = client.post("/api/assembly/configurations", json={"name": "Start"})
    assert cfg_r.status_code == 200
    cfg_id = cfg_r.json()["assembly"]["configurations"][0]["id"]

    client.patch(
        f"/api/assembly/instances/{a_id}",
        json={
            "transform": {"values": [1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
        },
    )
    r_b = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
            "name": "B",
            "transform": {"values": [1, 0, 0, 9, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
        },
    )
    b_id = v1_instances(r_b.json())[-1]["id"]

    restore = client.post(f"/api/assembly/configurations/{cfg_id}/restore")
    assert restore.status_code == 200
    instances = v1_instances(restore.json())
    a = next(i for i in instances if i["id"] == a_id)
    b = next(i for i in instances if i["id"] == b_id)
    assert a["transform"]["values"][3] == pytest.approx(1.0)
    assert b["transform"]["values"][3] == pytest.approx(9.0)
    assert restore.json()["assembly"]["configuration_cursor"] == cfg_id

    rename = client.patch(
        f"/api/assembly/configurations/{cfg_id}", json={"name": "Renamed"}
    )
    assert rename.status_code == 200
    assert rename.json()["assembly"]["configurations"][0]["name"] == "Renamed"

    overwrite = client.patch(
        f"/api/assembly/configurations/{cfg_id}", json={"overwrite_current": True}
    )
    assert overwrite.status_code == 200
    assert overwrite.json()["assembly"]["configurations"][0]["id"] == cfg_id

    delete = client.delete(f"/api/assembly/configurations/{cfg_id}")
    assert delete.status_code == 200
    assert delete.json()["assembly"]["configurations"] == []


def test_assembly_camera_pose_crud():
    client.post("/api/assembly")
    r = client.post(
        "/api/assembly/camera-poses",
        json={
            "name": "Iso",
            "position": [1, 2, 3],
            "target": [0, 0, 0],
            "up": [0, 1, 0],
            "fov": 45,
            "orbit_mode": "trackball",
        },
    )
    assert r.status_code == 200
    pose = r.json()["assembly"]["camera_poses"][0]
    assert pose["name"] == "Iso"

    r2 = client.patch(
        f"/api/assembly/camera-poses/{pose['id']}", json={"name": "Front"}
    )
    assert r2.status_code == 200
    assert r2.json()["assembly"]["camera_poses"][0]["name"] == "Front"


def test_assembly_keyframe_accepts_camera_pose_and_configuration():
    client.post("/api/assembly")
    client.post(
        "/api/assembly/instances", json={"source": _inline_source_dict(), "name": "A"}
    )
    cfg = client.post("/api/assembly/configurations", json={"name": "Start"}).json()[
        "assembly"
    ]["configurations"][0]
    pose = client.post(
        "/api/assembly/camera-poses",
        json={
            "name": "Iso",
            "position": [1, 2, 3],
            "target": [0, 0, 0],
            "up": [0, 1, 0],
            "fov": 45,
            "orbit_mode": "trackball",
        },
    ).json()["assembly"]["camera_poses"][0]
    anim = client.post("/api/assembly/animations", json={"name": "Anim"}).json()[
        "assembly"
    ]["animations"][0]

    kf_r = client.post(
        f"/api/assembly/animations/{anim['id']}/keyframes",
        json={
            "camera_pose_id": pose["id"],
            "configuration_id": cfg["id"],
        },
    )
    assert kf_r.status_code == 200
    kf = kf_r.json()["assembly"]["animations"][0]["keyframes"][0]
    assert kf["camera_pose_id"] == pose["id"]
    assert kf["configuration_id"] == cfg["id"]

    patch = client.patch(
        f"/api/assembly/animations/{anim['id']}/keyframes/{kf['id']}",
        json={"configuration_id": None},
    )
    assert patch.status_code == 200
    assert (
        patch.json()["assembly"]["animations"][0]["keyframes"][0]["configuration_id"]
        is None
    )


def test_patch_instance_cluster_transform_is_assembly_scoped_and_moves_cluster_mates():
    client.post("/api/assembly")
    r_a = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_cluster_source_dict(),
            "name": "Parent",
        },
    )
    parent_id = v1_instances(r_a.json())[0]["id"]
    r_b = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
            "name": "Child",
            "transform": {"values": [1, 0, 0, 2, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
        },
    )
    child_id = v1_instances(r_b.json())[-1]["id"]
    client.post(
        "/api/assembly/joints",
        json={
            "joint_type": "revolute",
            "instance_a_id": parent_id,
            "cluster_id_a": "cluster-a",
            "instance_b_id": child_id,
        },
    )

    moved_cluster = ClusterRigidTransform(
        id="cluster-a",
        name="Arm",
        helix_ids=["h1"],
        translation=[1.0, 0.0, 0.0],
    ).model_dump(mode="json")
    delta = {"values": [1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    r = client.patch(
        f"/api/assembly/instances/{parent_id}/cluster-transform",
        json={
            "cluster_id": "cluster-a",
            "cluster_transform": moved_cluster,
            "joint_id": "joint-a",
            "joint_value": 0.5,
            "delta_transform": delta,
        },
    )
    assert r.status_code == 200
    instances = v1_instances(r.json())
    parent = next(i for i in instances if i["id"] == parent_id)
    child = next(i for i in instances if i["id"] == child_id)

    assert parent["cluster_transform_overrides"][0]["translation"] == [1.0, 0.0, 0.0]
    assert parent["joint_states"]["joint-a"] == pytest.approx(0.5)
    assert parent["source"]["design"]["cluster_transforms"][0]["translation"] == [
        0.0,
        0.0,
        0.0,
    ]
    assert child["transform"]["values"][3] == pytest.approx(7.0)
    assert r.json()["assembly"]["feature_log"][-1]["op_kind"] == "assembly-transform-instance-cluster"

    undone = client.post("/api/assembly/undo")
    undone_instances = v1_instances(undone.json())
    assert next(i for i in undone_instances if i["id"] == parent_id)["cluster_transform_overrides"] == []
    assert next(i for i in undone_instances if i["id"] == child_id)["transform"]["values"][3] == pytest.approx(2.0)

    redone = client.post("/api/assembly/redo")
    redone_instances = v1_instances(redone.json())
    assert next(i for i in redone_instances if i["id"] == parent_id)["cluster_transform_overrides"][0]["translation"] == [1, 0, 0]
    assert next(i for i in redone_instances if i["id"] == child_id)["transform"]["values"][3] == pytest.approx(7.0)


def test_propagate_fk_records_move_rotate_feature():
    client.post("/api/assembly")
    created = client.post("/api/assembly/instances", json={
        "source": _inline_source_dict(), "name": "Moved part",
    })
    instance_id = v1_instances(created.json())[0]["id"]
    moved = client.post("/api/assembly/propagate_fk", json={
        "instance_id": instance_id,
        "transform": {"values": [1, 0, 0, 3, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
    })
    assert moved.status_code == 200
    entry = moved.json()["assembly"]["feature_log"][-1]
    assert entry["op_kind"] == "assembly-transform-instance"
    assert entry["params"]["instance_id"] == instance_id
    undone = client.post("/api/assembly/undo")
    assert v1_instances(undone.json())[0]["transform"]["values"][3] == pytest.approx(0.0)
    assert undone.json()["assembly"]["feature_log"] == created.json()["assembly"]["feature_log"]
    redone = client.post("/api/assembly/redo")
    assert v1_instances(redone.json())[0]["transform"]["values"][3] == pytest.approx(3.0)
    assert redone.json()["assembly"]["feature_log"][-1]["op_kind"] == "assembly-transform-instance"


def test_direct_instance_gizmo_patch_records_move_rotate_feature():
    client.post("/api/assembly")
    created = client.post("/api/assembly/instances", json={
        "source": _inline_source_dict(), "name": "Direct gizmo part",
    })
    instance_id = v1_instances(created.json())[0]["id"]
    moved = client.patch(f"/api/assembly/instances/{instance_id}", json={
        "transform": {"values": [1, 0, 0, 4, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
    })
    assert moved.status_code == 200
    assert moved.json()["assembly"]["feature_log"][-1]["op_kind"] == "assembly-transform-instance"
    assert v1_instances(client.post("/api/assembly/undo").json())[0]["transform"]["values"][3] == pytest.approx(0.0)
    assert v1_instances(client.post("/api/assembly/redo").json())[0]["transform"]["values"][3] == pytest.approx(4.0)


def test_patch_instance_cluster_transform_moves_mate_when_cluster_is_child_side():
    client.post("/api/assembly")
    r_a = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
            "name": "Parent",
            "transform": {"values": [1, 0, 0, 2, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
        },
    )
    parent_id = v1_instances(r_a.json())[0]["id"]
    r_b = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_cluster_source_dict(),
            "name": "ChildWithCluster",
        },
    )
    child_id = v1_instances(r_b.json())[-1]["id"]
    client.post(
        "/api/assembly/joints",
        json={
            "joint_type": "revolute",
            "instance_a_id": parent_id,
            "instance_b_id": child_id,
            "cluster_id_b": "cluster-a",
        },
    )

    moved_cluster = ClusterRigidTransform(
        id="cluster-a",
        name="Arm",
        helix_ids=["h1"],
        translation=[1.0, 0.0, 0.0],
    ).model_dump(mode="json")
    delta = {"values": [1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    r = client.patch(
        f"/api/assembly/instances/{child_id}/cluster-transform",
        json={
            "cluster_id": "cluster-a",
            "cluster_transform": moved_cluster,
            "delta_transform": delta,
        },
    )
    assert r.status_code == 200
    instances = v1_instances(r.json())
    parent = next(i for i in instances if i["id"] == parent_id)
    child = next(i for i in instances if i["id"] == child_id)

    assert child["cluster_transform_overrides"][0]["translation"] == [1.0, 0.0, 0.0]
    assert parent["transform"]["values"][3] == pytest.approx(7.0)
    assert child["transform"]["values"][3] == pytest.approx(0.0)


def test_patch_instance_cluster_transform_uses_connector_cluster_for_legacy_mate():
    parent = PartInstance(
        id="parent",
        name="Parent",
        source=PartSourceInline(
            design=Design.model_validate(_inline_cluster_source_dict()["design"])
        ),
        interface_points=[
            InterfacePoint(
                label="A1",
                position=Vec3(x=0, y=0, z=0),
                normal=Vec3(x=1, y=0, z=0),
                connection_type=ConnectionType.COVALENT,
                cluster_id="cluster-a",
            ),
        ],
    )
    child = PartInstance(
        id="child",
        name="Child",
        source=PartSourceInline(design=Design()),
        transform={"values": [1, 0, 0, 2, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
        interface_points=[
            InterfacePoint(
                label="B1",
                position=Vec3(x=0, y=0, z=0),
                normal=Vec3(x=-1, y=0, z=0),
                connection_type=ConnectionType.COVALENT,
            ),
        ],
    )
    assembly_state.set_assembly(
        Assembly(
            instances=[parent, child],
            joints=[
                AssemblyJoint(
                    joint_type="revolute",
                    instance_a_id="parent",
                    instance_b_id="child",
                    connector_a_label="A1",
                    connector_b_label="B1",
                ),
            ],
        )
    )

    moved_cluster = ClusterRigidTransform(
        id="cluster-a",
        name="Arm",
        helix_ids=["h1"],
        translation=[1.0, 0.0, 0.0],
    ).model_dump(mode="json")
    delta = {"values": [1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    r = client.patch(
        "/api/assembly/instances/parent/cluster-transform",
        json={
            "cluster_id": "cluster-a",
            "cluster_transform": moved_cluster,
            "delta_transform": delta,
        },
    )
    assert r.status_code == 200
    child_json = next(i for i in v1_instances(r.json()) if i["id"] == "child")
    assert child_json["transform"]["values"][3] == pytest.approx(7.0)


def test_patch_instance_cluster_transform_infers_blunt_connector_cluster_for_older_mate():
    parent = PartInstance(
        id="parent",
        name="Parent",
        source=PartSourceInline(
            design=Design.model_validate(_inline_cluster_source_dict()["design"])
        ),
        interface_points=[
            InterfacePoint(
                label="blunt:h1:start",
                position=Vec3(x=0, y=0, z=0),
                normal=Vec3(x=1, y=0, z=0),
                connection_type=ConnectionType.COVALENT,
            ),
        ],
    )
    child = PartInstance(
        id="child",
        name="Child",
        source=PartSourceInline(design=Design()),
        transform={"values": [1, 0, 0, 2, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
        interface_points=[
            InterfacePoint(
                label="B1",
                position=Vec3(x=0, y=0, z=0),
                normal=Vec3(x=-1, y=0, z=0),
                connection_type=ConnectionType.COVALENT,
            ),
        ],
    )
    assembly_state.set_assembly(
        Assembly(
            instances=[parent, child],
            joints=[
                AssemblyJoint(
                    joint_type="revolute",
                    instance_a_id="parent",
                    instance_b_id="child",
                    connector_a_label="blunt:h1:start",
                    connector_b_label="B1",
                ),
            ],
        )
    )

    moved_cluster = ClusterRigidTransform(
        id="cluster-a",
        name="Arm",
        helix_ids=["h1"],
        translation=[1.0, 0.0, 0.0],
    ).model_dump(mode="json")
    delta = {"values": [1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    r = client.patch(
        "/api/assembly/instances/parent/cluster-transform",
        json={
            "cluster_id": "cluster-a",
            "cluster_transform": moved_cluster,
            "delta_transform": delta,
        },
    )
    assert r.status_code == 200
    child_json = next(i for i in v1_instances(r.json()) if i["id"] == "child")
    assert child_json["transform"]["values"][3] == pytest.approx(7.0)


def test_patch_instance_cluster_transform_matches_specific_cluster_despite_broad_saved_cluster():
    parent = PartInstance(
        id="parent",
        name="Parent",
        source=PartSourceInline(
            design=Design.model_validate(
                _inline_overlapping_cluster_source_dict()["design"]
            )
        ),
        interface_points=[
            InterfacePoint(
                label="blunt:h1:start",
                position=Vec3(x=0, y=0, z=0),
                normal=Vec3(x=1, y=0, z=0),
                connection_type=ConnectionType.COVALENT,
                cluster_id="scaffold",
            ),
        ],
    )
    child = PartInstance(
        id="child",
        name="Child",
        source=PartSourceInline(design=Design()),
        transform={"values": [1, 0, 0, 2, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
        interface_points=[
            InterfacePoint(
                label="B1",
                position=Vec3(x=0, y=0, z=0),
                normal=Vec3(x=-1, y=0, z=0),
                connection_type=ConnectionType.COVALENT,
            ),
        ],
    )
    assembly_state.set_assembly(
        Assembly(
            instances=[parent, child],
            joints=[
                AssemblyJoint(
                    joint_type="rigid",
                    instance_a_id="parent",
                    cluster_id_a="scaffold",
                    instance_b_id="child",
                    connector_a_label="blunt:h1:start",
                    connector_b_label="B1",
                ),
            ],
        )
    )

    moved_cluster = ClusterRigidTransform(
        id="geometry",
        name="Geometry Cluster",
        helix_ids=["h1"],
        translation=[1.0, 0.0, 0.0],
    ).model_dump(mode="json")
    delta = {"values": [1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    r = client.patch(
        "/api/assembly/instances/parent/cluster-transform",
        json={
            "cluster_id": "geometry",
            "cluster_transform": moved_cluster,
            "delta_transform": delta,
        },
    )
    assert r.status_code == 200
    child_json = next(i for i in v1_instances(r.json()) if i["id"] == "child")
    assert child_json["transform"]["values"][3] == pytest.approx(7.0)


def test_patch_instance_cluster_transform_ignores_part_level_mates_without_cluster_ids():
    client.post("/api/assembly")
    r_a = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_cluster_source_dict(),
            "name": "Parent",
        },
    )
    parent_id = v1_instances(r_a.json())[0]["id"]
    r_b = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
            "name": "Child",
            "transform": {"values": [1, 0, 0, 2, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]},
        },
    )
    child_id = v1_instances(r_b.json())[-1]["id"]
    client.post(
        "/api/assembly/joints",
        json={
            "joint_type": "revolute",
            "instance_a_id": parent_id,
            "instance_b_id": child_id,
        },
    )

    moved_cluster = ClusterRigidTransform(
        id="cluster-a",
        name="Arm",
        helix_ids=["h1"],
        translation=[1.0, 0.0, 0.0],
    ).model_dump(mode="json")
    delta = {"values": [1, 0, 0, 5, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]}
    r = client.patch(
        f"/api/assembly/instances/{parent_id}/cluster-transform",
        json={
            "cluster_id": "cluster-a",
            "cluster_transform": moved_cluster,
            "delta_transform": delta,
        },
    )
    assert r.status_code == 200
    child = next(i for i in v1_instances(r.json()) if i["id"] == child_id)
    assert child["transform"]["values"][3] == pytest.approx(2.0)


def test_patch_instance_invalid_mode_returns_400():
    client.post("/api/assembly")
    add_r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
        },
    )
    inst_id = v1_instances(add_r.json())[0]["id"]

    r = client.patch(f"/api/assembly/instances/{inst_id}", json={"mode": "squiggly"})
    assert r.status_code == 400


def test_patch_instance_not_found_returns_404():
    client.post("/api/assembly")
    r = client.patch("/api/assembly/instances/nonexistent-id", json={"name": "X"})
    assert r.status_code == 404


# ── DELETE /assembly/instances/{id} ──────────────────────────────────────────


def test_delete_instance():
    client.post("/api/assembly")
    add_r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
        },
    )
    inst_id = v1_instances(add_r.json())[0]["id"]

    r = client.delete(f"/api/assembly/instances/{inst_id}")
    assert r.status_code == 200
    assert v1_instances(r.json()) == []


def test_delete_instance_also_removes_referencing_joints():
    """Deleting an instance must cascade to joints that reference it."""
    client.post("/api/assembly")
    r_a = client.post(
        "/api/assembly/instances", json={"source": _inline_source_dict(), "name": "A"}
    )
    r_b = client.post(
        "/api/assembly/instances", json={"source": _inline_source_dict(), "name": "B"}
    )
    id_a = v1_instances(r_a.json())[0]["id"]
    id_b = v1_instances(r_b.json())[-1]["id"]

    # Add joint from A → B
    client.post(
        "/api/assembly/joints",
        json={
            "instance_a_id": id_a,
            "instance_b_id": id_b,
        },
    )

    r = client.delete(f"/api/assembly/instances/{id_b}")
    assert r.status_code == 200
    assembly = r.json()["assembly"]
    assert all(j["instance_b_id"] != id_b for j in assembly["joints"])


def test_delete_instance_not_found_returns_404():
    client.post("/api/assembly")
    r = client.delete("/api/assembly/instances/no-such-id")
    assert r.status_code == 404


# ── POST /assembly/joints ─────────────────────────────────────────────────────


def test_add_joint_creates_joint():
    client.post("/api/assembly")
    r_a = client.post(
        "/api/assembly/instances", json={"source": _inline_source_dict(), "name": "A"}
    )
    r_b = client.post(
        "/api/assembly/instances", json={"source": _inline_source_dict(), "name": "B"}
    )
    id_a = v1_instances(r_a.json())[0]["id"]
    id_b = v1_instances(r_b.json())[-1]["id"]

    r = client.post(
        "/api/assembly/joints",
        json={
            "name": "Hinge",
            "instance_a_id": id_a,
            "instance_b_id": id_b,
            "axis_direction": [0.0, 0.0, 1.0],
        },
    )
    assert r.status_code == 201
    joints = r.json()["assembly"]["joints"]
    assert len(joints) == 1
    assert joints[0]["name"] == "Hinge"
    assert joints[0]["joint_type"] == "revolute"


def test_add_joint_snapshots_base_transform():
    """Adding a joint should set instance_b.base_transform to its current transform."""
    client.post("/api/assembly")
    transform = {"values": [1, 0, 0, 2, 0, 1, 0, 3, 0, 0, 1, 4, 0, 0, 0, 1]}
    r_b = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
            "transform": transform,
        },
    )
    id_b = v1_instances(r_b.json())[0]["id"]

    client.post("/api/assembly/joints", json={"instance_b_id": id_b})
    assembly = client.get("/api/assembly").json()["assembly"]
    inst = next(i for i in v1_instances(assembly) if i["id"] == id_b)
    assert inst["base_transform"] is not None
    assert inst["base_transform"]["values"][3] == pytest.approx(2.0)


def test_add_joint_invalid_instance_returns_404():
    client.post("/api/assembly")
    r = client.post(
        "/api/assembly/joints",
        json={
            "instance_b_id": "nonexistent",
        },
    )
    assert r.status_code == 404


# ── PATCH /assembly/joints/{id} ───────────────────────────────────────────────


def test_patch_joint_drives_revolute_transform():
    """Driving a revolute joint at 90° (pi/2) should rotate instance_b 90° about the Z axis."""
    client.post("/api/assembly")
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    id_b = v1_instances(r_b.json())[0]["id"]

    r_j = client.post(
        "/api/assembly/joints",
        json={
            "instance_b_id": id_b,
            "axis_origin": [0.0, 0.0, 0.0],
            "axis_direction": [0.0, 0.0, 1.0],
        },
    )
    joint_id = r_j.json()["assembly"]["joints"][0]["id"]

    r = client.patch(
        f"/api/assembly/joints/{joint_id}", json={"current_value": math.pi / 2}
    )
    assert r.status_code == 200

    assembly = r.json()["assembly"]
    joint = next(j for j in assembly["joints"] if j["id"] == joint_id)
    assert joint["current_value"] == pytest.approx(math.pi / 2)

    # Z-rotation 90°: R = [[0,-1,0],[1,0,0],[0,0,1]] (row-major)
    inst = next(i for i in v1_instances(assembly) if i["id"] == id_b)
    vals = inst["transform"]["values"]
    # Row-major layout: vals[r*4+c] = R[r][c]
    assert vals[0] == pytest.approx(0.0, abs=1e-6)  # R[0][0] = cos(90°)
    assert vals[5] == pytest.approx(0.0, abs=1e-6)  # R[1][1] = cos(90°)
    assert vals[4] == pytest.approx(1.0, abs=1e-6)  # R[1][0] = sin(90°)


def test_patch_joint_clamps_to_limits():
    client.post("/api/assembly")
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    id_b = v1_instances(r_b.json())[0]["id"]
    r_j = client.post(
        "/api/assembly/joints",
        json={
            "instance_b_id": id_b,
            "min_limit": -1.0,
            "max_limit": 1.0,
        },
    )
    joint_id = r_j.json()["assembly"]["joints"][0]["id"]

    r = client.patch(f"/api/assembly/joints/{joint_id}", json={"current_value": 5.0})
    assert r.status_code == 200
    joint = r.json()["assembly"]["joints"][0]
    assert joint["current_value"] == pytest.approx(1.0)

    r = client.patch(
        f"/api/assembly/joints/{joint_id}",
        json={
            "clear_limits": True,
            "current_value": 5.0,
        },
    )
    assert r.status_code == 200
    joint = r.json()["assembly"]["joints"][0]
    assert joint["min_limit"] is None
    assert joint["max_limit"] is None
    assert joint["current_value"] == pytest.approx(5.0)


def test_patch_joint_silent_skips_undo():
    """silent=True should not push to undo stack (for animation playback)."""
    client.post("/api/assembly")
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    id_b = v1_instances(r_b.json())[0]["id"]
    r_j = client.post("/api/assembly/joints", json={"instance_b_id": id_b})
    joint_id = r_j.json()["assembly"]["joints"][0]["id"]

    depth_before = client.get("/api/debug/assembly-undo-depth").json()["undo"]

    client.patch(
        f"/api/assembly/joints/{joint_id}",
        json={
            "current_value": 0.1,
            "silent": True,
        },
    )
    depth_after = client.get("/api/debug/assembly-undo-depth").json()["undo"]
    assert depth_after == depth_before  # no new undo entry


def test_patch_joint_not_found_returns_404():
    client.post("/api/assembly")
    r = client.patch("/api/assembly/joints/no-such-id", json={"current_value": 1.0})
    assert r.status_code == 404


# ── DELETE /assembly/joints/{id} ─────────────────────────────────────────────


def test_delete_joint():
    client.post("/api/assembly")
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    id_b = v1_instances(r_b.json())[0]["id"]
    r_j = client.post("/api/assembly/joints", json={"instance_b_id": id_b})
    joint_id = r_j.json()["assembly"]["joints"][0]["id"]

    r = client.delete(f"/api/assembly/joints/{joint_id}")
    assert r.status_code == 200
    assert r.json()["assembly"]["joints"] == []


# ── POST /assembly/undo + redo ────────────────────────────────────────────────


def test_undo_reverses_add_instance():
    """Adding an instance and then undoing should return to an empty instances list."""
    client.post("/api/assembly")
    client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    assert len(v1_instances(client.get("/api/assembly"))) == 1

    r = client.post("/api/assembly/undo")
    assert r.status_code == 200
    assert v1_instances(r.json()) == []


def test_undo_three_ops_in_sequence():
    client.post("/api/assembly")
    for i in range(3):
        client.post(
            "/api/assembly/instances",
            json={
                "source": _inline_source_dict(),
                "name": f"Part {i}",
            },
        )

    client.post("/api/assembly/undo")
    assert len(v1_instances(client.get("/api/assembly"))) == 2
    client.post("/api/assembly/undo")
    assert len(v1_instances(client.get("/api/assembly"))) == 1
    client.post("/api/assembly/undo")
    assert len(v1_instances(client.get("/api/assembly"))) == 0


def test_undo_nothing_returns_404():
    r = client.post("/api/assembly/undo")
    assert r.status_code == 404


def test_redo_after_undo():
    client.post("/api/assembly")
    client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    client.post("/api/assembly/undo")
    assert v1_instances(client.get("/api/assembly")) == []

    r = client.post("/api/assembly/redo")
    assert r.status_code == 200
    assert len(v1_instances(r.json())) == 1


def test_redo_nothing_returns_404():
    r = client.post("/api/assembly/redo")
    assert r.status_code == 404


# ── GET /assembly/instances/{id}/design ──────────────────────────────────────


def test_get_instance_design_inline():
    client.post("/api/assembly")
    r_i = client.post(
        "/api/assembly/instances",
        json={"source": _inline_source_dict(), "name": "Named Part"},
    )
    inst_id = v1_instances(r_i.json())[0]["id"]

    r = client.get(f"/api/assembly/instances/{inst_id}/design")
    assert r.status_code == 200
    body = r.json()
    assert "design" in body
    assert body["instance_name"] == "Named Part"


def test_get_instance_design_not_found_returns_404():
    client.post("/api/assembly")
    r = client.get("/api/assembly/instances/no-such-id/design")
    assert r.status_code == 404


# ── GET /assembly/instances/{id}/geometry ────────────────────────────────────


def test_get_instance_geometry_inline():
    """Phase-2: single-instance endpoint emits `nucleotides_compact`
    (parallel-arrays-per-helix-per-direction) instead of the verbose
    per-nuc dict list. ~50% smaller wire payload."""
    client.post("/api/assembly")
    r_i = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    inst_id = v1_instances(r_i.json())[0]["id"]

    r = client.get(f"/api/assembly/instances/{inst_id}/geometry")
    assert r.status_code == 200
    body = r.json()
    assert "nucleotides_compact" in body
    assert "helix_axes" in body
    assert isinstance(body["nucleotides_compact"], dict)
    # Compact form: keyed by helix_id → direction → parallel arrays.
    for helix_id, by_dir in body["nucleotides_compact"].items():
        for direction, b in by_dir.items():
            assert direction in ("FORWARD", "REVERSE")
            assert isinstance(b["bp"], list)
            assert len(b["bp"]) == len(
                b["bb"]
            )  # bp_index aligned with backbone_position


# ── GET /assembly/geometry (Phase 3: source-keyed dedup) ─────────────────────


def test_assembly_geometry_dedups_identical_sources():
    """Phase-3: N file-backed instances of the same path → one `sources`
    entry referenced by all N instance ids. Cuts batch payload from O(N)
    to O(unique sources)."""
    client.post("/api/assembly")
    # Three instances of the same inline source (same design id ⇒ same
    # source key).
    src = _inline_source_dict()
    ids = []
    for _ in range(3):
        r = client.post("/api/assembly/instances", json={"source": src})
        ids.append(v1_instances(r.json())[-1]["id"])

    r = client.get("/api/assembly/geometry")
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) >= {"sources", "instances"}
    # All three instances must be present in the instance→source map.
    assert set(v1_instances(body).keys()) == set(ids)
    # And the three should share ONE source entry.
    source_keys = set(v1_instances(body).values())
    assert len(source_keys) == 1, f"expected dedup; got {len(source_keys)} source(s)"
    src_key = next(iter(source_keys))
    assert src_key in body["sources"]
    src_entry = body["sources"][src_key]
    assert "nucleotides_compact" in src_entry
    assert "helix_axes" in src_entry
    assert "design" in src_entry


def test_batch_patch_applies_representation_atomically():
    """One PATCH /assembly/instances/batch sets representation on every
    instance in a single round-trip. Replaces the previous
    Promise.all-of-N PATCHes path that triggered N renderer rebuilds for
    a single 'Apply to all' click."""
    client.post("/api/assembly")
    ids = []
    for _ in range(3):
        r = client.post(
            "/api/assembly/instances", json={"source": _inline_source_dict()}
        )
        ids.append(v1_instances(r.json())[-1]["id"])

    r = client.patch(
        "/api/assembly/instances/batch",
        json={
            "patches": [{"id": iid, "representation": "cylinders"} for iid in ids],
        },
    )
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    reps = {i["representation"] for i in v1_instances(asm)}
    assert reps == {"cylinders"}, f"expected all cylinders, got {reps}"


def test_batch_patch_rejects_invalid_representation():
    client.post("/api/assembly")
    r = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    iid = v1_instances(r.json())[-1]["id"]
    r = client.patch(
        "/api/assembly/instances/batch",
        json={
            "patches": [{"id": iid, "representation": "not-a-real-rep"}],
        },
    )
    assert r.status_code == 400


def test_export_representation_default_and_roundtrip():
    """Assembly.export_representation defaults to 'full', survives a v2 .nass
    round-trip, and an old payload missing the field defaults to 'full'."""
    from backend.core.models import Assembly

    a = Assembly()
    assert a.export_representation == "full"
    a.export_representation = "cylinders"
    restored = Assembly.from_json(a.to_json())
    assert restored.export_representation == "cylinders"
    # Legacy payload without the field → default 'full' (model_validate, no warning).
    assert Assembly.from_dict({"instances": []}).export_representation == "full"


def test_set_export_representation_route():
    client.post("/api/assembly")
    r = client.post(
        "/api/assembly/export-representation", json={"representation": "cylinders"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["assembly"]["export_representation"] == "cylinders"
    # 'working' (export current reps as-is) is accepted.
    r = client.post(
        "/api/assembly/export-representation", json={"representation": "working"}
    )
    assert r.status_code == 200, r.text
    assert r.json()["assembly"]["export_representation"] == "working"
    # Invalid value rejected.
    r = client.post(
        "/api/assembly/export-representation", json={"representation": "bogus"}
    )
    assert r.status_code == 400


def test_resolve_follows_cluster_change_for_blunt_label():
    """When a cluster transform changes AFTER a mate is created (e.g. the
    user drags a hinge to a new relaxed angle via the feature-log slider),
    the connector's world position should follow the DNA. Then Resolve
    should detect the resulting discrepancy and re-snap inst_b.

    This works because ``_get_connector_world`` resolves blunt-end labels
    by pulling LIVE bp positions from the deformed_helix_axes /
    deformed_nucleotide_positions pipeline rather than using a stale
    stored ip.position. Cluster changes propagate automatically.
    """
    import numpy as np
    from backend.core.models import Helix, Vec3 as _V

    client.post("/api/assembly")

    # Single helix in each instance, with a cluster transform that wraps it.
    def _mk_helix(hid: str) -> Helix:
        return Helix(
            id=hid,
            name=hid,
            axis_start=_V(x=0.0, y=0.0, z=0.0),
            axis_end=_V(x=0.0, y=0.0, z=10.0),
            length_bp=32,
            bp_start=0,
            lattice_row=0,
            lattice_col=0,
        )

    design_a = Design(metadata=DesignMetadata(name="A"), helices=[_mk_helix("h_A")])
    design_b = Design(
        metadata=DesignMetadata(name="B"),
        helices=[_mk_helix("h_B")],
        cluster_transforms=[
            ClusterRigidTransform(
                id="clu-B",
                name="C",
                helix_ids=["h_B"],
                translation=[0.0, 0.0, 0.0],
                rotation=[0.0, 0.0, 0.0, 1.0],
                pivot=[0.0, 0.0, 0.0],
            )
        ],
    )

    inst_a = PartInstance(
        id="inst-A",
        name="A",
        source=PartSourceInline(design=design_a),
        # IP stored at helix end (z=10) — start with stale stored position
        # to confirm the live-geometry lookup wins.
        interface_points=[
            InterfacePoint(
                label="blunt:h_A:end",
                position=Vec3(x=0.0, y=0.0, z=999.0),
                normal=Vec3(x=0.0, y=0.0, z=1.0),
                connection_type=ConnectionType.BLUNT_END,
            )
        ],
    )
    inst_b = PartInstance(
        id="inst-B",
        name="B",
        source=PartSourceInline(design=design_b),
        interface_points=[
            InterfacePoint(
                label="blunt:h_B:start",
                position=Vec3(x=0.0, y=0.0, z=-999.0),
                normal=Vec3(x=0.0, y=0.0, z=-1.0),
                connection_type=ConnectionType.BLUNT_END,
                cluster_id="clu-B",
            )
        ],
        transform={
            "values": [
                1,
                0,
                0,
                0.0,
                0,
                1,
                0,
                0.0,
                0,
                0,
                1,
                10.0,
                0,
                0,
                0,
                1.0,
            ]
        },
    )
    joint = AssemblyJoint(
        id="joint-AB",
        name="AB",
        joint_type="rigid",
        instance_a_id="inst-A",
        instance_b_id="inst-B",
        connector_a_label="blunt:h_A:end",
        connector_b_label="blunt:h_B:start",
        axis_origin=[0.0, 0.0, 10.0],
        axis_direction=[0.0, 0.0, 1.0],
    )
    assembly_state.set_assembly(Assembly(instances=[inst_a, inst_b], joints=[joint]))

    # Sanity: with cluster_transform = identity, blunt:h_B:start is at
    # bp 0 of h_B = (0,0,0) in instance-local → world (0,0,10) after T_inst.
    # blunt:h_A:end is at bp 31 of h_A. Both helices have axis end at z=10.
    # Even though ip.position is stale (z=999/-999), live lookup wins.
    frames = client.get("/api/assembly/connector-frames").json()
    # connector A: helix h_A's "end" — at axis_end = (0,0,10) in local; T_a
    # is identity so world (0,0,10).
    a_pos = np.array(frames["inst-A"]["blunt:h_A:end"]["pos"])
    b_pos = np.array(frames["inst-B"]["blunt:h_B:start"]["pos"])
    assert a_pos == pytest.approx([0.0, 0.0, 10.0], abs=1e-3)
    assert b_pos == pytest.approx([0.0, 0.0, 10.0], abs=1e-3)

    # Now change the cluster: translate by +5 in X. Live lookup should
    # follow the bp into its new position; resolve should detect the
    # discrepancy and re-snap inst_b.
    asm = assembly_state.get_or_404()
    new_design_b = design_b.model_copy(
        update={
            "cluster_transforms": [
                ClusterRigidTransform(
                    id="clu-B",
                    name="C",
                    helix_ids=["h_B"],
                    translation=[5.0, 0.0, 0.0],
                    rotation=[0.0, 0.0, 0.0, 1.0],
                    pivot=[0.0, 0.0, 0.0],
                )
            ],
        }
    )
    new_inst_b = inst_b.model_copy(
        update={"source": PartSourceInline(design=new_design_b)}
    )
    assembly_state.set_assembly(
        asm.model_copy(
            update={
                "instances": [
                    i if i.id != "inst-B" else new_inst_b for i in asm.instances
                ],
            }
        )
    )

    # Pre-resolve: connector_b moved with the cluster to world (5, 0, 10).
    # connector_a still at (0, 0, 10). Discrepancy = 5.
    r = client.post("/api/assembly/resolve")
    status = r.json()["solve_status"]["joint-AB"]
    assert status["discrepancy"] == pytest.approx(5.0, abs=1e-3)
    assert status["satisfied"] is False

    # Post-resolve (second call shows the snap actually persisted): the
    # discrepancy drops to zero — resolve translated inst_b by -5 X.
    r2 = client.post("/api/assembly/resolve")
    status2 = r2.json()["solve_status"]["joint-AB"]
    assert status2["discrepancy"] == pytest.approx(0.0, abs=1e-3)


def test_cluster_transforms_signature_detects_changes():
    """The auto-resolve gating compares ``cluster_transforms`` before and
    after a seek; identical lists must hash equal, any rotation /
    translation / pivot tweak must hash different.
    """
    from backend.api.assembly import _cluster_transforms_signature

    base = Design(
        cluster_transforms=[
            ClusterRigidTransform(
                id="c1", translation=[0, 0, 0], rotation=[0, 0, 0, 1], pivot=[0, 0, 0]
            ),
            ClusterRigidTransform(
                id="c2", translation=[1, 2, 3], rotation=[0, 0, 0, 1], pivot=[0, 0, 0]
            ),
        ],
    )
    same = Design(
        cluster_transforms=[ct.model_copy(deep=True) for ct in base.cluster_transforms]
    )
    assert _cluster_transforms_signature(base) == _cluster_transforms_signature(same)

    # Translation diff
    moved = base.model_copy(
        update={
            "cluster_transforms": [
                base.cluster_transforms[0].model_copy(
                    update={"translation": [0.5, 0, 0]}
                ),
                base.cluster_transforms[1],
            ],
        }
    )
    assert _cluster_transforms_signature(base) != _cluster_transforms_signature(moved)

    # Empty list edge case
    empty = Design()
    assert _cluster_transforms_signature(empty) == ()


def test_part_geometry_signature_detects_deformation_changes():
    """The seek auto-resolve gate must fire on deformation edits, not just
    cluster moves — a bend/twist moves connectors (incl. periodic seams), so the
    assembly has to re-resolve. Regression: the old gate watched only
    cluster_transforms and skipped deformation-only changes.
    """
    from backend.api.assembly import _part_geometry_signature
    from backend.core.models import BendParams, DeformationOp, TwistParams

    base = Design()
    twisted = base.model_copy(
        update={
            "deformations": [
                DeformationOp(
                    type="twist",
                    plane_a_bp=0,
                    plane_b_bp=40,
                    affected_helix_ids=[],
                    params=TwistParams(total_degrees=45.0),
                )
            ]
        }
    )
    # A deformation appearing changes the signature (old gate would miss this).
    assert _part_geometry_signature(base) != _part_geometry_signature(twisted)

    # Editing the deformation's value changes it again.
    edited = base.model_copy(
        update={
            "deformations": [
                DeformationOp(
                    type="twist",
                    plane_a_bp=0,
                    plane_b_bp=40,
                    affected_helix_ids=[],
                    params=TwistParams(total_degrees=90.0),
                )
            ]
        }
    )
    assert _part_geometry_signature(twisted) != _part_geometry_signature(edited)

    # A different op type also differs.
    bent = base.model_copy(
        update={
            "deformations": [
                DeformationOp(
                    type="bend",
                    plane_a_bp=0,
                    plane_b_bp=40,
                    affected_helix_ids=[],
                    params=BendParams(
                        curvature_deg_per_bp=30.0 / 40, direction_deg=0.0
                    ),
                )
            ]
        }
    )
    assert _part_geometry_signature(bent) != _part_geometry_signature(twisted)

    # Identical designs hash equal (no spurious resolves).
    assert _part_geometry_signature(twisted) == _part_geometry_signature(
        base.model_copy(
            update={
                "deformations": [
                    DeformationOp(
                        id=twisted.deformations[0].id,
                        type="twist",
                        plane_a_bp=0,
                        plane_b_bp=40,
                        affected_helix_ids=[],
                        params=TwistParams(total_degrees=45.0),
                    )
                ]
            }
        )
    )


def test_seek_instance_features_no_cluster_change_skips_auto_resolve():
    """Seeking to a position whose feature-log replay leaves
    ``cluster_transforms`` unchanged must NOT fire auto-resolve. Keeps
    slider-driven seeks cheap when the change is purely topological /
    deformation / overhang-rotation.
    """
    # Set up: a part with NO feature log on disk, so any seek is a no-op
    # that doesn't change clusters.
    from backend.api.assembly import _WORKSPACE_DIR

    design = Design(metadata=DesignMetadata(name="test_part"))
    _WORKSPACE_DIR.mkdir(parents=True, exist_ok=True)
    part_path = _WORKSPACE_DIR / "_test_seek_no_cluster.nadoc"
    try:
        part_path.write_text(design.to_json(), encoding="utf-8")

        from backend.core.models import PartSourceFile

        client.post("/api/assembly")
        inst = PartInstance(
            id="inst-A",
            name="A",
            source=PartSourceFile(path="_test_seek_no_cluster.nadoc"),
        )
        assembly_state.set_assembly(Assembly(instances=[inst]))

        r = client.post(
            "/api/assembly/instances/inst-A/features/seek", json={"position": -1}
        )
        assert r.status_code == 200, r.text
        j = r.json()
        # No clusters → signature unchanged → no resolve.
        assert j["auto_resolved"] is False
        assert j["solve_status"] is None
    finally:
        if part_path.exists():
            part_path.unlink()


def test_resolve_re_snaps_rigid_mate_after_instance_drift():
    """Resolve translates inst_b so its connector_b coincides with
    connector_a in world space. Connector world positions are derived from
    ``T_inst @ ip.position`` — IP positions are stored cluster-baked at
    registration time, so the snap math doesn't re-apply Ct (that
    double-counts and moves the connector several nm off the actual DNA).

    Repro: instance_b's transform is offset by +3 X from its mate-creation
    pose, simulating "instance B was moved/dragged after the mate". Resolve
    should bring B back so the connectors coincide.
    """
    client.post("/api/assembly")

    inst_a = PartInstance(
        id="inst-A",
        name="A",
        source=PartSourceInline(design=Design()),
        interface_points=[
            InterfacePoint(
                label="A-port",
                position=Vec3(x=10.0, y=0.0, z=0.0),
                normal=Vec3(x=1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
            )
        ],
    )
    inst_b = PartInstance(
        id="inst-B",
        name="B",
        source=PartSourceInline(design=Design()),
        interface_points=[
            InterfacePoint(
                label="B-port",
                position=Vec3(x=0.0, y=0.0, z=0.0),
                normal=Vec3(x=-1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
            )
        ],
        # Drifted +3 X from the mate-creation pose (which would have had
        # inst_b transform translation = +10 X to make connectors coincide
        # at world (10,0,0)).
        transform={
            "values": [
                1,
                0,
                0,
                13.0,
                0,
                1,
                0,
                0.0,
                0,
                0,
                1,
                0.0,
                0,
                0,
                0,
                1.0,
            ]
        },
    )
    joint = AssemblyJoint(
        id="joint-AB",
        name="AB",
        joint_type="rigid",
        instance_a_id="inst-A",
        instance_b_id="inst-B",
        axis_origin=[10.0, 0.0, 0.0],
        axis_direction=[1.0, 0.0, 0.0],
        connector_a_label="A-port",
        connector_b_label="B-port",
    )
    assembly_state.set_assembly(
        Assembly(
            instances=[inst_a, inst_b],
            joints=[joint],
        )
    )

    r = client.post("/api/assembly/resolve")
    assert r.status_code == 200, r.text
    resp = r.json()

    status = resp.get("solve_status", {})
    assert "joint-AB" in status
    # Pre-resolve: B's connector world = T_b @ (0,0,0) = (13,0,0); A's = (10,0,0).
    assert status["joint-AB"]["discrepancy"] == pytest.approx(3.0, abs=1e-6)
    assert status["joint-AB"]["satisfied"] is False

    # Post-resolve: inst_b transform X drops 13 → 10.
    asm = resp["assembly"]
    b = next(i for i in v1_instances(asm) if i["id"] == "inst-B")
    assert b["transform"]["values"][3] == pytest.approx(10.0, abs=1e-6)


def test_all_connector_frames_uses_stored_ip_position():
    """GET /assembly/connector-frames returns ``T_inst @ ip.position`` for
    every IP — matches what the frontend renders for connector dots and
    what the DNA blunt-end auto-registration stores (which is itself
    cluster-aware via the helix geometry pipeline). The endpoint does NOT
    apply cluster transforms on top: that would double-count whenever an
    IP was registered via blunt-end auto-discovery, putting the highlight
    several nm off the actual DNA.
    """
    client.post("/api/assembly")

    # IP stored at a specific local position; instance transform shifts it
    # to a known world position.
    inst = PartInstance(
        id="inst-A",
        name="A",
        source=PartSourceInline(design=Design()),
        interface_points=[
            InterfacePoint(
                label="port",
                position=Vec3(x=2.0, y=3.0, z=-1.0),
                normal=Vec3(x=1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
            )
        ],
        transform={
            "values": [
                1,
                0,
                0,
                5.0,
                0,
                1,
                0,
                -2.0,
                0,
                0,
                1,
                0.5,
                0,
                0,
                0,
                1.0,
            ]
        },
    )
    assembly_state.set_assembly(Assembly(instances=[inst]))

    frames = client.get("/api/assembly/connector-frames").json()
    assert "inst-A" in frames and "port" in frames["inst-A"]
    # Expected: (2+5, 3-2, -1+0.5) = (7, 1, -0.5)
    assert frames["inst-A"]["port"]["pos"] == pytest.approx([7.0, 1.0, -0.5], abs=1e-9)


def test_refresh_mate_snaps_misaligned_mate_and_zeros_translation():
    """Clicking ⟳ on a misaligned mate should:
      1. Zero out the translation component of the captured M (the captured
         invariant is "connectors coincident with this relative rotation",
         not "connectors offset by N nm").
      2. Apply the snap immediately so inst_b moves into place — one click,
         not "refresh then resolve".

    Repro mirrors the Hinge dimers case: legacy joint exists; a part edit
    has tilted instance_b's connector inside its part; clicking refresh-mate
    is expected to capture the desired rotation AND snap inst_b so the
    connector positions coincide.
    """
    import numpy as np
    from scipy.spatial.transform import Rotation as _R

    client.post("/api/assembly")

    # Part B's cluster has a rotation already in place (simulating an edit
    # done after the mate was originally created).
    design_a = Design(metadata=DesignMetadata(name="A"))
    design_b = Design(
        metadata=DesignMetadata(name="B"),
        cluster_transforms=[
            ClusterRigidTransform(
                id="clu-B",
                name="C",
                translation=[2.0, -1.5, 0.5],
                rotation=list(_R.from_euler("z", 45.0, degrees=True).as_quat()),
                pivot=[0.0, 0.0, 0.0],
            )
        ],
    )
    inst_a = PartInstance(
        id="inst-A",
        name="A",
        source=PartSourceInline(design=design_a),
        interface_points=[
            InterfacePoint(
                label="port",
                position=Vec3(x=0.0, y=0.0, z=0.0),
                normal=Vec3(x=1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
            )
        ],
    )
    inst_b = PartInstance(
        id="inst-B",
        name="B",
        source=PartSourceInline(design=design_b),
        interface_points=[
            InterfacePoint(
                label="port",
                position=Vec3(x=0.0, y=0.0, z=0.0),
                normal=Vec3(x=-1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
                cluster_id="clu-B",
            )
        ],
        transform={
            "values": [
                1,
                0,
                0,
                5.0,
                0,
                1,
                0,
                0.0,
                0,
                0,
                1,
                0.0,
                0,
                0,
                0,
                1.0,
            ]
        },
    )
    legacy_joint = AssemblyJoint(
        id="joint-AB",
        name="AB",
        joint_type="rigid",
        instance_a_id="inst-A",
        instance_b_id="inst-B",
        connector_a_label="port",
        connector_b_label="port",
        # mate_relative_transform deliberately omitted — legacy joint.
    )
    assembly_state.set_assembly(
        Assembly(
            instances=[inst_a, inst_b],
            joints=[legacy_joint],
        )
    )

    # Sanity: pre-refresh, connectors are NOT coincident (the cluster offset
    # has moved inst_b's connector away from A's).
    r = client.get("/api/assembly/joints/joint-AB/connector-frames")
    pre = r.json()
    pre_disc = float(
        np.linalg.norm(np.array(pre["a"]["pos"]) - np.array(pre["b"]["pos"]))
    )
    assert pre_disc > 1.0  # well above coincidence tolerance

    # Refresh: should capture rotation-only M AND snap inst_b.
    r = client.post("/api/assembly/joints/joint-AB/refresh-mate")
    assert r.status_code == 200, r.text
    j = r.json()["assembly"]["joints"][0]
    M = j["mate_relative_transform"]
    assert M is not None and len(M) == 16
    # Translation column of the captured M MUST be zero.
    assert M[3] == pytest.approx(0.0, abs=1e-9)
    assert M[7] == pytest.approx(0.0, abs=1e-9)
    assert M[11] == pytest.approx(0.0, abs=1e-9)

    # After refresh, connector_b should coincide with connector_a in world
    # space (immediate snap applied).
    r = client.get("/api/assembly/joints/joint-AB/connector-frames")
    post = r.json()
    post_disc = float(
        np.linalg.norm(np.array(post["a"]["pos"]) - np.array(post["b"]["pos"]))
    )
    assert post_disc == pytest.approx(0.0, abs=1e-6)


def test_refresh_mate_captures_current_relative_transform():
    """POST /assembly/joints/{id}/refresh-mate populates mate_relative_transform
    on a legacy joint (one created without the field) so future resolves can
    restore the current alignment as the intended state.
    """
    client.post("/api/assembly")

    inst_a = PartInstance(
        id="inst-A",
        name="A",
        source=PartSourceInline(design=Design()),
        interface_points=[
            InterfacePoint(
                label="port",
                position=Vec3(x=0.0, y=0.0, z=0.0),
                normal=Vec3(x=1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
            )
        ],
    )
    inst_b = PartInstance(
        id="inst-B",
        name="B",
        source=PartSourceInline(design=Design()),
        interface_points=[
            InterfacePoint(
                label="port",
                position=Vec3(x=0.0, y=0.0, z=0.0),
                normal=Vec3(x=-1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
            )
        ],
    )
    legacy_joint = AssemblyJoint(
        id="joint-AB",
        name="AB",
        joint_type="rigid",
        instance_a_id="inst-A",
        instance_b_id="inst-B",
        connector_a_label="port",
        connector_b_label="port",
        # mate_relative_transform deliberately omitted — legacy joint.
    )
    assembly_state.set_assembly(
        Assembly(
            instances=[inst_a, inst_b],
            joints=[legacy_joint],
        )
    )

    # Sanity: legacy joint has no mate_relative_transform.
    asm0 = client.get("/api/assembly").json()["assembly"]
    assert asm0["joints"][0].get("mate_relative_transform") is None

    r = client.post("/api/assembly/joints/joint-AB/refresh-mate")
    assert r.status_code == 200, r.text
    j = r.json()["assembly"]["joints"][0]
    M = j["mate_relative_transform"]
    assert M is not None and len(M) == 16


def test_resolve_solve_status_satisfied_for_aligned_rigid_mate():
    """No drift → solve_status reports satisfied with zero discrepancy."""
    client.post("/api/assembly")
    inst_a = PartInstance(
        id="inst-A",
        name="A",
        source=PartSourceInline(design=Design()),
        interface_points=[
            InterfacePoint(
                label="port",
                position=Vec3(x=0.0, y=0.0, z=0.0),
                normal=Vec3(x=1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
            )
        ],
    )
    inst_b = PartInstance(
        id="inst-B",
        name="B",
        source=PartSourceInline(design=Design()),
        interface_points=[
            InterfacePoint(
                label="port",
                position=Vec3(x=0.0, y=0.0, z=0.0),
                normal=Vec3(x=-1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
            )
        ],
    )
    joint = AssemblyJoint(
        id="joint-AB",
        name="AB",
        joint_type="rigid",
        instance_a_id="inst-A",
        instance_b_id="inst-B",
        axis_origin=[0.0, 0.0, 0.0],
        axis_direction=[1.0, 0.0, 0.0],
        connector_a_label="port",
        connector_b_label="port",
    )
    assembly_state.set_assembly(Assembly(instances=[inst_a, inst_b], joints=[joint]))

    r = client.post("/api/assembly/resolve")
    assert r.status_code == 200
    status = r.json()["solve_status"]["joint-AB"]
    assert status["satisfied"] is True
    assert status["discrepancy"] == pytest.approx(0.0, abs=1e-9)


def test_assembly_geometry_distinct_sources_when_designs_differ():
    """Two instances with different inline designs each get their own
    source entry."""
    client.post("/api/assembly")
    src1 = _inline_source_dict()
    # Build a different inline source by tweaking the design.
    src2 = dict(src1)
    src2["design"] = dict(src1["design"])
    src2["design"]["id"] = str(__import__("uuid").uuid4())
    client.post("/api/assembly/instances", json={"source": src1})
    client.post("/api/assembly/instances", json={"source": src2})

    r = client.get("/api/assembly/geometry")
    assert r.status_code == 200
    body = r.json()
    src_keys = set(v1_instances(body).values())
    assert len(src_keys) == 2
    assert all(k in body["sources"] for k in src_keys)


# ── GET /debug/assembly ───────────────────────────────────────────────────────


def test_debug_assembly_structure():
    r = client.get("/api/debug/assembly")
    assert r.status_code == 200
    body = r.json()
    assert "assembly" in body
    assert "instance_count" in body
    assert "joint_count" in body
    assert body["instance_count"] == 0
    assert body["joint_count"] == 0


def test_debug_assembly_counts_update():
    client.post("/api/assembly")
    client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    r = client.get("/api/debug/assembly")
    assert r.json()["instance_count"] == 1
    assert r.json()["joint_count"] == 0


# ── GET /debug/assembly-undo-depth ───────────────────────────────────────────


def test_debug_undo_depth_structure():
    r = client.get("/api/debug/assembly-undo-depth")
    assert r.status_code == 200
    body = r.json()
    assert "undo" in body
    assert "redo" in body
    assert body["undo"] == 0
    assert body["redo"] == 0


def test_debug_undo_depth_increments():
    client.post("/api/assembly")
    client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    r = client.get("/api/debug/assembly-undo-depth")
    assert r.json()["undo"] >= 1


# ── GET /debug/assembly-joint-transform/{joint_id} ───────────────────────────


def test_debug_joint_transform_at_90deg():
    client.post("/api/assembly")
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    id_b = v1_instances(r_b.json())[0]["id"]
    r_j = client.post(
        "/api/assembly/joints",
        json={
            "instance_b_id": id_b,
            "axis_origin": [0.0, 0.0, 0.0],
            "axis_direction": [0.0, 0.0, 1.0],
        },
    )
    joint_id = r_j.json()["assembly"]["joints"][0]["id"]

    r = client.get(
        f"/api/debug/assembly-joint-transform/{joint_id}", params={"angle": math.pi / 2}
    )
    assert r.status_code == 200
    body = r.json()
    assert body["angle_deg"] == pytest.approx(90.0)
    assert "transform_preview" in body
    vals = body["transform_preview"]
    # Z-rotation 90°: R[0][0] = cos(90°) = 0, R[1][1] = cos(90°) = 0
    assert vals[0] == pytest.approx(0.0, abs=1e-6)  # R[0][0]
    assert vals[5] == pytest.approx(0.0, abs=1e-6)  # R[1][1]
    assert vals[4] == pytest.approx(1.0, abs=1e-6)  # R[1][0] = sin(90°)


def test_debug_joint_transform_not_found_returns_404():
    client.post("/api/assembly")
    r = client.get("/api/debug/assembly-joint-transform/no-such-joint")
    assert r.status_code == 404


# ── Assembly state isolation (design state must be unaffected) ────────────────


def test_assembly_mutations_do_not_affect_design_state():
    """Assembly CRUD mutations must never touch the design undo stack."""
    from backend.api import state as design_state
    from backend.core.models import Design

    design_state.close_session()
    design_state.set_design(Design())
    pre_depth = design_state.undo_depth()

    client.post("/api/assembly")
    for _ in range(5):
        client.post("/api/assembly/instances", json={"source": _inline_source_dict()})

    assert design_state.undo_depth() == pre_depth
    design_state.close_session()


# ── Instance overhang extrude — feature log at both levels ────────────────────


def test_extrude_instance_overhang_writes_feature_log_on_both_levels():
    """An assembly-mode extrude appends:
    (1) a full SnapshotLogEntry (with pre+post snapshots) on the instance design
    (2) a metadata-only SnapshotLogEntry on the assembly identifying the instance.
    """
    from backend.api import state as design_state
    from backend.api import assembly_state as asm_state
    from backend.core.lattice import make_bundle_design

    # 6HB bundle has plenty of valid overhang sites (1-cell bundles often don't).
    cells = [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3)]
    seed = make_bundle_design(cells, length_bp=42)

    # Enumerate a valid overhang site so the call doesn't 400.
    # Inline this rather than importing from test_overhang_geometry to avoid
    # cross-test module coupling.
    import re
    from backend.core.constants import (
        HONEYCOMB_HELIX_SPACING,
        BDNA_RISE_PER_BP,
    )
    import math
    from backend.core.models import StrandType

    _ID_RE = re.compile(r"^h_\w+_(-?\d+)_(-?\d+)$")

    def _row_col(hid):
        m = _ID_RE.match(hid)
        return (int(m.group(1)), int(m.group(2))) if m else (None, None)

    def _hc_xy(r, c):
        # Same formula as overhang_locations.js _hcCellXY.
        LATTICE_R = 1.125
        COL_PITCH = LATTICE_R * math.sqrt(3)
        ROW_PITCH = 3.0 * LATTICE_R
        odd = ((r + c) % 2 + 2) % 2
        return c * COL_PITCH, r * ROW_PITCH + (LATTICE_R if odd else 0)

    helix_by_id = {h.id: h for h in seed.helices}
    cell_z = {}
    for h in seed.helices:
        rr, cc = _row_col(h.id)
        if rr is None:
            continue
        cell_z.setdefault((rr, cc), []).append(
            (min(h.axis_start.z, h.axis_end.z), max(h.axis_start.z, h.axis_end.z))
        )

    def _occupied(nr, nc, z, eps=0.25):
        return any(
            z >= zmin - eps and z <= zmax + eps
            for zmin, zmax in cell_z.get((nr, nc), [])
        )

    site = None
    for strand in seed.strands:
        if strand.strand_type != StrandType.STAPLE or not strand.domains:
            continue
        for is_5p, dom, bp in [
            (True, strand.domains[0], strand.domains[0].start_bp),
            (False, strand.domains[-1], strand.domains[-1].end_bp),
        ]:
            h = helix_by_id.get(dom.helix_id)
            if h is None:
                continue
            row, col = _row_col(h.id)
            if row is None:
                continue
            local_i = bp - h.bp_start
            rise = (
                BDNA_RISE_PER_BP
                if h.axis_end.z >= h.axis_start.z
                else -BDNA_RISE_PER_BP
            )
            z = h.axis_start.z + local_i * rise
            ox, oy = _hc_xy(row, col)
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = row + dr, col + dc
                    nx, ny = _hc_xy(nr, nc)
                    if (
                        abs(math.hypot(nx - ox, ny - oy) - HONEYCOMB_HELIX_SPACING)
                        > 0.05
                    ):
                        continue
                    if _occupied(nr, nc, z):
                        continue
                    site = {
                        "helix_id": dom.helix_id,
                        "bp_index": bp,
                        "direction": dom.direction.value,
                        "is_five_prime": is_5p,
                        "neighbor_row": nr,
                        "neighbor_col": nc,
                    }
                    break
                if site:
                    break
            if site:
                break
        if site:
            break

    assert site, "could not find a valid overhang site on the 6HB fixture"

    # Set up the assembly with the bundle as an inline part.
    design_state.close_session()
    asm_state.close_session()
    client.post("/api/assembly")
    add_r = client.post(
        "/api/assembly/instances",
        json={
            "source": {"type": "inline", "design": seed.to_dict()},
            "name": "Bundle-A",
        },
    )
    assert add_r.status_code == 201, add_r.text
    inst_id = v1_instances(add_r.json())[-1]["id"]

    r = client.post(
        f"/api/assembly/instances/{inst_id}/overhang/extrude",
        json={**site, "length_bp": 8},
    )
    assert r.status_code == 200, r.text

    # (1) Part-level: full SnapshotLogEntry on the returned instance design.
    body = r.json()
    part_log = body["design"]["feature_log"]
    assert part_log, "part design must have at least one feature log entry"
    last_part = part_log[-1]
    assert last_part["feature_type"] == "snapshot"
    assert last_part["op_kind"] == "overhang-extrude"
    assert last_part["params"]["length_bp"] == 8
    # Full snapshots — pre and post are populated, entry not evicted.
    assert last_part["design_snapshot_gz_b64"], "pre-state snapshot must be populated"
    assert last_part["post_state_gz_b64"], "post-state snapshot must be populated"
    assert last_part["evicted"] is False

    # (2) Assembly-level: metadata-only SnapshotLogEntry tagging the instance.
    asm_log = body["assembly"]["feature_log"]
    assert asm_log, "assembly must have at least one feature log entry"
    last_asm = asm_log[-1]
    assert last_asm["feature_type"] == "snapshot"
    assert last_asm["op_kind"] == "overhang-extrude"
    assert last_asm["params"]["instance_id"] == inst_id
    assert last_asm["params"]["instance_name"] == "Bundle-A"
    assert last_asm["params"]["length_bp"] == 8
    # Lightweight: no payload, evicted=True so revert paths skip it.
    assert last_asm["design_snapshot_gz_b64"] == ""
    assert last_asm["post_state_gz_b64"] == ""
    assert last_asm["evicted"] is True

    # Cleanup
    asm_state.close_session()
    design_state.close_session()


def test_patch_instance_overhang_writes_feature_log_on_both_levels():
    """An assembly-mode overhang patch (sequence + label) appends:
    (1) a full SnapshotLogEntry on the instance design
    (2) a metadata-only SnapshotLogEntry on the assembly identifying the instance.
    """
    from backend.api import state as design_state
    from backend.api import assembly_state as asm_state
    from backend.core.lattice import make_bundle_design
    from backend.core.models import StrandType
    import math, re
    from backend.core.constants import (
        HONEYCOMB_HELIX_SPACING,
        BDNA_RISE_PER_BP,
    )

    # Use the same 6HB-fixture site-finder as the extrude test so we get a
    # known-good overhang on the instance before we patch it.
    cells = [(0, 1), (0, 2), (0, 3), (1, 1), (1, 2), (1, 3)]
    seed = make_bundle_design(cells, length_bp=42)

    _ID_RE = re.compile(r"^h_\w+_(-?\d+)_(-?\d+)$")

    def _row_col(hid):
        m = _ID_RE.match(hid)
        return (int(m.group(1)), int(m.group(2))) if m else (None, None)

    def _hc_xy(r, c):
        LATTICE_R = 1.125
        COL_PITCH = LATTICE_R * math.sqrt(3)
        ROW_PITCH = 3.0 * LATTICE_R
        odd = ((r + c) % 2 + 2) % 2
        return c * COL_PITCH, r * ROW_PITCH + (LATTICE_R if odd else 0)

    helix_by_id = {h.id: h for h in seed.helices}
    cell_z = {}
    for h in seed.helices:
        rr, cc = _row_col(h.id)
        if rr is None:
            continue
        cell_z.setdefault((rr, cc), []).append(
            (min(h.axis_start.z, h.axis_end.z), max(h.axis_start.z, h.axis_end.z))
        )

    def _occupied(nr, nc, z, eps=0.25):
        return any(
            z >= zmin - eps and z <= zmax + eps
            for zmin, zmax in cell_z.get((nr, nc), [])
        )

    site = None
    for strand in seed.strands:
        if strand.strand_type != StrandType.STAPLE or not strand.domains:
            continue
        for is_5p, dom, bp in [
            (True, strand.domains[0], strand.domains[0].start_bp),
            (False, strand.domains[-1], strand.domains[-1].end_bp),
        ]:
            h = helix_by_id.get(dom.helix_id)
            if h is None:
                continue
            row, col = _row_col(h.id)
            if row is None:
                continue
            local_i = bp - h.bp_start
            rise = (
                BDNA_RISE_PER_BP
                if h.axis_end.z >= h.axis_start.z
                else -BDNA_RISE_PER_BP
            )
            z = h.axis_start.z + local_i * rise
            ox, oy = _hc_xy(row, col)
            for dr in (-1, 0, 1):
                for dc in (-1, 0, 1):
                    if dr == 0 and dc == 0:
                        continue
                    nr, nc = row + dr, col + dc
                    nx, ny = _hc_xy(nr, nc)
                    if (
                        abs(math.hypot(nx - ox, ny - oy) - HONEYCOMB_HELIX_SPACING)
                        > 0.05
                    ):
                        continue
                    if _occupied(nr, nc, z):
                        continue
                    site = {
                        "helix_id": dom.helix_id,
                        "bp_index": bp,
                        "direction": dom.direction.value,
                        "is_five_prime": is_5p,
                        "neighbor_row": nr,
                        "neighbor_col": nc,
                    }
                    break
                if site:
                    break
            if site:
                break
        if site:
            break
    assert site, "could not find a valid overhang site on the 6HB fixture"

    design_state.close_session()
    asm_state.close_session()
    client.post("/api/assembly")
    add_r = client.post(
        "/api/assembly/instances",
        json={
            "source": {"type": "inline", "design": seed.to_dict()},
            "name": "Bundle-P",
        },
    )
    assert add_r.status_code == 201, add_r.text
    inst_id = v1_instances(add_r.json())[-1]["id"]

    # Create the overhang first.
    r = client.post(
        f"/api/assembly/instances/{inst_id}/overhang/extrude",
        json={**site, "length_bp": 8},
    )
    assert r.status_code == 200, r.text
    overhangs = r.json()["design"]["overhangs"]
    assert overhangs, "extrude should produce at least one overhang"
    overhang_id = overhangs[-1]["id"]
    log_after_extrude = r.json()["design"]["feature_log"]
    assert len(log_after_extrude) == 1, "exactly one entry from the extrude"

    # Patch sequence + label via the new endpoint.
    r = client.patch(
        f"/api/assembly/instances/{inst_id}/overhang/{overhang_id}",
        json={"sequence": "ACGTACGT", "label": "user-named"},
    )
    assert r.status_code == 200, r.text
    body = r.json()

    # (1) Part-level: full SnapshotLogEntry — second entry after the extrude.
    part_log = body["design"]["feature_log"]
    assert len(part_log) >= 2, f"expected ≥2 part entries, got {len(part_log)}"
    last_part = part_log[-1]
    assert last_part["feature_type"] == "snapshot"
    assert last_part["op_kind"] == "overhang-bulk"
    assert last_part["params"]["overhang_id"] == overhang_id
    assert last_part["params"]["sequence"] == "ACGTACGT"
    assert last_part["params"]["label"] == "user-named"
    assert last_part["design_snapshot_gz_b64"], "pre-state must be populated"
    assert last_part["post_state_gz_b64"], "post-state must be populated"
    assert last_part["evicted"] is False

    # (2) Assembly-level: metadata-only entry tagging the instance.
    asm_log = body["assembly"]["feature_log"]
    assert len(asm_log) >= 2, f"expected ≥2 assembly entries, got {len(asm_log)}"
    last_asm = asm_log[-1]
    assert last_asm["feature_type"] == "snapshot"
    assert last_asm["op_kind"] == "overhang-bulk"
    assert last_asm["params"]["instance_id"] == inst_id
    assert last_asm["params"]["instance_name"] == "Bundle-P"
    assert last_asm["params"]["overhang_id"] == overhang_id
    assert last_asm["design_snapshot_gz_b64"] == ""
    assert last_asm["evicted"] is True

    # Sanity: the patched overhang reflects the new label/sequence.
    patched = next(o for o in body["design"]["overhangs"] if o["id"] == overhang_id)
    assert patched["label"] == "user-named"
    assert patched["sequence"] == "ACGTACGT"

    asm_state.close_session()
    design_state.close_session()


# ── Wire-format v2 + transform-only PATCH (Phase 2b + Phase 2c) ───────────────


def test_assembly_response_carries_format_version_2_and_v2_fields():
    """Every assembly response is v2-only (contract step): format_version +
    sources + instances_v2, with no legacy ``instances`` field."""
    client.post("/api/assembly")
    r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
            "name": "A",
        },
    )
    assert r.status_code == 201
    body = r.json()["assembly"]
    # v1 field dropped at the contract step.
    assert "instances" not in body
    # Compat helper still expands v2 back to v1 shape for assertions.
    assert len(v1_instances(body)) == 1
    # v2 fields landed.
    assert body["format_version"] == 2
    assert "sources" in body
    assert "instances_v2" in body
    assert len(body["instances_v2"]) == 1
    compact = body["instances_v2"][0]
    assert "src_key" in compact
    assert "t12" in compact and len(compact["t12"]) == 12
    # The src_key in the compact dict resolves inside ``sources``.
    assert compact["src_key"] in body["sources"]


def test_patch_instance_transforms_route_applies_atomically_and_returns_ack():
    """PATCH /assembly/instances/transforms updates many instances at once and
    returns only an ack list (no feature_log entry, no full assembly)."""
    client.post("/api/assembly")
    # Create 3 instances.
    ids: list[str] = []
    for _ in range(3):
        r = client.post(
            "/api/assembly/instances",
            json={
                "source": _inline_source_dict(),
            },
        )
        ids.append(v1_instances(r.json())[-1]["id"])

    # Pack 16-float row-major translations.
    def _t16(dx, dy, dz):
        return [
            1,
            0,
            0,
            dx,
            0,
            1,
            0,
            dy,
            0,
            0,
            1,
            dz,
            0,
            0,
            0,
            1,
        ]

    r = client.patch(
        "/api/assembly/instances/transforms",
        json={
            "transforms": {
                ids[0]: _t16(1.0, 0.0, 0.0),
                ids[1]: _t16(2.0, 0.0, 0.0),
                ids[2]: _t16(3.0, 0.0, 0.0),
            },
        },
    )
    assert r.status_code == 200
    ack = r.json()
    assert "updated" in ack
    assert set(ack["updated"]) == set(ids)
    # Response shape is ONLY the ack — no "assembly" key.
    assert "assembly" not in ack

    # Verify the transforms actually landed.
    a = assembly_state.get_or_404()
    inst_by_id = {i.id: i for i in a.instances}
    assert inst_by_id[ids[0]].transform.values[3] == pytest.approx(1.0)
    assert inst_by_id[ids[1]].transform.values[3] == pytest.approx(2.0)
    assert inst_by_id[ids[2]].transform.values[3] == pytest.approx(3.0)


def test_patch_instance_transforms_accepts_compact_12_float_pack():
    """PATCH transforms accepts the 12-float compact pack (top 3 rows)."""
    client.post("/api/assembly")
    r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
        },
    )
    inst_id = v1_instances(r.json())[-1]["id"]

    t12 = [
        1,
        0,
        0,
        7.5,
        0,
        1,
        0,
        -3.0,
        0,
        0,
        1,
        0.25,
    ]
    r = client.patch(
        "/api/assembly/instances/transforms",
        json={
            "transforms": {inst_id: t12},
        },
    )
    assert r.status_code == 200
    a = assembly_state.get_or_404()
    inst = next(i for i in a.instances if i.id == inst_id)
    # 12-float pack expanded to a full 16-float row-major matrix.
    assert inst.transform.values == [
        1,
        0,
        0,
        7.5,
        0,
        1,
        0,
        -3.0,
        0,
        0,
        1,
        0.25,
        0,
        0,
        0,
        1,
    ]


def test_patch_instance_transforms_atomic_on_missing_id():
    """If any id is unknown, NO transforms get applied (atomicity)."""
    client.post("/api/assembly")
    r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
        },
    )
    real_id = v1_instances(r.json())[-1]["id"]
    before_T = list(
        next(
            i for i in assembly_state.get_or_404().instances if i.id == real_id
        ).transform.values
    )

    r = client.patch(
        "/api/assembly/instances/transforms",
        json={
            "transforms": {
                real_id: [
                    1,
                    0,
                    0,
                    99.0,
                    0,
                    1,
                    0,
                    0,
                    0,
                    0,
                    1,
                    0,
                    0,
                    0,
                    0,
                    1,
                ],
                "nonexistent-id": [
                    1,
                    0,
                    0,
                    0,
                    0,
                    1,
                    0,
                    0,
                    0,
                    0,
                    1,
                    0,
                    0,
                    0,
                    0,
                    1,
                ],
            },
        },
    )
    assert r.status_code == 404
    # Real id's transform was NOT changed — atomicity preserved.
    after_T = list(
        next(
            i for i in assembly_state.get_or_404().instances if i.id == real_id
        ).transform.values
    )
    assert after_T == before_T


def test_patch_instance_transforms_does_not_grow_undo_stack():
    """The transform PATCH is silent — drag frames don't pollute undo history."""
    client.post("/api/assembly")
    r = client.post(
        "/api/assembly/instances",
        json={
            "source": _inline_source_dict(),
        },
    )
    inst_id = v1_instances(r.json())[-1]["id"]
    depth_before = assembly_state.undo_depth()
    for k in range(5):
        client.patch(
            "/api/assembly/instances/transforms",
            json={
                "transforms": {
                    inst_id: [
                        1,
                        0,
                        0,
                        float(k),
                        0,
                        1,
                        0,
                        0,
                        0,
                        0,
                        1,
                        0,
                    ],
                },
            },
        )
    depth_after = assembly_state.undo_depth()
    assert depth_after == depth_before


def test_assembly_response_v2_sources_deduplicates_shared_source():
    """Multiple instances of the same source key collapse to a single
    entry in ``sources``."""
    client.post("/api/assembly")
    src = _inline_source_dict()
    # Re-using the SAME inline source dict means the resulting Design has the
    # same `id` → same src_key → must dedup.
    for _ in range(3):
        client.post("/api/assembly/instances", json={"source": src})
    r = client.get("/api/assembly")
    body = r.json()["assembly"]
    assert len(v1_instances(body)) == 3
    assert len(body["instances_v2"]) == 3
    # Three instances → one unique source (same design id → same src_key).
    assert len(body["sources"]) == 1
