"""Native cluster joins must move geometry and splice ordinary linear routes atomically."""

from collections import Counter
import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state
from backend.core.deformation import deformed_nucleotide_arrays
from backend.core.lattice import make_bundle_design, make_nick
from backend.core.lattice_frame_model import LatticeFrame
from backend.core.models import ClusterRigidTransform, Design, LatticeType
from backend.core.seamed_router import auto_scaffold_seamed
from backend.core.seamless_router import auto_scaffold_seamless
from backend.core.sequences import domain_bp_range, strand_nucleotide_count
from backend.physics.oxdna_interface import topology_rows, _walk_strand_nucleotides, write_topology


def make_join_design(n_clusters=3, n_helices=6, *, routed=True):
    """Use the real default scaffold router, including its one buried nick.

    This fixture is also used by the real-canvas Playwright test. It never
    reads a user design or replaces a routed linear strand with a closed cycle.
    """
    cells = [(row, col) for row in range(n_helices // 2) for col in range(2)]
    parts = []
    for index in range(n_clusters):
        part = make_bundle_design(cells, 96, lattice_type=LatticeType.SQUARE)
        if routed:
            part, result = (auto_scaffold_seamless if n_helices == 2 else auto_scaffold_seamed)(part)
            assert result.valid, result.errors
            assert len(part.scaffolds()) == 1
        names = {obj.id: f"{obj.id}_join{index}" for obj in [*part.helices, *part.strands]}
        def rename(value):
            if isinstance(value, dict): return {k: rename(v) for k, v in value.items()}
            if isinstance(value, list): return [rename(v) for v in value]
            return names.get(value, value) if isinstance(value, str) else value
        part = Design.model_validate(rename(part.model_dump(mode="json")))
        frame = LatticeFrame(id=f"join_frame_{index}", plane="XY",
                             placement_cluster_id=f"join_cluster_{index}")
        part.lattice_frames = [frame]
        for helix, cell in zip(part.helices, cells, strict=True):
            helix.grid_pos = cell
            helix.lattice_frame_id = frame.id
        for strand in part.strands:
            if strand.is_scaffold and routed:
                strand.id = f"scaffold_join{index}"
                strand.routing_seed = []
            strand.sequence = ("A" if strand.is_scaffold else "T") * strand_nucleotide_count(strand, part)
            if strand.is_scaffold:
                strand.custom_scaffold_length = len(strand.sequence)
        # A meaningful fine edit: a nick unrelated to the selected scaffold
        # ports must survive the join, as must its oligo metadata and sequence.
        staple = next(s for s in part.strands if not s.is_scaffold)
        domain = staple.domains[0]
        nick_bp = list(domain_bp_range(domain))[24]
        part = make_nick(part, domain.helix_id, nick_bp, domain.direction)
        for strand in part.strands:
            if not strand.is_scaffold:
                strand.name = f"manual-oligo-{index}-{strand.id}"
                strand.notes = "Keep this separately nicked oligo"
        angle = math.pi / 2 if index % 2 else 0
        part.cluster_transforms = [ClusterRigidTransform(
            id=f"join_cluster_{index}", name=f"Join fixture {index + 1}",
            helix_ids=[h.id for h in part.helices],
            translation=[index * 32.0, index * 4.0, 0.0],
            rotation=[0.0, math.sin(angle / 2), 0.0, math.cos(angle / 2)],
            pivot=[1.125, 0.0, 16.0],
        )]
        parts.append(part)
    design = Design(lattice_type=LatticeType.SQUARE,
                    helices=[h for p in parts for h in p.helices],
                    strands=[s for p in parts for s in p.strands],
                    crossovers=[x for p in parts for x in p.crossovers],
                    forced_ligations=[x for p in parts for x in p.forced_ligations],
                    lattice_frames=[f for p in parts for f in p.lattice_frames],
                    cluster_transforms=[c for p in parts for c in p.cluster_transforms])
    design.metadata.name = "__e2e__cluster_join_native_linear"
    return design


def backbone_slots(design):
    return Counter((d.helix_id, bp, d.direction.value)
                   for s in design.strands for d in s.domains for bp in domain_bp_range(d))


def physical_positions(design):
    return {h.id: deformed_nucleotide_arrays(h, design)["positions"].copy()
            for h in design.helices}


def snapshot():
    return (state.get_or_404().model_dump_json(), state.revision(),
            state.undo_depth(), state.redo_depth())


@pytest.fixture
def editor(monkeypatch, request):
    from backend.api.main import app
    monkeypatch.setattr(state, "_sessions", {})
    state.set_design(make_join_design(n_helices=getattr(request, "param", 6)))
    return TestClient(app)


def candidates(editor):
    response = editor.get("/api/design/cluster-join/candidates")
    assert response.status_code == 200, response.text
    return response.json()


def join_request(editor, first=0, second=1, first_kind="side", second_kind="end"):
    sites = candidates(editor)["sites"]
    selected = []
    for cluster, kind in [(first, first_kind), (second, second_kind)]:
        selected.append(next(s for s in sites
                             if s["cluster_id"] == f"join_cluster_{cluster}" and s["kind"] == kind))
    return dict(first={"cluster_id": selected[0]["cluster_id"], "port_id": selected[0]["id"]},
                second={"cluster_id": selected[1]["cluster_id"], "port_id": selected[1]["id"]},
                gap_nm=0.8, roll_deg=0.0, tilt_deg=0.0,
                expected_design_id=state.get_or_404().id, expected_revision=state.revision())


def prepare(editor, body):
    response = editor.post("/api/design/cluster-join/preview", json=body)
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["valid"], result
    return {**body, "preview_token": result["token"]}, result


def apply(editor, body):
    response = editor.post("/api/design/cluster-join/apply", json=body)
    assert response.status_code == 200, response.text
    return response.json()


def assert_geometry_equal(actual, expected):
    assert backbone_slots(actual) == backbone_slots(expected)
    assert actual.helices == expected.helices
    a, b = physical_positions(actual), physical_positions(expected)
    assert a.keys() == b.keys()
    for hid in a:
        np.testing.assert_allclose(a[hid], b[hid], atol=1e-8)
    assert actual.strands == expected.strands
    assert actual.crossovers == expected.crossovers
    assert actual.forced_ligations == expected.forced_ligations
    assert actual.cluster_transforms == expected.cluster_transforms
    assert actual.flexible_segment_marks == expected.flexible_segment_marks
    assert actual.flexible_connections == expected.flexible_connections


def assert_original_bases_preserved(before, after, added):
    old, new = backbone_slots(before), backbone_slots(after)
    assert all(new[key] == count for key, count in old.items())
    assert sum(new.values()) - sum(old.values()) == added
    assert all(count == 1 for key, count in new.items() if key not in old)


def assert_exported_join(before, after, added, tmp_path, *, strand_reduction=1):
    old_rows, _ = topology_rows(before)
    rows, nstrands = topology_rows(after)
    steps = list(_walk_strand_nucleotides(after))
    assert len(rows) == len(old_rows) + added == len(steps)
    assert nstrands == len(after.strands) == len(before.strands) - strand_reduction
    assert len({step.key for step in steps}) == len(steps)
    for i, (sid, base, n3, n5) in enumerate(rows):
        if n3 != -1:
            assert rows[n3][3] == i and rows[n3][0] == sid
        if n5 != -1:
            assert rows[n5][2] == i and rows[n5][0] == sid
        if not steps[i].strand.is_scaffold:
            assert base == "T", "Unchanged staple sequence must retain its physical bases"
    # One real chain per strand, including the donor's formerly buried nick.
    for sid in {row[0] for row in rows}:
        starts = [i for i, row in enumerate(rows) if row[0] == sid and row[3] == -1]
        assert len(starts) == 1
        visited = set()
        index = starts[0]
        while index != -1:
            assert index not in visited
            visited.add(index)
            index = rows[index][2]
        assert len(visited) == sum(row[0] == sid for row in rows)
    path = tmp_path / "joined.top"
    write_topology(after, path)
    assert path.read_text().splitlines()[0] == f"{len(rows)} {nstrands}"


@pytest.mark.parametrize("kinds", [("side", "end"), ("end", "side"), ("end", "end")])
@pytest.mark.parametrize("editor", [2, 6], indirect=True)
def test_native_linear_routes_merge_preserving_fine_edits_and_one_undo(editor, kinds, tmp_path):
    before = state.get_or_404().model_copy(deep=True)
    unchanged_staples = [s.model_dump() for s in before.strands if not s.is_scaffold]
    positions = physical_positions(before)
    initial = snapshot()
    body = join_request(editor, first_kind=kinds[0], second_kind=kinds[1])
    assert snapshot() == initial
    body, preview = prepare(editor, body)
    assert snapshot() == initial, "preview must not touch design, revision or undo/redo"
    apply(editor, body)
    after = state.get_or_404().model_copy(deep=True)
    assert len(after.scaffolds()) == len(before.scaffolds()) - 1
    assert_original_bases_preserved(before, after, preview["added_connector_nt"])
    assert [s.model_dump() for s in after.strands if not s.is_scaffold] == unchanged_staples
    assert state.undo_depth() == initial[2] + 1
    assert after.feature_log[-1].op_kind == "cluster-join"
    merged = next(s for s in after.scaffolds() if s.id == "scaffold_join0")
    assert merged.sequence is None
    assert merged.custom_scaffold_length is None
    assert_exported_join(before, after, preview["added_connector_nt"], tmp_path)
    now = physical_positions(after)
    for helix in before.helices:
        if helix.id.endswith("_join1"):
            assert not np.allclose(now[helix.id], positions[helix.id])
        else:
            np.testing.assert_allclose(now[helix.id], positions[helix.id], atol=1e-8)
    assert_geometry_equal(Design.from_json(after.to_json()), after)
    assert editor.post("/api/design/undo").status_code == 200
    assert_geometry_equal(state.get_or_404(), before)
    assert editor.post("/api/design/redo").status_code == 200
    assert_geometry_equal(state.get_or_404(), after)


@pytest.mark.parametrize("change", ["revision", "design", "missing_port", "same_cluster", "token"])
def test_rejected_join_is_transactionally_empty_and_preserves_redo(editor, change):
    body, _ = prepare(editor, join_request(editor))
    apply(editor, body)
    assert editor.post("/api/design/undo").status_code == 200
    body, _ = prepare(editor, join_request(editor))
    if change == "revision": body["expected_revision"] -= 1
    elif change == "design": body["expected_design_id"] = "wrong-document"
    elif change == "missing_port": body["second"]["port_id"] = "missing-port"
    elif change == "same_cluster": body["second"] = dict(body["first"])
    else: body["preview_token"] = "invalid-preview-token"
    before = snapshot()
    response = editor.post("/api/design/cluster-join/apply", json=body)
    assert response.status_code in (400, 404, 409, 422), response.text
    assert snapshot() == before


def test_repeated_join_uses_remaining_host_route_without_moving_previous_donor(editor):
    # Native poses are asserted from state below; response geometry is unused.
    editor.headers["X-NADOC-Skip-Geometry"] = "1"
    original = state.get_or_404().model_copy(deep=True)
    body, preview1 = prepare(editor, join_request(editor))
    apply(editor, body)
    first_join = state.get_or_404().model_copy(deep=True)
    body, preview2 = prepare(editor, join_request(editor, first=0, second=2))
    apply(editor, body)
    final = state.get_or_404()
    assert len(final.scaffolds()) == 1
    assert_original_bases_preserved(original, final,
                                   preview1["added_connector_nt"] + preview2["added_connector_nt"])
    a, b = physical_positions(first_join), physical_positions(final)
    for hid in a:
        if not hid.endswith("_join2"):
            np.testing.assert_allclose(a[hid], b[hid], atol=1e-8)
    prior_delete = snapshot()
    response = editor.delete("/api/design/features/0")
    assert response.status_code == 200, response.text
    assert response.json().get("needs_cascade_decision")
    assert snapshot() == prior_delete
    response = editor.delete("/api/design/features/0?cascade=true")
    assert response.status_code == 200, response.text
    assert_geometry_equal(state.get_or_404(), original)
    assert editor.post("/api/design/undo").status_code == 200
    assert_geometry_equal(state.get_or_404(), final)
    assert editor.post("/api/design/undo").status_code == 200
    assert_geometry_equal(state.get_or_404(), first_join)


def test_native_save_reload_and_history_seek_restore_pose_with_route(editor):
    before = state.get_or_404().model_copy(deep=True)
    body, _ = prepare(editor, join_request(editor))
    apply(editor, body)
    joined = state.get_or_404().model_copy(deep=True)
    exported = editor.get("/api/design/export")
    assert exported.status_code == 200
    state.set_design(Design.from_json(exported.text))
    for position, expected in [(-2, before), (-1, joined), (-2, before), (0, joined)]:
        response = editor.post("/api/design/features/seek", json={"position": position})
        assert response.status_code == 200, response.text
        assert_geometry_equal(state.get_or_404(), expected)


@pytest.mark.parametrize("operation", ["delete", "revert"])
def test_removing_join_restores_original_native_pose_and_routes(editor, operation):
    before = state.get_or_404().model_copy(deep=True)
    body, _ = prepare(editor, join_request(editor))
    apply(editor, body)
    joined = state.get_or_404().model_copy(deep=True)
    response = (editor.delete("/api/design/features/0") if operation == "delete"
                else editor.post("/api/design/features/0/revert"))
    assert response.status_code == 200, response.text
    assert not response.json().get("needs_cascade_decision")
    assert_geometry_equal(state.get_or_404(), before)
    assert not state.get_or_404().feature_log
    assert editor.post("/api/design/undo").status_code == 200
    assert_geometry_equal(state.get_or_404(), joined)


def test_manual_moves_around_join_seek_and_delete_in_chronological_order(editor):
    response = editor.patch("/api/design/cluster/join_cluster_1",
                            json={"translation": [35.0, 5.0, 1.0], "commit": True})
    assert response.status_code == 200, response.text
    before = state.get_or_404().model_copy(deep=True)
    body, _ = prepare(editor, join_request(editor))
    apply(editor, body)
    joined = state.get_or_404().model_copy(deep=True)
    donor = next(c for c in joined.cluster_transforms if c.id == "join_cluster_1")
    translation = [donor.translation[0] + 2.0, *donor.translation[1:]]
    response = editor.patch("/api/design/cluster/join_cluster_1",
                            json={"translation": translation, "commit": True})
    assert response.status_code == 200, response.text
    moved = state.get_or_404().model_copy(deep=True)
    for position, expected in [(0, before), (1, joined), (-1, moved), (1, joined), (-1, moved)]:
        response = editor.post("/api/design/features/seek", json={"position": position})
        assert response.status_code == 200, response.text
        assert_geometry_equal(state.get_or_404(), expected)
    response = editor.delete("/api/design/features/2")
    assert response.status_code == 200, response.text
    assert_geometry_equal(state.get_or_404(), joined)
    assert editor.post("/api/design/undo").status_code == 200
    assert_geometry_equal(state.get_or_404(), moved)


def test_deleting_pre_join_move_cannot_revive_it_by_reverting_join(editor):
    original = state.get_or_404().model_copy(deep=True)
    # Ordinary move history resets to identity before its first committed move.
    donor = next(c for c in original.cluster_transforms if c.id == "join_cluster_1")
    donor.translation = [0.0, 0.0, 0.0]
    donor.rotation = [0.0, 0.0, 0.0, 1.0]
    state.set_design(original)
    response = editor.patch("/api/design/cluster/join_cluster_1",
                            json={"translation": [35.0, 5.0, 1.0], "commit": True})
    assert response.status_code == 200, response.text
    body, _ = prepare(editor, join_request(editor))
    apply(editor, body)
    joined = state.get_or_404().model_copy(deep=True)
    response = editor.delete("/api/design/features/0")
    assert response.status_code == 200, response.text
    assert_geometry_equal(state.get_or_404(), joined)
    response = editor.post("/api/design/features/0/revert")
    assert response.status_code == 200, response.text
    assert_geometry_equal(state.get_or_404(), original)
