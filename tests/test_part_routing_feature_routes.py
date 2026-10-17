"""Real HTTP routing editors bind acquisition, child identity and full responses.

The evaluator seam is the same in-memory native worker used by the owned-host
tests. These cases exercise actual FastAPI routing and request context ownership;
separate worker tests qualify process transport rather than duplicating it here.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from starlette.requests import Request

from backend.api import crud, doc_context, part_routing_feature_route as routes, state
from backend.api import part_group_organization_gate as gate, part_publication_policy as policy
from backend.api.part_strict_http import StrictPartDispatch
from tests import test_part_routing_owned_edit as owned


document = owned.document
worker = owned.worker


@pytest.fixture
def client(document, worker):
    app = FastAPI()
    app.include_router(crud.router, prefix="/api")
    with TestClient(StrictPartDispatch(doc_context.DocContextMiddleware(app)),
                    raise_server_exceptions=False) as http:
        yield http, {"X-NADOC-Doc": doc_context.get_current_doc()}


def path(document, *, inputs=False):
    return f"/api/design/features/{document[1]}/{'routing-inputs' if inputs else 'edit'}"


def body(document, **changes):
    return {"params": {"bp_index": 10}, **owned.guards(document), **changes}


def canonical_unchanged(session, before):
    # Request markers belong to the ASGI task; canonical session state is shared.
    after = owned.saved(session)
    assert after[0] is before[0] and after[1:3] == before[1:3]
    for previous, current in zip(before[3:5], after[3:5], strict=True):
        assert len(previous) == len(current)
        assert all(a is b for a, b in zip(previous, current, strict=True))


def test_get_returns_exact_pre_child_choices_without_geometry_or_publication(client, document, worker, monkeypatch):
    http, headers = client
    session, _ = document
    before = owned.saved(session)
    monkeypatch.setattr(crud, "_geometry_for_design", lambda *_a, **_k: pytest.fail("Input GET computed geometry"))
    response = http.get(path(document, inputs=True), headers=headers,
                        params={"sub_index": 1, **owned.guards(document)})
    assert response.status_code == 200, response.text
    packet = response.json()
    assert packet["feature_id"] == "routing" and packet["child_id"] == "child-1"
    assert packet["source_design_id"] == session.design.id and packet["source_revision"] == session.revision
    assert packet["kind"] == "nick" and packet["params"]["bp_index"] == 9
    assert len(packet["prefix"]["helices"]) == 2 and len(packet["prefix"]["strands"]) == 5
    assert len(session.design.helices) == 3 and len(session.design.strands) == 8
    assert "nucleotides" not in packet and "candidate" not in packet
    assert len(worker.instances) == 1 and worker.instances[0].closed
    canonical_unchanged(session, before)


def test_post_edit_returns_complete_exact_candidate_and_one_revision(client, document, worker):
    http, headers = client
    session, index = document
    before = owned.saved(session)
    response = http.post(path(document), headers=headers, params={"sub_index": 1}, json=body(document))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["revision"] == before[2] + 1 == session.revision
    assert len(session.history) == len(before[3]) + 1 and not session.redo
    assert data["nucleotides"] and data["helix_axes"]
    assert data["straight_positions_by_helix"] and data["straight_helix_axes"]
    assert not any(data.get(key) for key in ("partial_geometry", "cluster_only", "positions_only"))
    assert data["design"]["id"] == session.design.id
    assert data["design"]["helices"] == session.design.model_dump(mode="json")["helices"]
    # Every rebuilt recovery body must replace the client's old bytes, including
    # later rows whose stable IDs did not change with this child edit.
    assert data["design"]["feature_log"] == session.design.model_dump(mode="json")["feature_log"]
    assert not data.get("feature_log_payloads_partial")
    parent = data["design"]["feature_log"][index]
    assert parent["id"] == "routing" and parent["children"][1]["id"] == "child-1"
    assert parent["children"][1]["params"]["bp_index"] == 10
    assert data["design"]["feature_log"][-1]["id"] == "suffix"
    assert session.design.feature_log[-1].design_snapshot_gz_b64 != before[0].feature_log[-1].design_snapshot_gz_b64
    assert session.design.feature_log[-1].post_state_gz_b64 != before[0].feature_log[-1].post_state_gz_b64
    assert len(worker.instances) == 1 and worker.instances[0].closed
    owned._verified(session.design)
    assert before[0].model_dump_json() == before[1]


@pytest.mark.parametrize("field", ["expected_design_id", "expected_revision", "expected_feature_id", "expected_child_id"])
@pytest.mark.parametrize("inputs", [False, True], ids=["post", "get"])
def test_exact_origin_guards_refuse_before_capture(client, document, worker, monkeypatch, field, inputs):
    http, headers = client
    session, _ = document
    before = owned.saved(session)
    monkeypatch.setattr(owned.host(), "capture", lambda *_a, **_k: pytest.fail("Stale HTTP edit captured source"))
    values = owned.guards(document, **{field: session.revision + 1 if field == "expected_revision" else "wrong"})
    response = (http.get(path(document, inputs=True), headers=headers, params={"sub_index": 1, **values})
                if inputs else http.post(path(document), headers=headers, params={"sub_index": 1},
                                         json={"params": {"bp_index": 10}, **values}))
    assert response.status_code == 409, response.text
    assert not worker.instances
    canonical_unchanged(session, before)


@pytest.mark.parametrize("child", ["omitted", "null"])
def test_incomplete_guarded_child_request_never_falls_back_to_address_only_edit(client, document, worker, monkeypatch, child):
    from backend.api import part_recipe_edit

    http, headers = client
    session, _ = document
    before = owned.saved(session)
    values = body(document, expected_revision=session.revision + 1)
    if child == "omitted":
        del values["expected_child_id"]
    else:
        values["expected_child_id"] = None
    monkeypatch.setattr(part_recipe_edit, "change_recipe", lambda *_a, **_k: pytest.fail("Guarded edit fell back"))
    response = http.post(path(document), headers=headers, params={"sub_index": 1}, json=values)
    assert response.status_code == 409, response.text
    assert not worker.instances
    canonical_unchanged(session, before)


@pytest.mark.parametrize("raw,status", [
    (b'{', 422), (b'[]', 422), (b'{"params":{},"params":{}}', 422),
    (b'{"params":{"bp_index":NaN}}', 422), (b'{"x":"\xff"}', 422),
    (b' ' * 256001, 413),
    (b'{"params":' + b'[' * 66 + b'0' + b']' * 66 + b'}', 422),
    (b'{"params":[' + b'0,' * 10000 + b'0]}', 422),
], ids=["malformed", "array", "duplicate", "nonfinite", "utf8", "bytes", "depth", "nodes"])
def test_bounded_body_refuses_before_native_host(client, document, worker, monkeypatch, raw, status):
    http, headers = client
    session, _ = document
    before = owned.saved(session)
    monkeypatch.setattr(owned.host(), "edit_routing", lambda *_a, **_k: pytest.fail("Malformed transport reached host"))
    response = http.post(path(document), params={"sub_index": 1},
        headers={**headers, "Content-Type": "application/json"}, content=raw)
    assert response.status_code == status, response.text
    assert not worker.instances
    canonical_unchanged(session, before)


def test_get_refuses_body_before_reading_or_starting_worker(client, document, worker, monkeypatch):
    http, headers = client
    before = owned.saved(document[0])
    monkeypatch.setattr(Request, "stream", lambda *_a, **_k: pytest.fail("Input GET acquired a body"))
    response = http.request("GET", path(document, inputs=True), headers=headers,
        params={"sub_index": 1, **owned.guards(document)}, content=b"{}")
    assert response.status_code == 400, response.text
    assert not worker.instances
    canonical_unchanged(document[0], before)


@pytest.mark.parametrize("strict", [False, True], ids=["organization-disabled", "strict"])
def test_policy_refuses_before_request_body(client, document, worker, monkeypatch, strict):
    http, headers = client
    session, _ = document
    if not strict and session.design.group_organization is None:
        # The organization switch must not prohibit guarded legacy authoring.
        monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
        response = http.post(path(document), headers=headers, params={"sub_index": 1}, json=body(document))
        assert response.status_code == 200, response.text
        assert len(worker.instances) == 1 and worker.instances[0].closed
        return
    if strict:
        state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
    else:
        monkeypatch.setattr(gate, "GROUP_ORGANIZATION_ENABLED", False)
    before = owned.saved(session)
    monkeypatch.setattr(Request, "stream", lambda *_a, **_k: pytest.fail("Denied policy acquired body"))
    response = http.post(path(document), headers=headers, content=b"{")
    assert response.status_code == (403 if strict else 409), response.text
    assert not worker.instances
    canonical_unchanged(session, before)


@pytest.mark.parametrize("race", ["source", "incarnation", "session", "revision", "policy"])
def test_body_acquisition_cannot_rebind_replacement_source(client, document, worker, monkeypatch, race):
    http, headers = client
    session, _ = document
    native, observed = routes.read_operation_json, {}
    document_id = headers["X-NADOC-Doc"]

    async def racing(*args, **kwargs):
        value = await native(*args, **kwargs)
        with state._lock:
            if race == "source":
                session.design = session.design.model_copy(deep=True)
            elif race == "incarnation":
                session.identity = "body-reset-incarnation"
            elif race == "session":
                replacement = type(session)()
                replacement.design, replacement.revision = session.design, session.revision
                state._sessions[document_id] = replacement
            elif race == "revision":
                session.revision += 1
            else:
                policy._install_configuration(policy.HostPolicyConfiguration())
            observed["session"] = state._sessions[document_id]
            observed["saved"] = owned.saved(observed["session"])
        return value

    monkeypatch.setattr(routes, "read_operation_json", racing)
    response = http.post(path(document), headers=headers, params={"sub_index": 1}, json=body(document))
    assert response.status_code == 409, response.text
    assert not worker.instances
    canonical_unchanged(observed["session"], observed["saved"])


def test_response_retains_published_candidate_after_another_source_change(client, document, worker, monkeypatch):
    http, headers = client
    session, index = document
    original, observed = crud._design_response_with_geometry, {}

    def racing(candidate, report, **options):
        observed["candidate"], observed["revision"] = candidate, session.revision
        assert options == {"embed_straight": True, "normalize_legacy": False,
                           "preserve_feature_log_id": "routing", "full_feature_log": True}
        with state._lock:
            session.design = candidate.copy_with(strands=[], metadata=candidate.metadata.model_copy(
                update={"name": "Later independent work"}))
            session.revision += 1
        return original(candidate, report, **options)

    monkeypatch.setattr(crud, "_design_response_with_geometry", racing)
    response = http.post(path(document), headers=headers, params={"sub_index": 1}, json=body(document))
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["revision"] == observed["revision"] < session.revision
    assert data["design"]["metadata"]["name"] == observed["candidate"].metadata.name
    assert data["design"]["metadata"]["name"] != session.design.metadata.name
    assert data["nucleotides"] and data["design"]["strands"] and not session.design.strands
    assert data["design"]["feature_log"][index]["children"][1]["params"]["bp_index"] == 10
    assert data["design"]["feature_log"] == observed["candidate"].model_dump(mode="json")["feature_log"]
    assert not data.get("feature_log_payloads_partial")


def test_2d_edit_retains_geometry_skip_contract(client, document, worker, monkeypatch):
    http, headers = client
    monkeypatch.setattr(crud, "_geometry_for_design", lambda *_a, **_k: pytest.fail("2D edit computed geometry"))
    response = http.post(path(document), headers={**headers, "X-NADOC-Skip-Geometry": "1"},
                         params={"sub_index": 1}, json=body(document))
    assert response.status_code == 200, response.text
    assert "nucleotides" not in response.json()
    assert response.json()["revision"] == document[0].revision
