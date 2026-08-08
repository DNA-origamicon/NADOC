"""Direct unit tests for backend.core.assembly_polymer.build_polymer_chain.

These exercise the pure record-assembly orchestration (geometry placement,
connector union, primary + pattern-mate replication) WITHOUT FastAPI /
assembly_state — the function takes plain instance/joint lists and returns
``(existing_instances, new_instances, new_joints)``. The route-level behavior
(validation, feature log, the count==2 no-op) is covered by test_polymerize.py;
this file pins the chain-building math the route now delegates to core.
"""

from __future__ import annotations

import numpy as np

from backend.core.assembly_polymer import build_polymer_chain
from backend.core.models import (
    AssemblyJoint,
    ConnectionType,
    Design,
    InterfacePoint,
    Mat4x4,
    PartInstance,
    PartSourceInline,
    Vec3,
)


# ── Fixtures (local, no TestClient) ────────────────────────────────────────────


def _translation(dx: float, dy: float, dz: float) -> Mat4x4:
    return Mat4x4(
        values=[
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
    )


def _ip(label: str, z: float, nz: float) -> InterfacePoint:
    return InterfacePoint(
        label=label,
        position=Vec3(x=0.0, y=0.0, z=z),
        normal=Vec3(x=0.0, y=0.0, z=nz),
        connection_type=ConnectionType.BLUNT_END,
    )


def _rod_instance(
    inst_id: str,
    name: str,
    design: Design,
    t: Mat4x4,
    ips: list[InterfacePoint] | None = None,
) -> PartInstance:
    return PartInstance(
        id=inst_id,
        name=name,
        source=PartSourceInline(design=design),
        transform=t,
        interface_points=ips
        if ips is not None
        else [
            _ip("front", 0.0, -1.0),
            _ip("back", 10.0, 1.0),
        ],
    )


def _seed_pair(
    joint_type: str = "rigid",
    ips_a: list[InterfacePoint] | None = None,
    ips_b: list[InterfacePoint] | None = None,
):
    """Two identical inline rods mated back→front along +Z (10 nm apart)."""
    design = Design()  # one shared inline design object
    inst_a = _rod_instance("inst-A", "Rod A", design, _translation(0, 0, 0), ips_a)
    inst_b = _rod_instance("inst-B", "Rod B", design, _translation(0, 0, 10), ips_b)
    joint = AssemblyJoint(
        id="joint-AB",
        name="AB",
        joint_type=joint_type,
        instance_a_id="inst-A",
        instance_b_id="inst-B",
        axis_origin=[0.0, 0.0, 10.0],
        axis_direction=[0.0, 0.0, 1.0],
        current_value=0.0,
        connector_a_label="back",
        connector_b_label="front",
        mate_relative_transform=[1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1],
    )
    return inst_a, inst_b, joint


def _z_of(inst: PartInstance) -> float:
    return inst.transform.to_array()[2, 3]


# ── Counts + direction ─────────────────────────────────────────────────────────


def test_forward_count4_adds_two_instances_two_joints():
    inst_a, inst_b, joint = _seed_pair()
    existing, new_i, new_j = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        [],
        4,
        "forward",
        [inst_a, inst_b],
        [joint],
    )
    assert len(existing) == 2  # seed pair, untouched count
    assert len(new_i) == 2  # count 4 − existing 2
    assert len(new_j) == 2


def test_backward_count3_prepends_one():
    inst_a, inst_b, joint = _seed_pair()
    _, new_i, new_j = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        [],
        3,
        "backward",
        [inst_a, inst_b],
        [joint],
    )
    assert len(new_i) == 1
    assert len(new_j) == 1
    # backward instance sits below A (z=0) → negative z.
    assert _z_of(new_i[0]) < 0.0


def test_both_count5_splits_two_forward_one_backward():
    inst_a, inst_b, joint = _seed_pair()
    _, new_i, _ = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        [],
        5,
        "both",
        [inst_a, inst_b],
        [joint],
    )
    assert len(new_i) == 3
    zs = sorted(_z_of(i) for i in new_i)
    # two new forward (z > 10), one backward (z < 0) — extra-on-forward.
    assert sum(1 for z in zs if z > 10.0) == 2
    assert sum(1 for z in zs if z < 0.0) == 1


def test_forward_transforms_step_along_delta():
    inst_a, inst_b, joint = _seed_pair()
    _, new_i, _ = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        [],
        4,
        "forward",
        [inst_a, inst_b],
        [joint],
    )
    # delta is +10 nm along Z; clones land at z=20, z=30.
    zs = sorted(_z_of(i) for i in new_i)
    assert zs == [20.0, 30.0]


# ── Connector union ─────────────────────────────────────────────────────────────


def test_connector_union_applied_to_seed_and_clones():
    # seed A has only 'back', seed B has only 'front' — every chained instance
    # plays both roles, so each must end up with BOTH labels.
    inst_a, inst_b, joint = _seed_pair(
        ips_a=[_ip("back", 10.0, 1.0)],
        ips_b=[_ip("front", 0.0, -1.0)],
    )
    existing, new_i, _ = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        [],
        4,
        "forward",
        [inst_a, inst_b],
        [joint],
    )
    for inst in existing + new_i:
        labels = {ip.label for ip in inst.interface_points}
        assert labels == {"back", "front"}, inst.name


def test_seed_originals_not_mutated_in_place():
    inst_a, inst_b, joint = _seed_pair(
        ips_a=[_ip("back", 10.0, 1.0)],
        ips_b=[_ip("front", 0.0, -1.0)],
    )
    build_polymer_chain(
        joint, inst_a, inst_b, [], 4, "forward", [inst_a, inst_b], [joint]
    )
    # the passed-in originals keep their single connector; the union lives only
    # on the returned `existing` copies.
    assert [ip.label for ip in inst_a.interface_points] == ["back"]
    assert [ip.label for ip in inst_b.interface_points] == ["front"]


# ── New-joint fields + wiring ────────────────────────────────────────────────────


def test_new_joints_preserve_type_labels_and_mate_transform():
    inst_a, inst_b, joint = _seed_pair(joint_type="revolute")
    _, _, new_j = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        [],
        4,
        "forward",
        [inst_a, inst_b],
        [joint],
    )
    for nj in new_j:
        assert nj.joint_type == "revolute"
        assert nj.connector_a_label == "back"
        assert nj.connector_b_label == "front"
        assert nj.mate_relative_transform == joint.mate_relative_transform
        assert nj.current_value == 0.0


def test_forward_joints_chain_prev_to_new():
    inst_a, inst_b, joint = _seed_pair()
    _, new_i, new_j = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        [],
        4,
        "forward",
        [inst_a, inst_b],
        [joint],
    )
    # first new joint binds (seed B → first clone); second binds (first → second).
    assert new_j[0].instance_a_id == "inst-B"
    assert new_j[0].instance_b_id == new_i[0].id
    assert new_j[1].instance_a_id == new_i[0].id
    assert new_j[1].instance_b_id == new_i[1].id


def test_clones_share_source_by_reference():
    inst_a, inst_b, joint = _seed_pair()
    _, new_i, _ = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        [],
        4,
        "forward",
        [inst_a, inst_b],
        [joint],
    )
    # model_construct shares the heavy source field (read-only downstream).
    for inst in new_i:
        assert inst.source is inst_b.source
        assert inst.representation == "cylinders"


# ── Pattern-mate replication ─────────────────────────────────────────────────────


def test_additional_pattern_member_cloned_at_each_step():
    inst_a, inst_b, joint = _seed_pair()
    # An additional part riding alongside seed A, plus a mate inside the unit.
    add = _rod_instance("inst-X", "X", inst_a.source.design, _translation(5, 0, 0))
    intra = AssemblyJoint(
        id="joint-AX",
        name="AX",
        joint_type="rigid",
        instance_a_id="inst-A",
        instance_b_id="inst-X",
        axis_origin=[5.0, 0.0, 0.0],
        axis_direction=[1.0, 0.0, 0.0],
        connector_a_label="back",
        connector_b_label="front",
    )
    _, new_i, new_j = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        [add],
        4,
        "forward",
        [inst_a, inst_b, add],
        [joint, intra],
    )
    # Additional ends up with `count` total instances → count-1 new clones.
    add_clones = [i for i in new_i if i.name.startswith("X")]
    assert len(add_clones) == 4 - 1
    # The intra-unit mate is replicated (new joints beyond the primary chain).
    intra_clones = [j for j in new_j if j.name.startswith("AX")]
    assert len(intra_clones) >= 1
    for jc in intra_clones:
        assert jc.connector_a_label == "back"
        assert jc.connector_b_label == "front"


def test_additional_clone_rides_delta_offset():
    inst_a, inst_b, joint = _seed_pair()
    add = _rod_instance(
        "inst-X", "X", inst_a.source.design, _translation(5, 0, 0)
    )  # at z=0, x=5
    _, new_i, _ = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        [add],
        3,
        "forward",
        [inst_a, inst_b, add],
        [joint],
    )
    add_clones = [i for i in new_i if i.name.startswith("X")]
    # delta is +10 Z; each additional clone preserves x=5 and steps in Z.
    for c in add_clones:
        arr = c.transform.to_array()
        assert np.isclose(arr[0, 3], 5.0)
        assert arr[2, 3] > 0.0


def test_no_additionals_no_pattern_joints():
    inst_a, inst_b, joint = _seed_pair()
    _, _, new_j = build_polymer_chain(
        joint,
        inst_a,
        inst_b,
        [],
        4,
        "forward",
        [inst_a, inst_b],
        [joint],
    )
    # only the primary chain joints — no pattern replication.
    assert all(nj.name.startswith("AB ") for nj in new_j)


# ── Periodic chain (single-seed, derived delta) ─────────────────────────────────

from backend.core.assembly_polymer import build_periodic_chain  # noqa: E402


def _z_translation(dz: float) -> np.ndarray:
    m = np.eye(4, dtype=float)
    m[2, 3] = dz
    return m


# part-local seam connectors: 5' end-cap at z=0 (normal -Z), 3' end-cap at z=5
# (normal +Z). Plain lists so the helper builds frames via the fallback path.
_SPECS = (([0.0, 0.0, 0.0], [0.0, 0.0, -1.0]), ([0.0, 0.0, 5.0], [0.0, 0.0, 1.0]))


def _periodic_seed(ips=None) -> PartInstance:
    """A single seed instance at the origin with one non-seam IP."""
    design = Design()
    return PartInstance(
        id="seed",
        name="Ring",
        source=PartSourceInline(design=design),
        transform=Mat4x4.from_array(np.eye(4)),
        interface_points=ips
        if ips is not None
        else [
            InterfacePoint(
                label="front",
                position=Vec3(x=0.0, y=0.0, z=0.0),
                normal=Vec3(x=0.0, y=0.0, z=-1.0),
                connection_type=ConnectionType.BLUNT_END,
            ),
        ],
    )


def _other(inst_id: str = "other") -> PartInstance:
    design = Design()
    return PartInstance(
        id=inst_id,
        name="Other",
        source=PartSourceInline(design=design),
        transform=Mat4x4.from_array(_z_translation(99.0)),
    )


def test_periodic_forward_count_and_placement():
    seed = _periodic_seed()
    delta = _z_translation(10.0)
    existing, new_i, new_j = build_periodic_chain(
        seed,
        delta,
        np.linalg.inv(delta),
        _SPECS,
        3,
        "forward",
        [seed],
    )
    # count=3 → 2 new copies beyond the seed, both forward.
    assert len(new_i) == 2
    assert [i.name for i in new_i] == ["Ring +1", "Ring +2"]
    # placed at T_seed @ delta^k → z = 10, 20.
    assert np.isclose(new_i[0].transform.to_array()[2, 3], 10.0)
    assert np.isclose(new_i[1].transform.to_array()[2, 3], 20.0)
    # one seam joint per consecutive pair.
    assert len(new_j) == 2


def test_periodic_backward_direction():
    seed = _periodic_seed()
    delta = _z_translation(10.0)
    _, new_i, new_j = build_periodic_chain(
        seed,
        delta,
        np.linalg.inv(delta),
        _SPECS,
        3,
        "backward",
        [seed],
    )
    assert [i.name for i in new_i] == ["Ring -1", "Ring -2"]
    assert np.isclose(new_i[0].transform.to_array()[2, 3], -10.0)
    assert np.isclose(new_i[1].transform.to_array()[2, 3], -20.0)
    assert len(new_j) == 2


def test_periodic_both_splits_extra_forward_when_odd():
    seed = _periodic_seed()
    delta = _z_translation(10.0)
    _, new_i, _ = build_periodic_chain(
        seed,
        delta,
        np.linalg.inv(delta),
        _SPECS,
        4,
        "both",
        [seed],
    )
    # new_total = 3 → forward (3+1)//2 = 2, backward = 1.
    fwd = [i for i in new_i if "+" in i.name]
    back = [i for i in new_i if "-" in i.name]
    assert len(fwd) == 2
    assert len(back) == 1


def test_periodic_seam_ips_added_to_seed_and_clones():
    seed = _periodic_seed()
    delta = _z_translation(10.0)
    existing, new_i, _ = build_periodic_chain(
        seed,
        delta,
        np.linalg.inv(delta),
        _SPECS,
        3,
        "forward",
        [seed],
    )
    seed_updated = next(i for i in existing if i.id == "seed")
    labels = {ip.label for ip in seed_updated.interface_points}
    assert "seam0:5p" in labels and "seam0:3p" in labels
    # the non-seam base IP is preserved.
    assert "front" in labels
    # every clone carries both seam connectors too.
    for clone in new_i:
        clabels = {ip.label for ip in clone.interface_points}
        assert "seam0:5p" in clabels and "seam0:3p" in clabels


def test_periodic_stale_seam_ips_replaced():
    # seed already has stale seam IPs from a prior polymerize.
    seed = _periodic_seed(
        ips=[
            InterfacePoint(
                label="seam0:5p",
                position=Vec3(x=1.0, y=1.0, z=1.0),
                normal=Vec3(x=0.0, y=0.0, z=1.0),
                connection_type=ConnectionType.COVALENT,
            ),
            InterfacePoint(
                label="keep",
                position=Vec3(x=0.0, y=0.0, z=0.0),
                normal=Vec3(x=1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
            ),
        ]
    )
    delta = _z_translation(10.0)
    existing, _, _ = build_periodic_chain(
        seed,
        delta,
        np.linalg.inv(delta),
        _SPECS,
        2,
        "forward",
        [seed],
    )
    seed_updated = next(i for i in existing if i.id == "seed")
    seam5 = [ip for ip in seed_updated.interface_points if ip.label == "seam0:5p"]
    assert len(seam5) == 1  # not duplicated
    # the fresh seam IP wins — position is the spec's, not the stale (1,1,1).
    assert np.isclose(seam5[0].position.z, 0.0)
    assert {ip.label for ip in seed_updated.interface_points} >= {
        "keep",
        "seam0:5p",
        "seam0:3p",
    }


def test_periodic_joint_wiring_and_labels():
    seed = _periodic_seed()
    delta = _z_translation(10.0)
    existing, new_i, new_j = build_periodic_chain(
        seed,
        delta,
        np.linalg.inv(delta),
        _SPECS,
        3,
        "forward",
        [seed],
    )
    seed_id = next(i for i in existing if i.id == "seed").id
    # forward: seed → f1, f1 → f2.
    assert new_j[0].instance_a_id == seed_id
    assert new_j[0].instance_b_id == new_i[0].id
    assert new_j[1].instance_a_id == new_i[0].id
    assert new_j[1].instance_b_id == new_i[1].id
    for j in new_j:
        assert j.joint_type == "rigid"
        assert j.connector_a_label == "seam0:3p"
        assert j.connector_b_label == "seam0:5p"
        # uniform mate frame captured from the first consecutive pair.
        assert j.mate_relative_transform is not None


def test_periodic_originals_untouched():
    seed = _periodic_seed()
    other = _other()
    delta = _z_translation(10.0)
    existing, _, _ = build_periodic_chain(
        seed,
        delta,
        np.linalg.inv(delta),
        _SPECS,
        3,
        "forward",
        [seed, other],
    )
    # the seed object passed in is not mutated in place.
    assert {ip.label for ip in seed.interface_points} == {"front"}
    # the unrelated instance is passed through by reference, unchanged.
    passed_other = next(i for i in existing if i.id == "other")
    assert passed_other is other
