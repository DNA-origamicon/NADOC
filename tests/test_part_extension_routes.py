"""Existing extension URLs bind bounded requests and exact candidate responses."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from backend.api import crud, doc_context, routes_extensions as routes, state
from backend.api import part_group_organization_gate as gate, part_publication_policy as policy
from backend.api.part_strict_http import StrictPartDispatch
from tests import test_part_extension_owned_recording as owned
from tests.test_group_organization_recording import before, unchanged


document = owned.document
organized = owned.organized
PATH = "/api/design/extensions"


@pytest.fixture
def client(organized):
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    with TestClient(StrictPartDispatch(doc_context.DocContextMiddleware(app)), raise_server_exceptions=False) as http:
        yield http, {"X-NADOC-Doc": doc_context.get_current_doc()}


def payload(session, **extra):
    return {**owned.values(session)[0], "expected_revision": session.revision, **extra}


def test_http_complete_crud_has_exact_geometry_rows_and_one_revision(client, organized):
    http, headers = client
    revision = organized.revision
    created = http.post(PATH, headers=headers, json=payload(organized))
    assert created.status_code == 201, created.text
    data = created.json()
    identity = data["extension"]["id"]
    assert data["revision"] == revision + 1
    assert data["nucleotides"] and data["helix_axes"] and not data.get("partial_geometry")
    assert any(n.get("extension_id") == identity for n in data["nucleotides"])
    assert data["design"]["feature_log"][-1]["params"]["_proof_version"] == 2
    updated = http.put(f"{PATH}/{identity}", headers=headers, json={"expected_revision": organized.revision, "modification": "cy3"})
    assert updated.status_code == 200, updated.text
    assert updated.json()["extension"]["sequence"] == "AT"
    batch = http.post(f"{PATH}/batch", headers=headers, json={"expected_revision": organized.revision,
        "items": [{"strand_id": organized.design.strands[1].id, "end": "five_prime", "modification": "cy3"}]})
    assert batch.status_code == 200 and len(batch.json()["design"]["extensions"]) == 2
    second = next(ext.id for ext in organized.design.extensions if ext.id != identity)
    for path, body in ((f"{PATH}/{identity}", {}), (f"{PATH}/batch", {"ext_ids": [second, second]})):
        removed = http.request("DELETE", path, headers=headers, json={**body, "expected_revision": organized.revision})
        assert removed.status_code == 200, removed.text
        assert removed.json()["partial_geometry"] and removed.json()["nucleotides"] == []
        assert len(removed.json()["changed_helix_ids"]) == 1
    assert organized.revision == revision + 5 and not organized.design.extensions


@pytest.mark.parametrize("revision", [None, True, -1, "1", 0])
def test_organized_http_requires_exact_strict_revision(client, organized, revision):
    http, headers = client
    saved = before(organized)
    response = http.post(PATH, headers=headers, json=payload(organized, expected_revision=revision))
    assert response.status_code in {409, 422}, response.text
    unchanged(organized, saved)


@pytest.mark.parametrize("raw,status", [
    (b'{', 422), (b'[]', 422), (b'{"sequence":"AT","sequence":"TT"}', 422),
    (b'{"value":NaN}', 422), (b' ' * 256001, 413),
    (b'{"value":' + b'[' * 66 + b'0' + b']' * 66 + b'}', 422),
])
def test_http_rejects_bad_transport_before_recording(client, organized, monkeypatch, raw, status):
    http, headers = client
    saved = before(organized)
    monkeypatch.setattr(routes, "record", lambda *_a, **_k: pytest.fail("Invalid transport reached recorder"))
    response = http.post(PATH, headers={**headers, "Content-Type": "application/json"}, content=raw)
    assert response.status_code == status, response.text
    unchanged(organized, saved)


@pytest.mark.parametrize("kind", ["disabled", "strict"])
def test_policy_refusal_precedes_request_body(client, organized, monkeypatch, kind):
    http, headers = client
    if kind == "disabled": monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    else: state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
    saved = before(organized)
    monkeypatch.setattr(Request, "stream", lambda *_: pytest.fail("Refusal acquired body"))
    response = http.post(PATH, headers=headers, content=b"{")
    assert response.status_code == (403 if kind == "strict" else 409)
    unchanged(organized, saved)


def test_2d_response_skips_native_geometry(client, organized, monkeypatch):
    http, headers = client
    monkeypatch.setattr(crud, "_geometry_for_design", lambda *_a, **_k: pytest.fail("2D computed geometry"))
    response = http.post(PATH, headers={**headers, "X-NADOC-Skip-Geometry": "1"}, json=payload(organized))
    assert response.status_code == 201, response.text
    assert "nucleotides" not in response.json() and response.json()["design"]["extensions"]


@pytest.mark.parametrize("action", ["update", "batch", "empty_upsert", "empty_delete"])
def test_accepted_noop_has_explicit_receipt_and_does_not_add_history(client, organized, action):
    http, headers = client
    created = http.post(PATH, headers=headers, json=payload(organized)).json()
    assert created["no_op"] is False
    saved = before(organized)
    revision = organized.revision
    if action == "update":
        result = http.put(f'{PATH}/{created["extension"]["id"]}', headers=headers,
                          json={"sequence": "AT", "expected_revision": revision})
    else:
        body = {"expected_revision": revision}
        body.update({"ext_ids": []} if action == "empty_delete" else
                    {"items": owned.values(organized) if action == "batch" else []})
        result = http.request("DELETE" if action == "empty_delete" else "POST",
                              f"{PATH}/batch", headers=headers, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["no_op"] is True and result.json()["revision"] == revision
    unchanged(organized, saved)


def test_response_uses_exact_published_candidate_after_another_document_change(client, organized, monkeypatch):
    http, headers = client
    native = routes._design_response_with_geometry
    observed = {}

    def racing(design, report, **options):
        observed["candidate"] = design
        observed["revision"] = organized.revision
        assert options["normalize_legacy"] is False
        with state._lock:
            organized.design = design.copy_with(metadata=design.metadata.model_copy(update={"name": "later edit"}), extensions=[])
            organized.revision += 1
        return native(design, report, **options)

    monkeypatch.setattr(routes, "_design_response_with_geometry", racing)
    response = http.post(PATH, headers=headers, json=payload(organized))
    assert response.status_code == 201, response.text
    result = response.json()
    assert result["revision"] == observed["revision"]
    assert result["design"]["metadata"]["name"] == observed["candidate"].metadata.name
    assert result["design"]["metadata"]["name"] != organized.design.metadata.name
    assert result["design"]["extensions"] and any(n.get("extension_id") for n in result["nucleotides"])
    assert not organized.design.extensions


@pytest.mark.parametrize("race", ["source", "policy", "session"])
def test_request_acquisition_cannot_rebind_a_new_source(client, organized, monkeypatch, race):
    from backend.api import part_extension_transport as transport
    http, headers = client
    native = transport.read_operation_json
    saved = {}

    async def racing(*args, **kwargs):
        value = await native(*args, **kwargs)
        with state._lock:
            if race == "source": organized.design = organized.design.model_copy(deep=True)
            if race == "session": organized.identity = "request-reset-incarnation"
            if race == "policy": policy._install_configuration(policy.HostPolicyConfiguration())
            saved["source"] = before(organized)
        return value

    monkeypatch.setattr(transport, "read_operation_json", racing)
    response = http.post(PATH, headers=headers, json=payload(organized))
    assert response.status_code == 409, response.text
    # Request ContextVars belong to the ASGI task; compare canonical state here.
    current = before(organized)
    expected = saved["source"]
    assert current[0] is expected[0] and current[1:3] == expected[1:3]
    for old, new in zip(expected[3:5], current[3:5]):
        assert len(old) == len(new) and all(a is b for a, b in zip(old, new))
