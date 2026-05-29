"""Integration tests for assembly gear relations.

These tests measure whether dragging the driver side via each of the three
rotation paths drives the gear-coupled side through the expected angle:

  1. ``PATCH /assembly/joints/{id}``                 — ring-drag path
  2. ``PATCH /assembly/instances/{id}``              — instance gizmo path
  3. ``POST  /assembly/groups/{id}/transform``       — group gizmo path

Each test:
  * builds a two-part assembly with two parallel revolute joints anchored at
    distinct world positions;
  * creates a gear relation linking them with a given ratio + invert flag;
  * drives the driver to a known angle via the path under test;
  * asserts the driven joint's ``current_value`` matches the gear formula
    AND the driven instance's transform reflects the same rotation.

Designed so failures point at exactly which path is broken — if (1) passes
but (2) and (3) fail, ``_sync_revolute_values_for_instances`` isn't running;
if (1) fails too, ``_propagate_gear_relations_from`` itself is broken.
"""
from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.models import (
    Assembly,
    AssemblyJoint,
    Design,
    GearRelation,
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


def _identity_mat4() -> Mat4x4:
    return Mat4x4(values=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1])


def _translation_mat4(x: float, y: float = 0.0, z: float = 0.0) -> Mat4x4:
    return Mat4x4(values=[1, 0, 0, x, 0, 1, 0, y, 0, 0, 1, z, 0, 0, 0, 1])


def _two_part_revolute_assembly(
    *,
    axis_b_world_x: float = 10.0,
) -> tuple[str, str, str, str]:
    """Seed an assembly with two parts. Part A is fixed at world origin.
    Part B sits at (axis_b_world_x, 0, 0) attached to A via a revolute joint
    whose axis runs along +Z through (axis_b_world_x, 0, 0). Returns
    ``(inst_a_id, inst_b_id, joint_id, assembly_id)``.

    base_transform on B is captured at current_value=0 so the angle-derivation
    helper has a valid reference frame for the gizmo / group-transform paths.
    """
    inst_a = PartInstance(
        name="PartA",
        source=PartSourceInline(design=Design()),
        transform=_identity_mat4(),
        fixed=True,
    )
    inst_b = PartInstance(
        name="PartB",
        source=PartSourceInline(design=Design()),
        transform=_translation_mat4(axis_b_world_x),
        base_transform=_translation_mat4(axis_b_world_x),
    )
    joint = AssemblyJoint(
        name="HingeAB",
        joint_type="revolute",
        instance_a_id=inst_a.id,
        instance_b_id=inst_b.id,
        axis_origin=[axis_b_world_x, 0.0, 0.0],
        axis_direction=[0.0, 0.0, 1.0],
        current_value=0.0,
    )
    a = Assembly(instances=[inst_a, inst_b], joints=[joint])
    assembly_state.set_assembly(a)
    return inst_a.id, inst_b.id, joint.id, a.id


def _two_revolute_two_instance_assembly() -> tuple[dict, str]:
    """Seed an assembly with TWO independent revolute joints (Part A↔Part B
    and Part C↔Part D), each anchored to its own fixed parent. Returns a
    dict of ``{inst_a, inst_b, joint_ab, inst_c, inst_d, joint_cd,
    group_b, group_d}`` and the assembly id. Groups wrap B and D so the
    group-transform path can be exercised. Each group has exactly one member
    so the group's rigid transform == the instance's transform delta.
    """
    inst_a = PartInstance(name="FixedA", source=PartSourceInline(design=Design()),
                          transform=_identity_mat4(), fixed=True)
    inst_b = PartInstance(name="WheelB", source=PartSourceInline(design=Design()),
                          transform=_translation_mat4(5.0),
                          base_transform=_translation_mat4(5.0))
    inst_c = PartInstance(name="FixedC", source=PartSourceInline(design=Design()),
                          transform=_translation_mat4(20.0), fixed=True)
    inst_d = PartInstance(name="WheelD", source=PartSourceInline(design=Design()),
                          transform=_translation_mat4(25.0),
                          base_transform=_translation_mat4(25.0))
    joint_ab = AssemblyJoint(
        name="Hinge_AB", joint_type="revolute",
        instance_a_id=inst_a.id, instance_b_id=inst_b.id,
        axis_origin=[5.0, 0.0, 0.0], axis_direction=[0.0, 0.0, 1.0],
        current_value=0.0,
    )
    joint_cd = AssemblyJoint(
        name="Hinge_CD", joint_type="revolute",
        instance_a_id=inst_c.id, instance_b_id=inst_d.id,
        axis_origin=[25.0, 0.0, 0.0], axis_direction=[0.0, 0.0, 1.0],
        current_value=0.0,
    )
    group_b = PartGroup(name="GroupB", instance_ids=[inst_b.id])
    group_d = PartGroup(name="GroupD", instance_ids=[inst_d.id])
    a = Assembly(
        instances=[inst_a, inst_b, inst_c, inst_d],
        joints=[joint_ab, joint_cd],
        groups=[group_b, group_d],
    )
    assembly_state.set_assembly(a)
    return {
        "inst_a": inst_a.id, "inst_b": inst_b.id,
        "inst_c": inst_c.id, "inst_d": inst_d.id,
        "joint_ab": joint_ab.id, "joint_cd": joint_cd.id,
        "group_b": group_b.id, "group_d": group_d.id,
    }, a.id


def _create_gear_relation(joint_a_id: str, joint_b_id: str, *, ratio: float = 1.0,
                          invert: bool = False) -> str:
    r = client.post("/api/assembly/gear-relations", json={
        "joint_a_id": joint_a_id,
        "joint_b_id": joint_b_id,
        "ratio": ratio,
        "invert": invert,
        "capture_anchors_from_current": True,
    })
    assert r.status_code == 201, r.text
    body = r.json()
    return body["assembly"]["gear_relations"][-1]["id"]


def _read_joint(joint_id: str) -> dict:
    a = assembly_state.get_or_404()
    j = next(j for j in a.joints if j.id == joint_id)
    return {
        "id": j.id, "current_value": j.current_value,
        "axis_origin": list(j.axis_origin),
        "axis_direction": list(j.axis_direction),
    }


def _instance_transform(instance_id: str) -> np.ndarray:
    a = assembly_state.get_or_404()
    inst = next(i for i in a.instances if i.id == instance_id)
    return np.array(inst.transform.values, dtype=float).reshape(4, 4)


def _rotate_about_z(angle: float, ox: float = 0.0, oy: float = 0.0) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    # World rotation about Z through (ox, oy, 0): T(o) @ Rz @ T(-o)
    return np.array([
        [c, -s, 0, ox - c * ox + s * oy],
        [s,  c, 0, oy - s * ox - c * oy],
        [0,  0, 1, 0],
        [0,  0, 0, 1],
    ])


# ── Path 1: ring-drag (PATCH /assembly/joints/{id}) ──────────────────────────

class TestGearViaPatchJoint:
    """Driving the driver joint's current_value directly should always drive
    the gear-coupled side. This is the canonical path the kinematics ticker
    uses for silent patches as well.
    """

    @pytest.mark.parametrize("ratio,invert,angle", [
        (1.0, False, math.pi / 4),
        (2.0, False, math.pi / 3),
        (0.5, False, math.pi / 6),
        (1.0, True,  math.pi / 4),
        (3.0, True,  math.pi / 5),
    ])
    def test_driven_follows_via_patch_joint(self, ratio, invert, angle):
        meta, _aid = _two_revolute_two_instance_assembly()
        rel_id = _create_gear_relation(meta["joint_ab"], meta["joint_cd"],
                                       ratio=ratio, invert=invert)

        r = client.patch(f"/api/assembly/joints/{meta['joint_ab']}", json={
            "current_value": angle,
        })
        assert r.status_code == 200, r.text

        sign = -1.0 if invert else 1.0
        expected_driven = sign * angle * ratio
        got_driver = _read_joint(meta["joint_ab"])["current_value"]
        got_driven = _read_joint(meta["joint_cd"])["current_value"]
        assert got_driver == pytest.approx(angle, abs=1e-6)
        assert got_driven == pytest.approx(expected_driven, abs=1e-6), (
            f"PATCH /joints: driver={got_driver:+.4f} driven={got_driven:+.4f} "
            f"expected {expected_driven:+.4f} (ratio={ratio} invert={invert})"
        )

    def test_driven_instance_transform_matches_driven_angle(self):
        meta, _aid = _two_revolute_two_instance_assembly()
        _create_gear_relation(meta["joint_ab"], meta["joint_cd"], ratio=1.0)

        client.patch(f"/api/assembly/joints/{meta['joint_ab']}", json={
            "current_value": math.pi / 4,
        })
        T = _instance_transform(meta["inst_d"])
        # Driven joint's axis runs through (25, 0, 0). Apply Rz(π/4) about
        # that point to the original transform T(25, 0, 0).
        expected = _rotate_about_z(math.pi / 4, ox=25.0, oy=0.0) @ np.array([
            [1, 0, 0, 25], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1],
        ])
        assert np.allclose(T, expected, atol=1e-6), (
            f"driven instance transform mismatch:\n{T}\nexpected:\n{expected}"
        )

    def test_unlimited_revolute_gear_does_not_clamp_high_ratio(self):
        meta, _aid = _two_revolute_two_instance_assembly()
        _create_gear_relation(meta["joint_ab"], meta["joint_cd"], ratio=5.0)

        r = client.patch(f"/api/assembly/joints/{meta['joint_ab']}", json={
            "current_value": math.pi,
        })
        assert r.status_code == 200, r.text

        got_driven = _read_joint(meta["joint_cd"])["current_value"]
        assert got_driven == pytest.approx(5.0 * math.pi, abs=1e-6)

    def test_driven_limit_pushes_back_driver(self):
        meta, _aid = _two_revolute_two_instance_assembly()
        _create_gear_relation(meta["joint_ab"], meta["joint_cd"], ratio=5.0)

        r = client.patch(f"/api/assembly/joints/{meta['joint_cd']}", json={
            "min_limit": -1.0,
            "max_limit": 1.0,
        })
        assert r.status_code == 200, r.text

        r = client.patch(f"/api/assembly/joints/{meta['joint_ab']}", json={
            "current_value": math.pi,
        })
        assert r.status_code == 200, r.text

        got_driver = _read_joint(meta["joint_ab"])["current_value"]
        got_driven = _read_joint(meta["joint_cd"])["current_value"]
        assert got_driven == pytest.approx(1.0, abs=1e-6)
        assert got_driver == pytest.approx(0.2, abs=1e-6)


# ── Path 2: instance gizmo (PATCH /assembly/instances/{id}) ──────────────────

class TestGearViaPatchInstance:
    """Driving the driver-side instance via a direct transform PATCH (which
    is what the TransformControls gizmo on an individual instance does) must
    also drive the gear-coupled side — backend has to derive the implied
    angle from the new transform vs base_transform.
    """

    def test_driven_follows_when_driver_instance_rotated(self):
        meta, _aid = _two_revolute_two_instance_assembly()
        _create_gear_relation(meta["joint_ab"], meta["joint_cd"], ratio=2.0)

        angle = math.pi / 6
        # Build the new transform for inst_b: rotate base_transform about
        # the joint's axis (axis_origin = (5, 0, 0), axis_direction = +Z)
        R = _rotate_about_z(angle, ox=5.0, oy=0.0)
        base = np.array([[1, 0, 0, 5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        new_T = R @ base

        r = client.patch(f"/api/assembly/instances/{meta['inst_b']}", json={
            "transform": {"values": [float(v) for v in new_T.flatten()]},
        })
        assert r.status_code == 200, r.text

        got_driver = _read_joint(meta["joint_ab"])["current_value"]
        got_driven = _read_joint(meta["joint_cd"])["current_value"]
        # Driver should have re-synced to the implied angle.
        assert got_driver == pytest.approx(angle, abs=1e-4), (
            f"driver current_value didn't re-sync from instance transform: "
            f"got {got_driver:+.4f}, expected {angle:+.4f}"
        )
        # Driven should follow at ratio 2.
        assert got_driven == pytest.approx(angle * 2.0, abs=1e-4), (
            f"driven didn't track via instance gizmo path: got {got_driven:+.4f}, "
            f"expected {angle * 2.0:+.4f}"
        )


# ── Path 3: group gizmo (POST /assembly/groups/{id}/transform) ───────────────

class TestGearViaGroupTransform:
    """Rotating the driver-side group via the group-transform endpoint must
    drive the gear-coupled side — backend has to detect that the moved group
    contains a revolute joint's child and re-anchor current_value from the
    post-transform instance pose.
    """

    def test_driven_follows_when_driver_group_rotated(self):
        meta, _aid = _two_revolute_two_instance_assembly()
        _create_gear_relation(meta["joint_ab"], meta["joint_cd"], ratio=1.0)

        angle = math.pi / 4
        delta = _rotate_about_z(angle, ox=5.0, oy=0.0)

        r = client.post(f"/api/assembly/groups/{meta['group_b']}/transform", json={
            "matrix": [float(v) for v in delta.flatten()],
        })
        assert r.status_code == 200, r.text

        got_driver = _read_joint(meta["joint_ab"])["current_value"]
        got_driven = _read_joint(meta["joint_cd"])["current_value"]
        assert got_driver == pytest.approx(angle, abs=1e-4), (
            f"driver didn't re-sync from group rotation: got {got_driver:+.4f}, "
            f"expected {angle:+.4f}"
        )
        assert got_driven == pytest.approx(angle, abs=1e-4), (
            f"driven didn't track via group gizmo path: got {got_driven:+.4f}, "
            f"expected {angle:+.4f}"
        )

    def test_driven_follows_when_driver_group_rotated_at_chain_ratio(self):
        """Same as above but with a non-unity ratio and the inverted flag,
        so we know the gear math runs (not just an accidental identity)."""
        meta, _aid = _two_revolute_two_instance_assembly()
        _create_gear_relation(meta["joint_ab"], meta["joint_cd"],
                              ratio=1.5, invert=True)

        angle = math.pi / 5
        delta = _rotate_about_z(angle, ox=5.0, oy=0.0)
        client.post(f"/api/assembly/groups/{meta['group_b']}/transform", json={
            "matrix": [float(v) for v in delta.flatten()],
        })

        got_driver = _read_joint(meta["joint_ab"])["current_value"]
        got_driven = _read_joint(meta["joint_cd"])["current_value"]
        expected_driven = -1.0 * angle * 1.5  # invert=True, ratio=1.5
        assert got_driver == pytest.approx(angle, abs=1e-4)
        assert got_driven == pytest.approx(expected_driven, abs=1e-4), (
            f"chain-ratio: got {got_driven:+.4f}, expected {expected_driven:+.4f}"
        )


# ── Symmetry / direction comparison: part vs group rotation ─────────────────

class TestPartVsGroupRotationParity:
    """Rotating a part directly (via instance PATCH) and rotating its
    one-member group (via group transform) should produce identical gear
    coupling. Lets us measure whether the two paths diverge — which would
    indicate one of them dropping the gear-sync step.
    """

    @pytest.mark.parametrize("ratio,invert", [(1.0, False), (2.0, False), (1.5, True)])
    def test_instance_path_and_group_path_agree(self, ratio, invert):
        # Path A: instance PATCH
        meta_inst, _ = _two_revolute_two_instance_assembly()
        _create_gear_relation(meta_inst["joint_ab"], meta_inst["joint_cd"],
                              ratio=ratio, invert=invert)
        angle = math.pi / 6
        R = _rotate_about_z(angle, ox=5.0, oy=0.0)
        base = np.array([[1, 0, 0, 5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        new_T = R @ base
        client.patch(f"/api/assembly/instances/{meta_inst['inst_b']}", json={
            "transform": {"values": [float(v) for v in new_T.flatten()]},
        })
        driven_via_instance = _read_joint(meta_inst["joint_cd"])["current_value"]

        # Path B: group PATCH
        meta_grp, _ = _two_revolute_two_instance_assembly()
        _create_gear_relation(meta_grp["joint_ab"], meta_grp["joint_cd"],
                              ratio=ratio, invert=invert)
        client.post(f"/api/assembly/groups/{meta_grp['group_b']}/transform", json={
            "matrix": [float(v) for v in R.flatten()],
        })
        driven_via_group = _read_joint(meta_grp["joint_cd"])["current_value"]

        assert driven_via_instance == pytest.approx(driven_via_group, abs=1e-4), (
            f"instance path -> {driven_via_instance:+.4f}, group path -> "
            f"{driven_via_group:+.4f}: the two rotation paths disagree."
        )


# ── Bidirectional propagation ───────────────────────────────────────────────

class TestGearBidirectional:
    """Spinning the DRIVEN side of a gear pair (joint_b) must drive the
    DRIVER side (joint_a) via the inverse formula
    ``θ_a = anchor_a + sign · (θ_b − anchor_b) / ratio``. Real gears mesh in
    both directions; this matches the user expectation when they grab the
    gold ring on either coupled wheel.
    """

    @pytest.mark.parametrize("ratio,invert,angle", [
        (1.0, False, math.pi / 4),
        (2.0, False, math.pi / 3),
        (0.5, False, math.pi / 6),
        (1.0, True,  math.pi / 4),
        (3.0, True,  math.pi / 5),
    ])
    def test_driver_follows_when_driven_patched(self, ratio, invert, angle):
        meta, _aid = _two_revolute_two_instance_assembly()
        _create_gear_relation(meta["joint_ab"], meta["joint_cd"],
                              ratio=ratio, invert=invert)

        # Drive the DRIVEN side (joint_cd, since joint_a=joint_ab in the relation).
        r = client.patch(f"/api/assembly/joints/{meta['joint_cd']}", json={
            "current_value": angle,
        })
        assert r.status_code == 200, r.text

        sign = -1.0 if invert else 1.0
        expected_driver = sign * angle / ratio
        got_driver = _read_joint(meta["joint_ab"])["current_value"]
        got_driven = _read_joint(meta["joint_cd"])["current_value"]
        assert got_driven == pytest.approx(angle, abs=1e-6)
        assert got_driver == pytest.approx(expected_driver, abs=1e-6), (
            f"INVERSE: driven={got_driven:+.4f} driver={got_driver:+.4f} "
            f"expected {expected_driver:+.4f} (ratio={ratio} invert={invert})"
        )

    def test_big_wheel_base_regression(self):
        """Mirrors workspace/BigSynth/Big_wheel_base.nass topology:
        driver = joint_a (instance_b = 'wheel 2'), driven = joint_b
        (instance_b = 'wheel 1'), ratio = 3.0, invert = False. User grabs
        the ring on the DRIVEN side and rotates 90°. Expectation: the
        DRIVER side rotates 30° in the same direction.
        """
        meta, _aid = _two_revolute_two_instance_assembly()
        # joint_ab = DRIVER, joint_cd = DRIVEN, ratio 3.0
        _create_gear_relation(meta["joint_ab"], meta["joint_cd"],
                              ratio=3.0, invert=False)

        # Drive DRIVEN side by 90°
        angle_driven = math.pi / 2
        client.patch(f"/api/assembly/joints/{meta['joint_cd']}", json={
            "current_value": angle_driven,
        })
        got_driven = _read_joint(meta["joint_cd"])["current_value"]
        got_driver = _read_joint(meta["joint_ab"])["current_value"]
        expected_driver = angle_driven / 3.0  # ~0.5236 rad ≈ 30°
        assert got_driven == pytest.approx(angle_driven, abs=1e-6)
        assert got_driver == pytest.approx(expected_driver, abs=1e-6), (
            f"Big_wheel_base regression: driven={got_driven:+.4f} (90°), "
            f"driver={got_driver:+.4f}, expected {expected_driver:+.4f} (30°)"
        )

    def test_chain_propagates_both_directions_from_middle(self):
        """Three-joint chain via two gear relations:
            joint_ab  --ratio 2.0--> joint_cd  --ratio 0.5--> joint_ef
        Drive joint_cd (the middle). Expectation: joint_ab follows at
        inverse(ratio_1) = 0.5x, joint_ef follows at ratio_2 = 0.5x.
        """
        # Build three-joint assembly: A→B, C→D, E→F.
        inst_a = PartInstance(name="A", source=PartSourceInline(design=Design()),
                              transform=_identity_mat4(), fixed=True)
        inst_b = PartInstance(name="B", source=PartSourceInline(design=Design()),
                              transform=_translation_mat4(5.0),
                              base_transform=_translation_mat4(5.0))
        inst_c = PartInstance(name="C", source=PartSourceInline(design=Design()),
                              transform=_translation_mat4(20.0), fixed=True)
        inst_d = PartInstance(name="D", source=PartSourceInline(design=Design()),
                              transform=_translation_mat4(25.0),
                              base_transform=_translation_mat4(25.0))
        inst_e = PartInstance(name="E", source=PartSourceInline(design=Design()),
                              transform=_translation_mat4(40.0), fixed=True)
        inst_f = PartInstance(name="F", source=PartSourceInline(design=Design()),
                              transform=_translation_mat4(45.0),
                              base_transform=_translation_mat4(45.0))
        j_ab = AssemblyJoint(name="J_AB", joint_type="revolute",
                              instance_a_id=inst_a.id, instance_b_id=inst_b.id,
                              axis_origin=[5.0, 0.0, 0.0], axis_direction=[0, 0, 1])
        j_cd = AssemblyJoint(name="J_CD", joint_type="revolute",
                              instance_a_id=inst_c.id, instance_b_id=inst_d.id,
                              axis_origin=[25.0, 0.0, 0.0], axis_direction=[0, 0, 1])
        j_ef = AssemblyJoint(name="J_EF", joint_type="revolute",
                              instance_a_id=inst_e.id, instance_b_id=inst_f.id,
                              axis_origin=[45.0, 0.0, 0.0], axis_direction=[0, 0, 1])
        a = Assembly(instances=[inst_a, inst_b, inst_c, inst_d, inst_e, inst_f],
                     joints=[j_ab, j_cd, j_ef])
        assembly_state.set_assembly(a)

        # Relations: AB -2.0-> CD, CD -0.5-> EF
        _create_gear_relation(j_ab.id, j_cd.id, ratio=2.0, invert=False)
        _create_gear_relation(j_cd.id, j_ef.id, ratio=0.5, invert=False)

        # Drive the middle joint by π/4
        angle = math.pi / 4
        client.patch(f"/api/assembly/joints/{j_cd.id}", json={
            "current_value": angle,
        })

        got_ab = _read_joint(j_ab.id)["current_value"]
        got_cd = _read_joint(j_cd.id)["current_value"]
        got_ef = _read_joint(j_ef.id)["current_value"]
        # Inverse on first relation: ab = anchor_ab + (cd - anchor_cd) / 2.0
        # Anchors captured at current_value = 0 for both, so:
        expected_ab = angle / 2.0
        expected_ef = angle * 0.5
        assert got_cd == pytest.approx(angle, abs=1e-6)
        assert got_ab == pytest.approx(expected_ab, abs=1e-6), (
            f"chain inverse: ab={got_ab:+.4f}, expected {expected_ab:+.4f}"
        )
        assert got_ef == pytest.approx(expected_ef, abs=1e-6), (
            f"chain forward: ef={got_ef:+.4f}, expected {expected_ef:+.4f}"
        )


# ── Parent-moved (axle-as-child) regression ─────────────────────────────────

class TestGearParentMovedTopology:
    """Regression for ``Big_wheel_base.nass``: revolute joint is authored
    "backwards" — the wheel base is ``instance_a`` (the moving parent) and a
    *fixed* axle is ``instance_b`` (the child). Rotating the big wheel via
    the group gizmo must still drive a gear-coupled small gear, because the
    joint's ``current_value`` (= child angle relative to parent) changes by
    −Δ when the parent rotates by +Δ and the child stays put.
    """

    def _build_big_wheel_assembly(self):
        # Big wheel = 4 wheel_base segments, all rigid-joined → Group 1.
        big_wheel_members = [
            PartInstance(name=f"wheel_base +{i}", source=PartSourceInline(design=Design()),
                         transform=_translation_mat4(i * 1.0))
            for i in range(4)
        ]
        # Axle: fixed, at the centre of the big wheel.
        axle = PartInstance(name="Axle", source=PartSourceInline(design=Design()),
                            transform=_translation_mat4(0.0), fixed=True,
                            base_transform=_translation_mat4(0.0))
        # Small gear: floats next to the axle, will follow the gear.
        small_gear = PartInstance(name="small gear", source=PartSourceInline(design=Design()),
                                  transform=_translation_mat4(3.0),
                                  base_transform=_translation_mat4(3.0))
        # Joint 1 (BACKWARD authoring): big_wheel → axle (axle is the child!)
        joint_big = AssemblyJoint(
            name="Big_wheel_to_axle", joint_type="revolute",
            instance_a_id=big_wheel_members[0].id, instance_b_id=axle.id,
            axis_origin=[0.0, 0.0, 0.0], axis_direction=[0.0, 0.0, 1.0],
            current_value=0.0,
        )
        # Joint 2: axle → small_gear (normal authoring)
        joint_small = AssemblyJoint(
            name="Axle_to_small_gear", joint_type="revolute",
            instance_a_id=axle.id, instance_b_id=small_gear.id,
            axis_origin=[3.0, 0.0, 0.0], axis_direction=[0.0, 0.0, 1.0],
            current_value=0.0,
        )
        # Group 1 wraps the big wheel.
        group_1 = PartGroup(name="Group 1", instance_ids=[m.id for m in big_wheel_members])
        a = Assembly(
            instances=[*big_wheel_members, axle, small_gear],
            joints=[joint_big, joint_small],
            groups=[group_1],
        )
        assembly_state.set_assembly(a)
        return {
            "members": [m.id for m in big_wheel_members],
            "axle_id": axle.id,
            "small_gear_id": small_gear.id,
            "joint_big_id": joint_big.id,
            "joint_small_id": joint_small.id,
            "group_1_id": group_1.id,
        }

    def test_rotating_big_wheel_group_drives_small_gear(self):
        meta = self._build_big_wheel_assembly()
        # Gear: driver = joint_small, driven = joint_big, ratio = 3.0
        # ⇒ inverse direction (driven joint_big moves → driver joint_small follows
        # at θ_small = θ_big / 3)
        _create_gear_relation(meta["joint_small_id"], meta["joint_big_id"],
                              ratio=3.0, invert=False)

        # Rotate Group 1 by π/2 about Z (the joint axis).
        angle = math.pi / 2
        delta = _rotate_about_z(angle, ox=0.0, oy=0.0)
        r = client.post(f"/api/assembly/groups/{meta['group_1_id']}/transform", json={
            "matrix": [float(v) for v in delta.flatten()],
        })
        assert r.status_code == 200, r.text

        # joint_big (driven side): current_value should be -π/2 (child angle
        # went down by Δ since parent rotated up by Δ and child is fixed).
        got_big = _read_joint(meta["joint_big_id"])["current_value"]
        assert got_big == pytest.approx(-angle, abs=1e-4), (
            f"parent-moved sync didn't update joint_big.current_value: "
            f"got {got_big:+.4f}, expected {-angle:+.4f}"
        )

        # joint_small (driver side): inverse propagation gives θ_small =
        # 0 + sign·(joint_big − 0)/ratio = (-π/2) / 3 = -π/6.
        got_small = _read_joint(meta["joint_small_id"])["current_value"]
        expected_small = -angle / 3.0
        assert got_small == pytest.approx(expected_small, abs=1e-4), (
            f"gear didn't propagate to small gear: got {got_small:+.4f}, "
            f"expected {expected_small:+.4f}"
        )

    def test_rotating_small_gear_drives_big_wheel_endpoint_not_fixed_axle(self):
        meta = self._build_big_wheel_assembly()
        r = client.post("/api/assembly/gear-relations", json={
            "joint_a_id": meta["joint_small_id"],
            "joint_b_id": meta["joint_big_id"],
            "endpoint_a_instance_id": meta["small_gear_id"],
            "endpoint_a_side": "b",
            "endpoint_b_instance_id": meta["members"][0],
            "endpoint_b_side": "a",
            "ratio": 3.0,
            "invert": False,
            "capture_anchors_from_current": True,
        })
        assert r.status_code == 201, r.text

        axle_before = _instance_transform(meta["axle_id"])
        wheel_before = _instance_transform(meta["members"][0])
        angle = math.pi / 8
        r = client.patch(f"/api/assembly/joints/{meta['joint_small_id']}", json={
            "current_value": angle,
        })
        assert r.status_code == 200, r.text

        axle_after = _instance_transform(meta["axle_id"])
        wheel_after = _instance_transform(meta["members"][0])
        assert axle_after == pytest.approx(axle_before, abs=1e-8)
        assert not np.allclose(wheel_after, wheel_before)
        assert _read_joint(meta["joint_big_id"])["current_value"] == pytest.approx(3.0 * angle, abs=1e-6)


# ── Deferred-commit / stale base_transform diagnostic ───────────────────────

class TestStaleBaseTransformAffectsGearMath:
    """If the user creates a gear relation BEFORE setting base_transform on
    the driver's child instance, the gear math still works (anchors capture
    the joint's current_value at relation creation), but the angle-derivation
    path used by patch_instance / transform_group needs base_transform to be
    set. This test pins that contract down so regressions surface here.
    """

    def test_missing_base_transform_blocks_instance_path_sync(self):
        """When inst_b.base_transform is None, the gizmo path can't derive
        the joint angle — driven joint should be left at its prior value
        rather than corrupted by a NaN angle."""
        meta, _ = _two_revolute_two_instance_assembly()
        # Clear base_transform on the driver's child to simulate the
        # "transform was never anchored" state.
        a = assembly_state.get_or_404()
        inst_b = next(i for i in a.instances if i.id == meta["inst_b"])
        inst_b.base_transform = None
        assembly_state.set_assembly(a)
        _create_gear_relation(meta["joint_ab"], meta["joint_cd"], ratio=1.0)

        angle = math.pi / 6
        R = _rotate_about_z(angle, ox=5.0, oy=0.0)
        base = np.array([[1, 0, 0, 5], [0, 1, 0, 0], [0, 0, 1, 0], [0, 0, 0, 1]])
        new_T = R @ base
        client.patch(f"/api/assembly/instances/{meta['inst_b']}", json={
            "transform": {"values": [float(v) for v in new_T.flatten()]},
        })

        got_driven = _read_joint(meta["joint_cd"])["current_value"]
        # With no base_transform, the sync helper bails — driven stays at 0.
        # This is the contract we want to enforce: stale state never poisons
        # the gear math with NaN or a garbage angle.
        assert got_driven == pytest.approx(0.0, abs=1e-9), (
            f"stale base_transform leaked into gear math: driven={got_driven}"
        )
