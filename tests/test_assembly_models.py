"""
Phase 1 tests — Assembly data models.

Validates that every new assembly model serialises/deserialises correctly,
that the PartSource discriminated union works, and that AssemblyState mirrors
DesignState behaviour (undo, redo, snapshot, get_or_create).
"""

from __future__ import annotations
from tests._assembly_compat import v1_instances


import pytest

from backend.core.models import (
    Assembly,
    AssemblyJoint,
    DesignMetadata,
    Mat4x4,
    PartInstance,
    PartLibrary,
    PartLibraryEntry,
    PartSourceFile,
    PartSourceInline,
)
from backend.api import assembly_state


# ── Helpers ───────────────────────────────────────────────────────────────────


def _minimal_design_dict() -> dict:
    """Return the smallest valid Design dict (no helices, no strands)."""
    from backend.core.models import Design

    return Design().to_dict()


# ── PartSource discriminated union ────────────────────────────────────────────


def test_part_source_inline_type():
    from backend.core.models import Design

    src = PartSourceInline(design=Design())
    assert src.type == "inline"
    d = src.model_dump()
    assert d["type"] == "inline"
    assert "design" in d


def test_part_source_file_type():
    src = PartSourceFile(path="foo/bar.nadoc")
    assert src.type == "file"
    assert src.sha256 is None
    d = src.model_dump()
    assert d["type"] == "file"
    assert d["path"] == "foo/bar.nadoc"


def test_part_source_file_with_hash():
    src = PartSourceFile(path="x.nadoc", sha256="abc123")
    assert src.sha256 == "abc123"


def test_part_source_inline_roundtrip():
    from backend.core.models import Design

    src = PartSourceInline(design=Design())
    raw = src.model_dump()
    from backend.core.models import PartSource
    from pydantic import TypeAdapter

    ta = TypeAdapter(PartSource)
    restored = ta.validate_python(raw)
    assert restored.type == "inline"


def test_part_source_file_roundtrip():
    src = PartSourceFile(path="a.nadoc", sha256="deadbeef")
    raw = src.model_dump()
    from backend.core.models import PartSource
    from pydantic import TypeAdapter

    ta = TypeAdapter(PartSource)
    restored = ta.validate_python(raw)
    assert restored.type == "file"
    assert restored.path == "a.nadoc"
    assert restored.sha256 == "deadbeef"


# ── PartInstance ──────────────────────────────────────────────────────────────


def test_part_instance_defaults():
    from backend.core.models import Design

    inst = PartInstance(source=PartSourceInline(design=Design()))
    assert inst.name == "Part"
    assert inst.mode == "flexible"
    assert inst.visible is True
    assert inst.joint_states == {}
    assert inst.base_transform is None
    # Default transform is identity
    assert inst.transform.values == [
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
    ]


def test_part_instance_json_roundtrip():
    inst = PartInstance(
        name="Arm",
        source=PartSourceFile(path="arm.nadoc", sha256="ff00"),
        mode="rigid",
        visible=False,
        joint_states={"joint-1": 1.5708},
    )
    raw = inst.model_dump_json()
    restored = PartInstance.model_validate_json(raw)
    assert restored.name == "Arm"
    assert restored.mode == "rigid"
    assert restored.visible is False
    assert restored.joint_states == {"joint-1": 1.5708}
    assert restored.source.type == "file"


def test_part_instance_base_transform():
    from backend.core.models import Design

    t = Mat4x4(values=[1, 0, 0, 5, 0, 1, 0, 3, 0, 0, 1, 0, 0, 0, 0, 1])
    inst = PartInstance(
        source=PartSourceInline(design=Design()),
        base_transform=t,
    )
    assert inst.base_transform is not None
    assert inst.base_transform.values[3] == 5.0  # tx in row-major


# ── AssemblyJoint ─────────────────────────────────────────────────────────────


def test_assembly_joint_defaults():
    joint = AssemblyJoint(instance_b_id="inst-2")
    assert joint.joint_type == "revolute"
    assert joint.instance_a_id is None
    assert joint.current_value == 0.0
    assert joint.min_limit is None
    assert joint.max_limit is None
    assert joint.axis_direction == [0.0, 0.0, 1.0]


def test_assembly_joint_roundtrip():
    joint = AssemblyJoint(
        name="Hinge",
        joint_type="revolute",
        instance_a_id="inst-1",
        instance_b_id="inst-2",
        axis_origin=[1.0, 2.0, 3.0],
        axis_direction=[0.0, 1.0, 0.0],
        current_value=0.785,
        min_limit=-1.57,
        max_limit=1.57,
    )
    raw = joint.model_dump_json()
    restored = AssemblyJoint.model_validate_json(raw)
    assert restored.name == "Hinge"
    assert restored.current_value == pytest.approx(0.785)
    assert restored.min_limit == pytest.approx(-1.57)
    assert restored.axis_origin == [1.0, 2.0, 3.0]


# ── PartLibrary ───────────────────────────────────────────────────────────────


def test_part_library_entry_roundtrip():
    entry = PartLibraryEntry(
        name="Base origami",
        path="/designs/base.nadoc",
        sha256="aabbcc",
        tags=["honeycomb", "validated"],
    )
    raw = entry.model_dump()
    restored = PartLibraryEntry.model_validate(raw)
    assert restored.name == "Base origami"
    assert restored.tags == ["honeycomb", "validated"]


def test_part_library_empty():
    lib = PartLibrary()
    assert lib.entries == []
    assert PartLibrary.model_validate(lib.model_dump()).entries == []


# ── Assembly ──────────────────────────────────────────────────────────────────


def test_assembly_defaults():
    a = Assembly()
    assert a.instances == []
    assert a.joints == []
    assert a.assembly_helices == []
    assert a.assembly_strands == []
    assert a.feature_log == []
    assert a.feature_log_cursor == -1


def test_assembly_json_roundtrip():
    a = Assembly(metadata=DesignMetadata(name="Test Assembly"))
    text = a.to_json()
    restored = Assembly.from_json(text)
    assert restored.metadata.name == "Test Assembly"
    assert restored.instances == []


def test_assembly_dict_roundtrip():
    a = Assembly()
    restored = Assembly.from_dict(a.to_dict())
    assert restored.id == a.id


def test_assembly_with_inline_instance():
    from backend.core.models import Design

    inst = PartInstance(
        name="Part A",
        source=PartSourceInline(design=Design()),
    )
    a = Assembly(instances=[inst])
    text = a.to_json()
    restored = Assembly.from_json(text)
    assert len(restored.instances) == 1
    assert restored.instances[0].name == "Part A"
    assert restored.instances[0].source.type == "inline"


def test_assembly_with_file_instance():
    inst = PartInstance(
        name="Part B",
        source=PartSourceFile(path="designs/part_b.nadoc"),
    )
    a = Assembly(instances=[inst])
    restored = Assembly.from_json(a.to_json())
    assert restored.instances[0].source.type == "file"
    assert restored.instances[0].source.path == "designs/part_b.nadoc"


def test_assembly_with_joint():
    joint = AssemblyJoint(
        name="Hinge",
        instance_b_id="inst-xyz",
        current_value=0.5,
    )
    a = Assembly(joints=[joint])
    restored = Assembly.from_json(a.to_json())
    assert len(restored.joints) == 1
    assert restored.joints[0].name == "Hinge"
    assert restored.joints[0].current_value == pytest.approx(0.5)


# ── AssemblyState ─────────────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_assembly_state():
    """Ensure a clean AssemblyState before and after each test."""
    assembly_state.close_session()
    yield
    assembly_state.close_session()


def test_assembly_state_get_or_create():
    a = assembly_state.get_or_create()
    assert isinstance(a, Assembly)
    assert a.instances == []
    # Calling again returns the same instance
    a2 = assembly_state.get_or_create()
    assert a2.id == a.id


def test_assembly_state_get_or_404_raises_when_empty():
    from fastapi import HTTPException

    with pytest.raises(HTTPException) as exc_info:
        assembly_state.get_or_404()
    assert exc_info.value.status_code == 404


def test_assembly_state_set_and_get():
    a = Assembly(metadata=DesignMetadata(name="My Assembly"))
    assembly_state.set_assembly(a)
    retrieved = assembly_state.get_or_404()
    assert retrieved.metadata.name == "My Assembly"


def test_assembly_state_undo_redo():
    a0 = Assembly(metadata=DesignMetadata(name="v0"))
    assembly_state.set_assembly(a0)

    a1 = Assembly(metadata=DesignMetadata(name="v1"))
    assembly_state.set_assembly(a1)

    a2 = Assembly(metadata=DesignMetadata(name="v2"))
    assembly_state.set_assembly(a2)

    assert assembly_state.get_or_404().metadata.name == "v2"

    # Undo → v1
    assembly_state.undo()
    assert assembly_state.get_or_404().metadata.name == "v1"

    # Undo → v0
    assembly_state.undo()
    assert assembly_state.get_or_404().metadata.name == "v0"

    # Undo from initial → 404
    from fastapi import HTTPException

    with pytest.raises(HTTPException):
        assembly_state.undo()

    # Redo → v1
    assembly_state.redo()
    assert assembly_state.get_or_404().metadata.name == "v1"


def test_assembly_state_snapshot_and_silent():
    a = Assembly(metadata=DesignMetadata(name="base"))
    assembly_state.set_assembly(a)
    assembly_state.snapshot()

    modified = a.model_copy(update={"metadata": DesignMetadata(name="modified")})
    assembly_state.set_assembly_silent(modified)
    assert assembly_state.get_or_404().metadata.name == "modified"

    assembly_state.undo()
    assert assembly_state.get_or_404().metadata.name == "base"


def test_assembly_state_undo_depth():
    # First set: _active_assembly was None, so nothing is pushed to history.
    assembly_state.set_assembly(Assembly())
    assert assembly_state.undo_depth() == 0
    # Second set: prior assembly pushed onto history.
    assembly_state.set_assembly(Assembly())
    assert assembly_state.undo_depth() == 1
    assembly_state.undo()
    assert assembly_state.redo_depth() == 1


def test_assembly_state_clear_history():
    assembly_state.set_assembly(Assembly())
    assembly_state.set_assembly(Assembly())
    assert assembly_state.undo_depth() >= 1
    assembly_state.clear_history()
    assert assembly_state.undo_depth() == 0
    assert assembly_state.redo_depth() == 0


def test_design_state_unaffected_by_assembly():
    """Assembly state mutations must not touch the design undo stack."""
    from backend.api import state as design_state
    from backend.core.models import Design

    design_state.close_session()
    d = Design()
    design_state.set_design(d)
    pre_depth = design_state.undo_depth()

    # Many assembly mutations
    for _ in range(5):
        assembly_state.set_assembly(Assembly())

    assert design_state.undo_depth() == pre_depth
    design_state.close_session()


# ── Adaptive undo cap (Phase 1d: project_path_to_thousands.md) ────────────────


def _make_assembly_with_n_instances(n: int, name: str = "v") -> Assembly:
    """Build an Assembly with ``n`` cheap PartInstances for cap tests."""
    from backend.core.models import Design

    src = PartSourceInline(design=Design())
    instances = [PartInstance(source=src) for _ in range(n)]
    return Assembly(
        metadata=DesignMetadata(name=name),
        instances=instances,
    )


def test_undo_cap_formula_small_assembly_keeps_baseline():
    """≤100 instances → full MAX_UNDO_STEPS history."""
    cap_empty = assembly_state._undo_cap_for(_make_assembly_with_n_instances(0))
    cap_small = assembly_state._undo_cap_for(_make_assembly_with_n_instances(100))
    assert cap_empty == assembly_state.MAX_UNDO_STEPS
    assert cap_small == assembly_state.MAX_UNDO_STEPS


def test_undo_cap_formula_shrinks_with_size():
    """Cap shrinks ~1 slot per 50 instances above 100; floored at 5."""
    # n=200 → 50 - 200//50 = 50 - 4 = 46
    assert assembly_state._undo_cap_for(_make_assembly_with_n_instances(200)) == 46
    # n=500 → 50 - 10 = 40
    assert assembly_state._undo_cap_for(_make_assembly_with_n_instances(500)) == 40
    # n=2000 → 50 - 40 = 10
    assert assembly_state._undo_cap_for(_make_assembly_with_n_instances(2000)) == 10
    # n=5000 → 50 - 100 = -50 → floored at 5
    assert assembly_state._undo_cap_for(_make_assembly_with_n_instances(5000)) == 5


def test_undo_cap_enforced_for_large_assembly():
    """Pushing >cap mutations of a large assembly must trim oldest entries."""
    big = _make_assembly_with_n_instances(2000, name="big_v0")
    expected_cap = assembly_state._undo_cap_for(big)
    assert expected_cap == 10  # sanity

    # Prime the active assembly so subsequent set_assembly() calls push to history.
    assembly_state.set_assembly(big)
    assert assembly_state.undo_depth() == 0  # first push doesn't snapshot

    # Push (expected_cap + 5) more mutations.
    for i in range(expected_cap + 5):
        assembly_state.set_assembly(
            _make_assembly_with_n_instances(2000, name=f"big_v{i + 1}")
        )

    # Depth must be capped, not the baseline 50.
    assert assembly_state.undo_depth() == expected_cap
    assert assembly_state.undo_depth() < assembly_state.MAX_UNDO_STEPS


def test_undo_cap_default_for_small_assembly_unchanged():
    """Small assemblies still get the full 50-deep history (regression)."""
    a = Assembly(metadata=DesignMetadata(name="seed"))
    assembly_state.set_assembly(a)
    # Push 60 small mutations.
    for i in range(60):
        assembly_state.set_assembly(Assembly(metadata=DesignMetadata(name=f"v{i}")))
    # Capped at MAX_UNDO_STEPS by the deque maxlen.
    assert assembly_state.undo_depth() == assembly_state.MAX_UNDO_STEPS


# ── Wire-format v2 — Phase 2a + Phase 5 expand step ───────────────────────────


def _shift_transform(dx: float, dy: float, dz: float) -> Mat4x4:
    """Return a Mat4x4 representing a pure translation."""
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


def test_part_instance_compact_dict_round_trip_minimal():
    """Default-only instance round-trips via compact dict + omits all default fields."""
    inst = PartInstance(
        id="inst-1",
        source=PartSourceFile(path="arm.nadoc"),
    )
    d = inst.to_compact_dict()
    # Defaults omitted — only id, source, t12 present.
    assert set(d.keys()) == {"id", "source", "t12"}
    assert d["id"] == "inst-1"
    assert len(d["t12"]) == 12
    # Identity transform's top 3 rows in row-major order.
    assert d["t12"] == [
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
    ]
    restored = PartInstance.from_compact_dict(d)
    assert restored.id == inst.id
    assert restored.source.path == "arm.nadoc"
    assert restored.transform.values == inst.transform.values
    assert restored.mode == "flexible"
    assert restored.visible is True
    assert restored.representation == "full"


def test_part_instance_compact_dict_round_trip_full_override():
    """Non-default fields are emitted and round-trip exactly."""
    transform = _shift_transform(5.0, -2.0, 0.5)
    inst = PartInstance(
        id="inst-2",
        name="Arm B",
        source=PartSourceFile(path="arm.nadoc"),
        transform=transform,
        mode="rigid",
        visible=False,
        representation="cylinders",
        fixed=True,
        allow_part_joints=True,
        joint_states={"j-1": 1.2345},
    )
    d = inst.to_compact_dict()
    # Compact pack the transform: row-major top 3 rows, translation in cols 3/7/11.
    assert d["t12"][3] == 5.0
    assert d["t12"][7] == -2.0
    assert d["t12"][11] == 0.5
    # All non-default fields present.
    for key in (
        "name",
        "mode",
        "visible",
        "representation",
        "fixed",
        "allow_part_joints",
        "joint_states",
    ):
        assert key in d, f"expected {key!r} in compact dict"

    restored = PartInstance.from_compact_dict(d)
    assert restored.name == "Arm B"
    assert restored.mode == "rigid"
    assert restored.visible is False
    assert restored.representation == "cylinders"
    assert restored.fixed is True
    assert restored.allow_part_joints is True
    assert restored.joint_states == {"j-1": pytest.approx(1.2345)}
    # Transform values restored exactly (last row is the implicit [0,0,0,1]).
    assert restored.transform.values == transform.values


def test_part_instance_compact_dict_via_src_key():
    """A compact dict carrying ``src_key`` resolves the source from the dedup map."""
    inst = PartInstance(
        id="inst-3",
        source=PartSourceFile(path="arm.nadoc"),
        transform=_shift_transform(3, 0, 0),
    )
    sources = {"f:arm.nadoc:": inst.source.model_dump(mode="json")}
    d = inst.to_compact_dict(src_key="f:arm.nadoc:")
    assert "source" not in d
    assert d["src_key"] == "f:arm.nadoc:"
    restored = PartInstance.from_compact_dict(d, sources=sources)
    assert restored.id == "inst-3"
    assert restored.source.path == "arm.nadoc"
    assert restored.transform.values[3] == pytest.approx(3.0)


def test_assembly_to_json_writes_v1_and_v2_co_present():
    """``Assembly.to_json`` includes both the legacy and the v2 sections so old
    readers keep working alongside new readers (Phase 5 expand step)."""
    a = Assembly(metadata=DesignMetadata(name="Dual"))
    a.instances.append(
        PartInstance(
            id="i1",
            source=PartSourceFile(path="arm.nadoc"),
            transform=_shift_transform(1, 2, 3),
        )
    )
    a.instances.append(
        PartInstance(
            id="i2",
            source=PartSourceFile(path="arm.nadoc"),  # same key as i1 → dedup
            transform=_shift_transform(4, 5, 6),
        )
    )
    a.instances.append(
        PartInstance(
            id="i3",
            source=PartSourceFile(path="leg.nadoc"),
            transform=_shift_transform(7, 8, 9),
        )
    )
    text = a.to_json()
    import json as _json

    payload = _json.loads(text)
    # Phase 5 contract: v1 ``instances`` field dropped on write.  Only v2
    # fields land in new saves.  v1 read path is preserved for legacy
    # ``.nass`` files — covered by test_assembly_from_json_falls_back_to_v1_for_legacy_payloads.
    assert "instances" not in payload
    # v2 fields present.
    assert payload["format_version"] == 2
    assert "sources" in payload
    assert "instances_v2" in payload
    # arm.nadoc deduplicated → 2 unique sources for 3 instances.
    assert len(payload["sources"]) == 2
    assert len(payload["instances_v2"]) == 3
    # Expanded v1-shape via the compat helper still works.
    assert len(v1_instances(payload)) == 3
    assert v1_instances(payload)[0]["transform"]["values"][3] == pytest.approx(1.0)
    # Compact dict carries src_key, not inline source.
    for compact in payload["instances_v2"]:
        assert "src_key" in compact
        assert "source" not in compact
        assert len(compact["t12"]) == 12


def test_assembly_from_json_prefers_v2_when_both_present():
    """``Assembly.from_json`` uses the v2 fields when a synthetically-constructed
    payload carries BOTH v1 and v2 fields (e.g. an upgrade-in-progress save).

    Post Phase 5 contract, new writes are v2-only — but the reader still
    must prefer v2 over any stale v1 if both are present in input data.
    """
    a = Assembly(metadata=DesignMetadata(name="V2Pref"))
    a.instances.append(
        PartInstance(
            id="i1",
            source=PartSourceFile(path="arm.nadoc"),
            transform=_shift_transform(11, 12, 13),
        )
    )
    import json as _json

    payload = _json.loads(a.to_json())
    # Inject a fake v1 ``instances`` block with WRONG transform data, to
    # confirm the reader prefers v2 over v1 when both are present.
    payload["instances"] = [
        {
            "id": "i1",
            "name": "Part",
            "source": {"type": "file", "path": "arm.nadoc"},
            "transform": {
                "values": [1, 0, 0, -1, 0, 1, 0, -1, 0, 0, 1, -1, 0, 0, 0, 1]
            },
        }
    ]
    restored = Assembly.from_json(_json.dumps(payload))
    # v2 path won → transform comes from instances_v2, not the injected v1.
    assert restored.instances[0].transform.values[3] == pytest.approx(11.0)
    assert restored.instances[0].transform.values[7] == pytest.approx(12.0)
    assert restored.instances[0].transform.values[11] == pytest.approx(13.0)


def test_assembly_from_json_falls_back_to_v1_for_legacy_payloads():
    """A payload without ``format_version`` / ``instances_v2`` still loads via the
    legacy v1 path."""
    import json as _json

    a = Assembly(metadata=DesignMetadata(name="Legacy"))
    a.instances.append(
        PartInstance(
            id="legacy-i1",
            source=PartSourceFile(path="arm.nadoc"),
            transform=_shift_transform(2, 4, 6),
        )
    )
    # Build a v1-only payload by hand: strip v2 keys.
    legacy_dict = a.model_dump()  # pure v1 — no format_version, no sources
    assert "format_version" not in legacy_dict
    legacy_text = _json.dumps(legacy_dict)
    restored = Assembly.from_json(legacy_text)
    assert restored.instances[0].id == "legacy-i1"
    assert restored.instances[0].transform.values[3] == pytest.approx(2.0)


def test_assembly_v2_save_load_round_trips_through_disk(tmp_path):
    """An Assembly saved via to_json + reloaded via from_json preserves every
    field through the dual-format wire shape (full round-trip)."""
    a = Assembly(metadata=DesignMetadata(name="DiskRT"))
    for i, dz in enumerate([0.0, 1.5, -2.7]):
        a.instances.append(
            PartInstance(
                id=f"i{i}",
                name=f"Part {i}",
                source=PartSourceFile(path="arm.nadoc"),
                transform=_shift_transform(0, 0, dz),
                mode="rigid" if i == 1 else "flexible",
                visible=(i != 2),
            )
        )
    a.joints.append(
        AssemblyJoint(
            id="j1",
            joint_type="revolute",
            instance_a_id="i0",
            instance_b_id="i1",
            axis_origin=[0, 0, 0],
            axis_direction=[0, 0, 1],
            current_value=0.5,
        )
    )

    path = tmp_path / "rt.nass"
    path.write_text(a.to_json(), encoding="utf-8")
    restored = Assembly.from_json(path.read_text(encoding="utf-8"))

    assert restored.metadata.name == "DiskRT"
    assert len(restored.instances) == 3
    assert restored.instances[1].mode == "rigid"
    assert restored.instances[2].visible is False
    assert restored.instances[2].transform.values[11] == pytest.approx(-2.7)
    # Joint state survives.
    assert restored.joints[0].current_value == pytest.approx(0.5)


def test_decode_assembly_snapshot_round_trips_v2():
    """encode_assembly_snapshot / decode_assembly_snapshot uses the dual-format
    payload (v2 round-trips losslessly)."""
    from backend.api.assembly_state import (
        encode_assembly_snapshot,
        decode_assembly_snapshot,
    )

    a = Assembly(metadata=DesignMetadata(name="Snap"))
    a.instances.append(
        PartInstance(
            id="snap-i1",
            source=PartSourceFile(path="arm.nadoc"),
            transform=_shift_transform(0.1, 0.2, 0.3),
            mode="rigid",
        )
    )
    payload, raw_len = encode_assembly_snapshot(a)
    assert payload != ""
    assert raw_len > 0
    restored = decode_assembly_snapshot(payload)
    assert restored.instances[0].id == "snap-i1"
    assert restored.instances[0].mode == "rigid"
    assert restored.instances[0].transform.values[3] == pytest.approx(0.1)
