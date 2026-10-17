"""Disabled transform HTTP routes share transport, leases and scalar receipts."""

from importlib import import_module

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, state
from backend.api import part_deformation_preview_sessions as host
from backend.api import part_publication_policy as policy
from backend.api.part_strict_http import StrictPartDispatch
from tests.test_part_transform_preview_sessions import (
    FAMILY, cancellation, checkpoint, document as document, identity, opening,
    unchanged, update, verified,
)


PATH = "/api/design/features/transform-preview"


def routes():
    return import_module("backend.api.routes_part_transform_preview")


@pytest.fixture
def client(document, monkeypatch):
    monkeypatch.setattr(routes(), "TRANSFORM_PREVIEW_ENABLED", True)
    app = FastAPI()
    app.include_router(routes().router, prefix="/api")
    wrapped = StrictPartDispatch(doc_context.DocContextMiddleware(app))
    with TestClient(wrapped, raise_server_exceptions=False) as http:
        yield http, {"X-NADOC-Doc": document}


def test_transform_routes_are_disabled_by_default():
    assert routes().TRANSFORM_PREVIEW_ENABLED is False


def test_actual_http_prepare_controls_only_apply_status_and_undo(client):
    http, headers = client
    before = checkpoint()
    response = http.post(PATH, headers=headers, json=opening())
    assert response.status_code == 200, response.text
    opened = response.json()
    identity(opened, "cluster_op")
    response = http.post(PATH + "/evaluate", headers=headers,
        json={**update(opened, params={"translation": [5, 0, 0]}), "include_geometry": False})
    assert response.status_code == 200, response.text
    assert response.json()["candidate"] is None and response.json()["control_state"]
    unchanged(before)
    response = http.post(PATH + "/apply", headers=headers,
        json=update(opened, sequence=2, params={"translation": [5, 0, 0]}))
    assert response.status_code == 200, response.text
    receipt = response.json()
    identity(receipt, "cluster_op")
    assert receipt["status"] == "applied" and receipt["revision"] == before["revision"] + 1
    response = http.post(PATH + "/status", headers=headers, json=cancellation(opened))
    assert response.status_code == 200, response.text
    assert all(response.json()[key] == value for key, value in receipt.items())
    verified(state.get_or_404())
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


def test_lost_http_apply_response_resolves_without_republishing(client, monkeypatch):
    http, headers = client
    response = http.post(PATH, headers=headers, json=opening())
    assert response.status_code == 200, response.text
    opened = response.json()
    before = checkpoint()
    shared = import_module("backend.api.routes_part_deformation_preview")
    original = shared.ORJSONResponse
    lost = False

    def response(value, *args, **kwargs):
        nonlocal lost
        if value.get("status") == "applied" and not lost:
            lost = True
            raise RuntimeError("Lost response after publication")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(shared, "ORJSONResponse", response)
    assert http.post(PATH + "/apply", headers=headers, json=update(opened)).status_code == 500
    response = http.post(PATH + "/status", headers=headers, json=cancellation(opened))
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "applied"
    assert response.json()["family"] == FAMILY
    assert http.post(PATH + "/apply", headers=headers, json=update(opened, sequence=2)).status_code == 409
    assert state.undo_depth() == len(before["history"]) + 1


@pytest.mark.parametrize("strict", [False, True], ids=["disabled", "strict-policy"])
def test_gate_refusal_precedes_body_acquisition_or_native_host(client, monkeypatch, strict):
    http, headers = client
    previous = policy.current_configuration()
    try:
        if strict:
            state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
        else:
            monkeypatch.setattr(routes(), "TRANSFORM_PREVIEW_ENABLED", False)
        monkeypatch.setattr(host, "prepare", lambda *_a, **_k: pytest.fail("entered host"))
        response = http.post(PATH, headers={**headers, "Content-Type": "application/json"}, content=b"not JSON")
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == ("construction_policy" if strict else "preview_disabled")
    finally:
        state.configure_part_publication_policy(previous)


@pytest.mark.parametrize("content,status", [(b'{"feature_id":"one","feature_id":"two"}', 422),
                                            (b" " * 256_001, 413)], ids=["duplicate-keys", "oversized"])
def test_bounded_closed_transport_refuses_before_native_work(client, monkeypatch, content, status):
    http, headers = client
    before = checkpoint()
    monkeypatch.setattr(host, "prepare", lambda *_a, **_k: pytest.fail("entered host"))
    response = http.post(PATH, headers={**headers, "Content-Type": "application/json"}, content=content)
    assert response.status_code == status, response.text
    unchanged(before)


def test_other_document_cannot_apply_or_cancel_existing_transform(client):
    http, headers = client
    response = http.post(PATH, headers=headers, json=opening())
    assert response.status_code == 200, response.text
    opened = response.json()
    other = {"X-NADOC-Doc": headers["X-NADOC-Doc"] + "-other"}
    before = checkpoint()
    assert http.post(PATH + "/apply", headers=other, json=update(opened)).status_code == 409
    assert http.post(PATH + "/status", headers=other, json=cancellation(opened)).status_code == 409
    assert other["X-NADOC-Doc"] not in state._sessions
    assert http.post(PATH + "/cancel", headers=headers, json=cancellation(opened)).json()["status"] == "cancelled"
    unchanged(before)


def test_transform_route_has_no_creation_endpoint(client):
    http, headers = client
    assert http.post(PATH + "/create", headers=headers, json=opening()).status_code == 404
