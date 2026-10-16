"""Closed comparison payloads bypass generic ASGI response traversal."""

from copy import deepcopy
import json

import fastapi.routing
from fastapi.testclient import TestClient
import pytest

from backend.api import part_evaluation_jobs as jobs, state
from tests.test_part_comparison_routes import app, JOBS
from tests.test_part_dna_comparison_integration import dna_ready as dna_ready
from tests.test_part_evaluation_comparison import ready as ready


@pytest.mark.parametrize("fixture_name", ["ready", "dna_ready"])
def test_closed_dto_encodes_directly_with_exact_decoded_values_and_context(request, monkeypatch, fixture_name):
    harness = request.getfixturevalue(fixture_name)
    original = jobs.comparison
    seen = []

    def record(identity, body):
        value = original(identity, body)
        seen.append(deepcopy(value))
        return value

    def forbid(*args, **kwargs):
        pytest.fail("Closed comparison DTO must not traverse FastAPI jsonable_encoder")

    monkeypatch.setattr(jobs, "comparison", record)
    monkeypatch.setattr(fastapi.routing, "jsonable_encoder", forbid)
    candidate = harness.job.result["candidate"]
    before = harness.source.model_dump_json()
    with TestClient(app()) as client:
        response = client.post(f"{JOBS}/{harness.id}/comparison", json=harness.body,
                               headers={"X-NADOC-Doc": harness.doc})
    assert response.status_code == 200, response.text
    assert response.headers["content-type"] == "application/json"
    assert len(seen) == 1
    assert response.json() == json.loads(json.dumps(seen[0], allow_nan=False))
    value = response.json()
    assert value["job_id"] == harness.id and value["design_id"] == harness.source.id
    assert value["source_revision"] == harness.revision
    assert value["repair_draft"] == {"draft_id": harness.source.repair_draft.draft_id,
                                     "generation": harness.source.repair_draft.generation}
    assert value["coverage"]["complete"] is True and value["coverage"]["scientific_qualification"] is False
    assert 0 < value["expires_in_seconds"] <= 900
    assert "candidate" not in value and "candidate_digests" not in value
    assert harness.source.model_dump_json() == before
    assert state.get_design_with_revision() == (harness.source, harness.revision) and state.undo_depth() == 0
    assert harness.job.result["candidate"] is candidate and harness.job.result["status"] == "ready"
