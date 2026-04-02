"""
Tests for the animation pre-bake API endpoint.

POST /design/features/geometry-batch returns pre-computed geometry for multiple
feature-log positions in one stateless call — the cursor must not change.
"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design

client = TestClient(app)


# ── Helpers ────────────────────────────────────────────────────────────────────


def _add_bend(design, plane_a: int, plane_b: int, angle_deg: float = 90.0):
    """Return a new design with one bend deformation added to the feature log."""
    from backend.core.deformation import helices_crossing_planes
    from backend.core.models import BendParams, DeformationLogEntry, DeformationOp

    op = DeformationOp(
        type="bend",
        plane_a_bp=plane_a,
        plane_b_bp=plane_b,
        affected_helix_ids=helices_crossing_planes(design, plane_a, plane_b),
        params=BendParams(angle_deg=angle_deg, direction_deg=0.0),
    )
    entry = DeformationLogEntry(deformation_id=op.id, op_snapshot=op)
    new_log = list(design.feature_log) + [entry]
    return design.copy_with(
        deformations=[op],
        feature_log=new_log,
        feature_log_cursor=-1,
    )


@pytest.fixture(autouse=True)
def reset_state():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


# ── Batch endpoint tests ───────────────────────────────────────────────────────


def test_geometry_batch_returns_200():
    r = client.post("/api/design/features/geometry-batch", json={"positions": [-1]})
    assert r.status_code == 200
    body = r.json()
    assert "-1" in body
    assert "nucleotides" in body["-1"]
    assert "helix_axes" in body["-1"]


def test_geometry_batch_does_not_change_cursor():
    """geometry-batch is stateless — cursor must be unchanged after the call."""
    design_before = design_state.get_design()
    cursor_before = design_before.feature_log_cursor

    client.post("/api/design/features/geometry-batch", json={"positions": [-2, -1, 0]})

    design_after = design_state.get_design()
    assert design_after.feature_log_cursor == cursor_before


def test_geometry_batch_no_deformations_all_positions_equal():
    """With no deformations, positions -2 and -1 return identical geometry."""
    r = client.post("/api/design/features/geometry-batch", json={"positions": [-2, -1]})
    assert r.status_code == 200
    body = r.json()
    nucs_empty = {
        (n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
        for n in body["-2"]["nucleotides"]
    }
    nucs_all = {
        (n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
        for n in body["-1"]["nucleotides"]
    }
    assert nucs_empty.keys() == nucs_all.keys()
    max_diff = max(
        np.linalg.norm(np.array(nucs_empty[k]) - np.array(nucs_all[k]))
        for k in nucs_empty
    )
    assert max_diff < 1e-9, f"Positions -2 and -1 differ on plain design: Δ={max_diff:.3e} nm"


def test_geometry_batch_position_zero_matches_seek_then_geometry():
    """Batch position 0 must match: seekFeatures(0) → GET /geometry."""
    # Add one bend to the feature log
    design = design_state.get_design()
    bent = _add_bend(design, plane_a=5, plane_b=35)
    design_state.set_design(bent)

    # Reference: seek to 0, then fetch geometry
    client.post("/api/design/features/seek", json={"position": 0})
    ref_r = client.get("/api/design/geometry")
    assert ref_r.status_code == 200
    ref_nucs = {
        (n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
        for n in ref_r.json()["nucleotides"]
    }

    # Restore cursor (seek changed it); reset to the bent design
    design_state.set_design(bent)

    # Now call batch for position 0
    batch_r = client.post("/api/design/features/geometry-batch", json={"positions": [0]})
    assert batch_r.status_code == 200
    batch_nucs = {
        (n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
        for n in batch_r.json()["0"]["nucleotides"]
    }

    assert ref_nucs.keys() == batch_nucs.keys()
    max_diff = max(
        np.linalg.norm(np.array(ref_nucs[k]) - np.array(batch_nucs[k]))
        for k in ref_nucs
    )
    assert max_diff < 1e-9, f"Batch pos 0 disagrees with seek+geometry: Δ={max_diff:.3e} nm"


def test_geometry_batch_multiple_positions_are_distinct():
    """With two bends, positions -2 / 0 / 1 / -1 produce four distinct states."""
    design = design_state.get_design()
    after_f1 = _add_bend(design, plane_a=5,  plane_b=20, angle_deg=45.0)
    after_f2 = _add_bend(after_f1, plane_a=22, plane_b=37, angle_deg=45.0)
    # after_f2 has two bends in the log; deformations = both ops active
    design_state.set_design(after_f2)

    r = client.post(
        "/api/design/features/geometry-batch",
        json={"positions": [-2, 0, 1, -1]},
    )
    assert r.status_code == 200
    body = r.json()
    assert set(body.keys()) == {"-2", "0", "1", "-1"}

    def centroid(nucs):
        pts = np.array([n["backbone_position"] for n in nucs])
        return pts.mean(axis=0)

    c_empty = centroid(body["-2"]["nucleotides"])
    c_f1    = centroid(body["0"]["nucleotides"])
    c_f2    = centroid(body["1"]["nucleotides"])
    c_all   = centroid(body["-1"]["nucleotides"])

    # Each successive deformation shifts the centroid — they must all differ
    assert not np.allclose(c_empty, c_f1, atol=1e-3), "F0 and F1 centroids are identical"
    assert not np.allclose(c_f1,   c_f2, atol=1e-3), "F1 and F2 centroids are identical"
    # -1 (all active) == 1 (index of last entry = second bend)
    assert np.allclose(c_f2, c_all, atol=1e-9), "position 1 and -1 (all) should match"


def test_geometry_batch_position_minus2_equals_straight():
    """Position -2 (empty state) must match straight geometry (no deformations)."""
    design = design_state.get_design()
    bent = _add_bend(design, plane_a=5, plane_b=35, angle_deg=90.0)
    design_state.set_design(bent)

    # Straight geometry via the existing endpoint
    straight_r = client.get("/api/design/geometry?apply_deformations=false")
    assert straight_r.status_code == 200
    straight_nucs = {
        (n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
        for n in straight_r.json()["nucleotides"]
    }

    batch_r = client.post("/api/design/features/geometry-batch", json={"positions": [-2]})
    assert batch_r.status_code == 200
    batch_nucs = {
        (n["helix_id"], n["bp_index"], n["direction"]): n["backbone_position"]
        for n in batch_r.json()["-2"]["nucleotides"]
    }

    assert straight_nucs.keys() == batch_nucs.keys()
    max_diff = max(
        np.linalg.norm(np.array(straight_nucs[k]) - np.array(batch_nucs[k]))
        for k in straight_nucs
    )
    assert max_diff < 1e-9, f"Position -2 differs from straight geometry: Δ={max_diff:.3e} nm"


def test_geometry_batch_helix_axes_present():
    """Each state in the batch response must include helix_axes with start/end."""
    r = client.post("/api/design/features/geometry-batch", json={"positions": [-2, -1]})
    assert r.status_code == 200
    for pos_key, state in r.json().items():
        axes = state.get("helix_axes", [])
        assert len(axes) >= 1, f"No helix_axes in position {pos_key}"
        for ax in axes:
            assert "helix_id" in ax
            assert len(ax["start"]) == 3
            assert len(ax["end"]) == 3


def test_geometry_batch_duplicates_deduplicated():
    """Duplicate positions are returned once each."""
    r = client.post(
        "/api/design/features/geometry-batch",
        json={"positions": [-1, -1, -1]},
    )
    assert r.status_code == 200
    body = r.json()
    assert list(body.keys()) == ["-1"]
