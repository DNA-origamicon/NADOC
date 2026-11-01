"""A saved protein placement resolves its own atoms across library changes."""

import pytest
from fastapi.testclient import TestClient

from backend.api import doc_context, state
from backend.api.main import app
from backend.core.atomistic import atomistic_to_json
from backend.core.models import Design
from backend.core.protein import parse_protein_pdb, protein_asset_to_atomistic
from tests.test_protein import _SYNTH_PDB, _design_with_overhang


@pytest.fixture
def placed():
    state.set_design(_design_with_overhang())
    client = TestClient(app)
    response = client.post("/api/design/protein/import", json={"content": _SYNTH_PDB, "name": "Saved protein"})
    assert response.status_code == 201, response.text
    identity = response.json()["id"]
    response = client.post("/api/design/protein/attachments",
                           json={"asset_id": identity, "overhang_id": "oh_5p"})
    assert response.status_code == 201, response.text
    # Reopen the portable model: there is no object alias to the session library.
    saved = state.get_design().model_dump_json()
    state.load_design(Design.model_validate_json(saved))
    yield client, identity
    state.remove_protein_asset(identity)
    state.close_session()


def _replace_library(identity):
    changed = parse_protein_pdb(_SYNTH_PDB.replace("6.700", "46.700"), name="Changed library")
    changed.id = identity
    state.add_protein_asset(changed)
    return changed


@pytest.mark.parametrize("library_change", ["replace", "remove"])
@pytest.mark.parametrize("endpoint", ["atomistic", "conjugation-candidates"])
def test_reopened_asset_queries_keep_document_source(placed, library_change, endpoint):
    client, identity = placed
    url = f"/api/design/protein/{endpoint}"
    before = client.get(url, params={"asset_id": identity})
    assert before.status_code == 200, before.text
    canonical = state.get_design().model_dump_json()
    revision = state.revision()
    if library_change == "replace":
        _replace_library(identity)
    else:
        state.remove_protein_asset(identity)
    after = client.get(url, params={"asset_id": identity})
    assert after.status_code == 200, after.text
    if endpoint == "conjugation-candidates":
        assert after.json()["candidates"] == before.json()["candidates"]
        assert after.json()["design_revision"] == revision
    else:
        assert after.json() == before.json()
    assert state.get_design().model_dump_json() == canonical
    assert state.revision() == revision


def test_two_documents_resolve_distinct_embedded_copies_before_shared_library(placed):
    client, identity = placed
    first = client.get("/api/design/protein/atomistic", params={"asset_id": identity}).json()
    library = _replace_library(identity)
    second = library.model_copy(deep=True)
    second.atoms[0].x += 50
    token = doc_context.set_current_doc("__test_protein_source_second__")
    try:
        state.load_design(Design(protein_assets=[second]))
    finally:
        doc_context.reset_current_doc(token)
    try:
        actual = client.get("/api/design/protein/atomistic", params={"asset_id": identity},
                            headers={"X-NADOC-Doc": "__test_protein_source_second__"})
        assert actual.status_code == 200, actual.text
        assert actual.json() == atomistic_to_json(protein_asset_to_atomistic(second))
        assert client.get("/api/design/protein/atomistic", params={"asset_id": identity}).json() == first
    finally:
        state.drop_doc("__test_protein_source_second__")


def test_library_only_asset_still_resolves_without_an_embedded_copy(placed):
    client, identity = placed
    library = _replace_library(identity)
    state.load_design(Design())
    actual = client.get("/api/design/protein/atomistic", params={"asset_id": identity})
    assert actual.status_code == 200, actual.text
    assert actual.json() == atomistic_to_json(protein_asset_to_atomistic(library))
    state.remove_protein_asset(identity)
    assert client.get("/api/design/protein/atomistic", params={"asset_id": identity}).status_code == 404
