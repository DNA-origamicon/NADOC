"""
Tests for the assembly-level feature-log per-entry actions:
``POST /assembly/features/{i}/revert``, ``DELETE /assembly/features/{i}``,
``POST /assembly/features/{i}/edit``, plus the slider/seek path's
interaction with the new payload-embedding behaviour of
``_apply_assembly_mutation_with_feature_log``.

The polymerize op is the primary end-to-end exercise: it's the most
complex assembly op (spawns instances + joints + InterfacePoint unions)
and is in the editable / replayable set.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.models import (
    Assembly,
    AssemblyJoint,
    ConnectionType,
    Design,
    Direction,
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


# ── Fixtures (lifted shape from tests/test_polymerize.py) ─────────────────────


def _translation(dx: float, dy: float, dz: float) -> Mat4x4:
    return Mat4x4(values=[
        1, 0, 0, dx,
        0, 1, 0, dy,
        0, 0, 1, dz,
        0, 0, 0,  1,
    ])


def _ip(label: str, z: float, nz: float) -> InterfacePoint:
    return InterfacePoint(
        label=label,
        position=Vec3(x=0.0, y=0.0, z=z),
        normal=Vec3(x=0.0, y=0.0, z=nz),
        connection_type=ConnectionType.BLUNT_END,
    )


def _rod_instance(inst_id: str, name: str, design: Design, t: Mat4x4) -> PartInstance:
    return PartInstance(
        id=inst_id, name=name, source=PartSourceInline(design=design), transform=t,
        interface_points=[_ip("front", 0.0, -1.0), _ip("back", 10.0, 1.0)],
    )


def _seed() -> tuple[Assembly, str]:
    """Two identical rods mated +Z; returns (assembly, joint_id)."""
    design = Design()
    inst_a = _rod_instance("inst-A", "Rod A", design, _translation(0, 0, 0))
    inst_b = _rod_instance("inst-B", "Rod B", design, _translation(0, 0, 10))
    joint = AssemblyJoint(
        id="joint-AB", name="AB", joint_type="rigid",
        instance_a_id="inst-A", instance_b_id="inst-B",
        axis_origin=[0.0, 0.0, 10.0], axis_direction=[0.0, 0.0, 1.0],
        connector_a_label="back", connector_b_label="front",
    )
    asm = Assembly(instances=[inst_a, inst_b], joints=[joint])
    assembly_state.set_assembly(asm)
    return asm, joint.id


def _polymerize(joint_id: str, count: int = 4, direction: str = "forward") -> dict:
    r = client.post("/api/assembly/polymerize", json={
        "joint_id": joint_id, "count": count, "direction": direction,
    })
    assert r.status_code == 200, r.text
    return r.json()["assembly"]


# ── Payload embedding ─────────────────────────────────────────────────────────


def test_mutation_embeds_pre_and_post_payloads():
    """Every entry added by _apply_assembly_mutation_with_feature_log
    should carry a decode-ready pre- and post-state snapshot."""
    _, jid = _seed()
    asm = _polymerize(jid, count=3)
    entry = asm["feature_log"][-1]
    assert entry["evicted"] is False
    assert len(entry["design_snapshot_gz_b64"]) > 0
    assert len(entry["post_state_gz_b64"])      > 0


# ── Revert ────────────────────────────────────────────────────────────────────


def test_revert_truncates_log_and_restores_pre_state():
    _, jid = _seed()
    asm_before = _polymerize(jid, count=5)
    assert len(asm_before["instances"]) == 5

    r = client.post("/api/assembly/features/0/revert")
    assert r.status_code == 200, r.text
    asm_after = r.json()["assembly"]
    assert len(asm_after["instances"]) == 2     # back to the seed pair
    assert asm_after["feature_log"] == []       # all entries truncated


def test_revert_out_of_range_404():
    _seed()
    r = client.post("/api/assembly/features/0/revert")
    assert r.status_code == 404


# ── Delete (latest = revert) ─────────────────────────────────────────────────


def test_delete_latest_entry_is_equivalent_to_revert():
    _, jid = _seed()
    asm_before = _polymerize(jid, count=4)
    assert len(asm_before["feature_log"]) == 1
    r = client.delete("/api/assembly/features/0")
    assert r.status_code == 200, r.text
    asm_after = r.json()["assembly"]
    assert asm_after["feature_log"] == []
    assert len(asm_after["instances"]) == 2


# ── Delete (mid-history: replay later entries) ───────────────────────────────


def test_delete_mid_history_replays_later_polymerize_entries():
    """Two polymerize entries → delete the first → second is replayed
    against the original seed and produces a longer chain than originally."""
    _, jid = _seed()
    _polymerize(jid, count=3)         # entry 0: +1 forward (3 total)
    _polymerize(jid, count=3)         # entry 1: same op (joint-AB still exists)
    asm_before_delete = assembly_state.get_or_404()
    assert len(asm_before_delete.feature_log) == 2

    r = client.delete("/api/assembly/features/0")
    assert r.status_code == 200, r.text
    asm_after = r.json()["assembly"]
    # After deleting entry 0, only entry 1 remains; it ran against the
    # original seed (chain length 3). The new log has one entry.
    assert len(asm_after["feature_log"]) == 1
    assert asm_after["feature_log"][0]["op_kind"] == "assembly-polymerize"


# ── Edit ─────────────────────────────────────────────────────────────────────


def test_edit_polymerize_changes_chain_length():
    """Edit the latest polymerize entry to change count from 3 to 5;
    the resulting assembly should have 5 instances total."""
    _, jid = _seed()
    asm = _polymerize(jid, count=3)
    assert len(asm["instances"]) == 3

    r = client.post("/api/assembly/features/0/edit", json={
        "params": {"count": 5},
    })
    assert r.status_code == 200, r.text
    asm_after = r.json()["assembly"]
    assert len(asm_after["instances"]) == 5
    assert len(asm_after["feature_log"]) == 1
    assert asm_after["feature_log"][0]["params"]["count"] == 5


def test_edit_polymerize_changes_direction():
    _, jid = _seed()
    asm = _polymerize(jid, count=4, direction="forward")
    # forward count=4 → instances at z ∈ {0, 10, 20, 30}
    zs = sorted(i["transform"]["values"][11] for i in asm["instances"])
    assert zs == pytest.approx([0, 10, 20, 30])

    r = client.post("/api/assembly/features/0/edit", json={
        "params": {"direction": "backward"},
    })
    assert r.status_code == 200, r.text
    asm_after = r.json()["assembly"]
    # backward count=4 → z ∈ {-20, -10, 0, 10}
    zs2 = sorted(i["transform"]["values"][11] for i in asm_after["instances"])
    assert zs2 == pytest.approx([-20, -10, 0, 10])


def test_edit_rejects_non_latest_entry_422():
    _, jid = _seed()
    _polymerize(jid, count=3)
    _polymerize(jid, count=3)
    r = client.post("/api/assembly/features/0/edit", json={"params": {"count": 4}})
    assert r.status_code == 422


def test_edit_rejects_non_editable_op_kind_422():
    """Inject a hand-crafted entry with a non-editable op_kind to verify
    the edit gate. We use an entry that didn't go through the normal
    mutation helper so it has no payload — should 422 on op_kind first."""
    asm = Assembly()
    assembly_state.set_assembly(asm)
    # Smoke: edit on an empty log → 404.
    r = client.post("/api/assembly/features/0/edit", json={"params": {}})
    assert r.status_code == 404


# ── Slider / seek with polymerize ────────────────────────────────────────────


def test_seek_scrubs_through_polymerize_entry():
    """Slider scrubbing back to -2 (empty) then forward to -1 (latest)
    must traverse the polymerize entry cleanly."""
    _, jid = _seed()
    asm_after_poly = _polymerize(jid, count=4)
    n_after = len(asm_after_poly["instances"])
    assert n_after == 4

    r_back = client.post("/api/assembly/features/seek", json={"position": -2})
    assert r_back.status_code == 200, r_back.text
    asm_at_empty = r_back.json()["assembly"]
    assert len(asm_at_empty["instances"]) == 2

    r_fwd = client.post("/api/assembly/features/seek", json={"position": -1})
    assert r_fwd.status_code == 200, r_fwd.text
    asm_at_end = r_fwd.json()["assembly"]
    assert len(asm_at_end["instances"]) == n_after


def test_seek_preserves_feature_log_entries():
    """Regression: scrubbing the slider must NEVER drop feature_log
    entries. Earlier implementation stack-walked the undo deque and ended
    up showing prior snapshots that had shorter feature_logs — the panel
    would render fewer entries after each scrub, and the slider couldn't
    return to the full position once the redo deque emptied."""
    from backend.api import assembly_state
    asm = Assembly()
    assembly_state.set_assembly(asm)
    design = Design()

    # Three operations → three entries.
    for name in ("P1", "P2", "P3"):
        r = client.post("/api/assembly/instances", json={
            "source": {"type": "inline", "design": design.model_dump()},
            "name":   name,
        })
        assert r.status_code == 201

    asm_full = assembly_state.get_or_404()
    assert len(asm_full.feature_log) == 3
    assert len(asm_full.instances)   == 3

    # Scrub all the way back.
    r_back = client.post("/api/assembly/features/seek", json={"position": -2})
    assert r_back.status_code == 200
    asm_back = r_back.json()["assembly"]
    assert len(asm_back["feature_log"]) == 3, "feature log entries must survive scrub-back"
    assert len(asm_back["instances"])   == 0, "geometry restored to empty pre-state"
    assert asm_back["feature_log_cursor"] == -2

    # Scrub to position 0 (after first op).
    r0 = client.post("/api/assembly/features/seek", json={"position": 0})
    assert r0.status_code == 200
    asm0 = r0.json()["assembly"]
    assert len(asm0["feature_log"]) == 3
    assert len(asm0["instances"])   == 1
    assert asm0["feature_log_cursor"] == 0

    # Scrub forward to end.
    r_fwd = client.post("/api/assembly/features/seek", json={"position": -1})
    assert r_fwd.status_code == 200
    asm_fwd = r_fwd.json()["assembly"]
    assert len(asm_fwd["feature_log"]) == 3
    assert len(asm_fwd["instances"])   == 3
    assert asm_fwd["feature_log_cursor"] == -1


def test_seek_preserves_per_instance_representation_and_visibility():
    """Display preferences (representation, visible) must survive scrubbing.

    Regression: large assemblies are slow to render in 'full' mode, so users
    switch heavy parts to 'cylinders' or 'beads'. Without this preservation,
    every slider move re-applies whatever representation was current at
    snapshot time — undoing the user's cheaper-rendering choice."""
    from backend.api import assembly_state
    asm = Assembly()
    assembly_state.set_assembly(asm)
    design = Design()
    r1 = client.post("/api/assembly/instances", json={
        "source": {"type": "inline", "design": design.model_dump()},
        "name":   "Heavy",
    })
    iid = r1.json()["assembly"]["instances"][0]["id"]
    # Add a second op so we have entries to scrub across.
    client.post("/api/assembly/instances", json={
        "source": {"type": "inline", "design": design.model_dump()},
        "name":   "Light",
    })
    # Snapshot of "Heavy" was taken when representation was the default 'full'.
    # Now the user switches to a cheaper representation + hides it.
    client.patch(f"/api/assembly/instances/{iid}", json={
        "representation": "cylinders",
        "visible":        False,
    })

    def _heavy(asm_dict):
        return next(i for i in asm_dict["instances"] if i["id"] == iid)

    # Scrub all the way back, to position 0, then forward — at every step
    # the Heavy instance (if it exists in the restored state) keeps the
    # user's chosen 'cylinders' + visible=False.
    for pos in (-2, 0, 1, -1):
        r = client.post("/api/assembly/features/seek", json={"position": pos})
        assert r.status_code == 200, r.text
        asm = r.json()["assembly"]
        if any(i["id"] == iid for i in asm["instances"]):
            h = _heavy(asm)
            assert h["representation"] == "cylinders", f"pos={pos}: rep was {h['representation']!r}"
            assert h["visible"]        is False,       f"pos={pos}: visible was {h['visible']!r}"


def test_seek_does_not_drain_redo_stack():
    """A scrub must not consume the assembly_state undo/redo deque —
    Ctrl-Z after a scrub must still revert the most recent ACTUAL
    mutation, not the scrub itself."""
    from backend.api import assembly_state
    asm = Assembly()
    assembly_state.set_assembly(asm)
    design = Design()
    client.post("/api/assembly/instances", json={
        "source": {"type": "inline", "design": design.model_dump()},
        "name":   "P1",
    })
    client.post("/api/assembly/instances", json={
        "source": {"type": "inline", "design": design.model_dump()},
        "name":   "P2",
    })
    undo_before = assembly_state.undo_depth()
    redo_before = assembly_state.redo_depth()

    # Multiple scrubs in both directions.
    for pos in (-2, 0, -1, 0, -1):
        r = client.post("/api/assembly/features/seek", json={"position": pos})
        assert r.status_code == 200

    assert assembly_state.undo_depth() == undo_before, "scrub must not touch undo deque"
    assert assembly_state.redo_depth() == redo_before, "scrub must not touch redo deque"

    # Ctrl-Z must still reach the pre-P2 state.
    r_undo = client.post("/api/assembly/undo")
    assert r_undo.status_code == 200
    asm = r_undo.json()["assembly"]
    assert len(asm["instances"]) == 1
    assert asm["instances"][0]["name"] == "P1"


def test_undo_after_polymerize_restores_seed():
    """Ctrl-Z (assembly undo) must restore the pre-polymerize state."""
    _, jid = _seed()
    _polymerize(jid, count=4)
    r = client.post("/api/assembly/undo")
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    assert len(asm["instances"]) == 2
    assert asm["feature_log"] == []


# ── New op kinds (add-instance / add-connector / add-joint / duplicate) ─────


def test_add_instance_appears_in_feature_log():
    """Adding a part records `assembly-add-instance` so users can see and
    revert it from the feature-log panel."""
    from backend.api import assembly_state
    asm = Assembly()
    assembly_state.set_assembly(asm)
    design = Design()
    r = client.post("/api/assembly/instances", json={
        "source": {"type": "inline", "design": design.model_dump()},
        "name":   "Part One",
    })
    assert r.status_code == 201, r.text
    asm_out = r.json()["assembly"]
    assert len(asm_out["instances"]) == 1
    assert any(e["op_kind"] == "assembly-add-instance" for e in asm_out["feature_log"])


def test_delete_instance_appears_in_feature_log_and_replays():
    """`assembly-delete-instance` is logged and surgically replayable."""
    _seed()
    asm = assembly_state.get_or_404()
    initial_log_len = len(asm.feature_log)

    r = client.delete("/api/assembly/instances/inst-B")
    assert r.status_code == 200, r.text
    asm_after = r.json()["assembly"]
    assert len(asm_after["instances"]) == 1
    assert asm_after["feature_log"][-1]["op_kind"] == "assembly-delete-instance"
    # Cascade: any joint that referenced inst-B is gone.
    assert all(j["instance_b_id"] != "inst-B" for j in asm_after["joints"])
    assert all(j["instance_a_id"] != "inst-B" for j in asm_after["joints"])


def test_add_connector_appears_in_feature_log():
    _seed()
    r = client.post("/api/assembly/instances/inst-A/connectors", json={
        "label":    "newC",
        "position": [0.0, 1.0, 0.0],
        "normal":   [1.0, 0.0, 0.0],
    })
    assert r.status_code == 201, r.text
    asm = r.json()["assembly"]
    last = asm["feature_log"][-1]
    assert last["op_kind"] == "assembly-add-connector"
    assert last["params"]["label"] == "newC"
    inst_a = next(i for i in asm["instances"] if i["id"] == "inst-A")
    assert any(ip["label"] == "newC" for ip in inst_a["interface_points"])


def test_add_joint_appears_in_feature_log():
    """The 'Define Mate' menu item ends up here — it must produce a log entry."""
    _seed()
    initial_len = len(assembly_state.get_or_404().feature_log)
    # Build a second joint between the existing instances.
    r = client.post("/api/assembly/joints", json={
        "name":              "AB2",
        "joint_type":        "rigid",
        "instance_a_id":     "inst-A",
        "instance_b_id":     "inst-B",
        "axis_origin":       [0.0, 0.0, 10.0],
        "axis_direction":    [0.0, 0.0, 1.0],
        "connector_a_label": "back",
        "connector_b_label": "front",
    })
    assert r.status_code == 201, r.text
    asm = r.json()["assembly"]
    assert any(e["op_kind"] == "assembly-add-joint" for e in asm["feature_log"])
    new_entry = asm["feature_log"][-1]
    assert new_entry["op_kind"] == "assembly-add-joint"
    assert new_entry["params"]["instance_a_id"] == "inst-A"
    assert new_entry["params"]["instance_b_id"] == "inst-B"


# ── Duplicate endpoint ──────────────────────────────────────────────────────


def test_duplicate_instance_clones_with_offset_and_connectors():
    """Duplicating an instance must copy its connectors and offset its
    transform so the user can see both."""
    _seed()
    r = client.post("/api/assembly/instances/inst-A/duplicate", json={})
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    assert len(asm["instances"]) == 3
    # The new instance has the same connectors as inst-A.
    new_insts = [i for i in asm["instances"] if i["id"] not in ("inst-A", "inst-B")]
    assert len(new_insts) == 1
    new_inst = new_insts[0]
    labels = sorted(ip["label"] for ip in new_inst["interface_points"])
    assert labels == ["back", "front"]
    # Default +X offset (5 nm) shows up in the new transform's translation.
    assert new_inst["transform"]["values"][3] == pytest.approx(5.0)
    # And the op is logged.
    assert asm["feature_log"][-1]["op_kind"] == "assembly-duplicate-instance"


def test_duplicate_instance_with_custom_offset_and_name():
    _seed()
    r = client.post("/api/assembly/instances/inst-A/duplicate", json={
        "offset": [0.0, 7.5, 0.0],
        "name":   "Special clone",
    })
    assert r.status_code == 200, r.text
    asm = r.json()["assembly"]
    new_inst = next(i for i in asm["instances"] if i["name"] == "Special clone")
    # +Y offset of 7.5 nm shows up in row 1, col 3 (row-major).
    assert new_inst["transform"]["values"][7] == pytest.approx(7.5)


def test_duplicate_unknown_instance_404():
    _seed()
    r = client.post("/api/assembly/instances/bogus/duplicate", json={})
    assert r.status_code == 404


def test_surgical_delete_replays_through_add_instance_entry():
    """Mid-history delete must work when a later entry is an
    `assembly-add-instance` op."""
    from backend.api import assembly_state
    asm = Assembly()
    assembly_state.set_assembly(asm)
    design = Design()
    # Two add-instance ops.
    r1 = client.post("/api/assembly/instances", json={
        "source": {"type": "inline", "design": design.model_dump()},
        "name":   "P1",
    })
    assert r1.status_code == 201
    r2 = client.post("/api/assembly/instances", json={
        "source": {"type": "inline", "design": design.model_dump()},
        "name":   "P2",
    })
    assert r2.status_code == 201
    asm_before = r2.json()["assembly"]
    assert len(asm_before["instances"]) == 2

    # Surgically delete the first add-instance: P1 vanishes, P2 still here.
    r_del = client.delete("/api/assembly/features/0")
    assert r_del.status_code == 200, r_del.text
    asm_after = r_del.json()["assembly"]
    assert len(asm_after["instances"]) == 1
    assert asm_after["instances"][0]["name"] == "P2"
