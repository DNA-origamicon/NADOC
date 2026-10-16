"""Private gated HTTP lifecycle with real document context and native tiny DNA."""

import json
from importlib import import_module
from pathlib import Path
import subprocess

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, part_publication_policy as policy, state
from backend.api.part_strict_http import StrictPartDispatch
from backend.core.part_history_contract import assess_part_history
from backend.api.part_proof_commands import dependencies, execute
from tests.test_part_deformation_preview_receipts import receipt_keys
from tests.test_part_deformation_preview_sessions import (
    cancellation, checkpoint, document as document, opening, unchanged, update,
)


PATH = "/api/design/features/deformation-preview"


def routes():
    return import_module("backend.api.routes_part_deformation_preview")


def application():
    app = FastAPI()
    app.include_router(routes().router, prefix="/api")
    return StrictPartDispatch(doc_context.DocContextMiddleware(app))


@pytest.fixture
def client(document, monkeypatch):
    host, identity = document
    monkeypatch.setattr(routes(), "DEFORMATION_PREVIEW_ENABLED", True, raising=False)
    with TestClient(application(), raise_server_exceptions=False) as http:
        yield http, {"X-NADOC-Doc": identity}, host


def test_private_route_defaults_disabled():
    assert routes().DEFORMATION_PREVIEW_ENABLED is False


def test_actual_http_preview_apply_status_cold_proof_and_undo(client):
    http, headers, _ = client
    before = checkpoint()
    response = http.post(PATH, headers=headers, json=opening())
    assert response.status_code == 200, response.text
    opened = response.json()
    assert opened["doc_id"] == headers["X-NADOC-Doc"]
    assert opened["stage"] == "feature" and opened["source_equivalence_checked"] is False
    assert opened["downstream_evaluated"] is False and opened["physical_validity"] is False
    assert opened["before"]["nucleotides"] and opened["candidate"]["nucleotides"]
    evaluated = http.post(PATH + "/evaluate", headers=headers, json=update(opened))
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["request_sequence"] == 1
    controls = http.post(PATH + "/evaluate", headers=headers,
                         json={**update(opened, sequence=2), "include_geometry": False})
    assert controls.status_code == 200 and controls.json()["candidate"] is None
    unchanged(before)
    applied = http.post(PATH + "/apply", headers=headers, json=update(opened, sequence=3))
    assert applied.status_code == 200, applied.text
    receipt = applied.json()
    assert set(receipt) == {"status", *receipt_keys(receipt)}
    assert receipt["status"] == "applied" and receipt["revision"] == before["revision"] + 1
    assert receipt["request_sequence"] == 3
    status = http.post(PATH + "/status", headers=headers, json=cancellation(opened))
    assert status.status_code == 200, status.text
    assert receipt_keys(status.json()) == receipt_keys(receipt)
    # Real Python HTTP bytes must satisfy the actual JavaScript receipt codec,
    # not an independently maintained fixture with more fields than the host.
    checked = subprocess.run(["node", "--input-type=module", "-e", """
        import { previewPublicationReceipt } from './frontend/src/api/deformation_preview_endpoints.js';
        let input = ''; for await (const chunk of process.stdin) input += chunk;
        const { applied, status, context } = JSON.parse(input);
        const receipt = previewPublicationReceipt(applied, context);
        process.stdout.write(JSON.stringify(previewPublicationReceipt(status, context, receipt)));
    """], input=json.dumps({"applied": receipt, "status": status.json(), "context": {
        "docId": headers["X-NADOC-Doc"], "designId": before["source"].id,
        "revision": before["revision"], "loadoutId": None}}), text=True, capture_output=True,
        timeout=5, check=True, cwd=Path(__file__).resolve().parents[1])
    assert receipt_keys(json.loads(checked.stdout)) == receipt_keys(receipt)
    assert assess_part_history(state.get_or_404(), execute=execute, dependencies=dependencies)["status"] == "verified"
    assert state.undo_depth() == len(before["history"]) + 1
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]
    assert http.post(PATH + "/status", headers=headers, json=cancellation(opened)).status_code == 409


def test_lost_apply_response_can_be_resolved_without_retrying_publication(client, monkeypatch):
    http, headers, _ = client
    opened = http.post(PATH, headers=headers, json=opening()).json()
    before = checkpoint()
    original = routes().ORJSONResponse
    lose_first_applied = True

    def lost(value, *args, **kwargs):
        nonlocal lose_first_applied
        if value.get("status") == "applied" and lose_first_applied:
            lose_first_applied = False
            raise RuntimeError("Response disappeared after successful publication")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(routes(), "ORJSONResponse", lost)
    assert http.post(PATH + "/apply", headers=headers, json=update(opened)).status_code == 500
    status = http.post(PATH + "/status", headers=headers, json=cancellation(opened))
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "applied"
    assert status.json()["revision"] == before["revision"] + 1
    assert http.post(PATH + "/apply", headers=headers, json=update(opened, sequence=2)).status_code == 409
    assert state.undo_depth() == len(before["history"]) + 1


def test_cancel_before_prepare_and_after_preview_never_publishes(client):
    http, headers, _ = client
    before = checkpoint()
    request = opening()
    assert http.post(PATH + "/cancel", headers=headers, json=request).json()["status"] == "cancelled"
    assert http.post(PATH, headers=headers, json=request).status_code == 409
    opened = http.post(PATH, headers=headers, json=opening()).json()
    assert http.post(PATH + "/cancel", headers=headers, json=cancellation(opened)).json()["status"] == "cancelled"
    assert http.post(PATH + "/evaluate", headers=headers, json=update(opened)).status_code == 409
    unchanged(before)


def test_document_switch_cannot_apply_or_read_another_documents_lease(client):
    http, headers, _ = client
    opened = http.post(PATH, headers=headers, json=opening()).json()
    before = checkpoint()
    other = {"X-NADOC-Doc": headers["X-NADOC-Doc"] + "-other"}
    for path, body in (("/status", cancellation(opened)), ("/apply", update(opened))):
        assert http.post(PATH + path, headers=other, json=body).status_code == 409
    assert other["X-NADOC-Doc"] not in state._sessions
    unchanged(before)


@pytest.mark.parametrize("strict", [False, True])
def test_disabled_or_strict_route_refuses_before_body_and_host(client, monkeypatch, strict):
    http, headers, host = client
    previous = policy.current_configuration()
    try:
        if strict:
            state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
        else:
            monkeypatch.setattr(routes(), "DEFORMATION_PREVIEW_ENABLED", False)
        monkeypatch.setattr(host, "prepare", lambda *_a: pytest.fail("Disabled route reached host"))
        response = http.post(PATH, headers={**headers, "Content-Type": "application/json"}, content=b"not JSON")
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == ("construction_policy" if strict else "preview_disabled")
    finally:
        state.configure_part_publication_policy(previous)


@pytest.mark.parametrize("content,status", [
    (b"{", 422), (b'{"expected_revision":0,"expected_revision":1}', 422),
    (b'{"expected_revision":NaN}', 422), (b"[]", 422), (b" " * 256_001, 413),
], ids=["malformed-json", "duplicate-key", "nonfinite-number", "nonobject", "oversized-body"])
def test_transport_refusals_never_reach_native_preparation(client, monkeypatch, content, status):
    http, headers, host = client
    before = checkpoint()
    monkeypatch.setattr(host, "prepare", lambda *_a: pytest.fail("Invalid transport reached host"))
    response = http.post(PATH, headers={**headers, "Content-Type": "application/json"}, content=content)
    assert response.status_code == status, response.text
    unchanged(before)


def test_projection_uses_explicit_response_without_generic_fastapi_coordinate_walk(client, monkeypatch):
    import fastapi.routing

    http, headers, _ = client
    monkeypatch.setattr(fastapi.routing, "jsonable_encoder",
                        lambda *_a, **_k: pytest.fail("Private display traversed FastAPI generic encoder"))
    response = http.post(PATH, headers=headers, json=opening())
    assert response.status_code == 200, response.text
    assert json.loads(response.content)["candidate"]["nucleotides"]
