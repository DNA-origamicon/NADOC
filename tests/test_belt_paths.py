"""Integration tests for assembly belt paths (UI-first, display-layer).

A BeltPath defines an open belt wrapping exactly two pulleys. Each pulley is a
revolute AssemblyJoint plus a rim connector on the rotating body; the pulley
radius (perpendicular distance from connector to axis) is computed on the
frontend and cached in the request as advisory geometry.

These tests cover the model validator, the CRUD routes, and round-trip
persistence through the Assembly model. No kinematics/part-mating exists yet.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.models import (
    Assembly,
    AssemblyJoint,
    BeltPath,
    BeltPulley,
    Design,
    Mat4x4,
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


def _identity_mat4() -> Mat4x4:
    return Mat4x4(values=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])


def _translation_mat4(x: float, y: float = 0.0, z: float = 0.0) -> Mat4x4:
    return Mat4x4(values=[1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1])


def _two_pulley_assembly() -> tuple[dict, str]:
    """Seed an assembly with two independent revolute joints (A↔B, C↔D), each
    anchored to a fixed parent. The rotating bodies (B, D) carry the pulleys.
    Returns ``{inst_*, joint_ab, joint_cd, prismatic}`` and the assembly id.
    A prismatic joint is added so the non-revolute rejection path can be tested.
    """
    inst_a = PartInstance(
        name="FixedA",
        source=PartSourceInline(design=Design()),
        transform=_identity_mat4(),
        fixed=True,
    )
    inst_b = PartInstance(
        name="PulleyB",
        source=PartSourceInline(design=Design()),
        transform=_translation_mat4(5.0),
        base_transform=_translation_mat4(5.0),
    )
    inst_c = PartInstance(
        name="FixedC",
        source=PartSourceInline(design=Design()),
        transform=_translation_mat4(20.0),
        fixed=True,
    )
    inst_d = PartInstance(
        name="PulleyD",
        source=PartSourceInline(design=Design()),
        transform=_translation_mat4(25.0),
        base_transform=_translation_mat4(25.0),
    )
    joint_ab = AssemblyJoint(
        name="Hinge_AB",
        joint_type="revolute",
        instance_a_id=inst_a.id,
        instance_b_id=inst_b.id,
        axis_origin=[5.0, 0.0, 0.0],
        axis_direction=[0.0, 0.0, 1.0],
    )
    joint_cd = AssemblyJoint(
        name="Hinge_CD",
        joint_type="revolute",
        instance_a_id=inst_c.id,
        instance_b_id=inst_d.id,
        axis_origin=[25.0, 0.0, 0.0],
        axis_direction=[0.0, 0.0, 1.0],
    )
    prismatic = AssemblyJoint(
        name="Slide_AC",
        joint_type="prismatic",
        instance_a_id=inst_a.id,
        instance_b_id=inst_c.id,
        axis_origin=[0.0, 0.0, 0.0],
        axis_direction=[1.0, 0.0, 0.0],
    )
    a = Assembly(
        instances=[inst_a, inst_b, inst_c, inst_d],
        joints=[joint_ab, joint_cd, prismatic],
    )
    assembly_state.set_assembly(a)
    return {
        "inst_a": inst_a.id,
        "inst_b": inst_b.id,
        "inst_c": inst_c.id,
        "inst_d": inst_d.id,
        "joint_ab": joint_ab.id,
        "joint_cd": joint_cd.id,
        "prismatic": prismatic.id,
    }, a.id


def _pulley(joint_id: str, *, radius: float = 3.0, center=(0.0, 0.0, 0.0)) -> dict:
    return {
        "joint_id": joint_id,
        "side": "b",
        "radius": radius,
        "center_world": list(center),
        "connector_world": [center[0], center[1] + radius, center[2]],
    }


def _create_belt(ids: dict, *, name: str = "Belt") -> dict:
    r = client.post(
        "/api/assembly/belt-paths",
        json={
            "name": name,
            "pulley_a": _pulley(ids["joint_ab"], radius=3.0, center=(5.0, 0.0, 0.0)),
            "pulley_b": _pulley(ids["joint_cd"], radius=2.0, center=(25.0, 0.0, 0.0)),
        },
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── 1. Model validation ───────────────────────────────────────────────────────


def test_belt_path_same_joint_rejected():
    pa = BeltPulley(joint_id="J1", radius=3.0)
    pb = BeltPulley(joint_id="J1", radius=2.0)
    with pytest.raises(ValueError, match="different joints"):
        BeltPath(pulley_a=pa, pulley_b=pb)


def test_belt_path_negative_radius_rejected():
    pa = BeltPulley(joint_id="J1", radius=3.0)
    pb = BeltPulley(joint_id="J2", radius=-1.0)
    with pytest.raises(ValueError, match="radius"):
        BeltPath(pulley_a=pa, pulley_b=pb)


def test_belt_path_roundtrips_through_model_dump():
    belt = BeltPath(
        name="MyBelt",
        pulley_a=BeltPulley(
            joint_id="J1", side="b", radius=3.0, center_world=[5, 0, 0]
        ),
        pulley_b=BeltPulley(joint_id="J2", side="a", radius=2.0),
    )
    restored = BeltPath.model_validate(belt.model_dump())
    assert restored == belt


# ── 2. CRUD roundtrip (HTTP) ──────────────────────────────────────────────────


def test_create_belt_path_resolves_pulleys():
    ids, _ = _two_pulley_assembly()
    body = _create_belt(ids, name="DriveBelt")
    belts = body["assembly"]["belt_paths"]
    assert len(belts) == 1
    belt = belts[0]
    assert belt["name"] == "DriveBelt"
    assert belt["pulley_a"]["joint_id"] == ids["joint_ab"]
    assert belt["pulley_a"]["instance_id"] == ids["inst_b"]
    assert belt["pulley_a"]["side"] == "b"
    assert belt["pulley_b"]["instance_id"] == ids["inst_d"]
    assert belt["pulley_a"]["radius"] == pytest.approx(3.0)


def test_create_belt_path_same_joint_400():
    ids, _ = _two_pulley_assembly()
    r = client.post(
        "/api/assembly/belt-paths",
        json={
            "pulley_a": _pulley(ids["joint_ab"]),
            "pulley_b": _pulley(ids["joint_ab"]),
        },
    )
    assert r.status_code == 400, r.text


def test_create_belt_path_non_revolute_400():
    ids, _ = _two_pulley_assembly()
    r = client.post(
        "/api/assembly/belt-paths",
        json={
            "pulley_a": _pulley(ids["joint_ab"]),
            "pulley_b": _pulley(ids["prismatic"]),
        },
    )
    assert r.status_code == 400, r.text


def test_create_belt_path_missing_joint_404():
    ids, _ = _two_pulley_assembly()
    r = client.post(
        "/api/assembly/belt-paths",
        json={
            "pulley_a": _pulley(ids["joint_ab"]),
            "pulley_b": _pulley("does-not-exist"),
        },
    )
    assert r.status_code == 404, r.text


def test_patch_belt_path_is_silent():
    ids, _ = _two_pulley_assembly()
    body = _create_belt(ids)
    belt_id = body["assembly"]["belt_paths"][0]["id"]
    log_len_before = len(body["assembly"]["feature_log"])

    r = client.patch(f"/api/assembly/belt-paths/{belt_id}", json={"name": "Renamed"})
    assert r.status_code == 200, r.text
    after = r.json()["assembly"]
    assert after["belt_paths"][0]["name"] == "Renamed"
    # Silent patch must NOT append a feature-log entry.
    assert len(after["feature_log"]) == log_len_before


def test_delete_belt_path_logs_op():
    ids, _ = _two_pulley_assembly()
    body = _create_belt(ids)
    belt_id = body["assembly"]["belt_paths"][0]["id"]

    r = client.delete(f"/api/assembly/belt-paths/{belt_id}")
    assert r.status_code == 200, r.text
    after = r.json()["assembly"]
    assert after["belt_paths"] == []
    assert after["feature_log"][-1]["op_kind"] == "assembly-delete-belt"


# ── 3. Persistence through the Assembly model ────────────────────────────────

# ── 4. Real-time coupling (drives like a gear, belt direction/ratio) ──────────


def _joint_value(ids_or_resp, joint_id):
    asm = assembly_state.get_or_404()
    return next(j.current_value for j in asm.joints if j.id == joint_id)


def test_belt_couples_joint_rotation_same_direction_and_ratio():
    ids, _ = _two_pulley_assembly()
    _create_belt(ids)  # pulley_a = joint_ab (rA=3), pulley_b = joint_cd (rB=2)
    # Rotate pulley A by 1.0 rad → pulley B follows at ratio rA/rB = 1.5, SAME sign
    # (open belt, parallel same-direction axes, both child side → invert False).
    r = client.patch(
        f"/api/assembly/joints/{ids['joint_ab']}", json={"current_value": 1.0}
    )
    assert r.status_code == 200, r.text
    assert _joint_value(r, ids["joint_cd"]) == pytest.approx(1.5, abs=1e-6)


def test_belt_coupling_is_bidirectional():
    ids, _ = _two_pulley_assembly()
    _create_belt(ids)
    # Drive the driven side: pulley B by 1.5 → pulley A follows at 1/1.5 = 1.0.
    r = client.patch(
        f"/api/assembly/joints/{ids['joint_cd']}", json={"current_value": 1.5}
    )
    assert r.status_code == 200, r.text
    assert _joint_value(r, ids["joint_ab"]) == pytest.approx(1.0, abs=1e-6)


def test_belt_anti_parallel_axes_flip_current_value_sign():
    # When pulley B's axis points the opposite way, the SAME world rotational
    # sense maps to an opposite current_value sign (invert True).
    ids, _ = _two_pulley_assembly()
    asm = assembly_state.get_or_404()
    joints = [
        j.model_copy(update={"axis_direction": [0.0, 0.0, -1.0]})
        if j.id == ids["joint_cd"]
        else j
        for j in asm.joints
    ]
    assembly_state.set_assembly(asm.model_copy(update={"joints": joints}))
    _create_belt(ids)
    r = client.patch(
        f"/api/assembly/joints/{ids['joint_ab']}", json={"current_value": 1.0}
    )
    assert r.status_code == 200, r.text
    assert _joint_value(r, ids["joint_cd"]) == pytest.approx(-1.5, abs=1e-6)


def test_belt_anchors_captured_so_no_jump_on_create():
    ids, _ = _two_pulley_assembly()
    # Pre-rotate both joints, then create the belt: anchors snapshot the current
    # pose so creation doesn't move anything.
    client.patch(f"/api/assembly/joints/{ids['joint_ab']}", json={"current_value": 0.4})
    client.patch(f"/api/assembly/joints/{ids['joint_cd']}", json={"current_value": 0.9})
    body = _create_belt(ids)
    belt = body["assembly"]["belt_paths"][0]
    assert belt["joint_a_anchor"] == pytest.approx(0.4)
    assert belt["joint_b_anchor"] == pytest.approx(0.9)
    # Values unchanged immediately after create.
    assert _joint_value(None, ids["joint_ab"]) == pytest.approx(0.4)
    assert _joint_value(None, ids["joint_cd"]) == pytest.approx(0.9)
    # Now nudge A by +0.2 → B moves from its anchor by 0.2*1.5 = 0.3 → 1.2.
    client.patch(f"/api/assembly/joints/{ids['joint_ab']}", json={"current_value": 0.6})
    assert _joint_value(None, ids["joint_cd"]) == pytest.approx(1.2, abs=1e-6)


# ── 5. Belt riders (Phase 1 static attach) ────────────────────────────────────


def _identity_values():
    return [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]


def test_create_belt_rider_records_and_places():
    ids, _ = _two_pulley_assembly()
    body = _create_belt(ids)
    belt_id = body["assembly"]["belt_paths"][0]["id"]
    # Attach the (free) pulley B instance as a rider with a placement transform.
    placed = [1, 0, 0, 7, 0, 1, 0, 8, 0, 0, 1, 9, 0, 0, 0, 1]
    r = client.post(
        "/api/assembly/belt-riders",
        json={
            "belt_path_id": belt_id,
            "instance_id": ids["inst_b"],
            "connector_label": "PulleyB_rim",
            "arc_param": 0.25,
            "transform": {"values": placed},
        },
    )
    assert r.status_code == 201, r.text
    asm = r.json()["assembly"]
    assert len(asm["belt_riders"]) == 1
    rider = asm["belt_riders"][0]
    assert rider["belt_path_id"] == belt_id
    assert rider["instance_id"] == ids["inst_b"]
    assert rider["arc_param"] == pytest.approx(0.25)
    # Placement transform was applied to the instance (read the in-memory model;
    # the response sends compact instances_v2, not full instances).
    inst = next(
        i for i in assembly_state.get_or_404().instances if i.id == ids["inst_b"]
    )
    assert inst.transform.values[3] == pytest.approx(7.0)


def test_create_belt_rider_missing_belt_404():
    ids, _ = _two_pulley_assembly()
    r = client.post(
        "/api/assembly/belt-riders",
        json={
            "belt_path_id": "nope",
            "instance_id": ids["inst_b"],
        },
    )
    assert r.status_code == 404, r.text


def test_create_belt_rider_bad_transform_400():
    ids, _ = _two_pulley_assembly()
    belt_id = _create_belt(ids)["assembly"]["belt_paths"][0]["id"]
    r = client.post(
        "/api/assembly/belt-riders",
        json={
            "belt_path_id": belt_id,
            "instance_id": ids["inst_b"],
            "transform": {"values": [1, 2, 3]},
        },
    )
    assert r.status_code == 400, r.text


def test_delete_belt_rider_logs_op():
    ids, _ = _two_pulley_assembly()
    belt_id = _create_belt(ids)["assembly"]["belt_paths"][0]["id"]
    r = client.post(
        "/api/assembly/belt-riders",
        json={
            "belt_path_id": belt_id,
            "instance_id": ids["inst_b"],
            "arc_param": 0.1,
        },
    )
    rider_id = r.json()["assembly"]["belt_riders"][0]["id"]
    d = client.delete(f"/api/assembly/belt-riders/{rider_id}")
    assert d.status_code == 200, d.text
    asm = d.json()["assembly"]
    assert asm["belt_riders"] == []
    assert asm["feature_log"][-1]["op_kind"] == "assembly-delete-belt-rider"


def test_belt_rider_survives_roundtrip():
    ids, _ = _two_pulley_assembly()
    belt_id = _create_belt(ids)["assembly"]["belt_paths"][0]["id"]
    client.post(
        "/api/assembly/belt-riders",
        json={
            "belt_path_id": belt_id,
            "instance_id": ids["inst_b"],
            "arc_param": 0.5,
        },
    )
    assembly = assembly_state.get_or_404()
    restored = Assembly.model_validate_json(assembly.model_dump_json())
    assert len(restored.belt_riders) == 1
    assert restored.belt_riders[0].arc_param == pytest.approx(0.5)


def test_belt_rider_ride_state_stored():
    ids, _ = _two_pulley_assembly()
    belt_id = _create_belt(ids)["assembly"]["belt_paths"][0]["id"]
    local = _identity_values()
    r = client.post(
        "/api/assembly/belt-riders",
        json={
            "belt_path_id": belt_id,
            "instance_id": ids["inst_b"],
            "arc_param": 0.4,
            "ref_angle": 0.7,
            "local_transform": local,
        },
    )
    assert r.status_code == 201, r.text
    rider = r.json()["assembly"]["belt_riders"][0]
    assert rider["ref_angle"] == pytest.approx(0.7)
    assert rider["local_transform"] == local


def test_endpoint_aware_revolute_moves_parent_not_fixed_child():
    """Backward topology (Belt_test1): the moving wheel is the joint's PARENT
    (instance_a); the fixed axle is the child (instance_b). Driving current_value
    with endpoint_side='a' must rotate the wheel and leave the fixed axle put.
    A plain patch (which moves instance_b) would rotate the fixed axle instead."""
    import math

    wheel = PartInstance(
        name="Wheel",
        source=PartSourceInline(design=Design()),
        transform=_translation_mat4(4.0),
        base_transform=_translation_mat4(4.0),
    )
    axle = PartInstance(
        name="Axle",
        source=PartSourceInline(design=Design()),
        transform=_identity_mat4(),
        fixed=True,
    )
    j = AssemblyJoint(
        name="Rev",
        joint_type="revolute",
        instance_a_id=wheel.id,
        instance_b_id=axle.id,  # parent=wheel, child=fixed axle
        axis_origin=[0.0, 0.0, 0.0],
        axis_direction=[0.0, 0.0, 1.0],
    )
    assembly_state.set_assembly(Assembly(instances=[wheel, axle], joints=[j]))

    r = client.patch(
        f"/api/assembly/joints/{j.id}",
        json={"current_value": -math.pi / 2, "endpoint_side": "a"},
    )
    assert r.status_code == 200, r.text
    asm = assembly_state.get_or_404()
    w = next(i for i in asm.instances if i.id == wheel.id)
    a = next(i for i in asm.instances if i.id == axle.id)
    # Fixed axle is untouched.
    assert a.transform.values == _identity_mat4().values
    # Wheel rotated +90° about +Z: (4,0,0) → (0,4,0). Translation = values[3], values[7].
    assert w.transform.values[3] == pytest.approx(0.0, abs=1e-6)
    assert w.transform.values[7] == pytest.approx(4.0, abs=1e-6)
    assert next(
        jj.current_value for jj in asm.joints if jj.id == j.id
    ) == pytest.approx(-math.pi / 2)


def test_revolute_value_drive_never_moves_fixed_child_without_endpoint_side():
    """The joint-edit form re-sends current_value (no endpoint_side) when toggling
    limits. With a fixed child (backward topology) the backend must INFER side 'a'
    and rotate the parent — never the fixed axle. Repro of the Belt_test1 bug."""
    import math

    wheel = PartInstance(
        name="Wheel",
        source=PartSourceInline(design=Design()),
        transform=_translation_mat4(4.0),
        base_transform=_translation_mat4(4.0),
    )
    axle = PartInstance(
        name="Axle",
        source=PartSourceInline(design=Design()),
        transform=_identity_mat4(),
        fixed=True,
    )
    j = AssemblyJoint(
        name="Rev",
        joint_type="revolute",
        instance_a_id=wheel.id,
        instance_b_id=axle.id,
        axis_origin=[0.0, 0.0, 0.0],
        axis_direction=[0.0, 0.0, 1.0],
        min_limit=-1.0,
        max_limit=1.0,
    )
    assembly_state.set_assembly(Assembly(instances=[wheel, axle], joints=[j]))

    # Mimic the form save: current_value (no endpoint_side) + clear_limits.
    r = client.patch(
        f"/api/assembly/joints/{j.id}",
        json={"current_value": -math.pi / 2, "clear_limits": True},
    )
    assert r.status_code == 200, r.text
    asm = assembly_state.get_or_404()
    a = next(i for i in asm.instances if i.id == axle.id)
    w = next(i for i in asm.instances if i.id == wheel.id)
    assert a.transform.values == _identity_mat4().values  # fixed axle untouched
    assert w.transform.values[7] == pytest.approx(
        4.0, abs=1e-6
    )  # wheel rotated to (0,4,0)
    jj = next(x for x in asm.joints if x.id == j.id)
    assert jj.min_limit is None and jj.max_limit is None  # limits cleared


def _seed_belt_rider(ids):
    """Create a belt + a seed rider (with ride-state) and return (belt_id, rider_id)."""
    belt_id = _create_belt(ids)["assembly"]["belt_paths"][0]["id"]
    r = client.post(
        "/api/assembly/belt-riders",
        json={
            "belt_path_id": belt_id,
            "instance_id": ids["inst_b"],
            "connector_label": "PulleyB_rim",
            "arc_param": 0.1,
            "ref_angle": 0.3,
            "local_transform": _identity_values(),
            "transform": {"values": _identity_values()},
        },
    )
    return belt_id, r.json()["assembly"]["belt_riders"][0]["id"]


def test_polymerize_belt_clones_and_records():
    ids, _ = _two_pulley_assembly()
    belt_id, rider_id = _seed_belt_rider(ids)
    n_inst_before = len(assembly_state.get_or_404().instances)
    # 2 new copies (chain of 3 incl. the seed) at distinct arc params.
    r = client.post(
        "/api/assembly/polymerize-belt",
        json={
            "rider_id": rider_id,
            "copies": [
                {"arc_param": 0.433, "transform": {"values": _identity_values()}},
                {"arc_param": 0.767, "transform": {"values": _identity_values()}},
            ],
        },
    )
    assert r.status_code == 201, r.text
    asm = assembly_state.get_or_404()
    assert len(asm.instances) == n_inst_before + 2
    # 1 seed + 2 new riders, all on the same belt, sharing the seed's ride-state.
    riders = [rd for rd in asm.belt_riders if rd.belt_path_id == belt_id]
    assert len(riders) == 3
    new = [rd for rd in riders if rd.id != rider_id]
    assert len(new) == 2
    for rd in new:
        assert rd.ref_angle == pytest.approx(0.3)
        assert rd.local_transform == _identity_values()
        assert rd.connector_label == "PulleyB_rim"
    assert sorted(round(rd.arc_param, 3) for rd in new) == [0.433, 0.767]
    # Single feature-log entry for the whole op.
    assert asm.feature_log[-1].op_kind == "assembly-polymerize-belt"


def test_polymerize_belt_missing_rider_404():
    ids, _ = _two_pulley_assembly()
    _seed_belt_rider(ids)
    r = client.post(
        "/api/assembly/polymerize-belt",
        json={
            "rider_id": "nope",
            "copies": [{"arc_param": 0.5, "transform": {"values": _identity_values()}}],
        },
    )
    assert r.status_code == 404, r.text


def test_polymerize_belt_bad_transform_400():
    ids, _ = _two_pulley_assembly()
    _, rider_id = _seed_belt_rider(ids)
    r = client.post(
        "/api/assembly/polymerize-belt",
        json={
            "rider_id": rider_id,
            "copies": [{"arc_param": 0.5, "transform": {"values": [1, 2, 3]}}],
        },
    )
    assert r.status_code == 400, r.text


def test_belt_path_survives_assembly_json_roundtrip():
    ids, _ = _two_pulley_assembly()
    _create_belt(ids, name="Persisted")
    assembly = assembly_state.get_or_404()
    assert len(assembly.belt_paths) == 1

    restored = Assembly.model_validate_json(assembly.model_dump_json())
    assert len(restored.belt_paths) == 1
    belt = restored.belt_paths[0]
    assert belt.name == "Persisted"
    assert belt.pulley_a.joint_id == ids["joint_ab"]
    assert belt.pulley_a.radius == pytest.approx(3.0)
    assert belt.pulley_b.instance_id == ids["inst_d"]
