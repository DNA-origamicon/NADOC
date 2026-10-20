"""Gated real HTTP Sweep editor lifecycle; no workspace or browser artifacts."""

from importlib import import_module

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, state
from backend.api import part_deformation_preview_sessions as host
from backend.api import part_publication_policy as policy
from backend.api.part_strict_http import StrictPartDispatch
from tests.test_part_deformation_preview_receipts import receipt_keys
from tests.test_part_sweep_preview_sessions import (
    cancellation, checkpoint, document as document, opening, unchanged, update, verified,
)


PATH = "/api/design/features/sweep-preview"


def routes():
    return import_module("backend.api.routes_part_sweep_preview")


@pytest.fixture
def client(document, monkeypatch):
    monkeypatch.setattr(routes(), "SWEEP_PREVIEW_ENABLED", True)
    app = FastAPI()
    app.include_router(routes().router, prefix="/api")
    wrapped = StrictPartDispatch(doc_context.DocContextMiddleware(app))
    with TestClient(wrapped, raise_server_exceptions=False) as http:
        yield http, {"X-NADOC-Doc": document}


def test_sweep_route_is_enabled_by_default():
    assert routes().SWEEP_PREVIEW_ENABLED is True


@pytest.mark.parametrize("operation", ["prepare", "evaluate"])
@pytest.mark.parametrize("encoding_fails", [False, True])
def test_preview_gc_pause_covers_encoding_and_restores_after_failure(client, monkeypatch, operation, encoding_fails):
    import gc
    from backend.api import routes_part_deformation_preview as adapter

    was_enabled = gc.isenabled()
    current = policy.require_compatibility(doc_context.get_current_doc(), "sweep_preview")
    def compute(*args, **kwargs):
        assert not gc.isenabled()
        return {"bounded": "preview"}
    def encode(value, **kwargs):
        assert not gc.isenabled()
        if encoding_fails:
            raise RuntimeError("encoding refused")
        return value
    monkeypatch.setattr(host, operation, compute)
    monkeypatch.setattr(adapter, "ORJSONResponse", encode)
    if encoding_fails:
        with pytest.raises(RuntimeError, match="encoding refused"):
            adapter._respond(operation, {}, current.generation, family="sweep")
    else:
        assert adapter._respond(operation, {}, current.generation, family="sweep") == {"bounded": "preview"}
    assert gc.isenabled() == was_enabled


def test_http_prepare_evaluate_apply_status_and_undo_are_native_and_source_bound(client):
    http, headers = client
    before = checkpoint()
    response = http.post(PATH, headers=headers, json=opening())
    assert response.status_code == 200, response.text
    opened = response.json()
    assert opened["doc_id"] == headers["X-NADOC-Doc"]
    assert opened["source_equivalence_checked"] is False
    assert opened["downstream_evaluated"] is False
    evaluated = http.post(PATH + "/evaluate", headers=headers, json=update(opened))
    assert evaluated.status_code == 200, evaluated.text
    assert evaluated.json()["request_sequence"] == 1
    unchanged(before)
    applied = http.post(PATH + "/apply", headers=headers, json=update(opened, sequence=2))
    assert applied.status_code == 200, applied.text
    receipt = applied.json()
    assert receipt["status"] == "applied"
    assert receipt["revision"] == before["revision"] + 1
    status = http.post(PATH + "/status", headers=headers, json=cancellation(opened))
    assert status.status_code == 200, status.text
    assert receipt_keys(status.json()) == receipt_keys(receipt)
    verified(state.get_or_404())
    assert state.undo_depth() == len(before["history"]) + 1
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["json"]


def test_lost_apply_response_resolves_by_status_without_retrying_publication(client, monkeypatch):
    http, headers = client
    opened_response = http.post(PATH, headers=headers, json=opening())
    assert opened_response.status_code == 200, opened_response.text
    opened = opened_response.json()
    before = checkpoint()
    shared = import_module("backend.api.routes_part_deformation_preview")
    original = shared.ORJSONResponse
    lost = False

    def response(value, *args, **kwargs):
        nonlocal lost
        if value.get("status") == "applied" and not lost:
            lost = True
            raise RuntimeError("Lost response after successful publication")
        return original(value, *args, **kwargs)

    monkeypatch.setattr(shared, "ORJSONResponse", response)
    assert http.post(PATH + "/apply", headers=headers, json=update(opened)).status_code == 500
    status = http.post(PATH + "/status", headers=headers, json=cancellation(opened))
    assert status.status_code == 200, status.text
    assert status.json()["status"] == "applied"
    assert status.json()["revision"] == before["revision"] + 1
    assert http.post(PATH + "/apply", headers=headers,
                     json=update(opened, sequence=2)).status_code == 409
    assert state.undo_depth() == len(before["history"]) + 1


def test_cancel_before_open_and_after_evaluation_preserves_current_part(client):
    http, headers = client
    before = checkpoint()
    request = opening()
    assert http.post(PATH + "/cancel", headers=headers, json=request).json()["status"] == "cancelled"
    assert http.post(PATH, headers=headers, json=request).status_code == 409
    response = http.post(PATH, headers=headers, json=opening())
    assert response.status_code == 200, response.text
    opened = response.json()
    assert http.post(PATH + "/evaluate", headers=headers, json=update(opened)).status_code == 200
    assert http.post(PATH + "/cancel", headers=headers,
                     json=cancellation(opened)).json()["status"] == "cancelled"
    assert http.post(PATH + "/apply", headers=headers,
                     json=update(opened, sequence=2)).status_code == 409
    unchanged(before)


def test_other_document_cannot_read_or_apply_lease(client):
    http, headers = client
    response = http.post(PATH, headers=headers, json=opening())
    assert response.status_code == 200, response.text
    opened = response.json()
    other = {"X-NADOC-Doc": headers["X-NADOC-Doc"] + "-other"}
    before = checkpoint()
    assert http.post(PATH + "/status", headers=other, json=cancellation(opened)).status_code == 409
    assert http.post(PATH + "/apply", headers=other, json=update(opened)).status_code == 409
    assert other["X-NADOC-Doc"] not in state._sessions
    unchanged(before)


@pytest.mark.parametrize("strict", [False, True], ids=["disabled", "strict-policy"])
def test_refusal_precedes_body_read_or_native_host(client, monkeypatch, strict):
    http, headers = client
    previous = policy.current_configuration()
    try:
        if strict:
            state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
        else:
            monkeypatch.setattr(routes(), "SWEEP_PREVIEW_ENABLED", False)
        monkeypatch.setattr(host, "prepare", lambda *_a, **_k:
            pytest.fail("Disabled or strict route entered native host"))
        response = http.post(PATH, headers={**headers, "Content-Type": "application/json"}, content=b"not JSON")
        assert response.status_code == 403, response.text
        assert response.json()["detail"]["code"] == ("construction_policy" if strict else "preview_disabled")
    finally:
        state.configure_part_publication_policy(previous)


@pytest.mark.parametrize("content, status", [
    (b'{"expected_revision":0,"expected_revision":1}', 422),
    (b" " * 256_001, 413),
], ids=["duplicate-key", "over-budget"])
def test_closed_bounded_transport_refuses_before_native_work(client, monkeypatch, content, status):
    http, headers = client
    before = checkpoint()
    monkeypatch.setattr(host, "prepare", lambda *_a, **_k:
        pytest.fail("Invalid transport entered native host"))
    response = http.post(PATH, headers={**headers, "Content-Type": "application/json"}, content=content)
    assert response.status_code == status, response.text
    unchanged(before)


def test_sweep_adapter_has_no_creation_endpoint(client):
    http, headers = client
    before = checkpoint()
    assert http.post(PATH + "/create", headers=headers, json=opening()).status_code == 404
    unchanged(before)
