"""Autoscaffold must finish native joins without discarding their actual bonds."""

import os
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state
from backend.core.cluster_join import _geometry, propose_cluster_join
from backend.core.cluster_join_free import propose_free_cluster_join
from backend.core.flexible_segments import all_cluster_gates
from backend.core.models import Design
from backend.core.scaffold_invariants import scaffold_routing_invariants
from backend.core.seamed_router import auto_scaffold_seamed
from backend.core.seamless_router import auto_scaffold_seamless
from backend.core.topology_integrity import (
    domain_order_errors,
    occupancy_errors,
    junction_errors,
    forced_edge,
)
from tests.test_cluster_join_api import (
    make_join_design,
    backbone_slots,
    assert_exported_join,
)
from tests.test_cluster_join_constraints import unrouted  # noqa: F401
from tests.test_cluster_join_core import request, edges


@pytest.fixture(scope="module")
def joined(unrouted):  # noqa: F811
    design, body = unrouted
    result, report = propose_free_cluster_join(design, body)
    assert report["connection_count"] >= 4
    return result


def assert_routed(before, after, *, seams=True, count=1):
    assert len(after.scaffolds()) == count
    assert not domain_order_errors(after)
    assert not occupancy_errors(after)
    assert not junction_errors(after)
    assert not scaffold_routing_invariants(after, require_seams=seams)
    assert after.forced_ligations == before.forced_ligations
    assert all(forced_edge(fl) in edges(after) for fl in before.forced_ligations)
    assert backbone_slots(before) <= backbone_slots(after)
    assert [s for s in before.strands if not s.is_scaffold] == [
        s for s in after.strands if not s.is_scaffold
    ]
    assert after.cluster_transforms == before.cluster_transforms
    assert len(after.flexible_connections) == len(before.flexible_connections)
    assert all(g["gate"] for g in all_cluster_gates(after).values())
    a, b = _geometry(before), _geometry(after)
    # Helix extension must not move any existing physical attachment.
    for fl in before.forced_ligations:
        for key in forced_edge(fl):
            np.testing.assert_allclose(a[key][0], b[key][0], atol=1e-8)
    original_helices = {h.id: h for h in before.helices}
    assert all(
        h == original_helices[h.id] for h in after.helices if h.id.startswith("join_")
    )


@pytest.mark.parametrize("runner", [auto_scaffold_seamed, auto_scaffold_seamless])
def test_join_then_route_preserves_connections_and_export(joined, runner, tmp_path):
    snapshot = joined.model_dump_json()
    routed, result = runner(joined)
    assert result.valid, result.errors
    assert_routed(joined, routed, seams=runner == auto_scaffold_seamed)
    added = sum(backbone_slots(routed).values()) - sum(backbone_slots(joined).values())
    assert_exported_join(
        joined, routed, added, tmp_path, strand_reduction=len(joined.scaffolds()) - 1
    )
    again, result = runner(routed)
    assert result.valid, result.errors
    assert again.model_dump_json() == routed.model_dump_json()
    assert joined.model_dump_json() == snapshot


def test_already_routed_clusters_can_be_joined_and_rerouted():
    design = make_join_design(2, n_helices=6)
    joined, _ = propose_cluster_join(design, request(design))
    routed, result = auto_scaffold_seamed(joined)
    assert result.valid, result.errors
    assert_routed(joined, routed)


def test_unconnected_cluster_is_routed_separately(joined):
    third = make_join_design(3, n_helices=8, routed=False)
    ids = set(third.cluster_transforms[2].helix_ids)
    extended = joined.copy_with(
        helices=joined.helices + [h for h in third.helices if h.id in ids],
        strands=joined.strands
        + [s for s in third.strands if s.domains[0].helix_id in ids],
        cluster_transforms=joined.cluster_transforms + [third.cluster_transforms[2]],
        lattice_frames=joined.lattice_frames + [third.lattice_frames[2]],
    )
    routed, result = auto_scaffold_seamed(extended)
    assert result.valid, result.errors
    assert len(routed.scaffolds()) == 2
    assert all(forced_edge(fl) in edges(routed) for fl in joined.forced_ligations)
    assert not junction_errors(routed)
    assert not occupancy_errors(routed)


def test_routing_failure_is_atomic(joined, monkeypatch):
    from types import SimpleNamespace
    import backend.core.join_scaffold_router as router

    monkeypatch.setattr(router, "milp", lambda *a, **kw: SimpleNamespace(x=None))
    snapshot = joined.model_dump_json()
    after, result = auto_scaffold_seamed(joined)
    assert not result.valid
    assert "preserving every Join bond" in result.errors[0]
    assert after.model_dump_json() == snapshot == joined.model_dump_json()


def test_autoscaffold_api_is_one_undoable_operation(joined, monkeypatch):
    from backend.api.main import app

    monkeypatch.setattr(state, "_sessions", {})
    state.set_design(joined.model_copy(deep=True))
    client = TestClient(app)
    depth = state.undo_depth()
    response = client.post("/api/design/auto-scaffold-seamed")
    assert response.status_code == 200, response.text
    after = state.get_or_404().model_copy(deep=True)
    assert_routed(joined, after)
    assert state.undo_depth() == depth + 1
    assert after.feature_log[-1].op_kind == "auto-scaffold-seamed"
    assert client.post("/api/design/undo").status_code == 200
    assert state.get_or_404().strands == joined.strands
    assert state.get_or_404().forced_ligations == joined.forced_ligations
    assert client.post("/api/design/redo").status_code == 200
    assert state.get_or_404().strands == after.strands
    assert state.get_or_404().flexible_segment_marks == after.flexible_segment_marks


@pytest.mark.skipif(
    not os.environ.get("NADOC_JOIN_VERIFY_DESIGN"),
    reason="Optional local design validation",
)
@pytest.mark.parametrize("runner", [auto_scaffold_seamed, auto_scaffold_seamless])
def test_temporary_user_design_routes_without_losing_join_bonds(tmp_path, runner):
    source = Path(os.environ["NADOC_JOIN_VERIFY_DESIGN"])
    original = source.read_bytes()
    temporary = tmp_path / "T-junction.nadoc"
    temporary.write_bytes(original)
    design = Design.model_validate_json(temporary.read_text())
    after, result = runner(design)
    assert result.valid, result.errors
    assert_routed(design, after, seams=runner == auto_scaffold_seamed)
    temporary.write_text(after.model_dump_json())
    assert_routed(
        design,
        Design.model_validate_json(temporary.read_text()),
        seams=runner == auto_scaffold_seamed,
    )
    from backend.physics.oxdna_interface import topology_rows, write_topology

    rows, nstrands = topology_rows(after)
    assert nstrands == len(after.strands)
    for i, (sid, base, n3, n5) in enumerate(rows):
        if n3 != -1:
            assert rows[n3][3] == i and rows[n3][0] == sid
        if n5 != -1:
            assert rows[n5][2] == i and rows[n5][0] == sid
    for sid in {row[0] for row in rows}:
        roots = [i for i, row in enumerate(rows) if row[0] == sid and row[3] == -1]
        assert len(roots) == 1
        visited, node = set(), roots[0]
        while node != -1:
            assert node not in visited
            visited.add(node)
            node = rows[node][2]
        assert len(visited) == sum(row[0] == sid for row in rows)
    write_topology(after, tmp_path / "T-junction.top")
    assert source.read_bytes() == original


def test_routing_preserves_assigned_bases(joined):
    from backend.core.scaffold_safety import sequence_keys
    from backend.core.sequences import strand_sequence_length

    before = joined.copy_with(
        strands=[
            s.model_copy(
                update={
                    "sequence": "ACGT" * (strand_sequence_length(joined, s) // 4)
                    + "ACGT"[: strand_sequence_length(joined, s) % 4]
                }
            )
            if s.is_scaffold
            else s
            for s in joined.strands
        ]
    )
    assigned = {
        key: base
        for s in before.scaffolds()
        for key, base in zip(sequence_keys(before, s), s.sequence)
    }
    after, result = auto_scaffold_seamed(before)
    assert result.valid, result.errors
    actual = {
        key: base
        for s in after.scaffolds()
        for key, base in zip(sequence_keys(after, s), s.sequence)
    }
    assert assigned.items() <= actual.items()
    assert all(actual[key] == "N" for key in actual.keys() - assigned.keys())


def test_switching_to_seamless_does_not_reuse_seamed_route(joined):
    from backend.core.crossover_positions import scaffold_seam_positions

    seamed, result = auto_scaffold_seamed(joined)
    assert result.valid, result.errors
    assert scaffold_seam_positions(seamed)
    seamless, result = auto_scaffold_seamless(seamed)
    assert result.valid, result.errors
    assert not scaffold_seam_positions(seamless)
    assert_routed(joined, seamless, seams=False)
