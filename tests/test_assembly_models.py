"""
Phase 1 tests — Assembly data models.

Validates that every new assembly model serialises/deserialises correctly,
that the PartSource discriminated union works, and that AssemblyState mirrors
DesignState behaviour (undo, redo, snapshot, get_or_create).
"""

from __future__ import annotations

import json

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
        1, 0, 0, 0,
        0, 1, 0, 0,
        0, 0, 1, 0,
        0, 0, 0, 1,
    ]


def test_part_instance_json_roundtrip():
    from backend.core.models import Design
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
    t = Mat4x4(values=[1,0,0,5, 0,1,0,3, 0,0,1,0, 0,0,0,1])
    inst = PartInstance(
        source=PartSourceInline(design=Design()),
        base_transform=t,
    )
    assert inst.base_transform is not None
    assert inst.base_transform.values[3] == 5.0   # tx in row-major


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
    from backend.core.models import Design
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
    pre_depth = len(design_state._history)

    # Many assembly mutations
    for _ in range(5):
        assembly_state.set_assembly(Assembly())

    assert len(design_state._history) == pre_depth
    design_state.close_session()
