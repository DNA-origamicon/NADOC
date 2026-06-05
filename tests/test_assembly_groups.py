"""Tests for PartGroup model + group routes (PowerPoint-style grouping).

Covers:
- ``PartGroup`` invariants enforced by ``Assembly._validate_groups``
- ``POST   /assembly/groups``                 (create)
- ``DELETE /assembly/groups/{id}``            (ungroup)
- ``PATCH  /assembly/groups/{id}``            (rename/visible/repr/expanded)
- ``POST   /assembly/groups/{id}/duplicate``  (deep copy, drops externals)
- ``DELETE /assembly/groups/{id}/cascade``    (delete group + all members)
- ``POST   /assembly/groups/{id}/transform``  (rigid move with closure)
- ``.nass`` round-trip preserves groups
- ``transitive_rigidly_attached`` helper semantics
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.assembly_groups import (
    collect_group_member_ids,
    transitive_rigidly_attached,
)
from backend.core.models import (
    Assembly,
    AssemblyJoint,
    Design,
    Mat4x4,
    PartGroup,
    PartInstance,
    PartSourceInline,
)

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    assembly_state.close_session()
    yield
    assembly_state.close_session()


def _inline_source_dict() -> dict:
    return {"type": "inline", "design": Design().to_dict()}


def _make_assembly_with_instances(n: int) -> Assembly:
    """Seed an assembly with ``n`` inline PartInstances and persist it."""
    insts = [
        PartInstance(
            name=f"Part {i}",
            source=PartSourceInline(design=Design()),
            transform=Mat4x4(values=[
                1, 0, 0, float(i * 10),
                0, 1, 0, 0,
                0, 0, 1, 0,
                0, 0, 0, 1,
            ]),
        )
        for i in range(n)
    ]
    a = Assembly(instances=insts)
    assembly_state.set_assembly(a)
    return a


def _get_assembly_dict() -> dict:
    """Read the active assembly via the API and return the ``assembly`` dict."""
    r = client.get("/api/assembly")
    assert r.status_code == 200
    return r.json()["assembly"]


# ── Model invariants ─────────────────────────────────────────────────────────

def test_group_field_default_empty():
    a = Assembly()
    assert a.groups == []


def test_group_missing_instance_id_rejected():
    inst = PartInstance(source=PartSourceInline(design=Design()))
    with pytest.raises(ValueError, match="missing instance"):
        Assembly(
            instances=[inst],
            groups=[PartGroup(instance_ids=["does-not-exist"])],
        )


def test_group_missing_subgroup_id_rejected():
    inst = PartInstance(source=PartSourceInline(design=Design()))
    with pytest.raises(ValueError, match="missing subgroup"):
        Assembly(
            instances=[inst],
            groups=[PartGroup(subgroup_ids=["does-not-exist"])],
        )


def test_group_double_parent_rejected():
    inst = PartInstance(source=PartSourceInline(design=Design()))
    with pytest.raises(ValueError, match="multiple groups"):
        Assembly(
            instances=[inst],
            groups=[
                PartGroup(instance_ids=[inst.id]),
                PartGroup(instance_ids=[inst.id]),
            ],
        )


def test_group_cycle_rejected():
    g1 = PartGroup(id="g1")
    g2 = PartGroup(id="g2")
    g1.subgroup_ids = ["g2"]
    g2.subgroup_ids = ["g1"]
    with pytest.raises(ValueError, match="cycle|multiple groups"):
        Assembly(groups=[g1, g2])


def test_group_self_reference_rejected():
    g = PartGroup(id="self-loop", subgroup_ids=["self-loop"])
    with pytest.raises(ValueError, match="contains itself"):
        Assembly(groups=[g])


def test_group_duplicate_ids_rejected():
    g1 = PartGroup(id="dup")
    g2 = PartGroup(id="dup")
    with pytest.raises(ValueError, match="duplicate group ids"):
        Assembly(groups=[g1, g2])


# ── Helpers ──────────────────────────────────────────────────────────────────

def test_collect_group_member_ids_resolves_nested():
    a = _make_assembly_with_instances(4)
    iids = [i.id for i in a.instances]
    g_inner = PartGroup(name="inner", instance_ids=[iids[0], iids[1]])
    g_outer = PartGroup(name="outer", instance_ids=[iids[2]], subgroup_ids=[g_inner.id])
    a = a.model_copy(update={"groups": [g_inner, g_outer]})
    assembly_state.set_assembly(a)

    inst_ids, group_ids = collect_group_member_ids(a, g_outer.id)
    assert inst_ids == {iids[0], iids[1], iids[2]}
    assert group_ids == {g_outer.id, g_inner.id}


def test_transitive_rigidly_attached_follows_rigid_joints_only():
    a = _make_assembly_with_instances(4)
    iids = [i.id for i in a.instances]
    a = a.model_copy(update={"joints": [
        AssemblyJoint(joint_type="rigid",     instance_a_id=iids[0], instance_b_id=iids[1]),
        AssemblyJoint(joint_type="revolute",  instance_a_id=iids[1], instance_b_id=iids[2]),
        AssemblyJoint(joint_type="rigid",     instance_a_id=iids[2], instance_b_id=iids[3]),
    ]})
    reached = transitive_rigidly_attached(a, {iids[0]})
    assert reached == {iids[0], iids[1]}, (
        "rigid joint pulls in iids[1], revolute joint blocks iids[2] and beyond"
    )


# ── Routes ───────────────────────────────────────────────────────────────────

def test_create_group_basic():
    a = _make_assembly_with_instances(3)
    iids = [i.id for i in a.instances]
    r = client.post("/api/assembly/groups", json={"instance_ids": iids[:2]})
    assert r.status_code == 200
    body = r.json()["assembly"]
    assert len(body["groups"]) == 1
    g = body["groups"][0]
    assert g["instance_ids"] == iids[:2]
    assert g["name"] == "Group 1"
    assert g["visible"] is True


def test_create_group_empty_rejected():
    _make_assembly_with_instances(1)
    r = client.post("/api/assembly/groups", json={"instance_ids": [], "subgroup_ids": []})
    assert r.status_code == 400


def test_create_group_unknown_instance_rejected():
    _make_assembly_with_instances(1)
    r = client.post("/api/assembly/groups", json={"instance_ids": ["nope"]})
    assert r.status_code == 404


def test_create_group_double_membership_rejected():
    a = _make_assembly_with_instances(2)
    iids = [i.id for i in a.instances]
    r1 = client.post("/api/assembly/groups", json={"instance_ids": [iids[0]]})
    assert r1.status_code == 200
    r2 = client.post("/api/assembly/groups", json={"instance_ids": [iids[0]]})
    assert r2.status_code == 400


def test_create_group_nested():
    a = _make_assembly_with_instances(3)
    iids = [i.id for i in a.instances]
    r1 = client.post("/api/assembly/groups", json={"instance_ids": iids[:2]})
    inner_id = r1.json()["assembly"]["groups"][0]["id"]
    r2 = client.post("/api/assembly/groups",
                     json={"instance_ids": [iids[2]], "subgroup_ids": [inner_id]})
    assert r2.status_code == 200
    body = r2.json()["assembly"]
    assert len(body["groups"]) == 2
    outer = next(g for g in body["groups"] if g["id"] != inner_id)
    assert outer["subgroup_ids"] == [inner_id]


def test_ungroup_returns_members_to_top_level():
    a = _make_assembly_with_instances(2)
    iids = [i.id for i in a.instances]
    r = client.post("/api/assembly/groups", json={"instance_ids": iids})
    gid = r.json()["assembly"]["groups"][0]["id"]
    r2 = client.delete(f"/api/assembly/groups/{gid}")
    assert r2.status_code == 200
    body = r2.json()["assembly"]
    assert body["groups"] == []
    # Instances unchanged
    new_iids = [e["id"] for e in body["instances_v2"]]
    assert set(new_iids) == set(iids)


def test_patch_group_rename_and_visible():
    a = _make_assembly_with_instances(2)
    iids = [i.id for i in a.instances]
    r = client.post("/api/assembly/groups", json={"instance_ids": iids})
    gid = r.json()["assembly"]["groups"][0]["id"]
    r2 = client.patch(f"/api/assembly/groups/{gid}",
                      json={"name": "Arm", "visible": False, "representation": "beads"})
    assert r2.status_code == 200
    g = r2.json()["assembly"]["groups"][0]
    assert g["name"] == "Arm"
    assert g["visible"] is False
    assert g["representation"] == "beads"
    # Members are NOT mutated (overlay only)
    for entry in r2.json()["assembly"]["instances_v2"]:
        assert entry.get("visible", True) is True
        assert entry.get("representation", "full") == "full"


def test_patch_group_clear_representation():
    a = _make_assembly_with_instances(1)
    iids = [i.id for i in a.instances]
    r = client.post("/api/assembly/groups", json={"instance_ids": iids})
    gid = r.json()["assembly"]["groups"][0]["id"]
    client.patch(f"/api/assembly/groups/{gid}", json={"representation": "cylinders"})
    r3 = client.patch(f"/api/assembly/groups/{gid}", json={"clear_representation": True})
    g = r3.json()["assembly"]["groups"][0]
    assert g["representation"] is None


def test_duplicate_group_drops_external_joints_keeps_internal():
    a = _make_assembly_with_instances(3)
    iids = [i.id for i in a.instances]
    # Joint INSIDE the group (iids[0] ↔ iids[1])
    # Joint CROSSING the group (iids[1] ↔ iids[2])
    a = a.model_copy(update={"joints": [
        AssemblyJoint(joint_type="rigid",    instance_a_id=iids[0], instance_b_id=iids[1]),
        AssemblyJoint(joint_type="revolute", instance_a_id=iids[1], instance_b_id=iids[2]),
    ]})
    assembly_state.set_assembly(a)
    r = client.post("/api/assembly/groups", json={"instance_ids": [iids[0], iids[1]]})
    gid = r.json()["assembly"]["groups"][0]["id"]

    r2 = client.post(f"/api/assembly/groups/{gid}/duplicate",
                     json={"offset": [20.0, 0.0, 0.0]})
    assert r2.status_code == 200
    body = r2.json()["assembly"]

    # Two groups now (original + clone), 5 instances (2 cloned + 3 original).
    assert len(body["groups"]) == 2
    assert len(body["instances_v2"]) == 5
    # 3 joints: original internal + original external + cloned internal.
    # External (revolute) NOT cloned.
    assert len(body["joints"]) == 3
    rigid_count = sum(1 for j in body["joints"] if j["joint_type"] == "rigid")
    revo_count  = sum(1 for j in body["joints"] if j["joint_type"] == "revolute")
    assert rigid_count == 2          # original internal + cloned internal
    assert revo_count  == 1          # original external NOT cloned


def test_cascade_delete_group_removes_members_and_joints():
    a = _make_assembly_with_instances(3)
    iids = [i.id for i in a.instances]
    a = a.model_copy(update={"joints": [
        AssemblyJoint(joint_type="rigid",    instance_a_id=iids[0], instance_b_id=iids[1]),
        AssemblyJoint(joint_type="revolute", instance_a_id=iids[1], instance_b_id=iids[2]),
    ]})
    assembly_state.set_assembly(a)
    r = client.post("/api/assembly/groups", json={"instance_ids": [iids[0], iids[1]]})
    gid = r.json()["assembly"]["groups"][0]["id"]

    r2 = client.delete(f"/api/assembly/groups/{gid}/cascade")
    assert r2.status_code == 200
    body = r2.json()["assembly"]
    assert body["groups"] == []
    remaining = [e["id"] for e in body["instances_v2"]]
    assert remaining == [iids[2]]
    # Both joints touched a deleted instance → both removed.
    assert body["joints"] == []


def test_transform_group_translation_via_rigid_joint():
    """Move group containing iids[0], iids[1]; iids[2] is rigid-attached to
    iids[1] from outside the group, so it should follow."""
    a = _make_assembly_with_instances(3)
    iids = [i.id for i in a.instances]
    a = a.model_copy(update={"joints": [
        AssemblyJoint(joint_type="rigid", instance_a_id=iids[1], instance_b_id=iids[2]),
    ]})
    assembly_state.set_assembly(a)
    r = client.post("/api/assembly/groups", json={"instance_ids": [iids[0], iids[1]]})
    gid = r.json()["assembly"]["groups"][0]["id"]

    r2 = client.post(f"/api/assembly/groups/{gid}/transform",
                     json={"translation": [100.0, 0.0, 0.0]})
    assert r2.status_code == 200

    a_after = assembly_state.get_or_404()
    by_id = {i.id: i for i in a_after.instances}
    # All three should have x-translation +100 from their starting positions
    # (iids[0]=0, iids[1]=10, iids[2]=20).
    assert by_id[iids[0]].transform.values[3] == pytest.approx(100.0)
    assert by_id[iids[1]].transform.values[3] == pytest.approx(110.0)
    assert by_id[iids[2]].transform.values[3] == pytest.approx(120.0)


def test_transform_group_revolute_external_stays_put():
    """Revolute joint to outside the group does NOT pull the external partner."""
    a = _make_assembly_with_instances(3)
    iids = [i.id for i in a.instances]
    a = a.model_copy(update={"joints": [
        AssemblyJoint(joint_type="revolute", instance_a_id=iids[1], instance_b_id=iids[2]),
    ]})
    assembly_state.set_assembly(a)
    r = client.post("/api/assembly/groups", json={"instance_ids": [iids[0], iids[1]]})
    gid = r.json()["assembly"]["groups"][0]["id"]

    client.post(f"/api/assembly/groups/{gid}/transform", json={"translation": [50.0, 0.0, 0.0]})

    a_after = assembly_state.get_or_404()
    by_id = {i.id: i for i in a_after.instances}
    assert by_id[iids[0]].transform.values[3] == pytest.approx(50.0)
    assert by_id[iids[1]].transform.values[3] == pytest.approx(60.0)
    # External revolute partner stays at its original 20.0
    assert by_id[iids[2]].transform.values[3] == pytest.approx(20.0)


def test_transform_group_matrix_input():
    """Send a 16-float row-major matrix; verify it's left-multiplied in."""
    a = _make_assembly_with_instances(1)
    iids = [i.id for i in a.instances]
    r = client.post("/api/assembly/groups", json={"instance_ids": iids})
    gid = r.json()["assembly"]["groups"][0]["id"]
    # Pure translation (1,2,3) as a 4×4 row-major matrix
    M = [
        1, 0, 0, 1,
        0, 1, 0, 2,
        0, 0, 1, 3,
        0, 0, 0, 1,
    ]
    r2 = client.post(f"/api/assembly/groups/{gid}/transform", json={"matrix": M})
    assert r2.status_code == 200
    inst = assembly_state.get_or_404().instances[0]
    assert inst.transform.values[3]  == pytest.approx(1.0)   # original x=0, +1
    assert inst.transform.values[7]  == pytest.approx(2.0)
    assert inst.transform.values[11] == pytest.approx(3.0)


def test_delete_instance_strips_from_group():
    """Removing an instance must clean up its id from any owning group so the
    Assembly validator doesn't reject the round-trip on next read."""
    a = _make_assembly_with_instances(2)
    iids = [i.id for i in a.instances]
    client.post("/api/assembly/groups", json={"instance_ids": iids})
    r = client.delete(f"/api/assembly/instances/{iids[0]}")
    assert r.status_code == 200
    body = r.json()["assembly"]
    # Group still exists but no longer references the deleted instance.
    assert len(body["groups"]) == 1
    assert body["groups"][0]["instance_ids"] == [iids[1]]


# ── Persistence (.nass round-trip) ───────────────────────────────────────────

def test_groups_round_trip_through_nass():
    a = _make_assembly_with_instances(3)
    iids = [i.id for i in a.instances]
    g_inner = PartGroup(name="inner", instance_ids=[iids[0], iids[1]])
    g_outer = PartGroup(name="outer", instance_ids=[iids[2]], subgroup_ids=[g_inner.id])
    a = a.model_copy(update={"groups": [g_inner, g_outer]})
    # to_json/from_json must round-trip via v2 wire format + validator.
    text = a.to_json()
    a2 = Assembly.from_json(text)
    assert len(a2.groups) == 2
    inner2 = next(g for g in a2.groups if g.name == "inner")
    outer2 = next(g for g in a2.groups if g.name == "outer")
    assert inner2.instance_ids == [iids[0], iids[1]]
    assert outer2.subgroup_ids == [inner2.id]
