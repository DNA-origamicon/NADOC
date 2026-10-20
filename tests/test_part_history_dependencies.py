"""Dependency inspection shares replay contracts without running geometry."""
from uuid import uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import doc_context, state
from backend.api.routes_feature_log import router
from backend.core.models import SnapshotLogEntry
from tests.sweep_history_fixture import fixture as sweep_fixture


@pytest.fixture
def client():
    doc = f"__dependencies__{uuid4()}"
    token = doc_context.set_current_doc(doc)
    app = FastAPI()
    app.include_router(router)
    try:
        with TestClient(app) as client:
            yield client
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)


def test_native_dependencies_are_conservative_revision_bound_and_read_only(client, monkeypatch):
    from backend.api import part_proof_commands

    source = sweep_fixture()
    state.load_design(source)
    original = source.model_dump_json()
    _, revision = state.get_design_with_revision()
    monkeypatch.setattr(part_proof_commands, "execute", lambda *_a, **_k: pytest.fail("Dependency view executed geometry"))
    response = client.get("/design/features/dependencies")
    assert response.status_code == 200, response.text
    graph = response.json()
    assert graph["design_id"] == source.id and graph["revision"] == revision
    nodes = {node["id"]: node for node in graph["features"]}
    assert nodes["selected-sweep"]["parents"] == ["bundle"]
    assert nodes["bundle"]["children"] == ["selected-sweep"]
    assert nodes["selected-sweep"]["children"] == ["later-extrusion"]
    assert nodes["later-extrusion"]["conservative"] is True
    assert source.model_dump_json() == original
    assert state.get_design_with_revision() == (source, revision)


def test_routing_children_keep_their_identity_and_history_row(client):
    from tests.deformation_history_app import fixture

    source = fixture("extrude-nick-batch")
    state.load_design(source)
    graph = client.get("/design/features/dependencies").json()
    child = graph["features"][-1]
    assert child["id"] == source.feature_log[-1].children[0].id
    assert child["row_index"] == 1 and child["label"] == "Output nick pair"
    assert child["parents"] == ["selected-extrude"]


def test_unknown_feature_is_an_explicit_conservative_barrier(client):
    source = sweep_fixture()
    source.feature_log.append(SnapshotLogEntry(id="unknown", op_kind="photoproduct-relax", label="Unqualified relaxation", params={}))
    state.load_design(source)
    graph = client.get("/design/features/dependencies").json()
    assert graph["complete"] is False
    assert graph["features"][-1]["known"] is False
    assert graph["features"][-1]["parents"] == ["later-extrusion"]


def test_duplicate_identities_are_refused(client):
    source = sweep_fixture()
    source.feature_log[-1].id = source.feature_log[0].id
    state.load_design(source)
    assert client.get("/design/features/dependencies").status_code == 409


def test_missing_part_is_not_an_empty_verified_graph(client):
    assert client.get("/design/features/dependencies").status_code == 404
