"""The registered source routes expose explicit metadata inspection and raw upload."""

import json

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import doc_context, state
from backend.api.part_repair_source_transport import METADATA_HEADER
from backend.api.routes_feature_log import router
from backend.core.part_repair_fingerprint import repair_base_fingerprint
from tests.test_part_repair_source_host import document as document, request
from tests.test_part_repair_sources import NEW, OLD, descriptor


PATH = "/api/design/features/repair-draft/source"


def client_app():
    app = FastAPI()
    app.add_middleware(doc_context.DocContextMiddleware)
    app.include_router(router, prefix="/api")
    return app


def test_registered_inspection_and_proposed_upload_have_no_geometry_effect(document):
    headers = {"X-NADOC-Doc": document}
    before, revision = state.get_design_with_revision()
    with TestClient(client_app()) as client:
        receipt = client.post(f"{PATH}/inspect", headers=headers, json=request())
        assert receipt.status_code == 200, receipt.text
        assert receipt.json()["expected_blob"] == {"state": "missing"}
        assert state.get_or_404() is before and state.revision() == revision
        result = client.post(PATH, content=NEW, headers={**headers,
            "Content-Type": "application/octet-stream", METADATA_HEADER: json.dumps(receipt.json())})
    assert result.status_code == 200, result.text
    after = state.get_or_404()
    assert after.repair_draft is before.repair_draft and after.helices is before.helices
    assert result.json()["repair_draft"]["base_status"] == "unchecked"
    assert descriptor(NEW).sha256 in after.input_sources and before.input_sources == {}
    assert state.revision() == revision + 1 and state.undo_depth() == 0


def test_published_restore_is_explicit_and_stale_receipt_is_not_reusable(document):
    headers = {"X-NADOC-Doc": document}
    before = state.get_or_404()
    with TestClient(client_app()) as client:
        selection = request(operation="restore_published")
        receipt = client.post(f"{PATH}/inspect", headers=headers, json=selection)
        assert receipt.status_code == 200
        upload_headers = {**headers, "Content-Type": "application/octet-stream",
                          METADATA_HEADER: json.dumps(receipt.json())}
        restored = client.post(PATH, content=OLD, headers=upload_headers)
        assert restored.status_code == 200, restored.text
        assert restored.json()["published_source_changed"]
        assert restored.json()["repair_draft"]["base_status"] == "rebase_required"
        repeated = client.post(PATH, content=OLD, headers=upload_headers)
        assert repeated.status_code == 409 and repeated.json()["detail"]["code"] == "draft_conflict"
    after = state.get_or_404()
    assert after.repair_draft is before.repair_draft
    assert repair_base_fingerprint(after) != after.repair_draft.base


def test_registered_source_schema_does_not_accept_bytes_or_candidate_in_metadata(document):
    with TestClient(client_app()) as client:
        bad = client.post(f"{PATH}/inspect", headers={"X-NADOC-Doc": document},
                          json={**request(), "candidate": {}, "raw": "design JSON"})
        assert bad.status_code == 422
        schema = client.get("/openapi.json").json()
    operation = schema["paths"][PATH]["post"]
    assert "application/octet-stream" in operation["requestBody"]["content"]
    assert operation["parameters"][0]["name"] == "X-NADOC-Repair-Source"
    assert state.get_or_404().input_sources == {}
