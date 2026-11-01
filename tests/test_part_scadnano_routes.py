"""scadnano source imports use the shared atomic replacement boundary."""

from copy import deepcopy
import json

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient
import pytest

from backend.api import routes_part_cadnano_import as routes, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import capabilities, dependencies, execute
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_input_sources import EmbeddedResolver, InputSource, command_sources
from tests.test_part_cadnano_routes import query, unchanged
from tests.test_part_scadnano_commands import source


PATH = "/api/design/features/import/scadnano"


@pytest.fixture
def client():
    token = set_current_doc("pinned-scadnano-route")
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    state.load_design(create_empty_part("Fresh part", "HONEYCOMB"))
    try:
        with TestClient(app) as api:
            yield api
    finally:
        state.close_session()
        reset_current_doc(token)


def post(client, *, raw=None, params=None, headers=None):
    return client.post(PATH, params=query() if params is None else params,
        content=json.dumps(source("extensions"), indent=1).encode() if raw is None else raw,
        headers={"content-type": "application/json", **(headers or {})})


def test_actual_route_preserves_bytes_loss_policy_undo_and_portable_proof(client):
    before, revision, depth = deepcopy(state.get_or_404()), state.revision(), state.undo_depth()
    raw = json.dumps(source("circular"), indent=1).encode()
    response = post(client, raw=raw)
    assert response.status_code == 201, response.text
    result = response.json()
    assert any("circular scaffold imported as linear" in warning for warning in result["import_warnings"])
    design = state.get_or_404()
    row, = design.feature_log
    assert row.op_kind == "scadnano-import" and row.params["loss_policy"] == "existing-importer-v1"
    descriptor, = command_sources(row.op_kind, row.params)
    assert EmbeddedResolver(design.input_sources)(descriptor) == raw
    assert result["revision"] == revision + 1 == state.revision()
    assert state.undo_depth() == depth + 1
    assert result["design"]["feature_log"][0]["post_state_gz_b64"]
    restored = Design.from_json(design.to_json())
    restored.feature_log[0].post_state_gz_b64 = "poisoned"
    proof = assess_part_history(restored, execute=execute, dependencies=dependencies)
    assert proof["status"] == "reproduced_import" and not proof["native_editable"], proof
    state.undo()
    assert state.get_or_404() == before
    state.redo()
    assert state.get_or_404() == design


def test_import_and_source_repair_capabilities_are_truthful(client):
    from backend.api.part_repair_source_policy import admit_descriptor

    contract = capabilities()["scadnano_contract"]
    assert contract["kinds"] == ["scadnano-import"] and contract["endpoint"] == f"POST {PATH}"
    operation = client.get("/openapi.json").json()["paths"][PATH]["post"]
    assert operation["requestBody"]["required"]
    assert post(client).status_code == 201
    row = state.get_or_404().feature_log[0]
    descriptor = InputSource.model_validate(row.params["source"])
    assert admit_descriptor(row.op_kind, row.params, "source", descriptor) == {
        "max_size_bytes": 100_000, "replacement_supported": True}


@pytest.mark.parametrize("case,status", [("stale", 409), ("retained", 422), ("media", 415),
    ("compression", 415), ("large", 413), ("invalid", 422), ("missing_query", 422)])
def test_failed_admission_does_not_replace_document(client, monkeypatch, case, status):
    params, headers, raw = query(), {}, None
    if case == "stale":
        params["expected_design_id"] = "different"
    elif case == "retained":
        state.get_or_404().metadata.tags = ["authored"]
    elif case == "media":
        headers["content-type"] = "text/plain"
    elif case == "compression":
        headers["content-encoding"] = "gzip"
    elif case == "large":
        raw = b" " * 100_001
    elif case == "invalid":
        raw = b'{"photoproduct_junctions":[]}'
    else:
        params.pop("expected_revision")
    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()
    response = post(client, params=params, headers=headers, raw=raw)
    assert response.status_code == status, response.text
    unchanged(before, revision, depth)


@pytest.mark.parametrize("stage", ["encode", "validate", "response", "undo"])
def test_preparation_and_publication_faults_are_atomic(client, monkeypatch, stage):
    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()

    def fail(*_args, **_kwargs):
        raise RuntimeError("injected failure")

    owner, name = {"encode": (state, "encode_design_snapshot"), "validate": (routes, "validate_design"),
        "response": (routes, "_design_response"), "undo": (state, "_snapshot_copy")}[stage]
    monkeypatch.setattr(owner, name, fail)
    with pytest.raises(RuntimeError, match="injected"):
        post(client)
    unchanged(before, revision, depth)


def test_concurrent_source_change_refuses_late_candidate(client, monkeypatch):
    prepare = routes._prepare
    changed = {}

    def edit_during_prepare(*args, **kwargs):
        candidate = prepare(*args, **kwargs)
        design = state.get_or_404()
        state.set_design(design.copy_with(metadata=design.metadata.model_copy(update={"name": "Concurrent edit"})))
        changed.update(before=state.get_or_404().model_dump_json(), revision=state.revision(), depth=state.undo_depth())
        return candidate

    monkeypatch.setattr(routes, "_prepare", edit_during_prepare)
    assert post(client).status_code == 409
    unchanged(**changed)


def test_disconnect_never_publishes_private_import(client, monkeypatch):
    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()

    async def disconnected(_request):
        return True

    monkeypatch.setattr(Request, "is_disconnected", disconnected)
    assert post(client).status_code == 499
    unchanged(before, revision, depth)


@pytest.fixture
def ordinary_client(client):
    from backend.api import crud

    client.app.include_router(crud.router, prefix="/api")
    return client


@pytest.mark.parametrize("case", ["square", "honeycomb", "extensions", "loopout", "circular", "inline"])
def test_ordinary_upload_records_complete_replayable_import(ordinary_client, case):
    from backend.core.part_history_proof import AUTHORING_FIELDS
    from tests.test_part_scadnano_commands import commands, legacy_pipeline
    from backend.core.part_scope_references import remap_design

    content = json.dumps(source(case))
    response = ordinary_client.post("/api/design/import/scadnano", json={"content": content, "name": "Uploaded source"})
    assert response.status_code == 200, response.text
    actual = state.get_or_404()
    row, = actual.feature_log
    assert row.op_kind == "scadnano-import"
    expected, warnings = legacy_pipeline(source(case))
    expected.metadata.name = "Uploaded source"
    expected = remap_design(expected, commands.identity_mapping(expected, commands.parse_command(row.op_kind, row.params)))
    assert actual.model_dump(include=AUTHORING_FIELDS) == expected.model_dump(include=AUTHORING_FIELDS)
    assert response.json().get("import_warnings", []) == warnings
    assert response.json()["revision"] == state.revision()
    assert response.json()["debug"]["helix_count"] == len(actual.helices)
    assert response.json()["import_history"]["status"] == "reproduced_import"
    assert state.undo_depth() == 0  # Ordinary file navigation preserves its existing semantics.
    assert assess_part_history(actual, execute=execute, dependencies=dependencies)["status"] == "reproduced_import"


@pytest.mark.parametrize("case", ["oversize", "extra_presentation"])
def test_ordinary_out_of_scope_import_keeps_existing_geometry_and_honest_history(ordinary_client, case):
    data = source()
    if case == "extra_presentation":
        data["major_tick_distance"] = 8
    content = json.dumps(data)
    if case == "oversize":
        content += " " * 100_000
    response = ordinary_client.post("/api/design/import/scadnano", json={"content": content})
    assert response.status_code == 200, response.text
    assert response.json()["import_history"]["status"] == "unverified"
    assert state.get_or_404().recipe_root is None
    assert not state.get_or_404().input_sources and not state.get_or_404().feature_log
    assert len(state.get_or_404().helices) == 2


def test_ordinary_native_preparation_failure_never_falls_back_or_replaces(ordinary_client, monkeypatch):
    from backend.core import scadnano

    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()

    def fail(*_args, **_kwargs):
        raise RuntimeError("native preparation failed")

    monkeypatch.setattr(routes, "_prepare", fail)
    monkeypatch.setattr(scadnano, "import_scadnano", lambda *_: pytest.fail("Retried legacy importer"))
    with pytest.raises(RuntimeError, match="native preparation failed"):
        ordinary_client.post("/api/design/import/scadnano", json={"content": json.dumps(source())})
    unchanged(before, revision, depth)


def test_ordinary_native_budget_refusal_is_actionable_and_atomic(ordinary_client, monkeypatch):
    from backend.core import scadnano
    from backend.core.part_history_proof import ProofBudgetExceeded

    before, revision, depth = state.get_or_404().model_dump_json(), state.revision(), state.undo_depth()

    def fail(*_args, **_kwargs):
        raise ProofBudgetExceeded("Import recovery exceeds its byte allowance")

    monkeypatch.setattr(routes, "_prepare", fail)
    monkeypatch.setattr(scadnano, "import_scadnano", lambda *_: pytest.fail("Retried legacy importer"))
    result = ordinary_client.post("/api/design/import/scadnano", json={"content": json.dumps(source())})
    assert result.status_code == 413, result.text
    assert result.json()["detail"]["code"] == "command_limit"
    unchanged(before, revision, depth)
