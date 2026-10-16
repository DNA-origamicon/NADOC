"""Ordinary HTTP patterns use owned input replay and exact source guards."""

import pytest
from fastapi.testclient import TestClient

from backend.api import doc_context
from backend.api.main import app
from tests import test_part_pattern_recording as recording
from tests.test_group_organization_history import _verified

document, worker, inputs = recording.document, recording.worker, recording.inputs


@pytest.mark.parametrize("kind", ["linear-pattern", "circular-pattern"])
def test_http_create_and_evicted_edit_preserve_native_contract(document, worker, kind):
    client = TestClient(app, headers={"X-NADOC-Doc": doc_context.get_current_doc()})
    source = document.design
    revision = document.revision
    response = client.post(f"/api/design/{kind}", json={**inputs(kind),
        "expected_design_id": source.id, "expected_revision": revision})
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["revision"] == revision + 1
    assert result["pattern_report"]
    assert result["nucleotides"] and result["straight_positions_by_helix"]
    created = document.design
    entry = created.feature_log[-1]
    assert not {"expected_revision", "expected_design_id", "expected_feature_id"} & entry.params.keys()
    assert entry.params["_organization_copy"] == inputs(kind)["_organization_copy"]
    entry.evicted = True
    entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = ""
    index = len(created.feature_log) - 1
    guards = {"expected_design_id": created.id, "expected_revision": document.revision,
              "expected_feature_id": entry.id}
    response = client.post(f"/api/design/features/{index}/edit", json={
        "params": {"spacing": 19} if kind == "linear-pattern" else {"total_angle": 180}, **guards})
    assert response.status_code == 200, response.text
    assert response.json()["pattern_report"]
    assert response.json()["nucleotides"] and response.json()["straight_positions_by_helix"]
    assert response.json()["design"]["id"] == created.id
    assert len(document.design.helices) == len(created.helices)
    assert not document.design.feature_log[-1].evicted
    _verified(document.design)
    before = document.design.model_dump_json()
    # Reusing the displayed editor's old revision cannot overwrite a later edit.
    response = client.post(f"/api/design/features/{index}/edit", json={
        "params": {"instances": 2}, **guards})
    assert response.status_code == 409, response.text
    assert document.design.model_dump_json() == before


@pytest.mark.parametrize("missing", ["expected_design_id", "expected_revision", "_organization_copy"])
def test_http_organized_creation_never_defaults_missing_intent(document, worker, missing):
    client = TestClient(app, headers={"X-NADOC-Doc": doc_context.get_current_doc()})
    body = {**inputs(), "expected_design_id": document.design.id,
            "expected_revision": document.revision}
    del body[missing]
    before = document.design.model_dump_json()
    response = client.post("/api/design/linear-pattern", json=body)
    assert response.status_code in {409, 422}, response.text
    assert document.design.model_dump_json() == before
    assert not worker.instances


@pytest.mark.parametrize("revision", [True, "1", 1.0, -1])
def test_http_pattern_revision_is_an_exact_nonnegative_integer(document, worker, revision):
    client = TestClient(app, headers={"X-NADOC-Doc": doc_context.get_current_doc()})
    response = client.post("/api/design/linear-pattern", json={**inputs(),
        "expected_design_id": document.design.id, "expected_revision": revision})
    assert response.status_code == 422
    assert not worker.instances
