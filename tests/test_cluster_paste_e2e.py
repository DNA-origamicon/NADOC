"""End-to-end tests for POST /design/cluster-paste.

Covers what the pure-core tests can't reach: the feature-log entry (and the
rollback / revert / delete it buys), and that `reconcile_cluster_membership`
running inside `mutate_with_feature_log` doesn't steal the pasted helices.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.api import state as design_state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.models import (
    ClusterRigidTransform,
    Design,
    Direction,
    Domain,
    Helix,
    LatticeType,
    Strand,
    StrandType,
    Vec3,
)


@pytest.fixture(autouse=True)
def _reset():
    design_state.set_design(_demo_design())
    yield
    design_state.set_design(_demo_design())


@pytest.fixture
def client():
    return TestClient(app)


def _seed() -> Design:
    """One helix at HC (0,0) in cluster 'cA'. A Δ=(0,+2) paste lands adjacent."""
    h = Helix(
        id="h_XY_0_0",
        axis_start=Vec3(x=0, y=0, z=0),
        axis_end=Vec3(x=0, y=0, z=100 * 0.34),
        length_bp=100,
        grid_pos=(0, 0),
    )
    s = Strand(
        id="s0",
        domains=[
            Domain(helix_id=h.id, start_bp=0, end_bp=99, direction=Direction.FORWARD)
        ],
        strand_type=StrandType.STAPLE,
    )
    return Design(
        lattice_type=LatticeType.HONEYCOMB,
        helices=[h],
        strands=[s],
        cluster_transforms=[
            ClusterRigidTransform(id="cA", name="Cluster A", helix_ids=[h.id])
        ],
    )


def test_paste_adds_helix_and_cluster(client):
    design_state.set_design(_seed())
    r = client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["cA"], "delta_row": 0, "delta_col": 2},
    )
    assert r.status_code == 200, r.text
    d = r.json()["design"]

    assert len(d["helices"]) == 2
    assert len(d["cluster_transforms"]) == 2
    new_cells = {tuple(h["grid_pos"]) for h in d["helices"]}
    assert new_cells == {(0, 0), (0, 2)}

    rep = r.json()["paste_report"]
    assert rep["requested_cluster_ids"] == ["cA"]
    assert rep["auto_added_cluster_ids"] == []
    assert rep["copied_helix_ids"] == ["h_XY_0_0"]


def test_paste_does_not_steal_helices_into_source_cluster(client):
    """The MutationReport orphan hint must survive the route's reconcile pass."""
    design_state.set_design(_seed())
    r = client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["cA"], "delta_row": 0, "delta_col": 2},
    )
    assert r.status_code == 200, r.text
    cts = {c["id"]: c for c in r.json()["design"]["cluster_transforms"]}

    assert cts["cA"]["helix_ids"] == ["h_XY_0_0"], "source cluster absorbed the copy"
    new = next(c for cid, c in cts.items() if cid != "cA")
    assert new["helix_ids"] == ["h_XY_0_2"]
    assert new["is_default"] is False


def test_paste_emits_a_feature_log_entry(client):
    design_state.set_design(_seed())
    r = client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["cA"], "delta_row": 0, "delta_col": 2},
    )
    log = r.json()["design"]["feature_log"]
    assert len(log) == 1
    assert log[0]["feature_type"] == "snapshot"
    assert log[0]["op_kind"] == "cluster-paste"
    assert "Paste 1 cluster" in log[0]["label"]


def test_paste_is_revertable(client):
    design_state.set_design(_seed())
    client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["cA"], "delta_row": 0, "delta_col": 2},
    )
    r = client.post("/api/design/features/0/revert")
    assert r.status_code == 200, r.text
    d = r.json()["design"]
    assert len(d["helices"]) == 1
    assert len(d["cluster_transforms"]) == 1
    assert d["feature_log"] == []


def test_paste_is_undoable(client):
    design_state.set_design(_seed())
    client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["cA"], "delta_row": 0, "delta_col": 2},
    )
    r = client.post("/api/design/undo")
    assert r.status_code == 200, r.text
    assert len(r.json()["design"]["helices"]) == 1


def test_paste_is_deletable_from_the_feature_log(client):
    design_state.set_design(_seed())
    client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["cA"], "delta_row": 0, "delta_col": 2},
    )
    r = client.delete("/api/design/features/0?cascade=true")
    assert r.status_code == 200, r.text
    assert len(r.json()["design"]["helices"]) == 1


def test_odd_parity_paste_returns_400(client):
    design_state.set_design(_seed())
    r = client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["cA"], "delta_row": 0, "delta_col": 1},
    )
    assert r.status_code == 400
    assert "odd parity" in r.json()["detail"]


def test_collision_returns_400(client):
    design_state.set_design(_seed())
    client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["cA"], "delta_row": 0, "delta_col": 2},
    )
    r = client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["cA"], "delta_row": 0, "delta_col": 2},
    )
    assert r.status_code == 400
    assert "collides" in r.json()["detail"]


def test_unknown_cluster_returns_400(client):
    design_state.set_design(_seed())
    r = client.post(
        "/api/design/cluster-paste",
        json={"cluster_ids": ["nope"], "delta_row": 0, "delta_col": 2},
    )
    assert r.status_code == 400
    assert "unknown cluster id" in r.json()["detail"]
