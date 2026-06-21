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

    span = max(1, plane_b - plane_a)
    op = DeformationOp(
        type="bend",
        plane_a_bp=plane_a,
        plane_b_bp=plane_b,
        affected_helix_ids=helices_crossing_planes(design, plane_a, plane_b),
        params=BendParams(curvature_deg_per_bp=angle_deg / span, direction_deg=0.0),
    )
    entry = DeformationLogEntry(deformation_id=op.id, op_snapshot=op)
    new_log = list(design.feature_log) + [entry]
    return design.copy_with(
        deformations=[op],
        feature_log=new_log,
        feature_log_cursor=-1,
    )


def _compact_to_pos_map(compact: dict) -> dict:
    """Flatten nucleotides_compact → {(helix_id, bp_index, direction): backbone_position}."""
    out = {}
    for helix_id, by_dir in compact.items():
        for direction, b in by_dir.items():
            for i, bp in enumerate(b["bp"]):
                out[(helix_id, bp, direction)] = b["bb"][i]
    return out


def _compact_centroid(compact: dict):
    """Centroid of all backbone positions in a compact response."""
    pts = []
    for by_dir in compact.values():
        for b in by_dir.values():
            pts.extend(b["bb"])
    return np.array(pts).mean(axis=0)


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
    assert "nucleotides_compact" in body["-1"]
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
    nucs_empty = _compact_to_pos_map(body["-2"]["nucleotides_compact"])
    nucs_all   = _compact_to_pos_map(body["-1"]["nucleotides_compact"])
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
    batch_nucs = _compact_to_pos_map(batch_r.json()["0"]["nucleotides_compact"])

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

    c_empty = _compact_centroid(body["-2"]["nucleotides_compact"])
    c_f1    = _compact_centroid(body["0"]["nucleotides_compact"])
    c_f2    = _compact_centroid(body["1"]["nucleotides_compact"])
    c_all   = _compact_centroid(body["-1"]["nucleotides_compact"])

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
    batch_nucs = _compact_to_pos_map(batch_r.json()["-2"]["nucleotides_compact"])

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


def test_surface_batch_includes_vertex_colors_in_strand_mode():
    """Surface batch must ship per-vertex strand colours so animation playback
    can restore the surface's vertex colouring after a topology rebuild
    (otherwise the surface drops to uniform grey mid-animation in photo mode
    and during video export)."""
    r = client.post(
        "/api/design/features/surface-batch",
        json={"positions": [-1], "color_mode": "strand"},
    )
    assert r.status_code == 200
    entry = r.json()["-1"]
    assert "vertices" in entry and len(entry["vertices"]) > 0
    assert "faces" in entry and len(entry["faces"]) > 0
    assert "vertex_colors" in entry, "strand color_mode must include vertex_colors"
    assert len(entry["vertex_colors"]) == len(entry["vertices"])


def test_surface_batch_omits_vertex_colors_in_uniform_mode():
    """uniform mode should NOT carry vertex_colors (the live mesh paints a
    flat colour; sending the array would just waste payload)."""
    r = client.post(
        "/api/design/features/surface-batch",
        json={"positions": [-1], "color_mode": "uniform"},
    )
    assert r.status_code == 200
    entry = r.json()["-1"]
    assert "vertices" in entry and "faces" in entry
    assert "vertex_colors" not in entry


def test_geometry_batch_duplicates_deduplicated():
    """Duplicate positions are returned once each."""
    r = client.post(
        "/api/design/features/geometry-batch",
        json={"positions": [-1, -1, -1]},
    )
    assert r.status_code == 200
    body = r.json()
    assert list(body.keys()) == ["-1"]


# ── Keyframe binding_states (bind/unbind φ on the timeline) ──────────────────

def test_keyframe_binding_states_create_patch_roundtrip():
    """A design keyframe carries per-binding φ via binding_states; create and
    patch both persist it, and it survives a design JSON round-trip."""
    design_state.set_design(_demo_design())
    a = client.post("/api/design/animations",
                    json={"name": "A", "fps": 30, "loop": False})
    assert a.status_code == 200, a.text
    anim_id = a.json()["design"]["animations"][-1]["id"]

    # Create with binding_states.
    k = client.post(f"/api/design/animations/{anim_id}/keyframes",
                    json={"binding_states": {"b1": 1.0}})
    assert k.status_code == 200, k.text
    anim = next(an for an in k.json()["design"]["animations"] if an["id"] == anim_id)
    kf = anim["keyframes"][-1]
    assert kf["binding_states"] == {"b1": 1.0}

    # Patch to a new φ map.
    p = client.patch(f"/api/design/animations/{anim_id}/keyframes/{kf['id']}",
                     json={"binding_states": {"b1": 0.0, "b2": 0.5}})
    assert p.status_code == 200, p.text
    anim = next(an for an in p.json()["design"]["animations"] if an["id"] == anim_id)
    kf2 = next(x for x in anim["keyframes"] if x["id"] == kf["id"])
    assert kf2["binding_states"] == {"b1": 0.0, "b2": 0.5}


def test_keyframe_binding_states_defaults_empty():
    design_state.set_design(_demo_design())
    a = client.post("/api/design/animations", json={"name": "A"})
    anim_id = a.json()["design"]["animations"][-1]["id"]
    k = client.post(f"/api/design/animations/{anim_id}/keyframes", json={})
    anim = next(an for an in k.json()["design"]["animations"] if an["id"] == anim_id)
    assert anim["keyframes"][-1]["binding_states"] == {}


# ── Keyframe strand_anim_phi (rich un/hybridization φ on the timeline) ───────

def test_keyframe_strand_anim_phi_create_patch_roundtrip():
    """A design keyframe carries per-overhang φ via strand_anim_phi; create and
    patch both persist it. Distinct from binding_states."""
    design_state.set_design(_demo_design())
    a = client.post("/api/design/animations", json={"name": "A"})
    anim_id = a.json()["design"]["animations"][-1]["id"]

    k = client.post(f"/api/design/animations/{anim_id}/keyframes",
                    json={"strand_anim_phi": {"ovhg_x": 1.0}})
    assert k.status_code == 200, k.text
    anim = next(an for an in k.json()["design"]["animations"] if an["id"] == anim_id)
    kf = anim["keyframes"][-1]
    assert kf["strand_anim_phi"] == {"ovhg_x": 1.0}
    assert kf["binding_states"] == {}  # the two fields are independent

    p = client.patch(f"/api/design/animations/{anim_id}/keyframes/{kf['id']}",
                     json={"strand_anim_phi": {"ovhg_x": 0.0, "ovhg_y": 0.5}})
    assert p.status_code == 200, p.text
    anim = next(an for an in p.json()["design"]["animations"] if an["id"] == anim_id)
    kf2 = next(x for x in anim["keyframes"] if x["id"] == kf["id"])
    assert kf2["strand_anim_phi"] == {"ovhg_x": 0.0, "ovhg_y": 0.5}


def test_keyframe_strand_anim_phi_defaults_empty():
    design_state.set_design(_demo_design())
    a = client.post("/api/design/animations", json={"name": "A"})
    anim_id = a.json()["design"]["animations"][-1]["id"]
    k = client.post(f"/api/design/animations/{anim_id}/keyframes", json={})
    anim = next(an for an in k.json()["design"]["animations"] if an["id"] == anim_id)
    assert anim["keyframes"][-1]["strand_anim_phi"] == {}


def test_keyframe_strand_anim_phi_patch_clears():
    """PATCH with an explicit empty map clears it (model_fields_set path)."""
    design_state.set_design(_demo_design())
    a = client.post("/api/design/animations", json={"name": "A"})
    anim_id = a.json()["design"]["animations"][-1]["id"]
    k = client.post(f"/api/design/animations/{anim_id}/keyframes",
                    json={"strand_anim_phi": {"ovhg_x": 1.0}})
    kf_id = next(an for an in k.json()["design"]["animations"]
                 if an["id"] == anim_id)["keyframes"][-1]["id"]
    p = client.patch(f"/api/design/animations/{anim_id}/keyframes/{kf_id}",
                     json={"strand_anim_phi": {}})
    anim = next(an for an in p.json()["design"]["animations"] if an["id"] == anim_id)
    kf2 = next(x for x in anim["keyframes"] if x["id"] == kf_id)
    assert kf2["strand_anim_phi"] == {}


# ── Trajectory keyframes (oxDNA trajectory playback) ─────────────────────────

def test_keyframe_trajectory_create_patch_roundtrip():
    """A trajectory keyframe carries is_trajectory + job id + frame range; create
    and patch both persist them."""
    design_state.set_design(_demo_design())
    a = client.post("/api/design/animations", json={"name": "A"})
    anim_id = a.json()["design"]["animations"][-1]["id"]

    k = client.post(
        f"/api/design/animations/{anim_id}/keyframes",
        json={"is_trajectory": True, "trajectory_engine": "oxdna"},
    )
    assert k.status_code == 200, k.text
    anim = next(an for an in k.json()["design"]["animations"] if an["id"] == anim_id)
    kf = anim["keyframes"][-1]
    assert kf["is_trajectory"] is True
    assert kf["trajectory_engine"] == "oxdna"
    assert kf["trajectory_job_id"] is None

    p = client.patch(
        f"/api/design/animations/{anim_id}/keyframes/{kf['id']}",
        json={"trajectory_job_id": "job-7", "trajectory_frame_start": 3,
              "trajectory_frame_end": 88},
    )
    assert p.status_code == 200, p.text
    anim = next(an for an in p.json()["design"]["animations"] if an["id"] == anim_id)
    kf2 = next(x for x in anim["keyframes"] if x["id"] == kf["id"])
    assert kf2["trajectory_job_id"] == "job-7"
    assert kf2["trajectory_frame_start"] == 3
    assert kf2["trajectory_frame_end"] == 88


def test_keyframe_trajectory_defaults():
    """A normal keyframe is not a trajectory keyframe; trajectory fields default."""
    design_state.set_design(_demo_design())
    a = client.post("/api/design/animations", json={"name": "A"})
    anim_id = a.json()["design"]["animations"][-1]["id"]
    k = client.post(f"/api/design/animations/{anim_id}/keyframes", json={})
    anim = next(an for an in k.json()["design"]["animations"] if an["id"] == anim_id)
    kf = anim["keyframes"][-1]
    assert kf["is_trajectory"] is False
    assert kf["trajectory_job_id"] is None
    assert kf["trajectory_frame_start"] is None


# ── Overhang strand_anim_setup endpoint ──────────────────────────────────────

def _demo_design_with_overhang():
    """Demo design plus one OverhangSpec referencing the existing helix/strand."""
    from backend.core.models import OverhangSpec
    d = _demo_design()
    oh = OverhangSpec(id="ovhg_x", helix_id="demo_helix", strand_id="staple_0")
    return d.model_copy(update={"overhangs": [oh]}, deep=True)


def test_overhang_strand_anim_setup_roundtrip_and_clear():
    design_state.set_design(_demo_design_with_overhang())
    setup = {"mode": "unzip", "form": "helical", "meltBp": 2.0,
             "thetaDeg": 30, "binder_strand_id": "binder_1"}

    r = client.patch("/api/design/overhangs/ovhg_x/strand-anim-setup",
                     json={"setup": setup})
    assert r.status_code == 200, r.text

    g = client.get("/api/design")
    oh = next(o for o in g.json()["design"]["overhangs"] if o["id"] == "ovhg_x")
    assert oh["strand_anim_setup"] == setup

    # Clear.
    r2 = client.patch("/api/design/overhangs/ovhg_x/strand-anim-setup",
                      json={"setup": None})
    assert r2.status_code == 200, r2.text
    g2 = client.get("/api/design")
    oh2 = next(o for o in g2.json()["design"]["overhangs"] if o["id"] == "ovhg_x")
    assert oh2["strand_anim_setup"] is None


def test_overhang_strand_anim_setup_404():
    design_state.set_design(_demo_design())
    r = client.patch("/api/design/overhangs/nope/strand-anim-setup",
                     json={"setup": {"mode": "unzip"}})
    assert r.status_code == 404


def test_strand_anim_fields_survive_model_roundtrip():
    """Both new display-only fields survive a Design JSON dump→reload."""
    from backend.core.models import Design
    d = _demo_design_with_overhang()
    d.overhangs[0].strand_anim_setup = {"mode": "displacement", "thetaDeg": 45}
    reloaded = Design.model_validate(d.model_dump())
    assert reloaded.overhangs[0].strand_anim_setup == {"mode": "displacement", "thetaDeg": 45}
