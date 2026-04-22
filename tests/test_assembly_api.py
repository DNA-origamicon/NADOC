"""
Phase 2 tests — Assembly CRUD API.

Uses FastAPI TestClient to exercise all assembly endpoints.  Each test resets
both the assembly and design states to prevent cross-contamination.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api.main import app
from backend.core.models import Assembly, AssemblyJoint, DesignMetadata, PartInstance, PartSourceInline

client = TestClient(app)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    """Clean assembly state before and after every test."""
    assembly_state.close_session()
    yield
    assembly_state.close_session()


def _inline_source_dict() -> dict:
    """Return a minimal PartSource dict with type='inline' and an empty Design."""
    from backend.core.models import Design
    return {"type": "inline", "design": Design().to_dict()}


# ── GET /assembly ─────────────────────────────────────────────────────────────

def test_get_assembly_creates_if_none():
    r = client.get("/api/assembly")
    assert r.status_code == 200
    body = r.json()
    assert "assembly" in body
    assert body["assembly"]["instances"] == []
    assert body["assembly"]["joints"] == []


def test_get_assembly_returns_existing():
    a = Assembly(metadata=DesignMetadata(name="Existing"))
    assembly_state.set_assembly(a)
    r = client.get("/api/assembly")
    assert r.status_code == 200
    assert r.json()["assembly"]["metadata"]["name"] == "Existing"


# ── POST /assembly ────────────────────────────────────────────────────────────

def test_create_assembly_returns_201():
    r = client.post("/api/assembly")
    assert r.status_code == 201
    body = r.json()
    assert body["assembly"]["instances"] == []
    assert body["assembly"]["joints"] == []


def test_create_assembly_replaces_existing():
    a = Assembly(metadata=DesignMetadata(name="Old"))
    assembly_state.set_assembly(a)

    r = client.post("/api/assembly")
    assert r.status_code == 201
    # New assembly has no name set (default empty string)
    new_id = r.json()["assembly"]["id"]
    assert new_id != a.id


# ── POST /assembly/import ─────────────────────────────────────────────────────

def test_import_assembly_roundtrip():
    a = Assembly(metadata=DesignMetadata(name="Imported"))
    r = client.post("/api/assembly/import", json={"content": a.to_json()})
    assert r.status_code == 200
    body = r.json()
    assert body["assembly"]["metadata"]["name"] == "Imported"
    assert body["assembly"]["id"] == a.id


def test_import_assembly_bad_json_returns_400():
    r = client.post("/api/assembly/import", json={"content": "not-json"})
    assert r.status_code == 400


# ── GET /assembly/export ──────────────────────────────────────────────────────

def test_export_assembly_returns_file():
    a = Assembly(metadata=DesignMetadata(name="My Assembly"))
    assembly_state.set_assembly(a)
    r = client.get("/api/assembly/export")
    assert r.status_code == 200
    assert "attachment" in r.headers["content-disposition"]
    assert ".nass" in r.headers["content-disposition"]
    # Body parses as valid Assembly JSON
    restored = Assembly.from_json(r.text)
    assert restored.id == a.id


def test_export_assembly_404_when_empty():
    r = client.get("/api/assembly/export")
    assert r.status_code == 404


# ── POST /assembly/instances ──────────────────────────────────────────────────

def test_add_instance_returns_201():
    client.post("/api/assembly")  # create fresh assembly
    r = client.post("/api/assembly/instances", json={
        "source": _inline_source_dict(),
        "name": "Part A",
    })
    assert r.status_code == 201
    body = r.json()
    instances = body["assembly"]["instances"]
    assert len(instances) == 1
    assert instances[0]["name"] == "Part A"
    assert instances[0]["source"]["type"] == "inline"


def test_add_instance_with_transform():
    client.post("/api/assembly")
    transform = {"values": [1,0,0,5, 0,1,0,3, 0,0,1,0, 0,0,0,1]}
    r = client.post("/api/assembly/instances", json={
        "source": _inline_source_dict(),
        "name": "Shifted",
        "transform": transform,
    })
    assert r.status_code == 201
    inst = r.json()["assembly"]["instances"][0]
    assert inst["transform"]["values"][3] == pytest.approx(5.0)


def test_add_instance_invalid_source_returns_400():
    client.post("/api/assembly")
    r = client.post("/api/assembly/instances", json={
        "source": {"type": "unknown"},
        "name": "Bad",
    })
    assert r.status_code == 400


# ── PATCH /assembly/instances/{id} ───────────────────────────────────────────

def test_patch_instance_name():
    client.post("/api/assembly")
    add_r = client.post("/api/assembly/instances", json={
        "source": _inline_source_dict(),
        "name": "Original",
    })
    inst_id = add_r.json()["assembly"]["instances"][0]["id"]

    r = client.patch(f"/api/assembly/instances/{inst_id}", json={"name": "Renamed"})
    assert r.status_code == 200
    instances = r.json()["assembly"]["instances"]
    assert instances[0]["name"] == "Renamed"


def test_patch_instance_visible():
    client.post("/api/assembly")
    add_r = client.post("/api/assembly/instances", json={
        "source": _inline_source_dict(),
    })
    inst_id = add_r.json()["assembly"]["instances"][0]["id"]

    r = client.patch(f"/api/assembly/instances/{inst_id}", json={"visible": False})
    assert r.status_code == 200
    assert r.json()["assembly"]["instances"][0]["visible"] is False


def test_patch_instance_mode():
    client.post("/api/assembly")
    add_r = client.post("/api/assembly/instances", json={
        "source": _inline_source_dict(),
    })
    inst_id = add_r.json()["assembly"]["instances"][0]["id"]

    r = client.patch(f"/api/assembly/instances/{inst_id}", json={"mode": "rigid"})
    assert r.status_code == 200
    assert r.json()["assembly"]["instances"][0]["mode"] == "rigid"


def test_patch_instance_invalid_mode_returns_400():
    client.post("/api/assembly")
    add_r = client.post("/api/assembly/instances", json={
        "source": _inline_source_dict(),
    })
    inst_id = add_r.json()["assembly"]["instances"][0]["id"]

    r = client.patch(f"/api/assembly/instances/{inst_id}", json={"mode": "squiggly"})
    assert r.status_code == 400


def test_patch_instance_not_found_returns_404():
    client.post("/api/assembly")
    r = client.patch("/api/assembly/instances/nonexistent-id", json={"name": "X"})
    assert r.status_code == 404


# ── DELETE /assembly/instances/{id} ──────────────────────────────────────────

def test_delete_instance():
    client.post("/api/assembly")
    add_r = client.post("/api/assembly/instances", json={
        "source": _inline_source_dict(),
    })
    inst_id = add_r.json()["assembly"]["instances"][0]["id"]

    r = client.delete(f"/api/assembly/instances/{inst_id}")
    assert r.status_code == 200
    assert r.json()["assembly"]["instances"] == []


def test_delete_instance_also_removes_referencing_joints():
    """Deleting an instance must cascade to joints that reference it."""
    client.post("/api/assembly")
    r_a = client.post("/api/assembly/instances", json={"source": _inline_source_dict(), "name": "A"})
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict(), "name": "B"})
    id_a = r_a.json()["assembly"]["instances"][0]["id"]
    id_b = r_b.json()["assembly"]["instances"][-1]["id"]

    # Add joint from A → B
    client.post("/api/assembly/joints", json={
        "instance_a_id": id_a,
        "instance_b_id": id_b,
    })

    r = client.delete(f"/api/assembly/instances/{id_b}")
    assert r.status_code == 200
    assembly = r.json()["assembly"]
    assert all(j["instance_b_id"] != id_b for j in assembly["joints"])


def test_delete_instance_not_found_returns_404():
    client.post("/api/assembly")
    r = client.delete("/api/assembly/instances/no-such-id")
    assert r.status_code == 404


# ── POST /assembly/joints ─────────────────────────────────────────────────────

def test_add_joint_creates_joint():
    client.post("/api/assembly")
    r_a = client.post("/api/assembly/instances", json={"source": _inline_source_dict(), "name": "A"})
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict(), "name": "B"})
    id_a = r_a.json()["assembly"]["instances"][0]["id"]
    id_b = r_b.json()["assembly"]["instances"][-1]["id"]

    r = client.post("/api/assembly/joints", json={
        "name": "Hinge",
        "instance_a_id": id_a,
        "instance_b_id": id_b,
        "axis_direction": [0.0, 0.0, 1.0],
    })
    assert r.status_code == 201
    joints = r.json()["assembly"]["joints"]
    assert len(joints) == 1
    assert joints[0]["name"] == "Hinge"
    assert joints[0]["joint_type"] == "revolute"


def test_add_joint_snapshots_base_transform():
    """Adding a joint should set instance_b.base_transform to its current transform."""
    client.post("/api/assembly")
    transform = {"values": [1,0,0,2, 0,1,0,3, 0,0,1,4, 0,0,0,1]}
    r_b = client.post("/api/assembly/instances", json={
        "source": _inline_source_dict(),
        "transform": transform,
    })
    id_b = r_b.json()["assembly"]["instances"][0]["id"]

    client.post("/api/assembly/joints", json={"instance_b_id": id_b})
    assembly = client.get("/api/assembly").json()["assembly"]
    inst = next(i for i in assembly["instances"] if i["id"] == id_b)
    assert inst["base_transform"] is not None
    assert inst["base_transform"]["values"][3] == pytest.approx(2.0)


def test_add_joint_invalid_instance_returns_404():
    client.post("/api/assembly")
    r = client.post("/api/assembly/joints", json={
        "instance_b_id": "nonexistent",
    })
    assert r.status_code == 404


# ── PATCH /assembly/joints/{id} ───────────────────────────────────────────────

def test_patch_joint_drives_revolute_transform():
    """Driving a revolute joint at 90° (pi/2) should rotate instance_b 90° about the Z axis."""
    client.post("/api/assembly")
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    id_b = r_b.json()["assembly"]["instances"][0]["id"]

    r_j = client.post("/api/assembly/joints", json={
        "instance_b_id": id_b,
        "axis_origin": [0.0, 0.0, 0.0],
        "axis_direction": [0.0, 0.0, 1.0],
    })
    joint_id = r_j.json()["assembly"]["joints"][0]["id"]

    r = client.patch(f"/api/assembly/joints/{joint_id}", json={"current_value": math.pi / 2})
    assert r.status_code == 200

    assembly = r.json()["assembly"]
    joint = next(j for j in assembly["joints"] if j["id"] == joint_id)
    assert joint["current_value"] == pytest.approx(math.pi / 2)

    # Z-rotation 90°: R = [[0,-1,0],[1,0,0],[0,0,1]] (row-major)
    inst = next(i for i in assembly["instances"] if i["id"] == id_b)
    vals = inst["transform"]["values"]
    # Row-major layout: vals[r*4+c] = R[r][c]
    assert vals[0] == pytest.approx(0.0, abs=1e-6)   # R[0][0] = cos(90°)
    assert vals[5] == pytest.approx(0.0, abs=1e-6)   # R[1][1] = cos(90°)
    assert vals[4] == pytest.approx(1.0, abs=1e-6)   # R[1][0] = sin(90°)


def test_patch_joint_clamps_to_limits():
    client.post("/api/assembly")
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    id_b = r_b.json()["assembly"]["instances"][0]["id"]
    r_j = client.post("/api/assembly/joints", json={
        "instance_b_id": id_b,
        "min_limit": -1.0,
        "max_limit": 1.0,
    })
    joint_id = r_j.json()["assembly"]["joints"][0]["id"]

    r = client.patch(f"/api/assembly/joints/{joint_id}", json={"current_value": 5.0})
    assert r.status_code == 200
    joint = r.json()["assembly"]["joints"][0]
    assert joint["current_value"] == pytest.approx(1.0)


def test_patch_joint_silent_skips_undo():
    """silent=True should not push to undo stack (for animation playback)."""
    client.post("/api/assembly")
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    id_b = r_b.json()["assembly"]["instances"][0]["id"]
    r_j = client.post("/api/assembly/joints", json={"instance_b_id": id_b})
    joint_id = r_j.json()["assembly"]["joints"][0]["id"]

    depth_before = client.get("/api/debug/assembly-undo-depth").json()["undo"]

    client.patch(f"/api/assembly/joints/{joint_id}", json={
        "current_value": 0.1,
        "silent": True,
    })
    depth_after = client.get("/api/debug/assembly-undo-depth").json()["undo"]
    assert depth_after == depth_before  # no new undo entry


def test_patch_joint_not_found_returns_404():
    client.post("/api/assembly")
    r = client.patch("/api/assembly/joints/no-such-id", json={"current_value": 1.0})
    assert r.status_code == 404


# ── DELETE /assembly/joints/{id} ─────────────────────────────────────────────

def test_delete_joint():
    client.post("/api/assembly")
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    id_b = r_b.json()["assembly"]["instances"][0]["id"]
    r_j = client.post("/api/assembly/joints", json={"instance_b_id": id_b})
    joint_id = r_j.json()["assembly"]["joints"][0]["id"]

    r = client.delete(f"/api/assembly/joints/{joint_id}")
    assert r.status_code == 200
    assert r.json()["assembly"]["joints"] == []


# ── POST /assembly/undo + redo ────────────────────────────────────────────────

def test_undo_reverses_add_instance():
    """Adding an instance and then undoing should return to an empty instances list."""
    client.post("/api/assembly")
    client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    assert len(client.get("/api/assembly").json()["assembly"]["instances"]) == 1

    r = client.post("/api/assembly/undo")
    assert r.status_code == 200
    assert r.json()["assembly"]["instances"] == []


def test_undo_three_ops_in_sequence():
    client.post("/api/assembly")
    for i in range(3):
        client.post("/api/assembly/instances", json={
            "source": _inline_source_dict(),
            "name": f"Part {i}",
        })

    client.post("/api/assembly/undo")
    assert len(client.get("/api/assembly").json()["assembly"]["instances"]) == 2
    client.post("/api/assembly/undo")
    assert len(client.get("/api/assembly").json()["assembly"]["instances"]) == 1
    client.post("/api/assembly/undo")
    assert len(client.get("/api/assembly").json()["assembly"]["instances"]) == 0


def test_undo_nothing_returns_404():
    r = client.post("/api/assembly/undo")
    assert r.status_code == 404


def test_redo_after_undo():
    client.post("/api/assembly")
    client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    client.post("/api/assembly/undo")
    assert client.get("/api/assembly").json()["assembly"]["instances"] == []

    r = client.post("/api/assembly/redo")
    assert r.status_code == 200
    assert len(r.json()["assembly"]["instances"]) == 1


def test_redo_nothing_returns_404():
    r = client.post("/api/assembly/redo")
    assert r.status_code == 404


# ── GET /assembly/library ─────────────────────────────────────────────────────

def _patch_library(monkeypatch, tmp_path):
    """Patch both _LIBRARY_DIR and _PROJECT_ROOT so relative_to() works."""
    import backend.api.assembly as asm_module
    lib_dir = tmp_path / "parts-library"
    lib_dir.mkdir(exist_ok=True)
    monkeypatch.setattr(asm_module, "_LIBRARY_DIR", lib_dir)
    monkeypatch.setattr(asm_module, "_PROJECT_ROOT", tmp_path)
    return lib_dir


def test_library_returns_empty_list_when_no_files(tmp_path, monkeypatch):
    """Library scan should return empty list when parts-library/ has no .nadoc files."""
    _patch_library(monkeypatch, tmp_path)
    r = client.get("/api/assembly/library")
    assert r.status_code == 200
    assert r.json()["entries"] == []


def test_library_returns_entry_with_sha256(tmp_path, monkeypatch):
    """A .nadoc file in parts-library/ must appear with correct sha256 and name."""
    from backend.core.models import Design
    import hashlib
    lib_dir = _patch_library(monkeypatch, tmp_path)

    content = Design().to_json()
    (lib_dir / "test_part.nadoc").write_text(content, encoding="utf-8")

    # Compute expected sha256 from raw bytes (same as _sha256_file reads)
    expected_sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

    r = client.get("/api/assembly/library")
    assert r.status_code == 200
    entries = r.json()["entries"]
    assert len(entries) == 1
    assert entries[0]["name"] == "test_part"
    assert entries[0]["sha256"] == expected_sha


def test_library_multiple_files(tmp_path, monkeypatch):
    from backend.core.models import Design
    lib_dir = _patch_library(monkeypatch, tmp_path)

    for i in range(3):
        (lib_dir / f"part_{i}.nadoc").write_text(Design().to_json(), encoding="utf-8")

    r = client.get("/api/assembly/library")
    assert r.status_code == 200
    assert len(r.json()["entries"]) == 3


# ── POST /assembly/library/register ──────────────────────────────────────────

def test_register_library_entry(tmp_path, monkeypatch):
    from backend.core.models import Design
    import backend.api.assembly as asm_module
    monkeypatch.setattr(asm_module, "_PROJECT_ROOT", tmp_path)

    p = tmp_path / "mypart.nadoc"
    p.write_text(Design().to_json(), encoding="utf-8")

    r = client.post("/api/assembly/library/register", json={"path": str(p), "tags": ["test"]})
    assert r.status_code == 201
    entry = r.json()["entry"]
    assert entry["name"] == "mypart"
    assert entry["tags"] == ["test"]
    assert len(entry["sha256"]) == 64


def test_register_library_missing_file_returns_400():
    r = client.post("/api/assembly/library/register", json={"path": "/nonexistent/file.nadoc"})
    assert r.status_code == 400


# ── GET /assembly/instances/{id}/design ──────────────────────────────────────

def test_get_instance_design_inline():
    from backend.core.models import Design
    client.post("/api/assembly")
    r_i = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    inst_id = r_i.json()["assembly"]["instances"][0]["id"]

    r = client.get(f"/api/assembly/instances/{inst_id}/design")
    assert r.status_code == 200
    assert "design" in r.json()


def test_get_instance_design_not_found_returns_404():
    client.post("/api/assembly")
    r = client.get("/api/assembly/instances/no-such-id/design")
    assert r.status_code == 404


# ── GET /assembly/instances/{id}/geometry ────────────────────────────────────

def test_get_instance_geometry_inline():
    client.post("/api/assembly")
    r_i = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    inst_id = r_i.json()["assembly"]["instances"][0]["id"]

    r = client.get(f"/api/assembly/instances/{inst_id}/geometry")
    assert r.status_code == 200
    body = r.json()
    assert "nucleotides" in body
    assert "helix_axes" in body
    assert isinstance(body["nucleotides"], list)


# ── GET /debug/assembly ───────────────────────────────────────────────────────

def test_debug_assembly_structure():
    r = client.get("/api/debug/assembly")
    assert r.status_code == 200
    body = r.json()
    assert "assembly" in body
    assert "instance_count" in body
    assert "joint_count" in body
    assert body["instance_count"] == 0
    assert body["joint_count"] == 0


def test_debug_assembly_counts_update():
    client.post("/api/assembly")
    client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    r = client.get("/api/debug/assembly")
    assert r.json()["instance_count"] == 1
    assert r.json()["joint_count"] == 0


# ── GET /debug/assembly-undo-depth ───────────────────────────────────────────

def test_debug_undo_depth_structure():
    r = client.get("/api/debug/assembly-undo-depth")
    assert r.status_code == 200
    body = r.json()
    assert "undo" in body
    assert "redo" in body
    assert body["undo"] == 0
    assert body["redo"] == 0


def test_debug_undo_depth_increments():
    client.post("/api/assembly")
    client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    r = client.get("/api/debug/assembly-undo-depth")
    assert r.json()["undo"] >= 1


# ── GET /debug/assembly-joint-transform/{joint_id} ───────────────────────────

def test_debug_joint_transform_at_90deg():
    client.post("/api/assembly")
    r_b = client.post("/api/assembly/instances", json={"source": _inline_source_dict()})
    id_b = r_b.json()["assembly"]["instances"][0]["id"]
    r_j = client.post("/api/assembly/joints", json={
        "instance_b_id": id_b,
        "axis_origin": [0.0, 0.0, 0.0],
        "axis_direction": [0.0, 0.0, 1.0],
    })
    joint_id = r_j.json()["assembly"]["joints"][0]["id"]

    r = client.get(f"/api/debug/assembly-joint-transform/{joint_id}", params={"angle": math.pi / 2})
    assert r.status_code == 200
    body = r.json()
    assert body["angle_deg"] == pytest.approx(90.0)
    assert "transform_preview" in body
    vals = body["transform_preview"]
    # Z-rotation 90°: R[0][0] = cos(90°) = 0, R[1][1] = cos(90°) = 0
    assert vals[0] == pytest.approx(0.0, abs=1e-6)   # R[0][0]
    assert vals[5] == pytest.approx(0.0, abs=1e-6)   # R[1][1]
    assert vals[4] == pytest.approx(1.0, abs=1e-6)   # R[1][0] = sin(90°)


def test_debug_joint_transform_not_found_returns_404():
    client.post("/api/assembly")
    r = client.get("/api/debug/assembly-joint-transform/no-such-joint")
    assert r.status_code == 404


# ── Assembly state isolation (design state must be unaffected) ────────────────

def test_assembly_mutations_do_not_affect_design_state():
    """Assembly CRUD mutations must never touch the design undo stack."""
    from backend.api import state as design_state
    from backend.core.models import Design

    design_state.close_session()
    design_state.set_design(Design())
    pre_depth = len(design_state._history)

    client.post("/api/assembly")
    for _ in range(5):
        client.post("/api/assembly/instances", json={"source": _inline_source_dict()})

    assert len(design_state._history) == pre_depth
    design_state.close_session()
