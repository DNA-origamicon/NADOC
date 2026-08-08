"""Direct input→output unit tests for the pure FK propagation kernel
(`backend/core/assembly_fk.py`), extracted from `backend/api/assembly.py`.

No TestClient — these assert the graph/matrix rules directly: rigid groups move
as one body, non-rigid children move by the parent's delta, fixed instances stay
anchored, and `visited` prevents re-moves.
"""

import numpy as np

from backend.core.assembly_fk import (
    _build_inst_by_id,
    _fk_apply_to_joint,
    _fk_expand_rigid_group,
    _fk_propagate,
    _move_instance_with_fk_delta,
)
from backend.core.models import (
    Assembly,
    AssemblyJoint,
    Mat4x4,
    PartInstance,
    PartSourceInline,
    Design,
)


# ── fixtures ──────────────────────────────────────────────────────────────────


def _inst(
    iid: str, *, fixed: bool = False, tx: float = 0.0, base: bool = False
) -> PartInstance:
    """A minimal PartInstance at translation (tx,0,0), optional base_transform."""
    t = np.eye(4)
    t[0, 3] = tx
    return PartInstance(
        id=iid,
        source=PartSourceInline(design=Design()),
        transform=Mat4x4.from_array(t),
        base_transform=Mat4x4.from_array(t) if base else None,
        fixed=fixed,
    )


def _translation(dx: float, dy: float = 0.0, dz: float = 0.0) -> np.ndarray:
    d = np.eye(4)
    d[:3, 3] = [dx, dy, dz]
    return d


def _tx(inst: PartInstance) -> float:
    """The x-translation component of an instance's transform."""
    return inst.transform.to_array()[0, 3]


# ── _build_inst_by_id ─────────────────────────────────────────────────────────


def test_build_inst_by_id_maps_every_instance():
    a, b = _inst("a"), _inst("b")
    asm = Assembly(instances=[a, b])
    by_id = _build_inst_by_id(asm)
    assert by_id == {"a": a, "b": b}
    assert by_id["a"] is a  # identity, not a copy — FK mutates in place


# ── _fk_apply_to_joint ────────────────────────────────────────────────────────


def test_fk_apply_to_joint_translates_origin_not_direction():
    j = AssemblyJoint(
        instance_b_id="b", axis_origin=[0, 0, 0], axis_direction=[0, 0, 1]
    )
    _fk_apply_to_joint(j, _translation(10))
    assert j.axis_origin == [10.0, 0.0, 0.0]
    # A pure translation leaves a (w=0) direction vector unchanged.
    assert np.allclose(j.axis_direction, [0.0, 0.0, 1.0])


def test_fk_apply_to_joint_rotates_and_renormalizes_direction():
    rot_z90 = np.eye(4)
    rot_z90[:3, :3] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
    j = AssemblyJoint(
        instance_b_id="b", axis_origin=[1, 0, 0], axis_direction=[1, 0, 0]
    )
    _fk_apply_to_joint(j, rot_z90)
    assert np.allclose(j.axis_origin, [0.0, 1.0, 0.0])  # origin rotated
    assert np.allclose(j.axis_direction, [0.0, 1.0, 0.0])  # x → y, unit length
    assert np.isclose(np.linalg.norm(j.axis_direction), 1.0)


# ── _fk_expand_rigid_group ────────────────────────────────────────────────────


def test_rigid_group_moves_bidirectionally_skipping_fixed():
    a, b, c = _inst("a"), _inst("b"), _inst("c", fixed=True)
    asm = Assembly(
        instances=[a, b, c],
        joints=[
            AssemblyJoint(joint_type="rigid", instance_a_id="a", instance_b_id="b"),
            AssemblyJoint(joint_type="rigid", instance_a_id="a", instance_b_id="c"),
        ],
    )
    visited = {"a"}
    queue: list = []
    _fk_expand_rigid_group(asm, "a", _translation(5), visited, queue)
    assert _tx(b) == 5.0  # rigid neighbour moved
    assert _tx(c) == 0.0  # fixed neighbour untouched
    assert "b" in visited and "c" not in visited
    assert queue == ["b"]


def test_rigid_group_respects_visited_no_remove():
    a, b = _inst("a"), _inst("b")
    asm = Assembly(
        instances=[a, b],
        joints=[
            AssemblyJoint(joint_type="rigid", instance_a_id="a", instance_b_id="b")
        ],
    )
    # b already visited → must not be moved again.
    visited = {"a", "b"}
    _fk_expand_rigid_group(asm, "a", _translation(5), visited, [])
    assert _tx(b) == 0.0


def test_rigid_group_also_moves_base_transform():
    a, b = _inst("a"), _inst("b", base=True)
    asm = Assembly(
        instances=[a, b],
        joints=[
            AssemblyJoint(joint_type="rigid", instance_a_id="a", instance_b_id="b")
        ],
    )
    _fk_expand_rigid_group(asm, "a", _translation(7), {"a"}, [])
    assert _tx(b) == 7.0
    assert b.base_transform.to_array()[0, 3] == 7.0


# ── _fk_propagate ─────────────────────────────────────────────────────────────


def test_propagate_moves_nonrigid_child_and_updates_joint_axis():
    a, b = _inst("a"), _inst("b")
    j = AssemblyJoint(
        joint_type="revolute",
        instance_a_id="a",
        instance_b_id="b",
        axis_origin=[0, 0, 0],
    )
    asm = Assembly(instances=[a, b], joints=[j])
    _fk_propagate(asm, {"a"}, _translation(3), {"a"})
    assert _tx(b) == 3.0
    assert j.axis_origin == [3.0, 0.0, 0.0]  # joint axis rode along


def test_propagate_skips_rigid_joints():
    # propagate handles only NON-rigid children; a rigid joint from the parent
    # must be left to _fk_expand_rigid_group, not double-moved here.
    a, b = _inst("a"), _inst("b")
    asm = Assembly(
        instances=[a, b],
        joints=[
            AssemblyJoint(joint_type="rigid", instance_a_id="a", instance_b_id="b")
        ],
    )
    _fk_propagate(asm, {"a"}, _translation(4), {"a"})
    assert _tx(b) == 0.0


def test_propagate_skips_fixed_child():
    a, b = _inst("a"), _inst("b", fixed=True)
    j = AssemblyJoint(
        joint_type="revolute",
        instance_a_id="a",
        instance_b_id="b",
        axis_origin=[0, 0, 0],
    )
    asm = Assembly(instances=[a, b], joints=[j])
    _fk_propagate(asm, {"a"}, _translation(3), {"a"})
    assert _tx(b) == 0.0
    assert j.axis_origin == [0.0, 0.0, 0.0]  # not touched for a fixed child


def test_propagate_cascades_through_chain():
    # a → b → c (two revolute links); moving a propagates all the way down.
    a, b, c = _inst("a"), _inst("b"), _inst("c")
    asm = Assembly(
        instances=[a, b, c],
        joints=[
            AssemblyJoint(joint_type="revolute", instance_a_id="a", instance_b_id="b"),
            AssemblyJoint(joint_type="revolute", instance_a_id="b", instance_b_id="c"),
        ],
    )
    _fk_propagate(asm, {"a"}, _translation(2), {"a"})
    assert _tx(b) == 2.0
    assert _tx(c) == 2.0


# ── _move_instance_with_fk_delta ──────────────────────────────────────────────


def test_move_instance_moves_self_and_subtree():
    a, b = _inst("a"), _inst("b")
    asm = Assembly(
        instances=[a, b],
        joints=[
            AssemblyJoint(joint_type="revolute", instance_a_id="a", instance_b_id="b")
        ],
    )
    moved = _move_instance_with_fk_delta(asm, "a", _translation(6), set())
    assert moved is True
    assert _tx(a) == 6.0  # self moved
    assert _tx(b) == 6.0  # kinematic child moved


def test_move_instance_returns_false_for_fixed_or_missing_or_visited():
    a = _inst("a", fixed=True)
    b = _inst("b")
    asm = Assembly(instances=[a, b])
    # fixed
    assert _move_instance_with_fk_delta(asm, "a", _translation(1), set()) is False
    assert _tx(a) == 0.0
    # missing id
    assert _move_instance_with_fk_delta(asm, "nope", _translation(1), set()) is False
    # already visited
    assert _move_instance_with_fk_delta(asm, "b", _translation(1), {"b"}) is False
    assert _tx(b) == 0.0
