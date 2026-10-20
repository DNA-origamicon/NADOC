"""Native source rebinding and frame placement through the owned HTTP editor.

All fixtures and recovery bodies stay in memory. One tiny real spawned edit
qualifies the private header/binder transport; other cases use the existing
controlled worker which executes the real evaluator.
"""

from multiprocessing.shared_memory import SharedMemory

import pytest

from backend.api import crud
from backend.api.part_proof_commands import execute
from backend.core import models as m
from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _geometry_for_design
from backend.core.part_history_contract import create_empty_part
from backend.core.part_history_proof import root_design
from backend.core.part_overlay_commands import command_input
from tests.test_group_organization_history import _poison, _verified
from tests.test_group_lineage_resize_pipeline import minor
from tests.test_part_extrusion_edit_routes import (
    TAIL_SEED, append, document, guards, install, recipe, worker,
)
from tests.test_part_pattern_recording import saved, unchanged

__all__ = ["document", "worker"]

SEEDS = ("f337cf3b-ced5-434e-a01e-8f78c1161b31",
         "0ae9f184-2f01-4fbc-a68f-0a53865af01c",
         "cc7c9f09-cfd4-46c3-9ec8-d4282b207a08")


def continuation_history(organized):
    current = create_empty_part("Continuation source edit", "HONEYCOMB")
    for index, seed in enumerate(SEEDS[:2]):
        current = append(current, "extrude-frame", {
            "history_seed": seed, "cells": [[0, 0], [0, 1]], "length_bp": 14,
            "plane": "XY", "translation_nm": [4 + index * 20, 0, 0],
            "expected_design_id": current.id, "expected_revision": 0,
        }, f"frame-{index}")
    frame_a, frame_b = (frame.id for frame in current.lattice_frames)
    if organized:
        current = append(current, "group-organize", {"expected_placement_ids": [
            placement.id for placement in current.cluster_transforms]}, "organize")
    prefix = current
    old_id = next(helix.id for helix in prefix.helices
                  if helix.lattice_frame_id == frame_a and helix.grid_pos == (0, 0))
    params = crud.BundleContinuationRequest(history_seed=SEEDS[2], cells=[[0, 0]],
        length_bp=7, plane="XY", offset_nm=14 * BDNA_RISE_PER_BP,
        source_frame_id=frame_a, ligate_adjacent=False).model_dump(mode="json")
    index = len(current.feature_log)
    current = append(current, "extrude-continuation", {
        **params, "_source_helix_ids": [old_id]}, "continuation")
    current = append(current, "extrude-segment", {"history_seed": TAIL_SEED,
        "cells": [[8, 8]], "length_bp": 7, "plane": "XY"}, "later")
    return current, index, prefix, frame_a, frame_b, old_id


@pytest.mark.parametrize("change_frame", [False, True], ids=["cells", "cells-and-frame"])
def test_continuation_rebinds_selected_receipt_from_original_prefix(document, worker, change_frame):
    source, index, prefix, frame_a, frame_b, old_id = continuation_history(document)
    _verified(source)
    selected_frame = frame_b if change_frame else frame_a
    target_id = next(helix.id for helix in prefix.helices
                     if helix.lattice_frame_id == selected_frame and helix.grid_pos == (0, 1))
    source = _poison(source)
    session, client = install(source)
    original = session.design.model_dump_json()
    response = client.post(f"/api/design/features/{index}/edit", json={
        "params": {"cells": [[0, 1]], "source_frame_id": selected_frame}, **guards(session, index)})
    assert response.status_code == 200, response.text[:600]
    updated = session.design
    assert updated.feature_log[index].params["_source_helix_ids"] == [target_id]
    assert source.feature_log[index].params["_source_helix_ids"] == [old_id]
    assert updated.find_helix(old_id).length_bp == prefix.find_helix(old_id).length_bp == 14
    assert updated.find_helix(target_id).length_bp == 21
    assert updated.feature_log[-1].params == source.feature_log[-1].params
    assert updated.lattice_frames == prefix.lattice_frames
    assert source.model_dump_json() == original
    _verified(m.Design.model_validate_json(updated.model_dump_json()))


def _native_replay_with_patch(source, index, patch):
    current = root_design(source.recipe_root, input_sources=source.input_sources).copy_with(id=source.id)
    for position, row in enumerate(source.feature_log):
        kind, params = command_input(row)
        if position == index:
            params = {**params, **patch}
        current = execute(kind, current, params).copy_with(id=source.id)
    return current


def test_explicit_frame_pose_edit_matches_native_geometry_and_cold_replay(document, worker):
    source, index = recipe("extrude-frame", document)
    patch = {"translation_nm": [8, -3, 2], "rotation_xyzw": [0, 0, 0.6, 0.8]}
    expected = _native_replay_with_patch(source, index, patch)
    old_geometry = _geometry_for_design(source)
    source = _poison(source)
    session, client = install(source)
    original = session.design.model_dump_json()
    response = client.post(f"/api/design/features/{index}/edit", json={
        "params": patch, **guards(session, index)})
    assert response.status_code == 200, response.text[:600]
    updated = session.design
    assert _geometry_for_design(updated) == _geometry_for_design(expected) != old_geometry
    assert deformed_helix_axes(updated) == deformed_helix_axes(expected)
    assert updated.cluster_transforms == expected.cluster_transforms
    assert response.json()["helix_axes"] == deformed_helix_axes(updated)
    assert source.model_dump_json() == original
    _verified(m.Design.model_validate_json(updated.model_dump_json()))


def test_missing_frame_source_returns_exact_reference_without_publication(document, worker):
    source, index = recipe("extrude-frame", document)
    session, client = install(source)
    session.redo.append(m.Design())
    before = saved(session)
    response = client.post(f"/api/design/features/{index}/edit", json={
        "params": {"source_frame_id": "missing-frame"}, **guards(session, index)})
    assert response.status_code == 409, response.text[:600]
    detail = response.json()["detail"]
    assert detail["code"] == "missing_reference"
    issue = detail["assessment"]["issues"][0]
    assert issue["references"] == [{"kind": "lattice_frame", "identity": "missing-frame",
                                     "parameter_path": ["source_frame_id"]}]
    unchanged(session, before)
    assert worker.instances and all(instance.closed for instance in worker.instances)


def test_removing_output_required_by_later_routing_removes_that_routing(document, worker):
    """cadnano-style: removing the helix a later nick acts on removes the nick
    (reported) instead of refusing the extrusion edit."""
    source = create_empty_part("Dependent extrusion output", "HONEYCOMB")
    source = append(source, "extrude-frame", {
        "history_seed": SEEDS[0], "cells": [[0, 0], [0, 1]], "length_bp": 14,
        "plane": "XY", "translation_nm": [4, 0, 0],
        "expected_design_id": source.id, "expected_revision": 0,
    }, "two-cell-frame")
    removed_id = next(helix.id for helix in source.helices if helix.grid_pos == (0, 1))
    if document:
        source = append(source, "group-organize", {"expected_placement_ids": [
            placement.id for placement in source.cluster_transforms]}, "organize")
    source = minor(source, "nick-batch", {"nicks": [{
        "helix_id": removed_id, "bp_index": 5, "direction": "FORWARD"}]})
    _verified(source)
    session, client = install(_poison(source))
    session.redo.append(m.Design())
    response = client.post("/api/design/features/0/edit", json={
        "params": {"cells": [[0, 0]]}, **guards(session, 0)})
    assert response.status_code == 200, response.text[:600]
    payload = response.json()
    assert [r["kind"] for r in payload["removed_features"]] == ["nick-batch"]
    assert any("no longer occupied" in w for w in payload["placement_warnings"])
    published = session.design
    assert not any(e.feature_type == "routing-cluster" for e in published.feature_log)
    assert all(h.id != removed_id for h in published.helices)
    assert worker.instances and all(instance.closed for instance in worker.instances)


@pytest.mark.parametrize("document", [False], indirect=True, ids=["legacy-real-spawn"])
def test_real_spawned_edit_checks_header_and_refreshes_continuation_source(document, monkeypatch):
    from backend.api import part_ordinary_recipe_recording as host

    source, index, prefix, _, frame_b, _ = continuation_history(document)
    session, client = install(_poison(source))
    expected = guards(session, index)
    before = saved(session)
    native_worker = host.EvaluationWorker
    observed = []

    def worker_instance(captured, operation):
        instance = native_worker(captured, operation)
        observed.append((instance, [buffer.name for buffer in instance._buffers], operation))
        return instance

    monkeypatch.setattr(host, "EvaluationWorker", worker_instance)
    try:
        response = client.post(f"/api/design/features/{index}/edit", json={
            "params": {"cells": [[0, 1]], "source_frame_id": frame_b}, **expected})
        assert response.status_code == 200, response.text[:600]
        assert len(observed) == 1
        instance, names, operation = observed[0]
        assert operation["header"]["extrusion_recording_version"] == 1
        assert operation["header"]["expected_feature_id"] == expected["expected_feature_id"]
        target_id = next(helix.id for helix in prefix.helices
                         if helix.lattice_frame_id == frame_b and helix.grid_pos == (0, 1))
        assert session.design.feature_log[index].params["_source_helix_ids"] == [target_id]
        assert session.design.find_helix(target_id).length_bp == 21
        assert session.revision == before[2] + 1 and len(session.history) == len(before[3]) + 1
        assert instance._closed and instance._process_closed and not instance.is_alive()
        for name in names:
            with pytest.raises(FileNotFoundError):
                buffer = SharedMemory(name=name)
                buffer.close()
        _verified(m.Design.model_validate_json(session.design.model_dump_json()))
    finally:
        for instance, _, _ in observed:
            instance.close()


def test_partial_routing_failure_identifies_child_without_publication(document, worker):
    from tests.deformation_history_app import fixture

    source = fixture("extrude-nick-batch")
    if document:
        source = append(source, "group-organize", {"expected_placement_ids": [
            placement.id for placement in source.cluster_transforms]}, "organize")
    session, client = install(source)
    before = saved(session)
    response = client.post("/api/design/features/0/edit", json={
        "params": {"length_bp": 5}, **guards(session, 0)})
    assert response.status_code == 409, response.text
    detail = response.json()["detail"]
    assert detail["feature_id"] == source.feature_log[1].children[0].id
    assert isinstance(detail["detail"], str) and detail["detail"]
    unchanged(session, before)
