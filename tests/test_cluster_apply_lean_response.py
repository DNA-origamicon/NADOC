"""Cluster transform Apply — backend response shape (Plan B).

Plan B's frontend optimisation depends on the PATCH /design/cluster/{id}
endpoint returning a LEAN response (design + validation only, no geometry)
on commit. The frontend's gizmo has already painted correct positions into
the renderer's instance buffers; the backend's role is just to persist
`cluster_transforms[idx]`. The frontend then runs an in-JS reconciliation
(helixCtrl.commitClusterPositions) to keep currentGeometry consistent with
the rendered state.

This test pins the response shape so a future commit can't regress by
re-introducing embedded geometry (Plan A's failed pattern).

Plan: /home/joshua/.claude/plans/we-are-updating-some-adaptive-chipmunk.md
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.core.lattice import make_bundle_design
from backend.core.models import ClusterRigidTransform

client = TestClient(app)


def _two_helix_design():
    return make_bundle_design([(0, 0), (0, 1)], length_bp=84)


@pytest.fixture(autouse=True)
def reset_state():
    design_state.set_design(_two_helix_design())
    yield
    design_state.close_session()


@pytest.fixture()
def cluster_id():
    design = design_state.get_or_404()
    h_id = design.helices[0].id
    ct = ClusterRigidTransform(name="TestCluster", helix_ids=[h_id])
    design_state.set_design(design.copy_with(cluster_transforms=[ct]))
    return ct.id


def test_commit_returns_design_without_geometry(cluster_id):
    """PATCH cluster commit must return a lean response — design + validation
    only. No nucleotides, no helix_axes, no partial_geometry markers."""
    r = client.patch(
        f"/api/design/cluster/{cluster_id}",
        json={
            "translation": [1.0, 0.0, 0.0],
            "rotation":    [0.0, 0.0, 0.0, 1.0],
            "pivot":       [0.0, 0.0, 0.0],
            "commit": True,
            "log":    True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "design" in body
    assert "validation" in body
    # Plan B: no geometry in the commit response.
    assert "nucleotides" not in body, (
        "Plan B regression — PATCH cluster commit returned embedded "
        "nucleotides; Plan A's pattern is known to cause visual snap-back. "
        "See /home/joshua/.claude/plans/we-are-updating-some-adaptive-chipmunk.md"
    )
    assert "helix_axes" not in body
    assert "partial_geometry" not in body
    assert "changed_helix_ids" not in body


def test_live_drag_returns_design_without_geometry(cluster_id):
    """Live drag (commit=False) also returns lean response."""
    r = client.patch(
        f"/api/design/cluster/{cluster_id}",
        json={
            "translation": [0.5, 0.0, 0.0],
            "rotation":    [0.0, 0.0, 0.0, 1.0],
            "pivot":       [0.0, 0.0, 0.0],
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert "nucleotides" not in body
    assert "helix_axes" not in body


def test_commit_persists_cluster_transform(cluster_id):
    """Sanity check: the backend still updates `cluster_transforms[idx]`
    on commit so the next save / load / undo / lazy getGeometry sees
    the new state."""
    r = client.patch(
        f"/api/design/cluster/{cluster_id}",
        json={
            "translation": [3.5, -1.0, 2.0],
            "rotation":    [0.0, 0.0, 0.0, 1.0],
            "pivot":       [0.0, 0.0, 0.0],
            "commit": True,
            "log":    True,
        },
    )
    assert r.status_code == 200, r.text
    body = r.json()
    ct = next(c for c in body["design"]["cluster_transforms"] if c["id"] == cluster_id)
    assert ct["translation"] == pytest.approx([3.5, -1.0, 2.0])

    # And lazily-fetched geometry reflects the cluster transform — this is
    # the path consumers (oxDNA / FEM / atomistic / save) will use when
    # they need fresh positions.
    g = client.get("/api/design/geometry").json()
    h_in_cluster = ct["helix_ids"][0]
    nuc0 = next(n for n in g["nucleotides"] if n["helix_id"] == h_in_cluster)
    # Backbone position should reflect the +3.5 X translation.
    assert nuc0["backbone_position"][0] > 3.0, (
        f"expected backbone_position.x > 3.0 after +3.5x cluster translate, "
        f"got {nuc0['backbone_position']}"
    )


def test_undo_of_cluster_commit_returns_lean_diff(cluster_id):
    """Undoing a cluster transform should take the same Plan-B fast-path
    as the Apply itself: backend signals `diff_kind: 'cluster_only'` and
    includes per-cluster delta records, frontend applies the delta to
    the renderer in-place rather than refetching geometry."""
    # First, commit a cluster transform.
    r = client.patch(
        f"/api/design/cluster/{cluster_id}",
        json={
            "translation": [2.0, 0.0, 0.0],
            "rotation":    [0.0, 0.0, 0.0, 1.0],
            "pivot":       [0.0, 0.0, 0.0],
            "commit": True, "log": True,
        },
    )
    assert r.status_code == 200, r.text

    # Undo — should be cluster-only diff.
    r = client.post("/api/design/undo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("diff_kind") == "cluster_only", (
        f"expected cluster_only diff, got {body.get('diff_kind')!r}; "
        f"backend regression — undo of cluster_op must take the lean path"
    )
    assert "nucleotides" not in body
    assert "helix_axes"  not in body
    diffs = body["cluster_diffs"]
    assert len(diffs) >= 1
    d = next(x for x in diffs if x["cluster_id"] == cluster_id)
    assert d["new_translation"] == pytest.approx([0.0, 0.0, 0.0])
    assert d["old_translation"] == pytest.approx([2.0, 0.0, 0.0])


def test_redo_of_cluster_commit_returns_lean_diff(cluster_id):
    """Same as undo: redo of a cluster transform takes the lean fast path."""
    r = client.patch(
        f"/api/design/cluster/{cluster_id}",
        json={
            "translation": [3.0, -1.0, 0.5],
            "rotation":    [0.0, 0.0, 0.0, 1.0],
            "pivot":       [0.0, 0.0, 0.0],
            "commit": True, "log": True,
        },
    )
    assert r.status_code == 200, r.text
    client.post("/api/design/undo")
    r = client.post("/api/design/redo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("diff_kind") == "cluster_only"
    assert "nucleotides" not in body
    diffs = body["cluster_diffs"]
    d = next(x for x in diffs if x["cluster_id"] == cluster_id)
    assert d["new_translation"] == pytest.approx([3.0, -1.0, 0.5])
    assert d["old_translation"] == pytest.approx([0.0, 0.0, 0.0])


def test_undo_of_topology_change_returns_full_geometry(cluster_id):
    """Undoing a non-cluster mutation (here: nick) must NOT take the
    cluster-only fast path — falls back to the legacy full-geometry
    response so the renderer rebuilds correctly."""
    design = design_state.get_or_404()
    h_id = design.helices[0].id
    r = client.post("/api/design/nick", json={
        "helix_id": h_id, "bp_index": 7, "direction": "FORWARD",
    })
    assert r.status_code in (200, 201), r.text
    r = client.post("/api/design/undo")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("diff_kind") != "cluster_only", (
        "nick undo should NOT be cluster-only — the fast path can't apply "
        "to topology changes"
    )
    # Full geometry is shipped in compact per-helix-per-direction parallel-array
    # form; the legacy `nucleotides` list field is no longer emitted on the
    # full-geometry path. Frontend `_syncFromDesignResponse` re-materialises a
    # flat nuc list from `nucleotides_compact` for the renderer.
    assert "nucleotides_compact" in body
    assert "helix_axes" in body


def test_commit_appends_cluster_op_to_feature_log(cluster_id):
    """Plan B preserves feature_log behavior — commit with log=True still
    appends a ClusterOpLogEntry (used for undo and history)."""
    r = client.patch(
        f"/api/design/cluster/{cluster_id}",
        json={
            "translation": [1.0, 2.0, 3.0],
            "rotation":    [0.0, 0.0, 0.0, 1.0],
            "pivot":       [0.0, 0.0, 0.0],
            "commit": True,
            "log":    True,
        },
    )
    assert r.status_code == 200, r.text
    log = r.json()["design"]["feature_log"]
    assert len(log) >= 1
    last = log[-1]
    assert last["feature_type"] == "cluster_op"
    assert last["cluster_id"] == cluster_id
    assert last["translation"] == pytest.approx([1.0, 2.0, 3.0])


# ── Slider seek — same Plan-B fast paths as undo/redo ─────────────────────────
#
# `_design_replace_response` is shared by /undo, /redo, and /features/seek so
# that scrubbing through cluster_op log entries goes through the lean
# cluster-only diff path (no full geometry recompute, no scene rebuild) — same
# wall-clock as Apply / Ctrl+Z. Seeks that change topology embed full geometry
# in the response, eliminating the legacy second round-trip via getGeometry().

def test_seek_through_cluster_op_returns_lean_diff(cluster_id):
    """Scrubbing the slider across a cluster_op log entry must take the
    cluster-only fast path. Backend signals diff_kind='cluster_only' with
    per-cluster delta records; frontend applies in-place via the same
    _applyClusterUndoRedoDeltas helper used for undo/redo."""
    # Commit a cluster transform so feature_log[0] is a ClusterOpLogEntry.
    client.patch(
        f"/api/design/cluster/{cluster_id}",
        json={
            "translation": [2.0, 0.0, 0.0],
            "rotation":    [0.0, 0.0, 0.0, 1.0],
            "pivot":       [0.0, 0.0, 0.0],
            "commit": True, "log": True,
        },
    )
    # Seek back to pre-F0 (no features active) — should be cluster-only diff.
    r = client.post("/api/design/features/seek", json={"position": -2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("diff_kind") == "cluster_only", (
        f"expected cluster_only diff_kind on cluster_op seek, got "
        f"{body.get('diff_kind')!r}"
    )
    assert "nucleotides" not in body
    assert "helix_axes"  not in body
    diffs = body["cluster_diffs"]
    assert len(diffs) >= 1
    d = next(x for x in diffs if x["cluster_id"] == cluster_id)
    assert d["new_translation"] == pytest.approx([0.0, 0.0, 0.0])
    assert d["old_translation"] == pytest.approx([2.0, 0.0, 0.0])

    # Seek forward to F1 (after the cluster_op) — also cluster-only.
    r = client.post("/api/design/features/seek", json={"position": 0})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("diff_kind") == "cluster_only"
    diffs = body["cluster_diffs"]
    d = next(x for x in diffs if x["cluster_id"] == cluster_id)
    assert d["new_translation"] == pytest.approx([2.0, 0.0, 0.0])
    assert d["old_translation"] == pytest.approx([0.0, 0.0, 0.0])


def test_seek_no_op_takes_positions_only_path(cluster_id):
    """A seek that lands on the current state (no diff at all) hits the
    positions_only path: ``_diff_is_cluster_only`` rejects it (no cluster
    delta), but ``_topology_unchanged`` is True so the compact per-nuc
    payload is shipped instead of the heavy embedded full geometry."""
    r = client.post("/api/design/features/seek", json={"position": -1})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("diff_kind") == "positions_only"
    assert "nucleotides" not in body          # NOT the embedded full path
    assert "positions_by_helix" in body
    pbh = body["positions_by_helix"]
    # Should have at least one helix with FORWARD/REVERSE positions arrays.
    assert pbh, "expected at least one helix in positions_by_helix"
    any_helix = next(iter(pbh.values()))
    any_dir   = next(iter(any_helix.values()))
    assert "bp" in any_dir and "bb" in any_dir
    assert len(any_dir["bp"]) == len(any_dir["bb"])
    assert "helix_axes" in body


def test_seek_topology_change_embeds_full_geometry(cluster_id):
    """A seek that crosses a topology change (here: nick add → strand split)
    falls through to the embedded full-geometry response — Fix B fast paths
    don't apply because nuc inventory changed."""
    design = design_state.get_or_404()
    helix_id = design.helices[0].id
    fwd = next((s for s in design.strands
                if s.domains and s.domains[0].direction.value == "FORWARD"), None)
    assert fwd is not None
    bp = (fwd.domains[0].start_bp + fwd.domains[0].end_bp) // 2
    r = client.post("/api/design/nick", json={
        "helix_id":  helix_id,
        "bp_index":  bp,
        "direction": "FORWARD",
    })
    assert r.status_code in (200, 201)

    # Seek back to before the nick — full embedded geometry, shipped in
    # compact per-helix-per-direction form (`nucleotides_compact`).
    r = client.post("/api/design/features/seek", json={"position": -2})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body.get("diff_kind") not in ("cluster_only", "positions_only")
    assert "nucleotides_compact" in body and isinstance(body["nucleotides_compact"], dict)
    assert any(body["nucleotides_compact"].values()), "expected at least one helix bucket"
    assert "helix_axes" in body
    # Sanity-check the inner shape: at least one helix has FORWARD or REVERSE
    # parallel arrays with bp / bb values.
    any_helix = next(iter(body["nucleotides_compact"].values()))
    any_dir   = next(iter(any_helix.values()))
    assert "bp" in any_dir and "bb" in any_dir
    assert len(any_dir["bp"]) == len(any_dir["bb"])
