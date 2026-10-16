"""Registered compatibility projection and strict closed-route refusal."""

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, part_publication_policy as policy, state
from backend.api.part_strict_http import StrictPartDispatch
from backend.api.routes_feature_log import router
from backend.core.models import Helix
from tests.test_part_evaluation_comparison import ready as ready


JOBS = "/api/design/features/evaluation/jobs"


def app():
    application = FastAPI()
    application.include_router(router, prefix="/api")
    return StrictPartDispatch(doc_context.DocContextMiddleware(application))


def test_http_comparison_is_private_then_original_commit_still_publishes_once(ready):
    headers = {"X-NADOC-Doc": ready.doc}
    with TestClient(app()) as client:
        compared = client.post(f"{JOBS}/{ready.id}/comparison", headers=headers, json=ready.body)
        assert compared.status_code == 200, compared.text
        data = compared.json()
        assert data["projection_version"] == 1 and data["job_id"] == ready.id
        assert data["source_revision"] == ready.revision
        assert 0 < data["expires_in_seconds"] <= 900
        assert data["coverage"]["complete"] and data["coverage"]["scientific_qualification"] is False
        assert data["published"]["units"] == data["proposed"]["units"] == "nm"
        assert "design" not in data and "candidate" not in data
        assert state.get_design_with_revision() == (ready.source, ready.revision)
        assert state.undo_depth() == 0
        inspected = client.get(f"{JOBS}/{ready.id}", headers=headers)
        assert inspected.json()["result"]["status"] == "ready"
        assert "candidate" not in inspected.json()["result"]
        published = client.post(f"{JOBS}/{ready.id}/commit", headers=headers)
        assert published.status_code == 200, published.text
        assert published.json()["revision"] == ready.revision + 1
        repeated = client.post(f"{JOBS}/{ready.id}/comparison", headers=headers, json=ready.body)
        assert repeated.status_code == 409
    assert state.undo_depth() == 1


@pytest.mark.parametrize("changes", [{"expected_revision": True}, {"projection_version": 2},
                                    {"candidate": {}}, {"expected_design_id": "x" * 257}])
def test_http_malformed_comparison_guards_never_capture_or_run(ready, changes):
    with TestClient(app()) as client:
        result = client.post(f"{JOBS}/{ready.id}/comparison", headers={"X-NADOC-Doc": ready.doc},
                             json={**ready.body, **changes})
    assert result.status_code == 422 and ready.opened == 0


@pytest.mark.parametrize("change", ["document", "revision", "draft", "generation", "source"])
def test_http_context_conflicts_preserve_current_state_and_private_candidate(ready, change):
    body = dict(ready.body)
    document = ready.doc
    if change == "document":
        document = "another-comparison-document"
    elif change == "source":
        with state._lock:
            state._sessions[ready.doc].design = ready.source.model_copy()
    else:
        field = {"revision": "expected_revision", "draft": "expected_draft_id", "generation": "expected_generation"}[change]
        body[field] = "other" if change == "draft" else 0
    current, revision = state.get_design_with_revision()
    candidate = ready.job.result["candidate"]
    with TestClient(app()) as client:
        result = client.post(f"{JOBS}/{ready.id}/comparison", headers={"X-NADOC-Doc": document}, json=body)
    assert result.status_code == (404 if change == "document" else 409), result.text
    if change != "document":
        assert result.json()["detail"]["code"] == "comparison_conflict"
    assert ready.opened == 0 and ready.job.result["candidate"] is candidate
    assert state.get_design_with_revision() == (current, revision)


def test_http_unsupported_family_returns_explicit_unavailable_instead_of_partial_panes(ready):
    ready.source.helices = [Helix(id="h", axis_start={"x": 0, "y": 0, "z": 0},
                                 axis_end={"x": 0, "y": 0, "z": 7}, length_bp=21)]
    with TestClient(app()) as client:
        result = client.post(f"{JOBS}/{ready.id}/comparison", headers={"X-NADOC-Doc": ready.doc}, json=ready.body)
    assert result.status_code == 422
    assert result.json()["detail"]["code"] == "unsupported_comparison_scope"
    assert "published" not in result.json() and "proposed" not in result.json() and ready.opened == 0


def test_http_user_job_cancel_discards_comparison_readiness_without_publication(ready):
    headers = {"X-NADOC-Doc": ready.doc}
    with TestClient(app()) as client:
        cancelled = client.delete(f"{JOBS}/{ready.id}", headers=headers)
        assert cancelled.status_code == 200
        result = client.post(f"{JOBS}/{ready.id}/comparison", headers=headers, json=ready.body)
        assert result.status_code == 409 and ready.opened == 0
    assert state.get_design_with_revision() == (ready.source, ready.revision) and state.undo_depth() == 0


def test_http_strict_closed_route_table_refuses_comparison_before_reading_its_body(ready, monkeypatch):
    previous = policy.current_configuration()
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(default_mode="registered_only"))
    from backend.api import part_evaluation_jobs
    monkeypatch.setattr(part_evaluation_jobs, "comparison", lambda *_: pytest.fail("Strict dispatch entered comparison"))
    try:
        with TestClient(app()) as client:
            response = client.post(f"{JOBS}/{ready.id}/comparison", headers={"X-NADOC-Doc": ready.doc},
                                   content=b"not even valid JSON")
        assert response.status_code == 403 and response.json()["detail"]["code"] == "construction_policy"
        assert ready.opened == 0
    finally:
        state.configure_part_publication_policy(previous)
