"""
Tests for the assembly Polymerize Origami feature.

Covers:
  - pure-math helpers in backend.core.assembly_polymer (sources_match,
    compute_chain_transforms, axis transform)
  - POST /assembly/polymerize: forward/backward/both/no-op/error paths,
    connector + joint propagation, and feature-log entry.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.assembly_polymer import (
    _sources_match,
    _split_count,
    compute_chain_transforms,
    transform_joint_axis,
)
from backend.core.models import (
    Assembly,
    AssemblyJoint,
    ConnectionType,
    Design,
    InterfacePoint,
    Mat4x4,
    PartInstance,
    PartSourceInline,
    Vec3,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def _reset():
    assembly_state.close_session()
    yield
    assembly_state.close_session()


# ── Fixtures ──────────────────────────────────────────────────────────────────


def _translation(dx: float, dy: float, dz: float) -> Mat4x4:
    return Mat4x4(values=[
        1, 0, 0, dx,
        0, 1, 0, dy,
        0, 0, 1, dz,
        0, 0, 0,  1,
    ])


def _rod_design() -> Design:
    """Tiny placeholder Design — identity matters via the inline reference."""
    return Design()


def _ip(label: str, z: float, nz: float) -> InterfacePoint:
    return InterfacePoint(
        label=label,
        position=Vec3(x=0.0, y=0.0, z=z),
        normal=Vec3(x=0.0, y=0.0, z=nz),
        connection_type=ConnectionType.BLUNT_END,
    )


def _rod_instance(inst_id: str, name: str, design: Design, t: Mat4x4,
                   ips: list[InterfacePoint] | None = None) -> PartInstance:
    """One rod instance with two InterfacePoints (front + back) by default."""
    return PartInstance(
        id=inst_id,
        name=name,
        source=PartSourceInline(design=design),
        transform=t,
        interface_points=ips if ips is not None else [
            _ip("front", 0.0, -1.0),
            _ip("back", 10.0, 1.0),
        ],
    )


def _seed_two_rod_assembly(joint_type: str = "rigid") -> tuple[Assembly, str]:
    """Two identical inline rods mated back→front along +Z. Returns (assembly, joint_id)."""
    design = _rod_design()
    inst_a = _rod_instance("inst-A", "Rod A", design, _translation(0.0, 0.0, 0.0))
    inst_b = _rod_instance("inst-B", "Rod B", design, _translation(0.0, 0.0, 10.0))
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
    )
    asm = Assembly(instances=[inst_a, inst_b], joints=[joint])
    assembly_state.set_assembly(asm)
    return asm, joint.id


def _seed_two_different_parts_assembly() -> tuple[Assembly, str]:
    design_a = _rod_design()
    design_b = Design()   # separate inline design — DIFFERENT object
    # Touch one of them so the dumps actually differ (the bare Design() dumps
    # are equal, but lattice_type / metadata can differ trivially).
    design_b = design_b.model_copy(update={"lattice_type": "square"})
    inst_a = _rod_instance("inst-A", "Rod A", design_a, _translation(0, 0, 0))
    inst_b = _rod_instance("inst-B", "Rod B", design_b, _translation(0, 0, 10))
    joint = AssemblyJoint(
        id="joint-AB", name="AB", joint_type="rigid",
        instance_a_id="inst-A", instance_b_id="inst-B",
        axis_origin=[0.0, 0.0, 10.0], axis_direction=[0.0, 0.0, 1.0],
        connector_a_label="back", connector_b_label="front",
    )
    asm = Assembly(instances=[inst_a, inst_b], joints=[joint])
    assembly_state.set_assembly(asm)
    return asm, joint.id


# ── Pure-math tests ───────────────────────────────────────────────────────────


def test_sources_match_inline_same_object():
    d = Design()
    a, b = PartSourceInline(design=d), PartSourceInline(design=d)
    assert _sources_match(a, b)


def test_sources_match_inline_different_objects_same_dump():
    a = PartSourceInline(design=Design())
    b = PartSourceInline(design=Design())
    assert _sources_match(a, b)


def test_sources_match_inline_different_dumps():
    a = PartSourceInline(design=Design())
    b = PartSourceInline(design=Design().model_copy(update={"lattice_type": "square"}))
    assert not _sources_match(a, b)


def test_split_count_forward_only():
    assert _split_count(5, "forward") == (3, 0)


def test_split_count_backward_only():
    assert _split_count(5, "backward") == (0, 3)


def test_split_count_both_even():
    # count=6 → 4 new total → 2 forward + 2 backward
    assert _split_count(6, "both") == (2, 2)


def test_split_count_both_odd_extra_goes_forward():
    # count=5 → 3 new total → 2 forward + 1 backward (per documented tie-break)
    assert _split_count(5, "both") == (2, 1)


def test_compute_chain_transforms_forward_steps_evenly():
    # A at origin, B translated +Z by 10. count=4, forward → 2 new instances.
    t_a = _translation(0, 0, 0)
    t_b = _translation(0, 0, 10)
    fwd, back = compute_chain_transforms(t_a, t_b, count=4, direction="forward")
    assert len(fwd) == 2
    assert len(back) == 0
    # First new transform translates by +20 from A; second by +30.
    np.testing.assert_allclose(fwd[0][:3, 3], [0, 0, 20], atol=1e-9)
    np.testing.assert_allclose(fwd[1][:3, 3], [0, 0, 30], atol=1e-9)


def test_compute_chain_transforms_backward_steps_evenly():
    t_a = _translation(0, 0, 0)
    t_b = _translation(0, 0, 10)
    fwd, back = compute_chain_transforms(t_a, t_b, count=4, direction="backward")
    assert len(fwd) == 0
    assert len(back) == 2
    # First backward instance at -10; second at -20.
    np.testing.assert_allclose(back[0][:3, 3], [0, 0, -10], atol=1e-9)
    np.testing.assert_allclose(back[1][:3, 3], [0, 0, -20], atol=1e-9)


def test_transform_joint_axis_rotates_direction_and_translates_origin():
    # 90° rotation around Z + +Y translation.
    rot = np.array([
        [0, -1, 0, 0],
        [1,  0, 0, 5],
        [0,  0, 1, 0],
        [0,  0, 0, 1],
    ], dtype=float)
    new_o, new_d = transform_joint_axis([1.0, 0.0, 0.0], [1.0, 0.0, 0.0], rot)
    np.testing.assert_allclose(new_o, [0.0, 6.0, 0.0], atol=1e-9)
    np.testing.assert_allclose(new_d, [0.0, 1.0, 0.0], atol=1e-9)


# ── API route tests ───────────────────────────────────────────────────────────


def test_polymerize_forward_extends_chain_to_total_count():
    _, jid = _seed_two_rod_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 5, "direction": "forward",
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    assert len(asm["instances"]) == 5
    assert len(asm["joints"]) == 4   # 1 seed + 3 new
    # Forward chain: every new instance translated by +10z relative to the prior one.
    # Validate by sorting instances by their z-translation and checking spacing.
    zs = sorted(inst["transform"]["values"][11] for inst in asm["instances"])
    assert zs == pytest.approx([0, 10, 20, 30, 40])


def test_polymerize_backward_prepends_instances():
    _, jid = _seed_two_rod_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 4, "direction": "backward",
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    assert len(asm["instances"]) == 4
    zs = sorted(inst["transform"]["values"][11] for inst in asm["instances"])
    assert zs == pytest.approx([-20, -10, 0, 10])


def test_polymerize_both_splits_evenly():
    _, jid = _seed_two_rod_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 6, "direction": "both",
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    assert len(asm["instances"]) == 6
    zs = sorted(inst["transform"]["values"][11] for inst in asm["instances"])
    assert zs == pytest.approx([-20, -10, 0, 10, 20, 30])


def test_polymerize_both_with_odd_extra_goes_forward():
    _, jid = _seed_two_rod_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 5, "direction": "both",
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    assert len(asm["instances"]) == 5
    zs = sorted(inst["transform"]["values"][11] for inst in asm["instances"])
    # 3 new = 2 forward + 1 backward (forward gets extra).
    assert zs == pytest.approx([-10, 0, 10, 20, 30])


def test_polymerize_rejects_when_sources_differ_422():
    _, jid = _seed_two_different_parts_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 4, "direction": "forward",
    })
    assert r.status_code == 422, r.text
    assert "identical" in r.text.lower()


def test_polymerize_count_2_is_noop():
    asm_before, jid = _seed_two_rod_assembly()
    n_log_before = len(asm_before.feature_log)
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 2, "direction": "forward",
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    assert len(asm["instances"]) == 2
    assert len(asm["joints"]) == 1
    assert len(asm["feature_log"]) == n_log_before


def test_polymerize_count_below_2_is_400():
    _, jid = _seed_two_rod_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 1, "direction": "forward",
    })
    assert r.status_code == 400


def test_polymerize_copies_connectors_to_new_instances():
    _, jid = _seed_two_rod_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 4, "direction": "forward",
    })
    asm = r.json()["assembly"]
    new_instances = [i for i in asm["instances"] if i["id"] not in ("inst-A", "inst-B")]
    assert len(new_instances) == 2
    for inst in new_instances:
        labels = sorted(ip["label"] for ip in inst["interface_points"])
        assert labels == ["back", "front"]


def test_polymerize_new_joints_preserve_type_and_connector_labels():
    _, jid = _seed_two_rod_assembly(joint_type="rigid")
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 4, "direction": "forward",
    })
    asm = r.json()["assembly"]
    new_joints = [j for j in asm["joints"] if j["id"] != "joint-AB"]
    assert len(new_joints) == 2
    for jt in new_joints:
        assert jt["joint_type"] == "rigid"
        assert jt["connector_a_label"] == "back"
        assert jt["connector_b_label"] == "front"


def test_polymerize_feature_log_entry():
    _, jid = _seed_two_rod_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 3, "direction": "forward",
    })
    asm = r.json()["assembly"]
    assert any(e["op_kind"] == "assembly-polymerize" for e in asm["feature_log"])


def test_polymerize_handles_seed_instances_with_single_connector_each():
    """Regression: Hinge Polys.nass case.

    User-defined connectors typically land one per instance (only the side
    being mated is named).  When polymerize chains those instances, every
    interior copy plays both 'a' and 'b' roles in adjacent joints, so each
    needs BOTH connector labels.  If the polymerizer only carries the
    source-side connector forward, every new joint is broken
    (connector_a_label points at an instance that doesn't have that IP).
    """
    design = _rod_design()
    inst_a = _rod_instance("inst-A", "Rod A", design, _translation(0, 0, 0),
                            ips=[_ip("connector_a", 0.0, -1.0)])
    inst_b = _rod_instance("inst-B", "Rod B", design, _translation(0, 0, 10),
                            ips=[_ip("connector_b", 10.0, 1.0)])
    joint = AssemblyJoint(
        id="joint-AB", name="AB", joint_type="rigid",
        instance_a_id="inst-A", instance_b_id="inst-B",
        axis_origin=[0.0, 0.0, 10.0], axis_direction=[0.0, 0.0, 1.0],
        connector_a_label="connector_a", connector_b_label="connector_b",
    )
    assembly_state.set_assembly(Assembly(instances=[inst_a, inst_b], joints=[joint]))

    r = client.post("/api/assembly/polymerize", json={
        "joint_id": joint.id, "count": 4, "direction": "forward",
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]

    # Every joint's connector_a_label must exist on its instance_a,
    # and connector_b_label on its instance_b.
    by_id = {i["id"]: i for i in asm["instances"]}
    for j in asm["joints"]:
        a_labels = {ip["label"] for ip in by_id[j["instance_a_id"]]["interface_points"]}
        b_labels = {ip["label"] for ip in by_id[j["instance_b_id"]]["interface_points"]}
        assert j["connector_a_label"] in a_labels, (
            f"joint {j['name']} instance_a_id={j['instance_a_id']} is missing "
            f"label {j['connector_a_label']!r} (has {sorted(a_labels)})"
        )
        assert j["connector_b_label"] in b_labels, (
            f"joint {j['name']} instance_b_id={j['instance_b_id']} is missing "
            f"label {j['connector_b_label']!r} (has {sorted(b_labels)})"
        )


def test_polymerize_unknown_joint_404():
    _seed_two_rod_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": "bogus", "count": 3, "direction": "forward",
    })
    assert r.status_code == 404


# ── Pattern polymerization (additional_instance_ids) ─────────────────────────


def _seed_pattern_assembly() -> tuple[Assembly, str]:
    """Two identical rods mated +Z plus a third 'add' part at +X offset
    mated to inst-A (the seed_a side). The third part has a different
    inline design (allowed for additionals — not for the seed pair).
    """
    from backend.core.models import LatticeType
    rod_design = _rod_design()
    add_design = Design(lattice_type=LatticeType.SQUARE)
    inst_a = _rod_instance("inst-A", "Rod A", rod_design, _translation(0, 0, 0))
    inst_b = _rod_instance("inst-B", "Rod B", rod_design, _translation(0, 0, 10))
    # Additional part offset +X from inst-A (so its clones go +X at each chain step).
    inst_c = PartInstance(
        id="inst-C", name="Add C", source=PartSourceInline(design=add_design),
        transform=_translation(5, 0, 0),
        interface_points=[
            InterfacePoint(
                label="left", position=Vec3(x=0.0, y=0.0, z=0.0),
                normal=Vec3(x=-1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
            ),
            InterfacePoint(
                label="right", position=Vec3(x=5.0, y=0.0, z=0.0),
                normal=Vec3(x=1.0, y=0.0, z=0.0),
                connection_type=ConnectionType.BLUNT_END,
            ),
        ],
    )
    seed_joint = AssemblyJoint(
        id="joint-AB", name="AB", joint_type="rigid",
        instance_a_id="inst-A", instance_b_id="inst-B",
        axis_origin=[0.0, 0.0, 10.0], axis_direction=[0.0, 0.0, 1.0],
        connector_a_label="back", connector_b_label="front",
    )
    # Mate between inst-A and inst-C (seed_a level).
    side_joint = AssemblyJoint(
        id="joint-AC", name="AC", joint_type="rigid",
        instance_a_id="inst-A", instance_b_id="inst-C",
        axis_origin=[2.5, 0.0, 0.0], axis_direction=[1.0, 0.0, 0.0],
        connector_a_label="back", connector_b_label="left",
    )
    asm = Assembly(instances=[inst_a, inst_b, inst_c], joints=[seed_joint, side_joint])
    assembly_state.set_assembly(asm)
    return asm, seed_joint.id


def test_polymerize_pattern_clones_additional_at_each_step():
    """Each new chain step also clones the 'to pattern' additional, at the
    same delta^step offset, so its relationship to the chain primary is
    preserved.  Additionals get one MORE clone than primary chain steps so
    the total per pattern member matches the chain length (= count)."""
    _, jid = _seed_pattern_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 4, "direction": "forward",
        "additional_instance_ids": ["inst-C"],
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    # 3 original + 2 new primaries + 3 new add-clones (count-1) = 8
    assert len(asm["instances"]) == 8
    add_clones = [i for i in asm["instances"]
                  if i["id"] not in ("inst-A", "inst-B", "inst-C") and i["name"].startswith("Add C")]
    assert len(add_clones) == 3
    zs = sorted(i["transform"]["values"][11] for i in add_clones)
    # +X offset is preserved (col 3 row 0 = X translation).
    xs = sorted(i["transform"]["values"][3] for i in add_clones)
    assert xs == pytest.approx([5.0, 5.0, 5.0])
    # Each add clone steps by +10 in Z.  count=4 → clones at +10, +20, +30.
    assert zs == pytest.approx([10.0, 20.0, 30.0])


def test_polymerize_pattern_replicates_intra_unit_mate():
    """The (inst-A, inst-C) mate must be replicated at each chain step
    between the matching cloned primary and the matching cloned additional."""
    _, jid = _seed_pattern_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 4, "direction": "forward",
        "additional_instance_ids": ["inst-C"],
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    # Original seed mate (AB), seed-mate chain extensions (+1, +2),
    # original AC mate, and AC replicas (+1, +2, +3). Total: 7 joints.
    assert len(asm["joints"]) == 7
    ac_replicas = [j for j in asm["joints"] if j["name"].startswith("AC ")]
    assert len(ac_replicas) == 3
    # Each replica preserves the original connector labels.
    for j in ac_replicas:
        assert j["connector_a_label"] == "back"
        assert j["connector_b_label"] == "left"


def test_polymerize_pattern_silently_drops_seed_pair_from_additionals():
    """If the user accidentally includes the seed-pair ids in
    additional_instance_ids, those are silently skipped (not double-cloned)."""
    _, jid = _seed_pattern_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 3, "direction": "forward",
        "additional_instance_ids": ["inst-A", "inst-B", "inst-C"],
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    # count=3 → 1 new primary; with inst-C pattern → 2 new add clones
    # (count-1, fixed off-by-one). Original 3 + 1 + 2 = 6 instances.
    assert len(asm["instances"]) == 6


def test_polymerize_pattern_404_on_unknown_additional():
    _, jid = _seed_pattern_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 3, "direction": "forward",
        "additional_instance_ids": ["bogus"],
    })
    assert r.status_code == 404


def test_polymerize_chain_length_applies_to_every_pattern_member():
    """User-reported off-by-one regression: with `count=N` and one
    additional pattern part, the final assembly must contain N total
    primaries AND N total instances of each additional.

    Before this fix, additionals got `count - 1` total (off by one).
    """
    for count in (3, 4, 5):
        assembly_state.close_session()
        _, jid = _seed_pattern_assembly()
        r = client.post("/api/assembly/polymerize", json={
            "joint_id": jid, "count": count, "direction": "forward",
            "additional_instance_ids": ["inst-C"],
        })
        assert r.status_code == 200, r.text
        asm = r.json()["assembly"]
        # Primary chain: seed_a + seed_b + (count-2) new = count instances
        # sharing the seed-pair source. Use the unique source identifier
        # to count chain members.
        primary_instances = [i for i in asm["instances"] if i["name"].startswith("Rod B") or i["id"] in ("inst-A", "inst-B")]
        assert len(primary_instances) == count, (
            f"count={count}: expected {count} primaries, got {len(primary_instances)}"
        )
        # Additional ('Add C' name family): inst-C + (count-1) new = count total.
        add_instances = [i for i in asm["instances"] if i["name"].startswith("Add C") or i["id"] == "inst-C"]
        assert len(add_instances) == count, (
            f"count={count}: expected {count} 'Add C' instances, got {len(add_instances)}"
        )


def test_polymerize_new_clones_default_to_cheap_representation():
    """Polymerize creates many copies of a potentially heavy part. Every
    new clone (primary + pattern additional) defaults to 'cylinders' so
    chain previews don't OOM the browser when each instance is a large
    origami.
    """
    _, jid = _seed_pattern_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 4, "direction": "forward",
        "additional_instance_ids": ["inst-C"],
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    seed_ids = {"inst-A", "inst-B", "inst-C"}
    new_clones = [i for i in asm["instances"] if i["id"] not in seed_ids]
    # count=4 forward: 2 new primaries + 3 add clones (count-1) = 5.
    assert len(new_clones) == 5
    for i in new_clones:
        assert i["representation"] == "cylinders", (
            f"clone {i['name']!r} kept rep {i['representation']!r}; should be 'cylinders'"
        )
    # Original seed instances are untouched.
    seed_a = next(i for i in asm["instances"] if i["id"] == "inst-A")
    assert seed_a["representation"] == "full"


def test_load_auto_downgrades_when_too_many_full_instances(tmp_path):
    """Loading a .nass with > threshold 'full' instances triggers an
    auto-downgrade so the file can be opened on machines without enough
    RAM to render every part at full detail. The notice is surfaced in
    the response so the frontend can toast it.
    """
    from backend.api import assembly_state
    design = _rod_design()
    # 8 instances at 'full' → above the 6-instance threshold.
    insts = []
    for i in range(8):
        insts.append(PartInstance(
            id=f"inst-{i}", name=f"P{i}",
            source=PartSourceInline(design=design),
            transform=_translation(0, 0, i * 10),
            representation="full",
        ))
    asm = Assembly(instances=insts)
    path = tmp_path / "heavy.nass"
    path.write_text(asm.to_json())

    r = client.post("/api/assembly/load", json={"path": str(path)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "notice" in body, "expected an auto-downgrade notice in the response"
    asm_out = body["assembly"]
    reps = {i["representation"] for i in asm_out["instances"]}
    assert reps == {"cylinders"}, f"expected all reps downgraded; got {reps}"


def test_load_does_not_downgrade_when_under_threshold(tmp_path):
    design = _rod_design()
    insts = [
        PartInstance(
            id=f"inst-{i}", name=f"P{i}",
            source=PartSourceInline(design=design),
            transform=_translation(0, 0, i * 10),
            representation="full",
        )
        for i in range(3)
    ]
    asm = Assembly(instances=insts)
    path = tmp_path / "light.nass"
    path.write_text(asm.to_json())

    r = client.post("/api/assembly/load", json={"path": str(path)})
    assert r.status_code == 200, r.text
    body = r.json()
    assert "notice" not in body
    reps = {i["representation"] for i in body["assembly"]["instances"]}
    assert reps == {"full"}, f"under-threshold load must not downgrade; got {reps}"


def test_polymerize_pattern_edit_changes_count_keeps_additionals():
    """Editing a polymerize-with-pattern entry must replay with the
    same additional_instance_ids."""
    _, jid = _seed_pattern_assembly()
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": jid, "count": 3, "direction": "forward",
        "additional_instance_ids": ["inst-C"],
    })
    assert r.status_code == 200
    r2 = client.post("/api/assembly/features/0/edit", json={
        "params": {"count": 5},
    })
    assert r2.status_code == 200, r2.text
    asm = r2.json()["assembly"]
    # count=5 → 3 new primaries + 4 new add clones (count-1) = 7 new
    # instances, plus original 3 = 10.
    assert len(asm["instances"]) == 10
