"""Direct input→output unit tests for the pure revolute-drive + gear/belt
coupling kinematics kernel (`backend/core/assembly_kinematics.py`), extracted
from `backend/api/assembly.py` (carve-up Refactor #15).

No TestClient — these assert the transform/coupling rules directly: a revolute
rotation moves a body about a world-fixed axis, the inverse recovers the angle,
gear relations drive coupled joints by the ratio, and a belt is expressed as an
equivalent gear edge.
"""

import math
import os

import numpy as np
import pytest

# Silence the kernel's [gear] diagnostic prints during tests.
os.environ["NADOC_GEAR_DEBUG"] = "0"


def pytest_approx(expected, abs_tol=1e-6):
    return pytest.approx(expected, abs=abs_tol)


from backend.core.assembly_kinematics import (  # noqa: E402
    _apply_revolute_joint,
    _derive_revolute_angle,
    _sync_revolute_values_for_instances,
    _sync_revolute_values_for_parent_moves,
    _gear_endpoint_side,
    _axis_angle_rotation_matrix,
    _apply_revolute_value_to_gear_endpoint,
    _belt_to_relation,
    _coupling_relations,
    _propagate_gear_relations_from,
)
from backend.core.assembly_fk import _build_inst_by_id  # noqa: E402
from backend.core.models import (  # noqa: E402
    Assembly,
    AssemblyJoint,
    BeltPath,
    BeltPulley,
    Design,
    GearRelation,
    Mat4x4,
    PartInstance,
    PartSourceInline,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


def _inst(
    iid: str, *, fixed: bool = False, tx: float = 0.0, base: bool = True
) -> PartInstance:
    """A minimal PartInstance translated to (tx,0,0); base_transform = transform."""
    t = np.eye(4)
    t[0, 3] = tx
    return PartInstance(
        id=iid,
        source=PartSourceInline(design=Design()),
        transform=Mat4x4.from_array(t),
        base_transform=Mat4x4.from_array(t) if base else None,
        fixed=fixed,
    )


def _zrot(angle: float) -> np.ndarray:
    """4×4 rotation about world +Z through the origin."""
    c, s = math.cos(angle), math.sin(angle)
    M = np.eye(4)
    M[0, 0], M[0, 1] = c, -s
    M[1, 0], M[1, 1] = s, c
    return M


# ── _apply_revolute_joint ──────────────────────────────────────────────────────


def test_apply_revolute_joint_moves_offset_body_about_axis():
    base = np.eye(4)
    base[:3, 3] = [1.0, 0.0, 0.0]
    out = _apply_revolute_joint(base, [0, 0, 0], [0, 0, 1], math.pi / 2)
    # (1,0,0) rotated +90° about +Z → (0,1,0)
    assert np.allclose(out[:3, 3], [0.0, 1.0, 0.0], atol=1e-9)


def test_apply_revolute_joint_point_on_axis_does_not_move():
    base = np.eye(4)  # body at the origin, which lies on the axis
    out = _apply_revolute_joint(base, [0, 0, 0], [0, 0, 1], 1.234)
    assert np.allclose(out[:3, 3], [0.0, 0.0, 0.0], atol=1e-9)


def test_apply_revolute_joint_degenerate_axis_returns_base_unchanged():
    base = np.eye(4)
    base[:3, 3] = [2.0, 3.0, 4.0]
    out = _apply_revolute_joint(base, [0, 0, 0], [0, 0, 0], 1.0)
    assert out is base


# ── _derive_revolute_angle (inverse of _apply_revolute_joint) ──────────────────


def test_derive_revolute_angle_recovers_applied_angle():
    base = np.eye(4)
    base[:3, 3] = [1.0, 0.0, 0.0]
    cur = _apply_revolute_joint(base, [0, 0, 0], [0, 0, 1], 0.7)
    ang = _derive_revolute_angle(base, cur, [0, 0, 1])
    assert ang == pytest_approx(0.7)


def test_derive_revolute_angle_sign_follows_axis():
    base = np.eye(4)
    base[:3, 3] = [1.0, 0.0, 0.0]
    cur = _apply_revolute_joint(base, [0, 0, 0], [0, 0, 1], -0.5)
    ang = _derive_revolute_angle(base, cur, [0, 0, 1])
    assert ang == pytest_approx(-0.5)


def test_derive_revolute_angle_zero_for_no_motion():
    base = np.eye(4)
    assert _derive_revolute_angle(base, base.copy(), [0, 0, 1]) == pytest_approx(0.0)


# ── _sync_revolute_values_for_instances ────────────────────────────────────────


def test_sync_revolute_values_derives_current_value_from_transform():
    inst = _inst("ib", tx=1.0)
    # Pose the instance as if rotated +60° about Z from its base.
    inst.transform = Mat4x4.from_array(
        _apply_revolute_joint(
            inst.base_transform.to_array(), [0, 0, 0], [0, 0, 1], math.pi / 3
        )
    )
    j = AssemblyJoint(
        id="j", instance_b_id="ib", axis_origin=[0, 0, 0], axis_direction=[0, 0, 1]
    )
    asm = Assembly(instances=[inst], joints=[j])
    changed = _sync_revolute_values_for_instances(asm, {"ib"})
    assert changed == ["j"]
    assert j.current_value == pytest_approx(math.pi / 3)


def test_sync_revolute_values_ignores_unlisted_and_nonrevolute():
    inst = _inst("ib", tx=1.0)
    inst.transform = Mat4x4.from_array(
        _apply_revolute_joint(inst.base_transform.to_array(), [0, 0, 0], [0, 0, 1], 0.4)
    )
    j_other = AssemblyJoint(id="j", instance_b_id="ib", axis_direction=[0, 0, 1])
    asm = Assembly(instances=[inst], joints=[j_other])
    # Empty instance set → nothing to sync.
    assert _sync_revolute_values_for_instances(asm, set()) == []
    assert j_other.current_value == pytest_approx(0.0)


def test_sync_revolute_values_uses_base_transform_override():
    inst = _inst("ib", tx=1.0, base=False)  # base_transform cleared (group-move case)
    base = np.eye(4)
    base[:3, 3] = [1.0, 0.0, 0.0]
    inst.transform = Mat4x4.from_array(
        _apply_revolute_joint(base, [0, 0, 0], [0, 0, 1], 0.25)
    )
    j = AssemblyJoint(id="j", instance_b_id="ib", axis_direction=[0, 0, 1])
    asm = Assembly(instances=[inst], joints=[j])
    # Without the override the sync would bail (base_transform is None).
    assert _sync_revolute_values_for_instances(asm, {"ib"}) == []
    changed = _sync_revolute_values_for_instances(
        asm, {"ib"}, base_transforms_override={"ib": Mat4x4.from_array(base)}
    )
    assert changed == ["j"]
    assert j.current_value == pytest_approx(0.25)


# ── _sync_revolute_values_for_parent_moves ─────────────────────────────────────


def test_sync_parent_move_decrements_child_value_by_delta():
    parent, child = _inst("parent"), _inst("child")
    j = AssemblyJoint(
        id="j",
        instance_a_id="parent",
        instance_b_id="child",
        axis_direction=[0, 0, 1],
        current_value=0.0,
    )
    asm = Assembly(instances=[parent, child], joints=[j])
    changed = _sync_revolute_values_for_parent_moves(
        asm, {"parent"}, _zrot(math.pi / 4)
    )
    assert changed == ["j"]
    # Parent rotated +45° about Z while child stayed → child-relative angle −45°.
    assert j.current_value == pytest_approx(-math.pi / 4)


def test_sync_parent_move_skips_when_both_moved():
    parent, child = _inst("parent"), _inst("child")
    j = AssemblyJoint(
        id="j", instance_a_id="parent", instance_b_id="child", axis_direction=[0, 0, 1]
    )
    asm = Assembly(instances=[parent, child], joints=[j])
    # Both endpoints moved → standard FK handles it; this helper must not fire.
    assert (
        _sync_revolute_values_for_parent_moves(asm, {"parent", "child"}, _zrot(0.3))
        == []
    )
    assert j.current_value == pytest_approx(0.0)


# ── _gear_endpoint_side ────────────────────────────────────────────────────────


def test_gear_endpoint_side_none_joint_defaults_b():
    rel = GearRelation(joint_a_id="ja", joint_b_id="jb")
    assert _gear_endpoint_side(rel, "b", None) == "b"


def test_gear_endpoint_side_explicit_side_wins():
    rel = GearRelation(joint_a_id="ja", joint_b_id="jb", endpoint_b_side="a")
    j = AssemblyJoint(id="jb", instance_a_id="ia", instance_b_id="ib")
    assert _gear_endpoint_side(rel, "b", j) == "a"


def test_gear_endpoint_side_infers_a_from_instance_match():
    rel = GearRelation(joint_a_id="ja", joint_b_id="jb", endpoint_b_instance_id="ia")
    j = AssemblyJoint(id="jb", instance_a_id="ia", instance_b_id="ib")
    assert _gear_endpoint_side(rel, "b", j) == "a"


def test_gear_endpoint_side_default_b_when_no_hint():
    rel = GearRelation(joint_a_id="ja", joint_b_id="jb")
    j = AssemblyJoint(id="jb", instance_a_id="ia", instance_b_id="ib")
    assert _gear_endpoint_side(rel, "b", j) == "b"


# ── _axis_angle_rotation_matrix ────────────────────────────────────────────────


def test_axis_angle_rotation_matrix_matches_zrot():
    R = _axis_angle_rotation_matrix([0, 0, 1], math.pi / 2)
    v = R @ np.array([1.0, 0.0, 0.0])
    assert np.allclose(v, [0.0, 1.0, 0.0], atol=1e-9)


# ── _apply_revolute_value_to_gear_endpoint ─────────────────────────────────────


def test_apply_revolute_value_moves_child_seed_and_sets_value():
    inst = _inst("ib", tx=1.0)
    j = AssemblyJoint(
        id="j",
        instance_b_id="ib",
        axis_origin=[0, 0, 0],
        axis_direction=[0, 0, 1],
        current_value=0.0,
    )
    asm = Assembly(instances=[inst], joints=[j])
    inst_by_id = _build_inst_by_id(asm)
    ok = _apply_revolute_value_to_gear_endpoint(asm, j, "b", math.pi / 2, inst_by_id)
    assert ok is True
    assert j.current_value == pytest_approx(math.pi / 2)
    assert np.allclose(inst.transform.to_array()[:3, 3], [0.0, 1.0, 0.0], atol=1e-9)


def test_apply_revolute_value_returns_false_for_fixed_seed():
    inst = _inst("ib", tx=1.0, fixed=True)
    j = AssemblyJoint(id="j", instance_b_id="ib", axis_direction=[0, 0, 1])
    asm = Assembly(instances=[inst], joints=[j])
    inst_by_id = _build_inst_by_id(asm)
    assert _apply_revolute_value_to_gear_endpoint(asm, j, "b", 1.0, inst_by_id) is False


def test_apply_revolute_value_returns_false_for_missing_seed():
    j = AssemblyJoint(id="j", instance_b_id="ghost", axis_direction=[0, 0, 1])
    asm = Assembly(instances=[], joints=[j])
    assert _apply_revolute_value_to_gear_endpoint(asm, j, "b", 1.0, {}) is False


# ── _belt_to_relation ──────────────────────────────────────────────────────────


def _belt(
    ra: float, rb: float, *, side_a="b", side_b="b", axis_a=(0, 0, 1), axis_b=(0, 0, 1)
) -> tuple[BeltPath, dict]:
    ja = AssemblyJoint(id="ja", instance_b_id="ia", axis_direction=list(axis_a))
    jb = AssemblyJoint(id="jb", instance_b_id="ib", axis_direction=list(axis_b))
    belt = BeltPath(
        id="belt1",
        name="B",
        pulley_a=BeltPulley(joint_id="ja", side=side_a, radius=ra),
        pulley_b=BeltPulley(joint_id="jb", side=side_b, radius=rb),
    )
    return belt, {"ja": ja, "jb": jb}


def test_belt_to_relation_ratio_and_same_sense():
    belt, jbi = _belt(2.0, 1.0)
    rel = _belt_to_relation(belt, jbi)
    assert rel is not None
    assert rel.ratio == pytest_approx(2.0)
    assert rel.invert is False  # both side 'b', parallel axes → same world sense


def test_belt_to_relation_inverts_for_opposed_axes():
    belt, jbi = _belt(1.0, 1.0, axis_b=(0, 0, -1))
    rel = _belt_to_relation(belt, jbi)
    assert rel.invert is True


def test_belt_to_relation_none_when_joint_missing_or_zero_radius():
    belt, jbi = _belt(1.0, 1.0)
    assert _belt_to_relation(belt, {}) is None  # joints absent
    belt0, jbi0 = _belt(1.0, 0.0)
    assert _belt_to_relation(belt0, jbi0) is None  # non-positive radius


# ── _coupling_relations ────────────────────────────────────────────────────────


def test_coupling_relations_includes_gears_and_belts():
    ja = AssemblyJoint(id="ja", instance_b_id="ia", axis_direction=[0, 0, 1])
    jb = AssemblyJoint(id="jb", instance_b_id="ib", axis_direction=[0, 0, 1])
    gear = GearRelation(id="g", joint_a_id="ja", joint_b_id="jb", ratio=1.0)
    belt = BeltPath(
        id="belt1",
        pulley_a=BeltPulley(joint_id="ja", radius=1.0),
        pulley_b=BeltPulley(joint_id="jb", radius=1.0),
    )
    asm = Assembly(joints=[ja, jb], gear_relations=[gear], belt_paths=[belt])
    rels = _coupling_relations(asm, {"ja": ja, "jb": jb})
    assert len(rels) == 2
    assert any(r.id == "g" for r in rels)
    assert any(r.id.startswith("__belt__") for r in rels)


# ── _propagate_gear_relations_from ─────────────────────────────────────────────


def _gear_pair(ratio: float, invert: bool = False) -> Assembly:
    ia, ib = _inst("ia", tx=1.0), _inst("ib", tx=1.0)
    ja = AssemblyJoint(
        id="ja",
        instance_b_id="ia",
        axis_origin=[0, 0, 0],
        axis_direction=[0, 0, 1],
        current_value=0.0,
    )
    jb = AssemblyJoint(
        id="jb",
        instance_b_id="ib",
        axis_origin=[0, 0, 0],
        axis_direction=[0, 0, 1],
        current_value=0.0,
    )
    rel = GearRelation(
        id="g", joint_a_id="ja", joint_b_id="jb", ratio=ratio, invert=invert
    )
    return Assembly(instances=[ia, ib], joints=[ja, jb], gear_relations=[rel])


def test_propagate_drives_coupled_joint_by_ratio():
    asm = _gear_pair(2.0)
    ja = next(j for j in asm.joints if j.id == "ja")
    jb = next(j for j in asm.joints if j.id == "jb")
    ja.current_value = 1.0  # user spun joint_a to 1 rad
    _propagate_gear_relations_from(asm, "ja")
    # θ_b = anchor_b + sign·(θ_a − anchor_a)·ratio = 0 + 1·(1−0)·2 = 2
    assert jb.current_value == pytest_approx(2.0)


def test_propagate_is_bidirectional_from_driven_side():
    asm = _gear_pair(2.0)
    ja = next(j for j in asm.joints if j.id == "ja")
    jb = next(j for j in asm.joints if j.id == "jb")
    jb.current_value = 2.0  # spin joint_b instead
    _propagate_gear_relations_from(asm, "jb")
    # inverse edge: θ_a = anchor_a + sign·(θ_b − anchor_b)/ratio = 2/2 = 1
    assert ja.current_value == pytest_approx(1.0)


def test_propagate_invert_flips_sign():
    asm = _gear_pair(1.0, invert=True)
    ja = next(j for j in asm.joints if j.id == "ja")
    jb = next(j for j in asm.joints if j.id == "jb")
    ja.current_value = 0.5
    _propagate_gear_relations_from(asm, "ja")
    assert jb.current_value == pytest_approx(-0.5)


def test_propagate_noop_without_relations():
    ib = _inst("ib", tx=1.0)
    jb = AssemblyJoint(
        id="jb", instance_b_id="ib", axis_direction=[0, 0, 1], current_value=3.0
    )
    asm = Assembly(instances=[ib], joints=[jb])
    _propagate_gear_relations_from(asm, "jb")  # no gears/belts → early return
    assert jb.current_value == pytest_approx(3.0)
