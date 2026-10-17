"""Explicit pinned protein imports publish bytes, asset and history atomically."""

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import routes_part_inputs as routes, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_input_sources import EmbeddedInput, describe, embed
from tests.test_protein import _SYNTH_PROT_DNA


@pytest.fixture
def client():
    token = set_current_doc("pinned-protein-import-route")
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    state.load_design(create_empty_part("Pinned import", "HONEYCOMB"))
    state.clear_history()
    try:
        with TestClient(app) as api:
            yield api
    finally:
        state.close_session()
        reset_current_doc(token)


def _body(data=None):
    data = _SYNTH_PROT_DNA.encode() if data is None else data
    source = describe(data, format="pdb", media_type="chemical/x-pdb")
    return {
        "source": source.model_dump(mode="json"), "data_b64": embed(source, data).data_b64,
        "name": "Pinned protein", "source_filename": "original.pdb", "exclude_dna": True,
        "expected_revision": state.revision(),
    }


def _post(client, body):
    return client.post("/api/design/features/import/protein", json=body)


def _unchanged(before, revision, depth):
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision and state.undo_depth() == depth


def test_pinned_import_records_source_and_asset_without_free_placement(client, monkeypatch):
    monkeypatch.setattr(state, "add_protein_asset", lambda *_a: pytest.fail("Mutable library was updated"))
    body = _body()
    revision = state.revision()
    response = _post(client, body)
    assert response.status_code == 201, response.text
    design = state.get_or_404()
    identity = response.json()["asset_id"]
    assert response.json()["revision"] == revision + 1
    assert design.protein_assets[0].id == identity
    assert design.protein_assets[0].name == "Pinned protein"
    assert len(design.protein_assets[0].atoms) == 9
    assert not design.protein_attachments
    assert len(design.feature_log) == 1 and state.undo_depth() == 1
    entry = design.feature_log[0]
    assert entry.op_kind == "protein-import"
    assert entry.params == {
        "_proof_version": 1, "protein_version": 1, "importer_version": 1,
        "source": body["source"], "asset_id": identity, "name": body["name"],
        "source_filename": body["source_filename"], "exclude_dna": True,
    }
    assert "data_b64" not in entry.params
    assert design.input_sources[body["source"]["sha256"]].data_b64 == body["data_b64"]
    proof = assess_part_history(design, execute=execute, dependencies=dependencies)
    assert proof["status"] == "reproduced_import", proof
    assert not proof["native_editable"]


def test_same_source_is_deduplicated_and_each_import_has_independent_identity(client):
    body = _body()
    first = _post(client, body)
    assert first.status_code == 201, first.text
    body.update(expected_revision=state.revision(), name="Second asset")
    second = _post(client, body)
    assert second.status_code == 201, second.text
    first_id, second_id = first.json()["asset_id"], second.json()["asset_id"]
    assert first_id != second_id
    assert len(state.get_or_404().input_sources) == 1
    assert [asset.id for asset in state.get_or_404().protein_assets] == [first_id, second_id]
    state.undo()
    assert [asset.id for asset in state.get_or_404().protein_assets] == [first_id]
    assert len(state.get_or_404().input_sources) == 1
    state.undo()
    assert not state.get_or_404().protein_assets and not state.get_or_404().input_sources
    state.redo()
    assert state.get_or_404().protein_assets[0].id == first_id
    assert len(state.get_or_404().input_sources) == 1


@pytest.mark.parametrize("change", [
    lambda b: b.pop("expected_revision"),
    lambda b: b.update(expected_revision=True),
    lambda b: b.update(expected_revision=-1),
    lambda b: b.update(asset_id="caller-selected-output"),
    lambda b: b["source"].update(format="mmcif"),
    lambda b: b["source"].update(media_type="text/plain"),
    lambda b: b["source"].update(path="/tmp/source.pdb"),
    lambda b: b["source"].update(size_bytes=250_001),
])
def test_request_contract_rejects_invalid_or_unsupported_inputs_without_mutation(client, change):
    body = _body()
    change(body)
    before = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    response = _post(client, body)
    assert response.status_code == 422
    _unchanged(before, revision, depth)


def test_requires_an_open_part(client):
    body = _body()
    state.close_session()
    response = _post(client, body)
    assert response.status_code == 404
    assert state.get_design() is None


def test_stale_revision_never_parses_or_publishes_asset(client, monkeypatch):
    body = _body()
    body["expected_revision"] -= 1
    monkeypatch.setattr(routes, "build", lambda *_a, **_kw: pytest.fail("Stale request reached parser"))
    before = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    response = _post(client, body)
    assert response.status_code == 409, response.text
    _unchanged(before, revision, depth)


@pytest.mark.parametrize("corruption", ["encoding", "digest", "size"])
def test_corrupt_source_fails_before_atomic_snapshot_allocation(client, monkeypatch, corruption):
    body = _body()
    if corruption == "encoding":
        body["data_b64"] = "!" * len(body["data_b64"])
    elif corruption == "digest":
        body["source"]["sha256"] = "0" * 64
    else:
        body["source"]["size_bytes"] -= 1
    monkeypatch.setattr(state, "encode_design_snapshot",
                        lambda *_a: pytest.fail("Corrupted source entered the recording transaction"))
    response = _post(client, body)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["code"] == "source_integrity_mismatch" and detail["status"] == "unverified"
    assert detail["references"] == [{"kind": "input_source", "identity": body["source"]["sha256"],
                                      "parameter_path": ["source"]}]
    assert not state.get_or_404().input_sources and not state.get_or_404().protein_assets


def test_existing_corrupt_immutable_source_is_not_silently_overwritten(client):
    body = _body()
    digest = body["source"]["sha256"]
    state.set_design(state.get_or_404().copy_with(input_sources={digest: EmbeddedInput(data_b64="AAAA")}))
    body["expected_revision"] = state.revision()
    before = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    response = _post(client, body)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "source_integrity_mismatch"
    _unchanged(before, revision, depth)


def test_oversized_atom_source_is_rejected_by_shared_builder_without_publication(client):
    line = next(line for line in _SYNTH_PROT_DNA.splitlines() if line.startswith("ATOM"))
    body = _body(((line + "\n") * 1001).encode())
    before = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    response = _post(client, body)
    assert response.status_code == 413, response.text
    assert response.json()["detail"]["code"] == "source_limit"
    _unchanged(before, revision, depth)


def test_empty_structure_is_failed_input_and_leaves_no_pinned_source(client):
    before = state.get_or_404().model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    response = _post(client, _body(b"REMARK no atoms\nEND\n"))
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_protein_input"
    _unchanged(before, revision, depth)


def test_recording_failure_rolls_back_source_asset_and_history_together(client, monkeypatch):
    before = deepcopy(state.get_or_404())
    revision, depth = state.revision(), state.undo_depth()
    original = state.encode_design_snapshot
    calls = 0

    def fail_post(design):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("post-state encoding failed")
        return original(design)

    monkeypatch.setattr(state, "encode_design_snapshot", fail_post)
    with pytest.raises(RuntimeError, match="encoding failed"):
        _post(client, _body())
    assert state.get_or_404() == before
    assert state.revision() == revision and state.undo_depth() == depth
