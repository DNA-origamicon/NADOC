"""Actual browser-number transport must preserve strict server expectations."""

import json
from pathlib import Path
import subprocess
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, state
from backend.api.routes_feature_log import router
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_contract import create_empty_part


ROOT = Path(__file__).resolve().parents[1]
PATH = "/api/design/features/repair-draft"
POSE = [1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0,
        0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0]
BROWSER = """
import fs from 'node:fs';
import {actionFromRepairField} from './src/features/part_repair_fields.js';
const input = JSON.parse(fs.readFileSync(0, 'utf8'));
if (input.catalog) {
  const field = input.catalog.fields.find(field => field.parameter_path[0] === input.parameter);
  input.body.actions = [actionFromRepairField(input.catalog, field, input.value)];
}
process.stdout.write(JSON.stringify(input.body));
"""


def browser_body(body, **choices):
    result = subprocess.run(["node", "--input-type=module", "-e", BROWSER], cwd=ROOT / "frontend",
        input=json.dumps({"body": body, **choices}), text=True, capture_output=True, check=True, timeout=10)
    return result.stdout


@pytest.fixture
def document():
    identity = f"__repair_expectation_transport__{uuid4()}"
    token = doc_context.set_current_doc(identity)
    request_revision, request_entry = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    source = create_empty_part("Typed browser expectations", "HONEYCOMB")
    source.feature_log = [
        SnapshotLogEntry(id="create", op_kind="nanoparticle-create", label="Gold", params={
            "_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold", "diameter_nm": 12.0}),
        SnapshotLogEntry(id="pose", op_kind="nanoparticle-patch", label="Pose", params={
            "_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "gold", "pose": list(POSE)}),
    ]
    state.load_design(source)
    app = FastAPI()
    app.add_middleware(doc_context.DocContextMiddleware)
    app.include_router(router, prefix="/api")
    try:
        with TestClient(app) as client:
            yield client, {"X-NADOC-Doc": identity, "Content-Type": "application/json"}
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(request_revision)
        doc_context.set_request_feature_log_entry_id(request_entry)


def draft_body(operation="create", **extra):
    source, revision = state.get_design_with_revision()
    draft = source.repair_draft
    return {"draft_version": 1, "operation": operation,
        "expected_design_id": source.id, "expected_revision": revision,
        "expected_draft_id": None if draft is None else draft.draft_id,
        "expected_generation": None if draft is None else draft.generation, **extra}


@pytest.mark.parametrize("feature,parameter,value", [
    ("create", "diameter_nm", "13.5"),
    ("pose", "pose", [*POSE[:3], 2.0, *POSE[4:]]),
])
def test_browser_metadata_action_roundtrip_preserves_float_expectations_on_real_http(
        document, monkeypatch, feature, parameter, value):
    client, headers = document
    source, revision = state.get_design_with_revision()
    response = client.post("/api/design/features/repair-inputs", headers=headers, json={
        "expected_design_id": source.id, "expected_revision": revision, "feature_id": feature})
    assert response.status_code == 200, response.text
    raw = browser_body(draft_body(), catalog=response.json(), parameter=parameter, value=value)
    displayed_old = json.loads(raw)["actions"][0]["expected_old"]
    # This is the real JS loss of numeric representation, not a Python JSON mock.
    assert type(displayed_old if parameter == "diameter_nm" else displayed_old[0]) is int
    saved = client.post(PATH, headers=headers, content=raw)
    assert saved.status_code == 200, saved.text
    canonical = state.get_or_404().repair_draft.actions[0].expected_old
    assert type(canonical if parameter == "diameter_nm" else canonical[0]) is float
    assert state.get_or_404().feature_log is source.feature_log and state.undo_depth() == 0

    # Reloading/updating the browser's saved proposal must not lose the receipt.
    reloaded = client.get(PATH, headers=headers)
    assert reloaded.status_code == 200
    raw = browser_body(draft_body("update", actions=reloaded.json()["draft"]["actions"]))
    updated = client.post(PATH, headers=headers, content=raw)
    assert updated.status_code == 200, updated.text
    canonical = state.get_or_404().repair_draft.actions[0].expected_old
    assert type(canonical if parameter == "diameter_nm" else canonical[0]) is float

    # The same lossless value survives an actual portable model roundtrip and
    # explicit rebase, then reaches the real native repair planner/executor.
    # Only job scheduling is replaced here; no alternate action decoder exists.
    restored = Design.model_validate_json(state.get_or_404().model_dump_json())
    state.load_design(restored)
    rebased = client.post(PATH, headers=headers, content=browser_body(draft_body("rebase")))
    assert rebased.status_code == 200, rebased.text
    from backend.api import part_evaluation_jobs as jobs
    from backend.api.part_proof_commands import dependencies, execute
    from backend.api.part_recipe_repair import prepare_repair
    from backend.core.part_verification_capture import capture
    results = []
    def start(request, *, expected_source, expected_session_identity):
        assert expected_source is state.get_or_404() and expected_session_identity
        result = prepare_repair(capture(expected_source, preserve_entry_types=True), request["repair"],
            source_revision=request["expected_revision"], executor=execute, dependency_resolver=dependencies)
        results.append(result)
        return {"job_id": "transport-only-scheduler", "status": result["status"]}
    monkeypatch.setattr(jobs, "start", start)
    body = draft_body()
    body.pop("operation")
    before, revision = state.get_design_with_revision()
    evaluated = client.post(f"{PATH}/evaluate", headers=headers, content=browser_body(body))
    assert evaluated.status_code == 202, evaluated.text
    assert results[0]["status"] == "ready", results[0]
    candidate = results[0]["candidate"]
    assert candidate.feature_log[0 if feature == "create" else 1].params[parameter] == (
        float(value) if parameter == "diameter_nm" else value)
    assert state.get_or_404() is before and state.revision() == revision and state.undo_depth() == 0


@pytest.mark.parametrize("old,receipt,status,code", [
    (True, "1.0", 422, None),
    (1, "true", 422, None),
    (12, "12", 409, "repair_conflict"),
    (13, "13.0", 409, "repair_conflict"),
    ({"a": 1}, '{"a":1,"a":1}', 422, None),
    (12, "NaN", 422, None),
])
def test_real_http_rejects_mismatching_or_forged_receipts_without_publishing(document, old, receipt, status, code):
    client, headers = document
    source, revision = state.get_design_with_revision()
    body = draft_body(actions=[{"action": "set_input", "feature_id": "create",
        "parameter_path": ["diameter_nm"], "expected_old": old,
        "expected_old_json": receipt, "value": 13.5}])
    rejected = client.post(PATH, headers=headers, content=browser_body(body))
    assert rejected.status_code == status, rejected.text
    if code:
        assert rejected.json()["detail"]["code"] == code
    assert state.get_or_404() is source and state.revision() == revision
    assert source.repair_draft is None and state.undo_depth() == 0
