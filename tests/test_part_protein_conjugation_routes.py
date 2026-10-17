"""Live conjugation records native inputs atomically and preserves API guards."""

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_protein_conjugation_commands as commands, routes_protein as routes, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.core.cluster_autodetect import with_default_cluster
from backend.core.models import ProteinAttachment, ProteinTargetFree, SnapshotLogEntry
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.protein import parse_protein_pdb
from tests.test_protein import _SYNTH_PDB, _design_with_overhang


@pytest.fixture
def client():
    token = set_current_doc("native-protein-conjugation-routes")
    asset = parse_protein_pdb(_SYNTH_PDB, name="synth")
    asset.id = "asset"
    asset.default_conjugation_atom_serial = 9
    design = _design_with_overhang().copy_with(protein_assets=[asset])
    design.overhangs[0].sequence = "ACGTACGT"
    design = with_default_cluster(design, identity_factory=lambda *_a: "source-cluster")
    state.load_design(design)
    state.clear_history()
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    try:
        with TestClient(app) as api:
            yield api
    finally:
        state.close_session()
        reset_current_doc(token)


def _post(client, **changes):
    return client.post("/api/design/protein/conjugate", json={
        "asset_id": "asset", "overhang_id": "oh_5p", "operation_id": "native-conjugation",
        "expected_revision": state.revision(), **changes,
    })


def _assert_unchanged(before, revision, undo):
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision and state.undo_depth() == undo


@pytest.mark.parametrize("convert", [False, True])
def test_native_route_records_exact_inputs_and_replays_complete_authoring(client, monkeypatch, convert):
    if convert:
        state.set_design(state.get_or_404().copy_with(protein_attachments=[ProteinAttachment(
            id="free-placement", asset_id="asset", target=ProteinTargetFree(), conjugation_atom_serial=9)]))
    before = deepcopy(state.get_or_404())
    revision, undo = state.revision(), state.undo_depth()
    monkeypatch.setattr(routes, "_resolve_protein_asset",
                        lambda *_a: pytest.fail("Native conjugation read mutable library"))
    response = _post(client, azide_end="3p", source_attachment_id="free-placement" if convert else None)
    assert response.status_code == 201, response.text
    payload = response.json()
    current = state.get_or_404()
    entry = current.feature_log[-1]
    assert dependencies(entry.op_kind, entry.params).known
    assert entry.params == {
        "_proof_version": 1, "protein_version": 1, "conjugation_version": 1,
        "asset_id": "asset", "overhang_id": "oh_5p", "azide_end": "3p",
        "source_attachment_id": "free-placement" if convert else None,
        "operation_id": "native-conjugation", "conjugation_atom_serial": 9,
        "attachment_id": payload["attachment_id"], "binder_strand_id": payload["binder_strand_id"],
        "group_id": current.staple_groups[-1].id,
    }
    if convert:
        assert payload["attachment_id"] == "free-placement"
    assert payload["element_validation"]["valid"]
    assert payload["element_validation"]["failed_metrics"] == []
    assert payload["process_metrics"]["operation_id"] == "native-conjugation"
    assert payload["process_metrics"]["outcome"] == "committed"
    assert all(value >= 0 for value in payload["process_metrics"]["stages_ms"].values())
    replayed = execute(entry.op_kind, before, entry.params)
    assert replayed.model_dump(include=AUTHORING_FIELDS) == current.model_dump(include=AUTHORING_FIELDS)
    assert state.revision() == revision + 1 and state.undo_depth() == undo + 1
    state.undo()
    assert state.get_or_404().protein_attachments == before.protein_attachments
    assert state.get_or_404().strands == before.strands
    state.redo()
    assert state.get_or_404().protein_attachments[-1].id == payload["attachment_id"]


def test_repeated_operation_id_is_rejected_without_new_candidate(client, monkeypatch):
    response = _post(client)
    assert response.status_code == 201, response.text
    before = state.get_or_404().model_dump_json()
    revision, undo = state.revision(), state.undo_depth()
    monkeypatch.setattr(commands, "evaluate", lambda *_a: pytest.fail("Duplicate operation was evaluated"))
    response = _post(client)
    assert response.status_code == 409, response.text
    _assert_unchanged(before, revision, undo)


def test_already_conjugated_source_remains_a_conflict_before_candidate_build(client, monkeypatch):
    response = _post(client)
    assert response.status_code == 201, response.text
    source_id = response.json()["attachment_id"]
    before = state.get_or_404().model_dump_json()
    revision, undo = state.revision(), state.undo_depth()
    monkeypatch.setattr(commands, "evaluate", lambda *_a: pytest.fail("Owned source reached native builder"))
    response = _post(client, operation_id="second-conversion", source_attachment_id=source_id)
    assert response.status_code == 409, response.text
    assert "Only a free protein placement" in response.json()["detail"]
    _assert_unchanged(before, revision, undo)


def test_operation_id_is_rechecked_inside_recording_transaction(client, monkeypatch):
    original = state.mutate_with_feature_log
    captured = {}

    def concurrent_receipt(*args, **kwargs):
        design = state.get_or_404().model_copy(deep=True)
        design.feature_log.append(SnapshotLogEntry(op_kind="protein-conjugate", label="Concurrent receipt",
            params={"operation_id": "native-conjugation"}, design_snapshot_gz_b64="unused"))
        state.set_design(design)
        captured.update(before=state.get_or_404().model_dump_json(), revision=state.revision(), undo=state.undo_depth())
        return original(*args, **kwargs)

    monkeypatch.setattr(state, "mutate_with_feature_log", concurrent_receipt)
    monkeypatch.setattr(commands, "evaluate", lambda *_a: pytest.fail("Concurrent duplicate was evaluated"))
    response = _post(client, expected_revision=None)
    assert response.status_code == 409, response.text
    assert "already committed" in response.json()["detail"]
    _assert_unchanged(**captured)


def test_stale_revision_is_rejected_before_native_evaluation(client, monkeypatch):
    before = state.get_or_404().model_dump_json()
    revision, undo = state.revision(), state.undo_depth()
    monkeypatch.setattr(commands, "evaluate", lambda *_a: pytest.fail("Stale request reached native evaluator"))
    response = _post(client, expected_revision=revision - 1)
    assert response.status_code == 409, response.text
    _assert_unchanged(before, revision, undo)


def test_default_atom_is_captured_from_the_locked_design(client, monkeypatch):
    original = state.mutate_with_feature_log

    def changed_before_transaction(*args, **kwargs):
        design = state.get_or_404().model_copy(deep=True)
        design.protein_assets[0].default_conjugation_atom_serial = 1
        state.set_design(design)
        return original(*args, **kwargs)

    monkeypatch.setattr(state, "mutate_with_feature_log", changed_before_transaction)
    response = _post(client, expected_revision=None)
    assert response.status_code == 201, response.text
    assert state.get_or_404().feature_log[-1].params["conjugation_atom_serial"] == 1
    assert state.get_or_404().protein_attachments[-1].conjugation_atom_serial == 1


@pytest.mark.parametrize("failure", ["missing_atom", "nonreactive", "missing_overhang", "native_validation"])
def test_native_failure_never_falls_back_or_publishes_partial_conjugate(client, monkeypatch, failure):
    overrides = {}
    if failure == "missing_atom":
        overrides["conjugation_atom_serial"] = 999
    elif failure == "nonreactive":
        overrides["conjugation_atom_serial"] = 2
    elif failure == "missing_overhang":
        overrides["overhang_id"] = "missing"
    else:
        state.get_or_404().overhangs[0].sequence = None
    monkeypatch.setattr(routes, "_resolve_protein_asset",
                        lambda *_a: pytest.fail("Failed native command fell back to legacy"))
    before = state.get_or_404().model_dump_json()
    revision, undo = state.revision(), state.undo_depth()
    response = _post(client, **overrides)
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["operation_id"] == "native-conjugation"
    if failure == "native_validation":
        assert detail["code"] == "element_validation_failed"
        assert not detail["element_validation"]["valid"]
        assert detail["process_metrics"]["outcome"] == "rejected_invalid"
    else:
        assert detail["code"] in {"missing_reference", "invalid_selection"}
    _assert_unchanged(before, revision, undo)


def test_record_failure_restores_every_native_output_and_receipt(client, monkeypatch):
    before = state.get_or_404().model_dump_json()
    revision, undo = state.revision(), state.undo_depth()
    original = state.encode_design_snapshot
    calls = 0

    def fail_post(design):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("conjugation post-state failure")
        return original(design)

    monkeypatch.setattr(state, "encode_design_snapshot", fail_post)
    with pytest.raises(RuntimeError, match="post-state failure"):
        _post(client)
    _assert_unchanged(before, revision, undo)


def test_library_only_conjugation_keeps_legacy_receipt(client, monkeypatch):
    current = state.get_or_404()
    state.add_protein_asset(current.protein_assets[0])
    state.set_design(current.copy_with(protein_assets=[]))
    monkeypatch.setattr(commands, "evaluate", lambda *_a: pytest.fail("Library asset entered native evaluator"))
    response = _post(client)
    assert response.status_code == 201, response.text
    entry = state.get_or_404().feature_log[-1]
    assert "conjugation_version" not in entry.params
    assert not dependencies(entry.op_kind, entry.params).known
    assert response.json()["element_validation"]["valid"]
