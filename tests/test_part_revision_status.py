"""Revision polling returns scalars only and never materializes a document."""

from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.api import state
from backend.api.doc_context import DocContextMiddleware, reset_current_doc, set_current_doc
from backend.api.part_revision_status import revision_status
from backend.core.models import Design


@pytest.fixture
def document():
    doc = f"__revision_status__{uuid4()}"
    token = set_current_doc(doc)
    try:
        yield doc
    finally:
        state.drop_doc(doc)
        reset_current_doc(token)


def forbidden(*_args, **_kwargs):
    pytest.fail("Revision status created, copied or serialized a Design")


def test_absent_revision_status_never_creates_a_session(document, monkeypatch):
    monkeypatch.setattr(state, "_session", forbidden)
    monkeypatch.setattr(state, "get_design", forbidden)
    assert revision_status() == {"doc_id": document, "design_id": None, "revision": 0, "has_design": False}
    assert document not in state._sessions


def test_current_revision_is_scalar_owned_output_without_model_access(document, monkeypatch):
    design = Design()
    state.load_design(design)
    revision = state.revision()
    monkeypatch.setattr(state, "_session", forbidden)
    monkeypatch.setattr(state, "get_design", forbidden)
    monkeypatch.setattr(Design, "model_dump", forbidden)
    monkeypatch.setattr(Design, "model_copy", forbidden)
    result = revision_status()
    assert result == {"doc_id": document, "design_id": design.id, "revision": revision, "has_design": True}
    result.update(design_id="caller changed output", revision=-1)
    assert revision_status()["design_id"] == design.id and revision_status()["revision"] == revision


def test_oversized_identity_is_rejected_without_serializing_source(document):
    state.load_design(Design(id="a" * 1025))
    with pytest.raises(HTTPException) as error:
        revision_status()
    assert error.value.status_code == 422 and error.value.detail["code"] == "revision_identity_limit"


def test_compatibility_revision_route_uses_existing_document_context_and_no_alias(document):
    from backend.api.routes_feature_log import router

    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        absent = client.get("/api/design/revision", headers={"X-NADOC-Doc": document})
        assert absent.json()["has_design"] is False and document not in state._sessions
        design = Design()
        state.load_design(design)
        current = client.get("/api/design/revision", params={"doc": document})
    assert current.status_code == 200 and current.json() == {
        "doc_id": document, "design_id": design.id, "revision": state.revision(), "has_design": True}
    assert "policy_generation" not in current.json()


def test_production_compatibility_revision_route_is_registered(document):
    from backend.api.main import app

    # Do not start the production lifespan or its persistence/background workers.
    client = TestClient(app)
    result = client.get("/api/design/revision", headers={"X-NADOC-Doc": document})
    assert result.status_code == 200 and result.json()["has_design"] is False
    assert document not in state._sessions
