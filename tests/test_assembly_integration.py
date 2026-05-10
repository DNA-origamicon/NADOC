"""
Phase 12 tests — Assembly integration: joints, flatten, undo, validation.

Exercises end-to-end flows:
  - Add two inline instances, add a revolute joint, drive angle → verify transform
  - Flatten: verify all IDs prefixed, no duplicates, helix count correct
  - Undo: verify state at each step
  - Validation: passes all checks + fails correctly on bad data
  - Mixed-lattice (HC + SQ) instances, flatten → single Design
"""

from __future__ import annotations

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import assembly_state
from backend.api import state as design_state
from backend.api.main import app
from backend.core.models import (
    AssemblyJoint,
    Design,
    DesignMetadata,
    Helix,
    LatticeType,
    Vec3,
)

client = TestClient(app)


# ── Helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset():
    """Reset assembly and design state before/after every test."""
    assembly_state.close_session()
    design_state.clear_history()
    yield
    assembly_state.close_session()
    design_state.clear_history()


def _make_design(n_helices: int = 2, lattice: str = "honeycomb") -> Design:
    """Return a minimal Design with n_helices of 10 bp each."""
    helices = []
    for i in range(n_helices):
        helices.append(Helix(
            axis_start=Vec3(x=float(i * 3), y=0.0, z=0.0),
            axis_end=Vec3(x=float(i * 3), y=0.0, z=3.4),
            length_bp=10,
        ))
    return Design(
        helices=helices,
        lattice_type=LatticeType(lattice.upper()),
        metadata=DesignMetadata(name=f"Design_{lattice}"),
    )


def _inline_source(design: Design) -> dict:
    return {"type": "inline", "design": design.to_dict()}


def _add_instance(design: Design, name: str = "Part") -> dict:
    r = client.post("/api/assembly/instances", json={
        "source": _inline_source(design),
        "name": name,
    })
    assert r.status_code == 201, r.text
    return r.json()


def _identity_values() -> list[float]:
    return [1,0,0,0, 0,1,0,0, 0,0,1,0, 0,0,0,1]


# ── Joint transform verification ──────────────────────────────────────────────

class TestJointTransform:
    def test_revolute_joint_cos_sin(self):
        """After driving a revolute joint to 45°, the transform matrix has cos/sin entries."""
        client.post("/api/assembly")
        d = _make_design()
        body_a = _add_instance(d, "PartA")
        body_b = _add_instance(d, "PartB")
        inst_a_id = body_a["assembly"]["instances"][0]["id"]
        inst_b_id = body_b["assembly"]["instances"][1]["id"]

        # Add revolute joint
        r = client.post("/api/assembly/joints", json={
            "instance_a_id": inst_a_id,
            "instance_b_id": inst_b_id,
            "axis_origin": [0.0, 0.0, 0.0],
            "axis_direction": [0.0, 0.0, 1.0],
            "joint_type": "revolute",
        })
        assert r.status_code == 201, r.text
        joint_id = r.json()["assembly"]["joints"][0]["id"]

        # Drive to 45°
        angle = math.pi / 4
        r = client.patch(f"/api/assembly/joints/{joint_id}", json={
            "current_value": angle,
        })
        assert r.status_code == 200, r.text

        # Use debug preview endpoint to read the transform matrix
        r2 = client.get(f"/api/debug/assembly-joint-transform/{joint_id}?angle={angle}")
        assert r2.status_code == 200
        mat = r2.json()["transform_preview"]
        m = np.array(mat).reshape(4, 4)
        # For a Z-axis revolute at 45°: m[0,0]≈cos, m[0,1]≈-sin (or +sin depending on convention)
        cos45 = math.cos(angle)
        sin45 = math.sin(angle)
        assert abs(abs(m[0, 0]) - cos45) < 1e-6, f"m[0,0]={m[0,0]} expected ±{cos45:.4f}"
        assert abs(abs(m[1, 0]) - sin45) < 1e-6, f"m[1,0]={m[1,0]} expected ±{sin45:.4f}"

    def test_joint_limits_respected(self):
        """Adding a joint with limits and driving past them is caught by validate."""
        client.post("/api/assembly")
        d = _make_design()
        _add_instance(d, "A")
        body_b = _add_instance(d, "B")
        inst_ids = body_b["assembly"]["instances"]
        inst_a_id, inst_b_id = inst_ids[0]["id"], inst_ids[1]["id"]

        r = client.post("/api/assembly/joints", json={
            "instance_a_id": inst_a_id,
            "instance_b_id": inst_b_id,
            "axis_origin": [0.0, 0.0, 0.0],
            "axis_direction": [0.0, 0.0, 1.0],
            "joint_type": "revolute",
            "min_limit": -1.0,
            "max_limit":  1.0,
            "current_value": 1.5,
        })
        assert r.status_code == 201, r.text

        # Validate should flag the limit exceeded
        rv = client.get("/api/assembly/validate")
        assert rv.status_code == 200
        report = rv.json()
        assert not report["passed"]
        limit_check = next(
            (c for c in report["results"] if c["check"] == "joint_limits_not_exceeded" and not c["ok"]),
            None,
        )
        assert limit_check is not None, "Expected joint_limits_not_exceeded failure"


# ── Flatten ───────────────────────────────────────────────────────────────────

class TestFlatten:
    def test_flatten_two_instances(self):
        """Flatten two instances: helix count = sum, IDs prefixed, no duplicates."""
        client.post("/api/assembly")
        d1 = _make_design(n_helices=2)
        d2 = _make_design(n_helices=3)
        _add_instance(d1, "A")
        _add_instance(d2, "B")

        r = client.get("/api/assembly/flatten")
        assert r.status_code == 200, r.text
        design = r.json()["design"]
        assert len(design["helices"]) == 5  # 2 + 3
        helix_ids = [h["id"] for h in design["helices"]]
        assert len(helix_ids) == len(set(helix_ids)), "Duplicate helix IDs"
        assert all(h["id"].startswith("inst-") for h in design["helices"])

    def test_flatten_includes_linker_helices(self):
        """Assembly-level linker helices appear with asm:: prefix."""
        client.post("/api/assembly")
        d = _make_design(n_helices=1)
        _add_instance(d, "A")

        # Add a linker helix
        r = client.post("/api/assembly/linker-helices", json={
            "axis_start": [10.0, 0.0, 0.0],
            "axis_end":   [10.0, 0.0, 3.4],
            "length_bp":  10,
        })
        assert r.status_code == 201, r.text

        r = client.get("/api/assembly/flatten")
        assert r.status_code == 200, r.text
        design = r.json()["design"]
        assert len(design["helices"]) == 2  # 1 instance + 1 linker
        asm_helices = [h for h in design["helices"] if h["id"].startswith("asm::")]
        assert len(asm_helices) == 1

    def test_flatten_load_as_design(self):
        """flatten/load-as-design sets the active design and returns design shape."""
        client.post("/api/assembly")
        d = _make_design(n_helices=2)
        _add_instance(d, "A")

        r = client.post("/api/assembly/flatten/load-as-design")
        assert r.status_code == 200, r.text
        body = r.json()
        assert "design" in body
        assert len(body["design"]["helices"]) == 2

    def test_flatten_mixed_lattice(self):
        """HC + SQ instances both appear in the flattened Design."""
        client.post("/api/assembly")
        hc = _make_design(n_helices=2, lattice="honeycomb")
        sq = _make_design(n_helices=2, lattice="square")
        _add_instance(hc, "HC")
        _add_instance(sq, "SQ")

        r = client.get("/api/assembly/flatten")
        assert r.status_code == 200, r.text
        design = r.json()["design"]
        assert len(design["helices"]) == 4


# ── Undo ─────────────────────────────────────────────────────────────────────

class TestUndo:
    def test_undo_three_ops(self):
        """Add instance, patch instance, add joint — undo 3× — verify state at each step."""
        client.post("/api/assembly")
        d = _make_design()
        _add_instance(d, "A")
        body_b = _add_instance(d, "B")
        instances = body_b["assembly"]["instances"]
        inst_a_id, inst_b_id = instances[0]["id"], instances[1]["id"]

        # Op 3: add joint
        client.post("/api/assembly/joints", json={
            "instance_a_id": inst_a_id,
            "instance_b_id": inst_b_id,
            "axis_origin": [0.0, 0.0, 0.0],
            "axis_direction": [0.0, 0.0, 1.0],
            "joint_type": "revolute",
        })

        # Undo joint
        r = client.post("/api/assembly/undo")
        assert r.status_code == 200
        assert len(r.json()["assembly"]["joints"]) == 0

        # Undo add B
        r = client.post("/api/assembly/undo")
        assert r.status_code == 200
        assert len(r.json()["assembly"]["instances"]) == 1

        # Undo add A
        r = client.post("/api/assembly/undo")
        assert r.status_code == 200
        assert len(r.json()["assembly"]["instances"]) == 0

    def test_undo_redo_roundtrip(self):
        """Undo then redo restores the state."""
        client.post("/api/assembly")
        d = _make_design()
        _add_instance(d, "X")

        client.post("/api/assembly/undo")
        r = client.get("/api/assembly")
        assert len(r.json()["assembly"]["instances"]) == 0

        client.post("/api/assembly/redo")
        r = client.get("/api/assembly")
        assert len(r.json()["assembly"]["instances"]) == 1


# ── Validation ────────────────────────────────────────────────────────────────

class TestValidation:
    def test_validate_passes_clean_assembly(self):
        """A well-formed assembly with no issues should pass all checks."""
        client.post("/api/assembly")
        d = _make_design()
        _add_instance(d, "A")
        _add_instance(d, "B")

        r = client.get("/api/assembly/validate")
        assert r.status_code == 200
        report = r.json()
        assert report["passed"], f"Expected passed, got: {report['results']}"

    def test_validate_fails_bad_joint_ref(self):
        """A joint referencing a non-existent instance_b_id fails validation."""
        client.post("/api/assembly")
        d = _make_design()
        body = _add_instance(d, "A")
        inst_id = body["assembly"]["instances"][0]["id"]

        # Add joint with invalid instance_b_id
        assembly = assembly_state.get_or_404()
        bad_joint = AssemblyJoint(
            instance_a_id=inst_id,
            instance_b_id="nonexistent-id-xyz",
            axis_origin=[0, 0, 0],
            axis_direction=[0, 0, 1],
        )
        updated = assembly.model_copy(update={"joints": [bad_joint]}, deep=True)
        assembly_state.set_assembly(updated)

        r = client.get("/api/assembly/validate")
        assert r.status_code == 200
        report = r.json()
        assert not report["passed"]
        failed = [c for c in report["results"] if not c["ok"]]
        assert any(c["check"] == "joint_instance_refs_valid" for c in failed)

    def test_validate_empty_assembly(self):
        """Empty assembly returns no failed checks."""
        client.post("/api/assembly")
        r = client.get("/api/assembly/validate")
        assert r.status_code == 200
        report = r.json()
        assert report["passed"]
