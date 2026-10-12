"""Unrouted joins create exported bonds immediately; legacy plans remain readable."""

from itertools import combinations

import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from fastapi.testclient import TestClient

from backend.api import state
from backend.core.models import Design
from backend.core.cluster_join import propose_cluster_join
from backend.core.cluster_join_free import propose_free_cluster_join
from backend.core.cluster_join_constraints import realize_join_constraints
from backend.core.cluster_join_matching import maximum_connections
from backend.core.seamed_router import auto_scaffold_seamed
from backend.core.topology_integrity import forced_edge
from tests.test_cluster_join_api import (
    make_join_design,
    backbone_slots,
    assert_exported_join,
)
from tests.test_cluster_join_core import request, edges, key


@pytest.fixture(scope="module")
def unrouted():
    design = make_join_design(2, n_helices=8, routed=False)
    _, manual = propose_cluster_join(
        design, request(design, kinds=("side", "end"), gap=2)
    )
    delta = np.asarray(manual["donor_world_delta"]).reshape(4, 4, order="F")
    body = dict(
        mode="free",
        moving_cluster_id="join_cluster_1",
        world_translation=delta[:3, 3].tolist(),
        world_rotation=Rotation.from_matrix(delta[:3, :3]).as_quat().tolist(),
        reach_nm=6,
        expected_design_id=design.id,
        expected_revision=1,
    )
    return design, body


def assert_bridges_realized(after, report):
    actual = edges(after)
    helices = {h.id: h for h in after.helices}
    for bridge in report["bridges"]:
        hid = bridge["helix_id"]
        assert helices[hid].length_bp == bridge["extra_bases"]
        assert (key(bridge["from"]), (hid, 0, "FORWARD")) in actual
        assert (
            (hid, bridge["extra_bases"] - 1, "FORWARD"),
            key(bridge["to"]),
        ) in actual
    assert all(forced_edge(bond) in actual for bond in after.forced_ligations)


def test_unrouted_apply_creates_all_previewed_connections_and_preserves_pose(
    unrouted, tmp_path
):
    design, body = unrouted
    snapshot = design.model_dump_json()
    after, report = propose_free_cluster_join(design, body)
    assert not report["deferred_routing"]
    assert report["connection_count"] >= 4
    assert not after.cluster_join_constraints
    assert len(report["bridges"]) == 2 * report["connection_count"]
    assert report["added_connector_nt"] > 0
    assert len(after.helices) - len(design.helices) == len(report["bridges"])
    assert len(after.forced_ligations) - len(design.forced_ligations) == 2 * len(
        report["bridges"]
    )
    assert (
        after.cluster_transforms[1].model_dump(mode="json") == report["donor_transform"]
    )
    assert design.model_dump_json() == snapshot
    assert_bridges_realized(after, report)
    assert_exported_join(
        design,
        after,
        report["added_connector_nt"],
        tmp_path,
        strand_reduction=report["connection_count"],
    )
    original_slots, after_slots = backbone_slots(design), backbone_slots(after)
    assert all(after_slots[k] == n for k, n in original_slots.items())
    assert [s for s in after.strands if not s.is_scaffold] == [
        s for s in design.strands if not s.is_scaffold
    ]
    # Unused precursor strands keep their identities, sequence and routing seed.
    attached = {key(b[side]) for b in report["bridges"] for side in ("from", "to")}
    from backend.core.sequences import domain_bp_range

    for strand in design.scaffolds():
        if not any(
            (dm.helix_id, bp, dm.direction.value) in attached
            for dm in strand.domains
            for bp in domain_bp_range(dm)
        ):
            assert next(s for s in after.strands if s.id == strand.id) == strand
    restored = Design.model_validate_json(after.model_dump_json())
    assert_bridges_realized(restored, report)
    with pytest.raises(ValueError, match="connected outside"):
        propose_free_cluster_join(
            after,
            {**body, "world_translation": [0, 0, 0], "world_rotation": [0, 0, 0, 1]},
        )


@pytest.mark.parametrize(
    "kinds", [("side", "end"), ("end", "side"), ("end", "end"), ("side", "side")]
)
def test_manual_unrouted_join_also_creates_real_connections(unrouted, kinds):
    design, _ = unrouted
    after, report = propose_cluster_join(design, request(design, kinds=kinds, gap=2))
    assert not report["deferred_routing"] and report["connection_count"] == 1
    assert not after.cluster_join_constraints
    assert_bridges_realized(after, report)


def test_legacy_saved_connections_remain_realizable(unrouted):
    from backend.core.models import ClusterJoinConstraint, JoinAttachment, JoinEndpoint

    design, body = unrouted
    joined, preview = propose_free_cluster_join(design, body)
    planned = design.model_copy(deep=True)
    planned.cluster_transforms = joined.cluster_transforms
    for i in range(0, len(preview["bridges"]), 2):
        a, b = preview["bridges"][i : i + 2]
        planned.cluster_join_constraints.append(
            ClusterJoinConstraint(
                id=f"legacy_{i}",
                reach_nm=6,
                first=JoinAttachment(
                    cluster_id="join_cluster_0",
                    source=JoinEndpoint(**a["from"]),
                    target=JoinEndpoint(**b["to"]),
                ),
                second=JoinAttachment(
                    cluster_id="join_cluster_1",
                    source=JoinEndpoint(**b["from"]),
                    target=JoinEndpoint(**a["to"]),
                ),
            )
        )
    routed, result = auto_scaffold_seamed(planned)
    assert result.valid, result.errors
    after = realize_join_constraints(routed)
    assert not after.cluster_join_constraints
    assert len(after.helices) - len(routed.helices) == len(preview["bridges"])
    assert all(forced_edge(bond) in edges(after) for bond in after.forced_ligations)


def test_api_preview_is_readonly_apply_realizes_every_bridge_and_undo_redo(
    unrouted, monkeypatch
):
    from backend.api.main import app

    monkeypatch.setattr(state, "_sessions", {})
    design, body = unrouted
    state.set_design(design.model_copy(deep=True))
    client = TestClient(app)
    body = {**body, "expected_revision": state.revision()}
    snapshot = state.get_or_404().model_dump_json()
    preview = client.post("/api/design/cluster-join/preview", json=body).json()
    assert preview["valid"], preview
    assert state.get_or_404().model_dump_json() == snapshot
    applied = client.post(
        "/api/design/cluster-join/apply",
        json={**body, "preview_token": preview["preview_token"]},
    )
    assert applied.status_code == 200, applied.text
    after = state.get_or_404().model_copy(deep=True)
    assert applied.json()["join"]["bridges"] == preview["bridges"]
    assert not after.cluster_join_constraints
    assert_bridges_realized(after, preview)
    assert client.post("/api/design/undo").status_code == 200
    assert state.get_or_404().strands == design.strands
    assert state.get_or_404().helices == design.helices
    assert state.get_or_404().forced_ligations == design.forced_ligations
    assert state.get_or_404().cluster_transforms == design.cluster_transforms
    assert client.post("/api/design/redo").status_code == 200
    assert state.get_or_404().strands == after.strands
    assert state.get_or_404().cluster_transforms == after.cluster_transforms
    assert_bridges_realized(state.get_or_404(), preview)


def test_maximum_matching_uses_augmenting_paths_and_multiple_fixed_clusters():
    def port(hid, cluster):
        return {
            "id": hid,
            "cluster_id": cluster,
            "from": dict(helix_id=hid, bp_index=0, direction="FORWARD"),
            "to": dict(helix_id=hid, bp_index=1, direction="FORWARD"),
        }

    a, b = port("a", "fixed1"), port("b", "fixed2")
    x, y = port("x", "moving"), port("y", "moving")
    candidates = [(a, x, 1, []), (a, y, 2, []), (b, x, 2, [])]
    selected, _ = maximum_connections(candidates)
    assert selected == [1, 2]  # Nearest-first would strand b and y.
    for n in range(1, len(candidates) + 1):
        for subset in combinations(candidates, n):
            selected, _ = maximum_connections(subset)
            oracle = max(
                len(chosen)
                for r in range(n + 1)
                for chosen in combinations(subset, r)
                if len({p[0]["id"] for p in chosen}) == r
                and len({p[1]["id"] for p in chosen}) == r
            )
            assert len(selected) == oracle


@pytest.mark.parametrize("routed", [False, True])
def test_join_connectors_enable_constrained_movement_without_cluster_ownership(
    routed, monkeypatch
):
    from backend.api.main import app
    from backend.core.flexible_segments import all_cluster_gates, cluster_flexible_gate

    monkeypatch.setattr(state, "_sessions", {})
    design = make_join_design(2, n_helices=8, routed=routed)
    after, report = propose_cluster_join(
        design, request(design, kinds=("side", "end"), gap=2)
    )
    connector_ids = {b["helix_id"] for b in report["bridges"]}
    assert not any(
        connector_ids.intersection(c.helix_ids) for c in after.cluster_transforms
    )
    assert len(after.flexible_connections) == len(report["bridges"])
    gates = all_cluster_gates(after)
    for cluster in after.cluster_transforms:
        assert gates[cluster.id]["gate"]
        assert gates[cluster.id]["rigid_blocking"] == []
        assert gates[cluster.id] == cluster_flexible_gate(after, cluster.id)
    state.set_design(after)
    info = TestClient(app).get("/api/design/flexible-connections").json()
    assert info["gates"] == gates
    assert len(info["connections"]) == len(report["bridges"])
    # A second, unmarked bridge must still prevent constrained motion even
    # though the first bridge remains a valid flexible tether.
    blocked = after.model_copy(deep=True)
    hid = report["bridges"][0]["helix_id"]
    strands = {s.id: s for s in blocked.strands}
    blocked.flexible_segment_marks = [
        m
        for m in blocked.flexible_segment_marks
        if strands[m.strand_id].domains[m.domain_index].helix_id != hid
    ]
    assert all(
        not g["gate"] and g["rigid_blocking"]
        for g in all_cluster_gates(blocked).values()
    )


def test_partially_unmarked_join_cannot_enable_an_incomplete_constraint_set(unrouted):
    from backend.core.flexible_segments import all_cluster_gates

    design, body = unrouted
    after, report = propose_free_cluster_join(design, body)
    hid = report["bridges"][0]["helix_id"]
    strands = {s.id: s for s in after.strands}
    mark = next(
        m
        for m in after.flexible_segment_marks
        if strands[m.strand_id].domains[m.domain_index].helix_id == hid
        and m.bp_index == 1
    )
    after.flexible_segment_marks.remove(mark)
    assert all(
        not g["gate"] and g["rigid_blocking"] for g in all_cluster_gates(after).values()
    )
