"""Historical extrusion edits rebuild native downstream work from inputs.

Tiny designs and transport stay in memory; no application workspace or physical
simulation is used. Native geometry is the response oracle, not cached output.
"""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from backend.api import crud, doc_context, state
from backend.api import part_group_organization_gate as gate
from backend.api import part_publication_policy as policy
from backend.api.main import app
from backend.core import models as m
from backend.core.part_history_contract import create_empty_part
from tests.conftest import valid_overhang_sites
from tests.test_group_organization_history import _append, _poison, _verified
from tests import test_part_pattern_recording as recording

worker = recording.worker
KINDS = ("bundle-create", "extrude-segment", "extrude-continuation",
         "extrude-deformed-continuation", "extrude-frame", "circle-segment", "overhang-extrude")
SEED = "26740451-8372-4577-b506-0952810cc907"
TAIL_SEED = "e86db321-ad47-4a44-929c-8179e0adc555"


def append(design, kind, params, identity):
    return _append(design, m.SnapshotLogEntry(id=identity, op_kind=kind,
        label=kind, params={**params, "_proof_version": 1}))


def recipe(kind, organized):
    empty = create_empty_part("Extrusion history", "HONEYCOMB")
    cells = [[0, 1], [0, 2], [0, 3], [1, 1], [1, 2], [1, 3]] if kind == "overhang-extrude" else [[0, 0]]
    source = append(empty, "bundle-create", crud.BundleRequest(cells=cells,
        length_bp=42 if kind == "overhang-extrude" else 21,
        name="Extrusion history", history_seed=SEED).model_dump(mode="json"), "base")
    index = 0
    if kind != "bundle-create":
        params = {"history_seed": str(uuid4()), "cells": [[4, 4]], "length_bp": 7, "plane": "XY"}
        if kind == "circle-segment":
            params.pop("length_bp")
            params["cell_lengths"] = [7]
        elif kind == "extrude-deformed-continuation":
            params.update(grid_origin=[0, 0, 0], axis_dir=[0, 0, 1],
                          frame_right=[1, 0, 0], frame_up=[0, 1, 0])
        elif kind == "extrude-frame":
            params.update(expected_design_id=source.id, expected_revision=0)
        elif kind == "overhang-extrude":
            params = crud.OverhangExtrudeRequest(**valid_overhang_sites(source)[0],
                length_bp=7, history_seed=str(uuid4())).model_dump(mode="json")
        source = append(source, kind, params, "selected-extrusion")
        index = 1
    if organized:
        source = append(source, "group-organize", {"expected_placement_ids": [
            placement.id for placement in source.cluster_transforms]}, "organize")
    source = append(source, "extrude-segment", {"history_seed": TAIL_SEED,
        "cells": [[8, 8]], "length_bp": 7, "plane": "XY"}, "later-extrusion")
    return source, index


@pytest.fixture(params=[False, True], ids=["legacy", "organized"])
def document(request, monkeypatch):
    token = doc_context.set_current_doc(f"__extrusion_edit__{uuid4()}")
    markers = (doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id())
    monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
    monkeypatch.setattr(policy, "_configuration", (policy.HostPolicyConfiguration(), 7))
    try:
        yield request.param
    finally:
        state.drop_doc(doc_context.get_current_doc())
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(markers[0])
        doc_context.set_request_feature_log_entry_id(markers[1])


def install(source):
    state.load_design(source)
    session = state._sessions[doc_context.get_current_doc()]
    client = TestClient(app, headers={"X-NADOC-Doc": doc_context.get_current_doc()})
    return session, client


def guards(session, index):
    return {"expected_design_id": session.design.id, "expected_revision": session.revision,
            "expected_feature_id": session.design.feature_log[index].id}


@pytest.mark.parametrize("kind", KINDS)
def test_seven_families_edit_evicted_inputs_through_later_features_and_undo(document, worker, kind):
    source, index = recipe(kind, document)
    _verified(source)
    source = _poison(source)
    source.feature_log[index].evicted = True
    session, client = install(source)
    old = session.design
    expected = guards(session, index)
    ids = [row.id for row in old.feature_log]
    helix_ids = [helix.id for helix in old.helices]
    patch = {"cell_lengths": [14]} if kind == "circle-segment" else {"length_bp": 14}
    response = client.post(f"/api/design/features/{index}/edit", json={"params": patch, **expected})
    assert response.status_code == 200, response.text[:500]
    body = response.json()
    assert body["revision"] == expected["expected_revision"] + 1
    assert body["nucleotides"] and body["straight_positions_by_helix"]
    assert not body.get("partial_geometry") and not body.get("geometry_skipped")
    assert body.get("diff_kind") not in {"cluster_only", "positions_only"}
    updated = session.design
    assert [row.id for row in updated.feature_log] == ids
    assert [helix.id for helix in updated.helices] == helix_ids
    assert updated.feature_log[index].params["history_seed"] == old.feature_log[index].params["history_seed"]
    assert updated.feature_log[-1].params == old.feature_log[-1].params
    assert not updated.feature_log[index].evicted
    _verified(m.Design.model_validate_json(updated.model_dump_json()))
    # The editor's original expectations cannot overwrite the accepted result.
    repeated = client.post(f"/api/design/features/{index}/edit", json={"params": patch, **expected})
    assert repeated.status_code == 409, repeated.text[:500]
    assert session.design is updated
    state.undo()
    assert session.design.model_dump(mode="json") == old.model_dump(mode="json")
    state.redo()
    _verified(session.design)


@pytest.mark.parametrize("field", ["expected_design_id", "expected_revision", "expected_feature_id"])
def test_exact_editor_expectations_refuse_without_starting_native_worker(document, worker, field):
    source, index = recipe("extrude-segment", document)
    session, client = install(source)
    expected = guards(session, index)
    expected[field] = expected[field] + 1 if field == "expected_revision" else "different"
    before = recording.saved(session)
    response = client.post(f"/api/design/features/{index}/edit", json={"params": {"length_bp": 14}, **expected})
    assert response.status_code == 409, response.text[:500]
    recording.unchanged(session, before)
    assert not worker.instances


def test_early_extrusion_response_replaces_all_regenerated_suffix_recovery(document, worker):
    source, index = recipe("bundle-create", document)
    session, client = install(source)
    previous = session.design
    old_tail = previous.feature_log[-1]
    response = client.post(f"/api/design/features/{index}/edit", json={
        "params": {"length_bp": 28}, **guards(session, index)})
    assert response.status_code == 200, response.text[:500]
    packet = response.json()
    published = session.design
    new_tail = published.feature_log[-1]
    assert new_tail.id == old_tail.id == "later-extrusion"
    assert new_tail.params == old_tail.params
    assert new_tail.design_snapshot_gz_b64 != old_tail.design_snapshot_gz_b64
    assert new_tail.post_state_gz_b64 != old_tail.post_state_gz_b64
    # Partial-history responses would let the browser backfill these stable IDs
    # with recovery bytes belonging to the previous bundle length.
    assert packet["design"]["feature_log"] == published.model_dump(mode="json")["feature_log"]
    assert not packet.get("feature_log_payloads_partial")
    assert previous.helices[0].length_bp == 21


def test_cannot_edit_an_extrusion_as_a_routing_child(document, worker):
    source, index = recipe("extrude-segment", document)
    session, client = install(source)
    before = recording.saved(session)
    response = client.post(f"/api/design/features/{index}/edit?sub_index=0",
        json={"params": {"length_bp": 14}, **guards(session, index)})
    assert response.status_code == 422, response.text[:500]
    recording.unchanged(session, before)
    assert not worker.instances
