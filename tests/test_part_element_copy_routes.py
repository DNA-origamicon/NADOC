"""Explicit same-part copy is bound to the current document and atomic history."""

from copy import deepcopy
from uuid import UUID

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_element_copy_commands as commands, routes_part_element_copy as routes, state
from backend.api import routes_nanoparticles as legacy_routes
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import AUTHORING_FIELDS, ProofBudgetExceeded
from backend.core.part_verification_capture import capture
from tests.test_native_element_copy_proof import recipe
from tests.test_part_element_copy_commands import protein_batch


PATH = "/api/design/features/copy-elements"


@pytest.fixture
def client():
    token = set_current_doc("explicit-same-part-copy-route")
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    app.include_router(legacy_routes.router, prefix="/api")
    state.load_design(recipe(imported=True))
    state.clear_history()
    try:
        with TestClient(app) as api:
            yield api
    finally:
        state.close_session()
        reset_current_doc(token)


def body(**changes):
    return {"nanoparticle_ids": ["first"], "expected_revision": state.revision(),
            "expected_design_id": state.get_or_404().id, **changes}


def unchanged(before, revision, depth):
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision and state.undo_depth() == depth


def test_http_schema_has_explicit_identity_revision_and_no_snapshot_or_output_fields(client):
    schema = client.get("/openapi.json").json()
    operation = schema["paths"][PATH]["post"]
    request_ref = operation["requestBody"]["content"]["application/json"]["schema"]["$ref"]
    request = schema["components"]["schemas"][request_ref.rsplit("/", 1)[1]]
    assert set(request["required"]) == {"expected_revision", "expected_design_id"}
    assert set(request["properties"]) == {"protein_ids", "nanoparticle_ids", "paste_index",
                                          "expected_revision", "expected_design_id"}
    assert request["additionalProperties"] is False


@pytest.mark.parametrize("mixed", [False, True])
def test_host_ids_route_parity_and_single_undo_redo(client, monkeypatch, mixed):
    request = body(protein_ids=["protein"] if mixed else [],
        nanoparticle_ids=["dot", "first"] if mixed else ["first"], paste_index=3)
    output_uuids = [UUID(int=index) for index in range(101, 104)]
    allocation = iter(output_uuids)
    monkeypatch.setattr(routes, "uuid4", lambda: next(allocation))
    before = deepcopy(state.get_or_404())
    revision, depth = state.revision(), state.undo_depth()
    response = client.post(PATH, json=request)
    assert response.status_code == 200, response.text
    current = state.get_or_404()
    entry = current.feature_log[-1]
    assert entry.op_kind == "element-paste" and entry.params["copy_version"] == 1
    assert dependencies(entry.op_kind, entry.params).known
    assert "expected_design_id" not in entry.params and "expected_revision" not in entry.params
    count = len(request["protein_ids"]) + len(request["nanoparticle_ids"])
    assert entry.params["protein_output_ids"] + entry.params["nanoparticle_output_ids"] == [str(x) for x in output_uuids[:count]]
    expected, refs = commands.evaluate("element-paste", before, entry.params)
    assert response.json()["pasted_refs"] == refs
    assert current.model_dump(include=AUTHORING_FIELDS) == expected.model_dump(include=AUTHORING_FIELDS)
    assert execute(entry.op_kind, before, entry.params).model_dump(include=AUTHORING_FIELDS) == current.model_dump(include=AUTHORING_FIELDS)
    assert {"design", "validation", "revision", "pasted_refs"} <= response.json().keys()
    assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
    state.undo()
    assert state.get_or_404().model_dump(include=AUTHORING_FIELDS) == before.model_dump(include=AUTHORING_FIELDS)
    state.redo()
    assert state.get_or_404().model_dump(include=AUTHORING_FIELDS) == current.model_dump(include=AUTHORING_FIELDS)


def test_default_paste_index_and_repeated_calls_allocate_distinct_outputs(client):
    first = client.post(PATH, json=body())
    assert first.status_code == 200, first.text
    first_id = first.json()["pasted_refs"][0]["id"]
    assert state.get_or_404().feature_log[-1].params["paste_index"] == 1
    second = client.post(PATH, json=body(paste_index=2))
    assert second.status_code == 200, second.text
    second_id = second.json()["pasted_refs"][0]["id"]
    assert first_id != second_id and UUID(first_id) != UUID(second_id)
    assert state.get_or_404().nanoparticles[-2].pose.values[3] == 15.0
    assert state.get_or_404().nanoparticles[-1].pose.values[3] == 30.0


@pytest.mark.parametrize("change", [
    lambda b: b.pop("expected_revision"), lambda b: b.pop("expected_design_id"),
    lambda b: b.update(expected_revision=True), lambda b: b.update(expected_design_id=12),
    lambda b: b.update(expected_revision=-1), lambda b: b.update(expected_design_id=""),
    lambda b: b.update(source={}), lambda b: b.update(nanoparticle_output_ids=["caller-output"]),
    lambda b: b.update(protein_output_ids=[]), lambda b: b.update(copy_version=1),
    lambda b: b.update(paste_index=True), lambda b: b.update(paste_index=0),
    lambda b: b.update(nanoparticle_ids=[]), lambda b: b.update(nanoparticle_ids=["first", "first"]),
    lambda b: b.update(nanoparticle_ids=["x"] * (commands.MAX_ELEMENTS + 1)),
])
def test_invalid_request_is_rejected_before_identity_allocation_or_mutation(client, monkeypatch, change):
    request = body()
    change(request)
    before = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    monkeypatch.setattr(routes, "uuid4", lambda: pytest.fail("Invalid request allocated identities"))
    response = client.post(PATH, json=request)
    assert response.status_code == 422, response.text
    unchanged(before, revision, depth)


def test_requires_open_part_without_creating_a_document(client):
    request = body()
    state.close_session()
    response = client.post(PATH, json=request)
    assert response.status_code == 404
    assert state.get_design() is None


@pytest.mark.parametrize("mismatch", ["revision", "design"])
def test_stale_or_misbound_request_never_evaluates_and_is_atomic(client, monkeypatch, mismatch):
    request = body()
    request["expected_revision" if mismatch == "revision" else "expected_design_id"] = (
        request["expected_revision"] - 1 if mismatch == "revision" else "different-part")
    before = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    monkeypatch.setattr(commands, "evaluate", lambda *_a: pytest.fail("Stale or misbound copy evaluated"))
    response = client.post(PATH, json=request)
    assert response.status_code == 409, response.text
    if mismatch == "design":
        assert response.json()["detail"]["code"] == "design_identity_mismatch"
    unchanged(before, revision, depth)


def test_design_identity_is_rechecked_inside_locked_callback(client, monkeypatch):
    request = body(expected_revision=state.revision() + 1)
    original = state.mutate_with_feature_log
    captured = {}

    def switch_document(*args, **kwargs):
        state.load_design(state.get_or_404().model_copy(deep=True, update={"id": "newly-opened-part"}))
        captured.update(before=state.get_or_404().model_dump_json(), revision=state.revision(), depth=state.undo_depth())
        return original(*args, **kwargs)

    monkeypatch.setattr(state, "mutate_with_feature_log", switch_document)
    monkeypatch.setattr(commands, "evaluate", lambda *_a: pytest.fail("Wrong active part reached copy builder"))
    response = client.post(PATH, json=request)
    assert response.status_code == 409, response.text
    assert response.json()["detail"]["code"] == "design_identity_mismatch"
    unchanged(**captured)


@pytest.mark.parametrize("failure,status,code", [
    ("missing", 404, "missing_reference"), ("duplicate", 422, "invalid_selection"),
    ("owned", 422, "unsupported_element_copy_source"), ("budget", 413, "command_limit"),
    ("source_limit", 413, "source_limit"),
])
def test_failed_native_copy_is_structured_atomic_and_never_falls_back(client, monkeypatch, failure, status, code):
    from backend.core import element_copy

    request = body()
    if failure == "missing":
        request["nanoparticle_ids"] = ["missing"]
    elif failure == "duplicate":
        design = state.get_or_404().model_copy(deep=True)
        design.nanoparticles.append(deepcopy(design.nanoparticles[0]))
        state.set_design(design)
        request["expected_revision"] = state.revision()
    elif failure == "owned":
        request.update(nanoparticle_ids=[], protein_ids=["protein"])
        design = state.get_or_404().model_copy(deep=True)
        design.protein_attachments[0].binder_strand_id = "unavailable-binder"
        state.set_design(design)
        request["expected_revision"] = state.revision()
    else:
        def unavailable(*_a):
            if failure == "budget":
                raise ProofBudgetExceeded("copy work exceeds budget")
            raise CommandContractError("selected asset exceeds admission", code="source_limit")
        monkeypatch.setattr(commands, "evaluate", unavailable)
    monkeypatch.setattr(element_copy, "paste_elements", lambda *_a: pytest.fail("Native failure entered frozen paste"))
    before = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    response = client.post(PATH, json=request)
    assert response.status_code == status, response.text
    assert response.json()["detail"]["code"] == code
    assert response.json()["detail"]["status"] in {"failed", "unverified"}
    unchanged(before, revision, depth)


def test_recording_failure_restores_candidate_receipt_revision_and_undo(client, monkeypatch):
    before = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    original = state.encode_design_snapshot
    calls = 0

    def fail_post(design):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("copy post-state encoding failed")
        return original(design)

    monkeypatch.setattr(state, "encode_design_snapshot", fail_post)
    with pytest.raises(RuntimeError, match="post-state encoding"):
        client.post(PATH, json=body())
    unchanged(before, revision, depth)


@pytest.mark.parametrize("shared", [True, False])
def test_real_aggregate_atom_limit_is_413_before_placement_and_preserves_history(client, monkeypatch, shared):
    design, params = protein_batch(5, 1000, shared=shared)
    state.load_design(design)
    state.clear_history()
    before = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    monkeypatch.setattr("backend.core.protein.compose_protein_world_transform",
                        lambda *_a: pytest.fail("Rejected request reached world placement"))
    response = client.post(PATH, json=body(protein_ids=params["protein_ids"], nanoparticle_ids=[]))
    assert response.status_code == 413, response.text
    assert response.json()["detail"]["code"] == "source_limit"
    assert response.json()["detail"]["status"] == "unverified"
    unchanged(before, revision, depth)


def test_free_protein_without_atom_selection_is_structured_and_atomic(client):
    design = state.get_or_404().model_copy(deep=True)
    design.protein_attachments[0].conjugation_atom_serial = None
    state.set_design(design)
    before = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    response = client.post(PATH, json=body(protein_ids=["protein"], nanoparticle_ids=[]))
    assert response.status_code == 422, response.text
    issue = response.json()["detail"]
    assert issue["code"] == "invalid_selection"
    assert issue["references"] == [{"kind": "protein_attachment", "identity": "protein", "parameter_path": ["protein_ids", 0]}]
    unchanged(before, revision, depth)


def test_live_copy_cold_replays_with_poisoned_recovery(client):
    response = client.post(PATH, json=body(protein_ids=["protein"], nanoparticle_ids=["dot", "first"]))
    assert response.status_code == 200, response.text
    current = Design.from_json(state.get_or_404().to_json())
    for entry in current.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
    worker = VerificationWorker(capture(current))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "reproduced_import", result
        assert result["checked_commands"] == 7
    finally:
        worker.close()


def test_legacy_clipboard_keeps_frozen_source_and_unverified_receipt(client, monkeypatch):
    frozen = state.get_or_404().model_dump(mode="json")
    current = state.get_or_404().model_copy(deep=True)
    current.nanoparticles[0].diameter_nm = 99.0
    state.set_design(current)
    monkeypatch.setattr(commands, "evaluate", lambda *_a: pytest.fail("Frozen clipboard entered same-part contract"))
    response = client.post("/api/design/element-paste", json={"source": frozen,
        "nanoparticle_ids": ["first"], "paste_index": 2})
    assert response.status_code == 200, response.text
    copied = state.get_or_404().nanoparticles[-1]
    assert copied.diameter_nm == 10.0 and copied.pose.values[3] == 30.0
    entry = state.get_or_404().feature_log[-1]
    assert "copy_version" not in entry.params
    assert not dependencies(entry.op_kind, entry.params).known
