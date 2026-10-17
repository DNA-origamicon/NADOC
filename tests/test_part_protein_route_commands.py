"""Existing placement routes record the exact native inputs they publish."""

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_protein_commands as commands, routes_protein as routes, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.core.models import Mat4x4, ProteinAttachment, ProteinTargetDesign, ProteinTargetFree
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.protein import parse_protein_pdb
from tests.test_protein import _SYNTH_PDB, _design_with_overhang


@pytest.fixture
def client():
    token = set_current_doc("native-protein-placement-routes")
    asset = parse_protein_pdb(_SYNTH_PDB, name="Captured protein")
    asset.id = "asset"
    asset.default_conjugation_atom_serial = 9
    design = _design_with_overhang().copy_with(protein_assets=[asset])
    design.overhangs[0].sequence = "ACGTACGT"
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


def _attach(client, **values):
    return client.post("/api/design/protein/attachments", json={
        "asset_id": "asset", "overhang_id": "oh_5p", **values,
    })


def _assert_replay(before):
    current = state.get_or_404()
    entry = current.feature_log[-1]
    assert dependencies(entry.op_kind, entry.params).known
    replayed = execute(entry.op_kind, before, entry.params)
    assert replayed.model_dump(include=AUTHORING_FIELDS) == current.model_dump(include=AUTHORING_FIELDS)
    return entry


def test_create_uses_captured_asset_and_records_selected_defaults(client, monkeypatch):
    monkeypatch.setattr(routes, "_resolve_protein_asset",
                        lambda *_a: pytest.fail("Native route consulted mutable library"))
    before = deepcopy(state.get_or_404())
    revision = state.revision()
    response = _attach(client, attach_end="root", handle_complement_bp=3, handle_spacer_nt=2)
    assert response.status_code == 201, response.text
    entry = _assert_replay(before)
    assert entry.params == {
        "_proof_version": 1, "protein_version": 1,
        "attachment_id": response.json()["attachment_id"], "asset_id": "asset",
        "target": {"kind": "overhang", "overhang_id": "oh_5p", "attach_end": "root"},
        "conjugation_atom_serial": 9, "handle_complement_bp": 3, "handle_spacer_nt": 2,
    }
    assert state.revision() == revision + 1 and state.undo_depth() == 1
    state.undo()
    assert state.get_or_404().protein_attachments == before.protein_attachments
    state.redo()
    assert state.get_or_404().protein_attachments[0].id == response.json()["attachment_id"]


def test_default_atom_is_selected_from_design_inside_recording_callback(client, monkeypatch):
    original = state.mutate_with_feature_log

    def changed_before_lock(*args, **kwargs):
        current = deepcopy(state.get_or_404())
        current.protein_assets[0].default_conjugation_atom_serial = 2
        state.set_design(current)
        return original(*args, **kwargs)

    monkeypatch.setattr(state, "mutate_with_feature_log", changed_before_lock)
    response = _attach(client)
    assert response.status_code == 201, response.text
    current = state.get_or_404()
    assert current.feature_log[-1].params["conjugation_atom_serial"] == 2
    assert current.protein_attachments[0].conjugation_atom_serial == 2
    assert current.protein_attachments[0].conjugation_chemistry is None


@pytest.mark.parametrize("target", ["free", "overhang"])
def test_patch_records_actual_fields_and_native_gizmo_override_order(client, target):
    current = state.get_or_404()
    placement = ProteinAttachment(id="placement", asset_id="asset", conjugation_atom_serial=9,
        target=ProteinTargetFree() if target == "free" else ProteinTargetDesign(overhang_id="oh_5p"))
    state.set_design(current.copy_with(protein_attachments=[placement]))
    before = deepcopy(state.get_or_404())
    pose = Mat4x4().values
    pose[3] = 25
    patch = {"pose": pose, "gizmo_move": {"pivot": [0, 0, 0], "translation": [3, 2, 1],
            "rotation": [0, 0, 0, 1]}, "visible": False, "handle_complement_bp": 2,
             "handle_spacer_nt": None, "conjugation_atom_serial": 9}
    response = client.patch("/api/design/protein/attachments/placement", json=patch)
    assert response.status_code == 200, response.text
    entry = _assert_replay(before)
    assert entry.params == {"_proof_version": 1, "protein_version": 1,
                            "attachment_id": "placement", **patch}
    assert state.get_or_404().protein_attachments[0].pose.values[3] == 3


def test_delete_records_native_identity_and_preserves_unowned_topology(client):
    response = _attach(client)
    assert response.status_code == 201, response.text
    identity = response.json()["attachment_id"]
    before = deepcopy(state.get_or_404())
    response = client.delete(f"/api/design/protein/attachments/{identity}")
    assert response.status_code == 200, response.text
    entry = _assert_replay(before)
    assert entry.params == {"_proof_version": 1, "protein_version": 1, "attachment_id": identity}
    assert not state.get_or_404().protein_attachments
    assert state.get_or_404().strands == before.strands


@pytest.mark.parametrize("case", ["missing_atom", "duplicate_asset", "missing_overhang"])
def test_native_create_invalid_references_are_atomic_structured_failures(client, case):
    current = state.get_or_404()
    if case == "missing_atom":
        current.protein_assets[0].default_conjugation_atom_serial = 999
    elif case == "duplicate_asset":
        current.protein_assets *= 2
    else:
        current.overhangs = []
    before = current.model_dump_json()
    revision, depth = state.revision(), state.undo_depth()
    response = _attach(client)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] in {"missing_reference", "invalid_selection"}
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision and state.undo_depth() == depth


def test_native_record_failure_restores_design_history_and_revision(client, monkeypatch):
    before = deepcopy(state.get_or_404())
    revision, depth = state.revision(), state.undo_depth()
    original = state.encode_design_snapshot
    calls = 0

    def fail_post(design):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("protein post-state failure")
        return original(design)

    monkeypatch.setattr(state, "encode_design_snapshot", fail_post)
    with pytest.raises(RuntimeError, match="post-state failure"):
        _attach(client)
    assert state.get_or_404() == before
    assert state.revision() == revision and state.undo_depth() == depth


def test_library_only_create_retains_explicitly_unsupported_legacy_receipt(client, monkeypatch):
    current = state.get_or_404()
    state.add_protein_asset(current.protein_assets[0])
    state.set_design(current.copy_with(protein_assets=[]))
    monkeypatch.setattr(commands, "build", lambda *_a, **_kw: pytest.fail("Legacy create entered native builder"))
    response = _attach(client)
    assert response.status_code == 201, response.text
    entry = state.get_or_404().feature_log[-1]
    assert "protein_version" not in entry.params and not dependencies(entry.op_kind, entry.params).known


@pytest.mark.parametrize("ownership", ["binder", "azide", "legacy_bound_target"])
def test_owned_or_ambiguous_patch_retains_legacy_contract(client, monkeypatch, ownership):
    current = state.get_or_404()
    attachment = ProteinAttachment(id="placement", asset_id="asset", conjugation_atom_serial=9,
                                   target=ProteinTargetDesign(overhang_id="oh_5p"))
    if ownership == "binder":
        attachment.binder_strand_id = "binder"
    elif ownership == "azide":
        attachment.azide_end = "5p"
    else:
        current.strands[0].domains[0].binds_overhang_id = "oh_5p"
    state.set_design(current.copy_with(protein_attachments=[attachment]))
    monkeypatch.setattr(commands, "build", lambda *_a, **_kw: pytest.fail("Owned placement entered native builder"))
    response = client.patch("/api/design/protein/attachments/placement", json={"visible": False})
    assert response.status_code == 200, response.text
    entry = state.get_or_404().feature_log[-1]
    assert "protein_version" not in entry.params and not dependencies(entry.op_kind, entry.params).known
