"""
Tests for the ClusterJoint CRUD API.

POST   /design/cluster/{cluster_id}/joint  — create joint
PATCH  /design/joint/{joint_id}            — update joint
DELETE /design/joint/{joint_id}            — delete joint

Joints are design metadata (not in feature_log) and support undo/redo.
"""

from __future__ import annotations

import math

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import ClusterRigidTransform

client = TestClient(app)

_AXIS_ORIGIN    = [1.0, 2.0, 3.0]
_AXIS_DIRECTION = [0.0, 1.0, 0.0]   # already normalised


# ── Fixtures ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def reset_state():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


@pytest.fixture()
def cluster_id():
    """Create a cluster and return its id."""
    design = design_state.get_or_404()
    helix_id = design.helices[0].id
    ct = ClusterRigidTransform(name="TestCluster", helix_ids=[helix_id])
    design_state.set_design(design.copy_with(cluster_transforms=[ct]))
    return ct.id


# ── POST /design/cluster/{cluster_id}/joint ────────────────────────────────────

def test_create_joint_returns_200(cluster_id):
    r = client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={
            "axis_origin": _AXIS_ORIGIN,
            "axis_direction": _AXIS_DIRECTION,
            "surface_detail": 6,
            "name": "HingeA",
        },
    )
    assert r.status_code == 200
    body = r.json()
    joints = body["design"]["cluster_joints"]
    assert len(joints) == 1
    j = joints[0]
    assert j["cluster_id"] == cluster_id
    assert j["name"] == "HingeA"
    assert j["joint_type"] == "revolute"
    # Cluster fixture uses identity transform, so local == world here.
    assert j["local_axis_origin"] == pytest.approx(_AXIS_ORIGIN)
    # Direction should be normalised (already unit in this case)
    assert abs(sum(v * v for v in j["local_axis_direction"]) - 1.0) < 1e-6
    assert j["surface_detail"] == 6


def test_create_joint_normalises_direction(cluster_id):
    """Backend normalises axis_direction regardless of input magnitude."""
    r = client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={
            "axis_origin": [0, 0, 0],
            "axis_direction": [0.0, 3.0, 0.0],   # length 3, not unit
        },
    )
    assert r.status_code == 200
    j = r.json()["design"]["cluster_joints"][0]
    # Cluster fixture is identity transform, so local == world.
    assert j["local_axis_direction"] == pytest.approx([0.0, 1.0, 0.0])


def test_create_joint_zero_direction_returns_400(cluster_id):
    r = client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": [0, 0, 0], "axis_direction": [0.0, 0.0, 0.0]},
    )
    assert r.status_code == 400


def test_create_joint_unknown_cluster_returns_404():
    r = client.post(
        "/api/design/cluster/no-such-id/joint",
        json={"axis_origin": [0, 0, 0], "axis_direction": [1.0, 0.0, 0.0]},
    )
    assert r.status_code == 404


def test_create_joint_persists_in_design(cluster_id):
    client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": _AXIS_ORIGIN, "axis_direction": _AXIS_DIRECTION},
    )
    design = design_state.get_or_404()
    assert len(design.cluster_joints) == 1
    assert design.cluster_joints[0].cluster_id == cluster_id


def test_create_joint_logs_joint_place_minor_op(cluster_id):
    """Joint creation is logged as a 'joint-place' minor op under the open
    Fine Routing cluster (or opens a new one). Phase 3: joint placement is
    deterministically tracked so the feature-log slider can reproduce it."""
    from backend.core.models import RoutingClusterLogEntry

    client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": _AXIS_ORIGIN, "axis_direction": _AXIS_DIRECTION},
    )
    log = design_state.get_or_404().feature_log
    assert log, "feature_log must contain at least one entry after joint create"
    last = log[-1]
    assert isinstance(last, RoutingClusterLogEntry)
    assert last.children[-1].op_subtype == 'joint-place'
    # Params capture the deterministic joint_id + cluster_id + local-frame axis
    p = last.children[-1].params
    assert p['cluster_id'] == cluster_id
    assert 'joint_id' in p
    assert p['local_axis_origin']    == pytest.approx(_AXIS_ORIGIN)
    assert p['local_axis_direction'] == pytest.approx(_AXIS_DIRECTION)


def test_create_joint_pushes_undo(cluster_id):
    """Creating a joint should be undoable."""
    client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": _AXIS_ORIGIN, "axis_direction": _AXIS_DIRECTION},
    )
    assert len(design_state.get_or_404().cluster_joints) == 1

    r = client.post("/api/design/undo")
    assert r.status_code == 200
    assert len(r.json()["design"]["cluster_joints"]) == 0


# ── PATCH /design/joint/{joint_id} ────────────────────────────────────────────

def _make_joint(cluster_id):
    r = client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": _AXIS_ORIGIN, "axis_direction": _AXIS_DIRECTION, "name": "J1"},
    )
    return r.json()["design"]["cluster_joints"][0]["id"]


def test_patch_joint_name(cluster_id):
    jid = _make_joint(cluster_id)
    r = client.patch(f"/api/design/joint/{jid}", json={"name": "Renamed"})
    assert r.status_code == 200
    j = next(j for j in r.json()["design"]["cluster_joints"] if j["id"] == jid)
    assert j["name"] == "Renamed"


def test_patch_joint_axis(cluster_id):
    jid = _make_joint(cluster_id)
    new_dir = [1.0, 0.0, 0.0]
    r = client.patch(f"/api/design/joint/{jid}", json={"axis_direction": new_dir})
    assert r.status_code == 200
    j = next(j for j in r.json()["design"]["cluster_joints"] if j["id"] == jid)
    # Cluster fixture has identity transform, so local == world.
    assert j["local_axis_direction"] == pytest.approx(new_dir)


def test_patch_joint_surface_detail(cluster_id):
    jid = _make_joint(cluster_id)
    r = client.patch(f"/api/design/joint/{jid}", json={"surface_detail": 12})
    assert r.status_code == 200
    j = next(j for j in r.json()["design"]["cluster_joints"] if j["id"] == jid)
    assert j["surface_detail"] == 12


def test_patch_joint_unknown_returns_404():
    r = client.patch("/api/design/joint/no-such-id", json={"name": "X"})
    assert r.status_code == 404


def test_patch_joint_normalises_direction(cluster_id):
    jid = _make_joint(cluster_id)
    r = client.patch(f"/api/design/joint/{jid}", json={"axis_direction": [2.0, 0.0, 0.0]})
    assert r.status_code == 200
    j = next(j for j in r.json()["design"]["cluster_joints"] if j["id"] == jid)
    # Identity-transform cluster, so local == world.
    assert j["local_axis_direction"] == pytest.approx([1.0, 0.0, 0.0])


def test_patch_joint_zero_direction_returns_400(cluster_id):
    jid = _make_joint(cluster_id)
    r = client.patch(f"/api/design/joint/{jid}", json={"axis_direction": [0.0, 0.0, 0.0]})
    assert r.status_code == 400


# ── DELETE /design/joint/{joint_id} ───────────────────────────────────────────

def test_delete_joint(cluster_id):
    jid = _make_joint(cluster_id)
    r = client.delete(f"/api/design/joint/{jid}")
    assert r.status_code == 200
    assert r.json()["design"]["cluster_joints"] == []


def test_delete_joint_unknown_returns_404():
    r = client.delete("/api/design/joint/no-such-id")
    assert r.status_code == 404


def test_delete_joint_pushes_undo(cluster_id):
    jid = _make_joint(cluster_id)
    client.delete(f"/api/design/joint/{jid}")
    assert len(design_state.get_or_404().cluster_joints) == 0

    r = client.post("/api/design/undo")
    assert r.status_code == 200
    joints = r.json()["design"]["cluster_joints"]
    assert len(joints) == 1
    assert joints[0]["id"] == jid


# ── One joint per cluster (second POST replaces first) ────────────────────────

def test_multiple_joints_on_same_cluster(cluster_id):
    """Each cluster supports at most one joint; a second POST replaces the first."""
    client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": [0, 0, 0], "axis_direction": [1, 0, 0], "name": "J1"},
    )
    client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": [0, 0, 0], "axis_direction": [0, 1, 0], "name": "J2"},
    )
    design = design_state.get_or_404()
    # The second POST replaces the first — only J2 survives.
    assert len(design.cluster_joints) == 1
    assert design.cluster_joints[0].name == "J2"


# ── Serialisation round-trip ──────────────────────────────────────────────────

def test_joint_survives_design_dict_roundtrip(cluster_id):
    """ClusterJoint must survive to_dict → from_dict without loss."""
    from backend.core.models import Design

    client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": _AXIS_ORIGIN, "axis_direction": _AXIS_DIRECTION, "surface_detail": 8},
    )
    design = design_state.get_or_404()
    reloaded = Design.from_dict(design.to_dict())
    assert len(reloaded.cluster_joints) == 1
    j = reloaded.cluster_joints[0]
    # Cluster fixture has identity transform, so local == world here.
    assert j.local_axis_origin == pytest.approx(_AXIS_ORIGIN)
    assert j.surface_detail == 8


# ── Rotate-about-joint geometry validation ────────────────────────────────────
#
# These tests verify that the backend correctly applies the formula
#   new_pos = R @ (p_orig − J) + J
# when the cluster is PATCHed with pivot = J (axis_origin) and translation = [0,0,0].
#
# The design under test is a 6-helix honeycomb bundle (6HB, 42 bp).
# The joint's axis_origin is placed at the axis_start of the first helix —
# a corner of the bundle face.  Axis direction = +Z (along the bundle).
# Rotations are 90° about Z so the expected new positions are easy to verify.

import math
import numpy as np

from backend.core.lattice import make_bundle_design
from backend.core.models import ClusterRigidTransform

_R90Z_QUAT = [0.0, 0.0, math.sin(math.pi / 4), math.cos(math.pi / 4)]  # 90° about +Z
_R180Z_QUAT = [0.0, 0.0, 1.0, 0.0]                                      # 180° about +Z


def _r90z() -> np.ndarray:
    """3×3 rotation matrix for 90° CCW about +Z."""
    return np.array([[0., -1., 0.],
                     [1.,  0., 0.],
                     [0.,  0., 1.]])


def _setup_6hb_with_joint():
    """
    Build a 6HB design (42 bp, HC lattice), create a cluster for all helices,
    place a joint at the axis_start of the first helix (XY corner of the face,
    Z=0), and install it as the active design.

    Returns (cluster_id, joint_origin_np_array).
    """
    design = make_bundle_design(
        [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)],
        length_bp=42,
    )

    # Approximate centroid as mean of helix axis midpoints.
    helix_ids = [h.id for h in design.helices]
    cx = sum((h.axis_start.x + h.axis_end.x) / 2 for h in design.helices) / len(design.helices)
    cy = sum((h.axis_start.y + h.axis_end.y) / 2 for h in design.helices) / len(design.helices)
    cz = sum((h.axis_start.z + h.axis_end.z) / 2 for h in design.helices) / len(design.helices)

    ct = ClusterRigidTransform(
        name="6HB",
        helix_ids=helix_ids,
        pivot=[cx, cy, cz],
        translation=[0.0, 0.0, 0.0],
        rotation=[0.0, 0.0, 0.0, 1.0],
    )
    design = design.copy_with(cluster_transforms=[ct])
    design_state.set_design(design)

    # Joint at axis_start of first helix — a corner of the bundle cross-section.
    h0 = design.helices[0]
    j_origin = [h0.axis_start.x, h0.axis_start.y, h0.axis_start.z]

    r = client.post(
        f"/api/design/cluster/{ct.id}/joint",
        json={
            "axis_origin":    j_origin,
            "axis_direction": [0.0, 0.0, 1.0],
            "name":           "CornerHinge",
        },
    )
    assert r.status_code == 200

    return ct.id, np.array(j_origin)


def _backbone_positions() -> dict[tuple, np.ndarray]:
    """Return {(helix_id, bp_index, direction): backbone_position_array}."""
    resp = client.get("/api/design/geometry")
    assert resp.status_code == 200
    return {
        (n["helix_id"], n["bp_index"], n["direction"]): np.array(n["backbone_position"])
        for n in resp.json()["nucleotides"]
    }


def test_6hb_rotate_about_joint_matches_formula():
    """
    PATCH cluster with pivot=J, rotation=R90Z, translation=[0,0,0].
    Every nucleotide must satisfy: new_pos = R90Z @ (orig_pos − J) + J.
    """
    cluster_id, J = _setup_6hb_with_joint()

    orig = _backbone_positions()

    r = client.patch(f"/api/design/cluster/{cluster_id}", json={
        "rotation":    _R90Z_QUAT,
        "translation": [0.0, 0.0, 0.0],
        "pivot":       J.tolist(),
        "commit":      True,
    })
    assert r.status_code == 200

    after = _backbone_positions()
    assert after.keys() == orig.keys()

    R = _r90z()
    max_err = max(
        np.linalg.norm((R @ (p - J) + J) - after[k])
        for k, p in orig.items()
    )
    assert max_err < 1e-8, f"Max deviation from R@(p−J)+J formula: {max_err:.3e} nm"


def test_6hb_rotate_about_joint_preserves_distances():
    """
    Rotation is an isometry — distance from J must be unchanged for every nucleotide.
    """
    cluster_id, J = _setup_6hb_with_joint()

    orig = _backbone_positions()

    client.patch(f"/api/design/cluster/{cluster_id}", json={
        "rotation":    _R90Z_QUAT,
        "translation": [0.0, 0.0, 0.0],
        "pivot":       J.tolist(),
        "commit":      True,
    })

    after = _backbone_positions()

    max_delta = max(
        abs(np.linalg.norm(after[k] - J) - np.linalg.norm(orig[k] - J))
        for k in orig
    )
    assert max_delta < 1e-8, f"Max |distance| change from J: {max_delta:.3e} nm"


def test_6hb_rotate_about_joint_z_unchanged():
    """90° rotation about +Z must leave every nucleotide's Z coordinate unchanged."""
    cluster_id, J = _setup_6hb_with_joint()

    orig = _backbone_positions()

    client.patch(f"/api/design/cluster/{cluster_id}", json={
        "rotation":    _R90Z_QUAT,
        "translation": [0.0, 0.0, 0.0],
        "pivot":       J.tolist(),
        "commit":      True,
    })

    after = _backbone_positions()

    max_dz = max(abs(after[k][2] - orig[k][2]) for k in orig)
    assert max_dz < 1e-8, f"Max Z shift during +Z rotation: {max_dz:.3e} nm"


def test_6hb_second_rotation_about_joint_accumulates():
    """
    Two successive 90° rotations about J must equal one 180° rotation from orig.

    After each PATCH the backend re-applies the stored absolute rotation to the
    original nucleotide positions, so the second PATCH just needs rotation=R180.
    """
    cluster_id, J = _setup_6hb_with_joint()

    orig = _backbone_positions()

    # First 90°
    client.patch(f"/api/design/cluster/{cluster_id}", json={
        "rotation":    _R90Z_QUAT,
        "translation": [0.0, 0.0, 0.0],
        "pivot":       J.tolist(),
        "commit":      True,
    })

    # Second 90° — absolute rotation is now 180°
    client.patch(f"/api/design/cluster/{cluster_id}", json={
        "rotation":    _R180Z_QUAT,
        "translation": [0.0, 0.0, 0.0],
        "pivot":       J.tolist(),
        "commit":      True,
    })

    after = _backbone_positions()

    R180 = _r90z() @ _r90z()  # [[−1,0,0],[0,−1,0],[0,0,1]]
    max_err = max(
        np.linalg.norm((R180 @ (p - J) + J) - after[k])
        for k, p in orig.items()
    )
    assert max_err < 1e-8, f"Max 180° rotation error: {max_err:.3e} nm"


def test_6hb_three_successive_rotations():
    """
    Three successive 90° rotations about the same joint must accumulate to 270°.

    Each PATCH replaces the stored absolute rotation, so:
      after 1st PATCH: rotation = R90,  translation = 0
      after 2nd PATCH: rotation = R180, translation = 0
      after 3rd PATCH: rotation = R270, translation = 0
    Final positions must satisfy new_pos = R270 @ (orig - J) + J with NO offset.
    """
    cluster_id, J = _setup_6hb_with_joint()

    orig = _backbone_positions()

    for absolute_turns in [1, 2, 3]:
        # Quaternion for absolute_turns × 90° about +Z
        angle = absolute_turns * math.pi / 2
        quat = [0.0, 0.0, math.sin(angle / 2), math.cos(angle / 2)]
        r = client.patch(f"/api/design/cluster/{cluster_id}", json={
            "rotation":    quat,
            "translation": [0.0, 0.0, 0.0],
            "pivot":       J.tolist(),
            "commit":      True,
        })
        assert r.status_code == 200

    after = _backbone_positions()

    # R270 = R90^3 = R90 applied three times
    R270 = _r90z() @ _r90z() @ _r90z()
    max_err = max(
        np.linalg.norm((R270 @ (p - J) + J) - after[k])
        for k, p in orig.items()
    )
    assert max_err < 1e-8, f"Max 270° accumulation error: {max_err:.3e} nm"


def test_6hb_joint_at_centroid_no_translation():
    """
    When J equals the cluster centroid, translation must stay [0,0,0] after rotation.
    This is the degenerate case where joint and pivot coincide.
    """
    cluster_id, _ = _setup_6hb_with_joint()

    # Overwrite joint to be at the stored pivot (centroid)
    design = design_state.get_or_404()
    ct = next(c for c in design.cluster_transforms if c.id == cluster_id)
    J_centroid = ct.pivot  # [cx, cy, cz]

    client.patch(f"/api/design/cluster/{cluster_id}", json={
        "rotation":    _R90Z_QUAT,
        "translation": [0.0, 0.0, 0.0],
        "pivot":       J_centroid,
        "commit":      True,
    })

    updated = design_state.get_or_404()
    ct2 = next(c for c in updated.cluster_transforms if c.id == cluster_id)
    assert ct2.translation == pytest.approx([0.0, 0.0, 0.0], abs=1e-10)


# ── Backbone cone endpoint validation ─────────────────────────────────────────
#
# A backbone cone connects consecutive nucleotides within a strand.  Its start
# and end points are the backbone_position values of those two nucleotides.
#
# After a joint-based rotation about J every cone endpoint must satisfy:
#   pos_after = R @ (pos_before − J) + J
#
# This is a stronger, more targeted check than the per-bead formula tests above:
# it explicitly builds the same (from, to) pairs that the frontend renderer uses
# — including crossover-base (__xb__) synthetic beads — and asserts that both
# endpoints of every cone are at the correct rotated positions.  Failures on
# cross-helix cones (is_cross_helix=True) indicate an __xb__ update bug.


def _grouped_by_strand(geometry: list[dict]) -> dict[str, list[dict]]:
    """Group geometry nucleotides by strand_id, sorted in strand traversal order.

    Replicates the helix_renderer.js byStrand sort:
      1. domain_index ascending   (places __xb__ beads between the domains they bridge)
      2. bp_index ascending for FORWARD strands, descending for REVERSE
    """
    groups: dict[str, list[dict]] = {}
    for nuc in geometry:
        sid = nuc.get("strand_id")
        if not sid:
            continue
        groups.setdefault(sid, []).append(nuc)
    for nucs in groups.values():
        nucs.sort(key=lambda n: (
            n.get("domain_index", 0),
            n["bp_index"] if n["direction"] == "FORWARD" else -n["bp_index"],
        ))
    return groups


def _cone_pairs(geometry: list[dict]) -> list[dict]:
    """Return every backbone cone as a dict describing its two endpoints.

    Each element::

        {
            "from_pos":      np.ndarray (3,),   # backbone_position of fromNuc
            "to_pos":        np.ndarray (3,),   # backbone_position of toNuc
            "is_cross_helix": bool,             # True when from/to span different helices
            "from_helix":    str,
            "to_helix":      str,
            "from_key":      tuple,             # (helix_id, bp_index, direction) for fromNuc
            "to_key":        tuple,
            "strand_id":     str,
        }
    """
    groups = _grouped_by_strand(geometry)
    pairs = []
    for strand_id, nucs in groups.items():
        for i in range(len(nucs) - 1):
            a, b = nucs[i], nucs[i + 1]
            pairs.append({
                "from_pos":       np.array(a["backbone_position"]),
                "to_pos":         np.array(b["backbone_position"]),
                "is_cross_helix": a["helix_id"] != b["helix_id"],
                "from_helix":     a["helix_id"],
                "to_helix":       b["helix_id"],
                "from_key":       (a["helix_id"], a["bp_index"], a["direction"]),
                "to_key":         (b["helix_id"], b["bp_index"], b["direction"]),
                "strand_id":      strand_id,
            })
    return pairs


def _apply_rotation(pos: np.ndarray, R: np.ndarray, J: np.ndarray) -> np.ndarray:
    return R @ (pos - J) + J


def test_6hb_cone_endpoints_match_bead_positions_after_rotation():
    """
    After a 90° rotation about J, every cone's from_pos and to_pos must equal
    R @ (original_pos − J) + J for the respective backbone bead.

    Failure message names the worst cone, its helix IDs, and whether it is a
    cross-helix (XB) cone so the source of the error is immediately clear.
    """
    cluster_id, J = _setup_6hb_with_joint()

    geo_before = client.get("/api/design/geometry").json()["nucleotides"]
    pairs_before = _cone_pairs(geo_before)
    assert pairs_before, "No cone pairs found — design may have no strands"

    client.patch(f"/api/design/cluster/{cluster_id}", json={
        "rotation":    _R90Z_QUAT,
        "translation": [0.0, 0.0, 0.0],
        "pivot":       J.tolist(),
        "commit":      True,
    })

    geo_after = client.get("/api/design/geometry").json()["nucleotides"]
    pairs_after = _cone_pairs(geo_after)

    assert len(pairs_after) == len(pairs_before), (
        f"Cone count changed: {len(pairs_before)} → {len(pairs_after)}"
    )

    R = _r90z()

    max_from_err = 0.0
    max_to_err   = 0.0
    worst_from   = None
    worst_to     = None

    for pb, pa in zip(pairs_before, pairs_after):
        from_expected = _apply_rotation(pb["from_pos"], R, J)
        to_expected   = _apply_rotation(pb["to_pos"],   R, J)

        from_err = np.linalg.norm(pa["from_pos"] - from_expected)
        to_err   = np.linalg.norm(pa["to_pos"]   - to_expected)

        if from_err > max_from_err:
            max_from_err = from_err
            worst_from = {
                "strand_id":    pb["strand_id"],
                "from_helix":   pb["from_helix"],
                "to_helix":     pb["to_helix"],
                "is_cross":     pb["is_cross_helix"],
                "from_key":     pb["from_key"],
                "orig":         pb["from_pos"].round(6).tolist(),
                "expected":     from_expected.round(6).tolist(),
                "actual":       pa["from_pos"].round(6).tolist(),
                "err_nm":       round(from_err, 9),
            }
        if to_err > max_to_err:
            max_to_err = to_err
            worst_to = {
                "strand_id":    pb["strand_id"],
                "from_helix":   pb["from_helix"],
                "to_helix":     pb["to_helix"],
                "is_cross":     pb["is_cross_helix"],
                "to_key":       pb["to_key"],
                "orig":         pb["to_pos"].round(6).tolist(),
                "expected":     to_expected.round(6).tolist(),
                "actual":       pa["to_pos"].round(6).tolist(),
                "err_nm":       round(to_err, 9),
            }

    assert max_from_err < 1e-8, (
        f"Cone from-endpoint error {max_from_err:.3e} nm\n"
        f"  is_cross_helix={worst_from['is_cross']} "
        f"({worst_from['from_helix']} → {worst_from['to_helix']})\n"
        f"  key:      {worst_from['from_key']}\n"
        f"  orig:     {worst_from['orig']}\n"
        f"  expected: {worst_from['expected']}\n"
        f"  actual:   {worst_from['actual']}"
    )
    assert max_to_err < 1e-8, (
        f"Cone to-endpoint error {max_to_err:.3e} nm\n"
        f"  is_cross_helix={worst_to['is_cross']} "
        f"({worst_to['from_helix']} → {worst_to['to_helix']})\n"
        f"  key:      {worst_to['to_key']}\n"
        f"  orig:     {worst_to['orig']}\n"
        f"  expected: {worst_to['expected']}\n"
        f"  actual:   {worst_to['actual']}"
    )


def test_6hb_cone_direction_vectors_after_rotation():
    """
    The direction vector of each cone (to_pos − from_pos) must equal
    R @ original_direction after rotation.

    This is a focused check on cone orientation that is independent of
    translation, making it easier to distinguish "cone points wrong way"
    (direction error) from "cone is in the wrong place" (position error).
    Reports cross-helix status so XB failures stand out.
    """
    cluster_id, J = _setup_6hb_with_joint()

    geo_before = client.get("/api/design/geometry").json()["nucleotides"]
    pairs_before = _cone_pairs(geo_before)

    client.patch(f"/api/design/cluster/{cluster_id}", json={
        "rotation":    _R90Z_QUAT,
        "translation": [0.0, 0.0, 0.0],
        "pivot":       J.tolist(),
        "commit":      True,
    })

    geo_after = client.get("/api/design/geometry").json()["nucleotides"]
    pairs_after = _cone_pairs(geo_after)

    R = _r90z()

    max_dir_err = 0.0
    worst       = None

    for pb, pa in zip(pairs_before, pairs_after):
        orig_dir     = pb["to_pos"] - pb["from_pos"]
        if np.linalg.norm(orig_dir) < 1e-8:
            continue                              # degenerate zero-length cone
        expected_dir = R @ orig_dir
        actual_dir   = pa["to_pos"] - pa["from_pos"]

        err = np.linalg.norm(actual_dir - expected_dir)
        if err > max_dir_err:
            max_dir_err = err
            worst = {
                "strand_id":    pb["strand_id"],
                "from_helix":   pb["from_helix"],
                "to_helix":     pb["to_helix"],
                "is_cross":     pb["is_cross_helix"],
                "from_key":     pb["from_key"],
                "to_key":       pb["to_key"],
                "orig_dir":     orig_dir.round(6).tolist(),
                "expected_dir": expected_dir.round(6).tolist(),
                "actual_dir":   actual_dir.round(6).tolist(),
                "err_nm":       round(err, 9),
            }

    assert max_dir_err < 1e-8, (
        f"Cone direction error {max_dir_err:.3e} nm\n"
        f"  is_cross_helix={worst['is_cross']} "
        f"({worst['from_helix']} → {worst['to_helix']})\n"
        f"  from_key:     {worst['from_key']}\n"
        f"  to_key:       {worst['to_key']}\n"
        f"  orig_dir:     {worst['orig_dir']}\n"
        f"  expected_dir: {worst['expected_dir']}\n"
        f"  actual_dir:   {worst['actual_dir']}"
    )


# ── Local-frame storage: drift-free + injection + migration ───────────────────
#
# Phase 2 storage refactor: ClusterJoint now stores its axis once, in the
# parent cluster's local frame. World-space is derived lazily on every API
# response via _inject_joint_world_axes. These tests verify:
#   1. The local-frame fields are invariant under repeated cluster transforms
#      (drift-free).
#   2. The injected world-space fields update correctly when the cluster moves.
#   3. Legacy world-space designs (axis_origin / axis_direction) migrate
#      cleanly via the Design pre-validator.

def test_local_axis_is_invariant_under_repeated_cluster_transforms(cluster_id):
    """Place a joint, then PATCH the cluster many times. The stored
    local_axis_origin / local_axis_direction must NOT drift."""
    r = client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": _AXIS_ORIGIN, "axis_direction": _AXIS_DIRECTION},
    )
    assert r.status_code == 200
    j0 = r.json()["design"]["cluster_joints"][0]
    initial_local_origin = list(j0["local_axis_origin"])
    initial_local_dir    = list(j0["local_axis_direction"])

    # Apply 30 different cluster transforms in succession.
    for k in range(30):
        theta = (k + 1) * 0.137
        qz = math.sin(theta / 2)
        qw = math.cos(theta / 2)
        r = client.patch(f"/api/design/cluster/{cluster_id}", json={
            "translation": [0.3 * k, -0.2 * k, 0.1 * k],
            "rotation":    [0.0, 0.0, qz, qw],
            "pivot":       [0.5, 0.5, 0.5],
            "commit":      True,
        })
        assert r.status_code == 200

    # Read back the joint; local-frame fields must be unchanged.
    design = client.get("/api/design").json()["design"]
    j_final = design["cluster_joints"][0]
    assert j_final["local_axis_origin"]    == pytest.approx(initial_local_origin, abs=1e-12)
    assert j_final["local_axis_direction"] == pytest.approx(initial_local_dir,    abs=1e-12)


def test_world_axes_injected_match_local_to_world(cluster_id):
    """After a cluster transform, the injected axis_origin / axis_direction
    must equal _local_to_world_joint(local, ct)."""
    from backend.core.models import _local_to_world_joint

    client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": [1.0, 0.0, 0.0], "axis_direction": [0.0, 0.0, 1.0]},
    )
    # Rotate the cluster 90° about +Y around pivot (0,0,0), then translate.
    qy = math.sin(math.pi / 4)
    qw = math.cos(math.pi / 4)
    r = client.patch(f"/api/design/cluster/{cluster_id}", json={
        "translation": [10.0, 0.0, 0.0],
        "rotation":    [0.0, qy, 0.0, qw],
        "pivot":       [0.0, 0.0, 0.0],
        "commit":      True,
    })
    assert r.status_code == 200

    design = r.json()["design"]
    ct = next(c for c in design["cluster_transforms"] if c["id"] == cluster_id)
    j  = design["cluster_joints"][0]

    expected_origin, expected_dir = _local_to_world_joint(
        j["local_axis_origin"], j["local_axis_direction"], ct,
    )
    assert j["axis_origin"]    == pytest.approx(expected_origin, abs=1e-9)
    assert j["axis_direction"] == pytest.approx(expected_dir,    abs=1e-9)


def test_migrate_legacy_world_space_joint(cluster_id):
    """A design dict with old-schema cluster_joints (axis_origin /
    axis_direction in world space) must round-trip through Design.from_dict
    and emerge with local_axis_origin / local_axis_direction populated such
    that re-deriving world coords reproduces the original world axes."""
    from backend.core.models import Design, _local_to_world_joint

    design = design_state.get_or_404()
    # Move the cluster off-identity so the migration math is non-trivial.
    qz = math.sin(math.pi / 6)
    qw = math.cos(math.pi / 6)
    ct = design.cluster_transforms[0].model_copy(update={
        "translation": [3.0, -2.0, 1.0],
        "rotation":    [0.0, 0.0, qz, qw],
        "pivot":       [1.0, 1.0, 1.0],
    })
    moved = design.copy_with(cluster_transforms=[ct])

    # Synthesise a legacy joint dict (old schema) and inject it.
    legacy_world_origin = [4.5, 1.5, 0.0]
    legacy_world_dir    = [0.0, 0.0, 1.0]
    raw = moved.to_dict()
    raw["cluster_joints"] = [{
        "id":             "legacy-j-1",
        "cluster_id":     cluster_id,
        "name":           "Legacy",
        "joint_type":     "revolute",
        "axis_origin":    legacy_world_origin,
        "axis_direction": legacy_world_dir,
        "surface_detail": 6,
    }]
    # Round-trip through the validator. Expect migration to fire.
    migrated = Design.from_dict(raw)
    assert len(migrated.cluster_joints) == 1
    j = migrated.cluster_joints[0]

    # The legacy fields must be gone.
    j_dict = j.model_dump()
    assert "axis_origin"    not in j_dict
    assert "axis_direction" not in j_dict

    # And re-deriving world coords from the new local frame must reproduce
    # the original world axes (within floating-point tolerance).
    ct_dict = migrated.cluster_transforms[0].model_dump()
    world_origin, world_dir = _local_to_world_joint(
        j.local_axis_origin, j.local_axis_direction, ct_dict,
    )
    assert world_origin == pytest.approx(legacy_world_origin, abs=1e-9)
    assert world_dir    == pytest.approx(legacy_world_dir,    abs=1e-9)


def test_migrate_legacy_world_space_joint_is_idempotent(cluster_id):
    """Running migration twice on already-migrated data must be a no-op."""
    from backend.core.models import Design

    client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": _AXIS_ORIGIN, "axis_direction": _AXIS_DIRECTION},
    )
    design = design_state.get_or_404()
    # First round-trip.
    once  = Design.from_dict(design.to_dict())
    # Second round-trip — must not change anything.
    twice = Design.from_dict(once.to_dict())
    j1 = once.cluster_joints[0]
    j2 = twice.cluster_joints[0]
    assert j1.local_axis_origin    == j2.local_axis_origin
    assert j1.local_axis_direction == j2.local_axis_direction


# ── Phase 3: joint-place / joint-update / joint-delete in feature_log ─────────

def test_patch_joint_logs_minor_op(cluster_id):
    """PATCH /design/joint/{id} appends a 'joint-update' minor op."""
    from backend.core.models import RoutingClusterLogEntry

    jid = _make_joint(cluster_id)
    client.patch(f"/api/design/joint/{jid}", json={"name": "Renamed"})
    log = design_state.get_or_404().feature_log
    assert isinstance(log[-1], RoutingClusterLogEntry)
    last_child = log[-1].children[-1]
    assert last_child.op_subtype == 'joint-update'
    assert last_child.params['joint_id'] == jid
    assert last_child.params['name'] == 'Renamed'


def test_delete_joint_logs_minor_op(cluster_id):
    """DELETE /design/joint/{id} appends a 'joint-delete' minor op."""
    from backend.core.models import RoutingClusterLogEntry

    jid = _make_joint(cluster_id)
    client.delete(f"/api/design/joint/{jid}")
    log = design_state.get_or_404().feature_log
    assert isinstance(log[-1], RoutingClusterLogEntry)
    last_child = log[-1].children[-1]
    assert last_child.op_subtype == 'joint-delete'
    assert last_child.params['joint_id'] == jid


def test_joint_place_replays_deterministically(cluster_id):
    """Replaying a 'joint-place' op against a pre-state must reproduce the
    same joint with the same id and axis. This is what mid-cluster slider
    seek depends on."""
    from backend.api.crud import _replay_minor_op

    r = client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": _AXIS_ORIGIN, "axis_direction": _AXIS_DIRECTION, "name": "Seek"},
    )
    expected_joint = r.json()["design"]["cluster_joints"][0]
    log = design_state.get_or_404().feature_log
    cluster_entry = log[-1]
    minor = cluster_entry.children[-1]
    assert minor.op_subtype == 'joint-place'

    # Hydrate the cluster's pre-state and replay the op.
    from backend.api.state import decode_design_snapshot
    pre_design = decode_design_snapshot(cluster_entry.pre_state_gz_b64)
    replayed = _replay_minor_op(pre_design, minor.op_subtype, minor.params)
    assert len(replayed.cluster_joints) == 1
    j = replayed.cluster_joints[0]
    assert j.id == expected_joint['id']
    assert j.local_axis_origin    == pytest.approx(expected_joint['local_axis_origin'])
    assert j.local_axis_direction == pytest.approx(expected_joint['local_axis_direction'])
    assert j.name == 'Seek'


def test_joint_op_appends_to_open_routing_cluster(cluster_id):
    """Successive joint ops accumulate in one Fine Routing cluster (don't open
    a new one each time)."""
    from backend.core.models import RoutingClusterLogEntry

    client.post(
        f"/api/design/cluster/{cluster_id}/joint",
        json={"axis_origin": _AXIS_ORIGIN, "axis_direction": _AXIS_DIRECTION},
    )
    jid = design_state.get_or_404().cluster_joints[0].id
    client.patch(f"/api/design/joint/{jid}", json={"name": "A"})
    client.patch(f"/api/design/joint/{jid}", json={"name": "B"})
    client.delete(f"/api/design/joint/{jid}")

    log = design_state.get_or_404().feature_log
    cluster_entries = [e for e in log if isinstance(e, RoutingClusterLogEntry)]
    assert len(cluster_entries) == 1
    subtypes = [c.op_subtype for c in cluster_entries[0].children]
    assert subtypes == ['joint-place', 'joint-update', 'joint-update', 'joint-delete']

