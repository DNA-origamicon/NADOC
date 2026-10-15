"""Known legacy routes refuse strict work before I/O or live model access."""

from uuid import uuid4

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from backend.api import crud, routes_design_interchange as interchange, routes_design_loadouts as loadouts, state
from backend.api import part_publication_policy as policy
from backend.api.doc_context import DocContextMiddleware, reset_current_doc, set_current_doc


@pytest.fixture
def document():
    doc = f"__strict_legacy_routes__{uuid4()}"
    token = set_current_doc(doc)
    previous = policy.current_configuration()
    state.configure_part_publication_policy(policy.HostPolicyConfiguration(
        default_mode=previous.default_mode, document_modes={**previous.document_modes, doc: "registered_only"}))
    source = state.create_empty_part("Strict route", "HONEYCOMB")
    try:
        yield doc, source, state.revision()
    finally:
        state.configure_part_publication_policy(previous)
        state.drop_doc(doc)
        reset_current_doc(token)


def forbidden(*_args, **_kwargs):
    pytest.fail("Strict refusal happened after legacy I/O, model access or preparation")


@pytest.mark.parametrize("operation", ["create", "bundle", "load", "install", "save", "undo", "redo",
    "loadout-create", "loadout-select", "loadout-activate", "loadout-rename", "loadout-delete"])
def test_known_legacy_routes_reject_before_reading_models_or_running_preparation(document, monkeypatch, operation):
    _doc, source, revision = document
    from backend.core import part_document_io, part_history_contract

    monkeypatch.setattr(state, "get_or_404", forbidden)
    monkeypatch.setattr(state, "_snapshot_copy", forbidden)
    monkeypatch.setattr(part_document_io, "read_file", forbidden)
    monkeypatch.setattr(part_history_contract, "create_empty_part", forbidden)
    monkeypatch.setattr(loadouts, "ensure_loadouts", forbidden)
    monkeypatch.setattr(loadouts, "decode_snapshot", forbidden)
    monkeypatch.setattr(loadouts, "encode_snapshot", forbidden)
    monkeypatch.setattr(interchange.os, "makedirs", forbidden)
    calls = {
        "create": lambda: crud.create_design(crud.CreateDesignRequest(name="Unadmitted")),
        "bundle": lambda: crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=21)),
        "load": lambda: crud.load_design(crud.FilePathRequest(path="/must-not-read/strict.nadoc")),
        "install": lambda: crud._install_loaded_design(object()),
        "save": lambda: interchange.save_design(interchange.FilePathRequest(path="/must-not-write/strict.nadoc")),
        "undo": crud.undo_design,
        "redo": crud.redo_design,
        "loadout-create": lambda: loadouts.create_loadout(loadouts.LoadoutCreateBody(name="Unadmitted")),
        "loadout-select": lambda: loadouts.select_loadout("unadmitted"),
        "loadout-activate": loadouts.activate_last_editable_loadout,
        "loadout-rename": lambda: loadouts.rename_loadout("unadmitted", loadouts.LoadoutRenameBody(name="Unadmitted")),
        "loadout-delete": lambda: loadouts.delete_loadout("unadmitted"),
    }
    with pytest.raises(HTTPException) as error:
        calls[operation]()
    assert error.value.status_code == 403 and error.value.detail["code"] == "construction_policy"
    assert state.get_design_with_revision() == (source, revision)
    assert state.undo_depth() == state.redo_depth() == 0


def test_actual_save_route_refuses_before_file_creation_even_with_client_policy_flags(document, monkeypatch):
    doc, source, revision = document
    monkeypatch.setattr(state, "get_or_404", forbidden)
    monkeypatch.setattr(interchange.os, "makedirs", forbidden)
    app = FastAPI()
    app.add_middleware(DocContextMiddleware)
    app.include_router(interchange.router, prefix="/api")
    with TestClient(app) as client:
        response = client.post("/api/design/save",
            headers={"X-NADOC-Doc": doc, "X-NADOC-Policy": "compatibility", "X-NADOC-Agent": "human"},
            json={"path": "/must-not-write/strict.nadoc"})
    assert response.status_code == 403 and response.json()["detail"]["code"] == "construction_policy"
    assert state.get_design_with_revision() == (source, revision)


def test_compatibility_policy_still_reaches_existing_handler(document, monkeypatch):
    _doc, _source, _revision = document
    state.configure_part_publication_policy(policy.HostPolicyConfiguration())
    called = []

    def legacy():
        called.append(True)
        raise HTTPException(404, detail="Legacy handler reached")

    monkeypatch.setattr(state, "get_or_404", legacy)
    with pytest.raises(HTTPException) as error:
        interchange.save_design(interchange.FilePathRequest(path="/unused.nadoc"))
    assert error.value.status_code == 404 and called == [True]
