"""Gated, bounded HTTP authoring keeps organization and placement roles separate.

Tiny in-memory native history exercises the real recorder and response boundary.
Transport failures must never reach it; no workspace or application is launched.
"""

import asyncio
from importlib import import_module
import json
from threading import current_thread
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from backend.api import doc_context, part_group_organization_gate as gate
from backend.api import part_publication_policy as policy, state
from backend.api.part_strict_http import StrictPartDispatch
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_group_organization import build
from backend.core.validator import ValidationReport
from tests.test_group_organization_history import history, _verified


PATH = "/api/design/group-organization/commands"


def routes():
    return import_module("backend.api.routes_part_group_organization")


def host():
    return import_module("backend.api.part_group_organization_recording")


def body(kind="group-organize", inputs=None, *, revision=None):
    if inputs is None:
        inputs = {"expected_placement_ids": [item.id for item in state.get_or_404().cluster_transforms]}
    return {"kind": kind, "inputs": inputs,
            "expected_revision": state.revision() if revision is None else revision}


@pytest.fixture
def document(monkeypatch):
    identity = "__group_commands__" + uuid4().hex
    token = doc_context.set_current_doc(identity)
    old_revision = doc_context.current_request_revision()
    old_entry = doc_context.current_request_feature_log_entry_id()
    configuration = policy.current_configuration()
    try:
        source = history()[1][2]
        state.load_design(source)
        monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", True)
        session = state._sessions[identity]
        yield identity, session, source
    finally:
        try:
            state.drop_doc(identity)
            state.configure_part_publication_policy(configuration)
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(old_revision)
            doc_context.set_request_feature_log_entry_id(old_entry)


@pytest.fixture
def client(document):
    app = FastAPI()
    app.include_router(routes().router, prefix="/api")
    application = StrictPartDispatch(doc_context.DocContextMiddleware(app))
    with TestClient(application, raise_server_exceptions=False) as http:
        yield http, {"X-NADOC-Doc": document[0]}


def checkpoint(session):
    return (session.design, session.design.model_dump_json(), session.revision,
            tuple(session.history), tuple(session.redo))


def unchanged(session, before):
    after = checkpoint(session)
    assert after[0] is before[0] and after[1:3] == before[1:3]
    for actual, expected in zip(after[3:], before[3:], strict=True):
        assert len(actual) == len(expected)
        assert all(a is b for a, b in zip(actual, expected, strict=True))


def unexpected(*_args, **_kwargs):
    pytest.fail("Refused transport reached native preparation/publication")


def test_host_switch_defaults_off():
    assert gate.GROUP_ORGANIZATION_ENABLED is False


@pytest.mark.parametrize("strict", [False, True], ids=["disabled", "strict"])
def test_gate_and_policy_refuse_before_reading_any_body(client, document, monkeypatch, strict):
    http, headers = client
    if strict:
        state.configure_part_publication_policy(policy.HostPolicyConfiguration(
            document_modes={document[0]: "registered_only"}))
    else:
        monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    monkeypatch.setattr(Request, "stream", unexpected)
    monkeypatch.setattr(host(), "apply", unexpected)
    before = checkpoint(document[1])
    response = http.post(PATH, headers={**headers, "Content-Type": "application/json"}, content=b"{")
    assert response.status_code == (403 if strict else 409), response.text
    assert response.json()["detail"]["code"] == (
        "construction_policy" if strict else "group_organization_not_enabled")
    unchanged(document[1], before)


@pytest.mark.parametrize("content,status", [
    (b"{", 422), (b"[]", 422), (b'"scalar"', 422),
    (b'{"kind":"group-organize","kind":"group-dissolve"}', 422),
    (b'{"expected_revision":NaN}', 422), (b'{"expected_revision":1e999}', 422),
    (b'{"kind":"\xff"}', 422), (b" " * 256_001, 413),
    (b'{"inputs":' + b"[" * 66 + b"0" + b"]" * 66 + b"}", 422),
], ids=["json", "array", "scalar", "duplicate", "nan", "infinity", "utf8", "bytes", "depth"])
def test_bounded_json_rejects_before_host(client, document, monkeypatch, content, status):
    http, headers = client
    monkeypatch.setattr(host(), "apply", unexpected)
    before = checkpoint(document[1])
    response = http.post(PATH, headers={**headers, "Content-Type": "application/json"}, content=content)
    assert response.status_code == status, response.text
    unchanged(document[1], before)


@pytest.mark.parametrize("patch", [
    {"kind": "cluster_create"}, {"kind": []}, {"inputs": []},
    {"expected_revision": True}, {"expected_revision": -1},
    {"expected_revision": 1.0}, {"expected_revision": "1"},
    {"candidate": {}}, {"enabled": True},
])
def test_closed_request_has_no_authority_or_coercion_controls(client, document, monkeypatch, patch):
    http, headers = client
    monkeypatch.setattr(host(), "apply", unexpected)
    before = checkpoint(document[1])
    response = http.post(PATH, headers=headers, json={**body(), **patch})
    assert response.status_code == 422, response.text
    unchanged(document[1], before)


@pytest.mark.parametrize("extra,status", [
    ({"Content-Type": "text/plain"}, 415),
    ({"Content-Type": "application/json; charset=latin1"}, 415),
    ({"Content-Encoding": "gzip"}, 415),
    ({"Content-Length": "256001"}, 413),
    ({"Content-Length": "-1"}, 400),
])
def test_transport_headers_refuse_before_host(client, monkeypatch, extra, status):
    http, headers = client
    monkeypatch.setattr(host(), "apply", unexpected)
    response = http.post(PATH, headers={**headers, "Content-Type": "application/json", **extra},
                         content=json.dumps(body()))
    assert response.status_code == status, response.text


def test_policy_aba_during_body_acquisition_refuses_before_host(client, document, monkeypatch):
    http, headers = client
    original = routes()._read_request
    configuration = policy.current_configuration()

    async def change_policy(request):
        value = await original(request)
        state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
        state.configure_part_publication_policy(configuration)
        return value

    monkeypatch.setattr(routes(), "_read_request", change_policy)
    monkeypatch.setattr(host(), "apply", unexpected)
    before = checkpoint(document[1])
    response = http.post(PATH, headers=headers, json=body())
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "policy_changed"
    unchanged(document[1], before)


def test_stream_limit_checks_before_retaining_oversized_chunk(document, monkeypatch):
    sent = 0

    async def receive():
        nonlocal sent
        sent += 1
        return {"type": "http.request", "body": b"x" * 256_001, "more_body": True}

    request = Request({"type": "http", "headers": [(b"content-type", b"application/json")]}, receive)
    with pytest.raises(HTTPException) as error:
        asyncio.run(routes()._read_request(request))
    assert error.value.status_code == 413 and sent == 1
    # Refusal releases the one nonqueued acquisition slot.
    valid = Request({"type": "http", "headers": [(b"content-type", b"application/json")]},
                    _receive_once(json.dumps(body()).encode()))
    assert asyncio.run(routes()._read_request(valid))["kind"] == "group-organize"


def _receive_once(payload):
    async def receive():
        return {"type": "http.request", "body": payload, "more_body": False}
    return receive


def test_response_uses_exact_candidate_without_normalization_or_event_loop_work(client, document, monkeypatch):
    from backend.api import crud

    http, headers = client
    source = document[2]
    params = {"_proof_version": 1, "expected_placement_ids": [c.id for c in source.cluster_transforms]}
    row = SnapshotLogEntry(id="new-row", label="Organize", op_kind="group-organize", params=params,
                           design_snapshot_gz_b64="retained-created-body")
    candidate = build("group-organize", source, params).copy_with(feature_log=[*source.feature_log, row])
    expected = candidate.model_dump_json()
    calls = []

    def apply(kind, inputs, *, expected_revision):
        assert doc_context.get_current_doc() == document[0]
        assert not state._lock.locked()
        assert current_thread().name == "AnyIO worker thread"
        calls.append((kind, inputs, expected_revision))
        doc_context.set_request_revision(73)
        return candidate, ValidationReport(), row

    monkeypatch.setattr(host(), "apply", apply)
    monkeypatch.setattr(crud, "_ensure_default_cluster", unexpected)
    response = http.post(PATH, headers=headers, json=body(revision=42))
    assert response.status_code == 200, response.text
    value = response.json()
    assert calls == [("group-organize", {"expected_placement_ids": params["expected_placement_ids"]}, 42)]
    assert value["revision"] == 73
    assert value["design"]["feature_log"][-1]["design_snapshot_gz_b64"] == "retained-created-body"
    assert value["design"]["group_organization"] == candidate.group_organization.model_dump(mode="json")
    assert not {"nucleotides", "helix_axes"} & value.keys()
    assert candidate.model_dump_json() == expected and document[1].design is source


def test_actual_http_conversion_regroup_placement_and_dissolve_cold_replay(client, document):
    http, headers = client
    session, source = document[1:]
    before = source.model_dump_json()
    placement = next(c for c in source.cluster_transforms if c.id == "placement")
    poses = [item.model_dump(mode="json") for item in source.cluster_transforms]

    def post(kind, inputs):
        revision, depth, count = session.revision, len(session.history), len(session.design.feature_log)
        response = http.post(PATH, headers=headers, json=body(kind, inputs, revision=revision))
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["revision"] == revision + 1 == session.revision
        assert len(session.history) == depth + 1
        assert len(session.design.feature_log) == count + 1
        assert value["design"]["feature_log"][-1]["id"] == session.design.feature_log[-1].id
        return value

    post("group-organize", {"expected_placement_ids": [item.id for item in source.cluster_transforms]})
    post("group-dissolve", {"group_ids": [placement.id]})
    response = post("group-create", {"name": "Regrouped", "helix_ids": placement.helix_ids,
                                    "domain_ids": [], "color": "#abcdef", "opacity": 0.4})
    group = next(item for item in response["design"]["group_organization"]["groups"] if item["name"] == "Regrouped")
    post("group-update", {"group_id": group["id"], "fields": {"name": "Edited group"}})
    assert [item.model_dump(mode="json") for item in session.design.cluster_transforms] == poses
    response = post("placement-update", {"placement_id": placement.id, "fields": {"translation": [7, 8, 9]}})
    assert response["nucleotides"] and response["helix_axes"]
    assert next(c for c in session.design.cluster_transforms if c.id == placement.id).translation == [7, 8, 9]
    assert session.design.feature_log[-1].feature_type == "cluster_op"
    assert not session.design.feature_log[-1].authored_fields
    post("group-dissolve", {"group_ids": [group["id"]]})
    _verified(Design.model_validate_json(session.design.model_dump_json()))
    assert source.model_dump_json() == before
    restored, _ = state.undo()
    assert group["id"] in {item.id for item in restored.group_organization.groups}


def test_stale_revision_and_host_failure_are_not_successful_responses(client, document, monkeypatch):
    http, headers = client
    before = checkpoint(document[1])
    stale = http.post(PATH, headers=headers, json=body(revision=document[1].revision + 1))
    assert stale.status_code == 409, stale.text
    unchanged(document[1], before)

    def failed(*_args, **_kwargs):
        raise HTTPException(409, detail={"code": "group_source_changed", "detail": "Changed source"})

    monkeypatch.setattr(host(), "apply", failed)
    refused = http.post(PATH, headers=headers, json=body())
    assert refused.status_code == 409 and refused.json()["detail"]["code"] == "group_source_changed"
    unchanged(document[1], before)


def test_noop_response_keeps_its_checked_revision_when_another_edit_commits(client, document, monkeypatch):
    from backend.api import crud

    http, headers = client
    converted = http.post(PATH, headers=headers, json=body())
    assert converted.status_code == 200, converted.text
    session = document[1]
    group = session.design.group_organization.groups[0]
    source, revision, depth = session.design, session.revision, len(session.history)
    original = crud._design_response

    def later_publication(candidate, report, **kwargs):
        own_revision = doc_context.current_request_revision()
        own_entry = doc_context.current_request_feature_log_entry_id()
        host().apply("group-update", {"group_id": group.id, "fields": {"name": "Later edit"}},
                     expected_revision=session.revision)
        # A different request has its own response context. Preserve the first
        # request's real host stamp while emulating that publication interleave.
        doc_context.set_request_revision(own_revision)
        doc_context.set_request_feature_log_entry_id(own_entry)
        assert candidate is source and session.design is not source
        return original(candidate, report, **kwargs)

    monkeypatch.setattr(crud, "_design_response", later_publication)
    response = http.post(PATH, headers=headers, json=body("group-update",
        {"group_id": group.id, "fields": {"name": group.name}}, revision=revision))
    assert response.status_code == 200, response.text
    assert response.json()["revision"] == revision
    assert response.json()["design"]["group_organization"]["groups"][0]["name"] == group.name
    assert session.revision == revision + 1 and len(session.history) == depth + 1
    assert session.design.group_organization.groups[0].name == "Later edit"
