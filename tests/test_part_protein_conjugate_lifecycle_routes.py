"""Live owned-conjugate edits record strict inputs and publish atomically."""

from copy import deepcopy

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.api import part_protein_conjugate_lifecycle as commands, routes_protein as routes, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.core import models as m
from backend.core.part_history_proof import AUTHORING_FIELDS
from tests.test_part_protein_conjugate_lifecycle import _make_conjugate, _move, _params


@pytest.fixture(scope="module")
def native_conjugate():
    return _make_conjugate()


@pytest.fixture
def client(native_conjugate):
    token = set_current_doc("native-protein-conjugate-lifecycle-routes")
    state.load_design(deepcopy(native_conjugate))
    state.clear_history()
    app = FastAPI()
    app.include_router(routes.router, prefix="/api")
    try:
        with TestClient(app) as api:
            yield api
    finally:
        state.close_session()
        reset_current_doc(token)


def _request(client, action, **patch):
    path = "/api/design/protein/attachments/placement"
    return client.delete(path) if action == "delete" else client.patch(path, json=patch)


def _assert_unchanged(before, revision, undo):
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision and state.undo_depth() == undo


@pytest.mark.parametrize("action,patch", [
    ("patch", {"gizmo_move": _move(), "visible": False}),
    ("patch", {"visible": False}),
    ("patch", {"visible": None, "gizmo_move": None}),
    ("delete", {}),
])
def test_live_lifecycle_records_exact_inputs_and_replays_all_authoring(client, monkeypatch, action, patch):
    before = deepcopy(state.get_or_404())
    revision, undo = state.revision(), state.undo_depth()
    monkeypatch.setattr(routes, "_resolve_protein_asset",
                        lambda *_a: pytest.fail("Native lifecycle accessed mutable library"))
    response = _request(client, action, **patch)
    assert response.status_code == 200, response.text
    current = state.get_or_404()
    entry = current.feature_log[-1]
    assert entry.op_kind == f"protein-attach-{action}"
    assert entry.params == _params(**patch)
    assert dependencies(entry.op_kind, entry.params).known
    replayed = execute(entry.op_kind, before, entry.params)
    assert replayed.model_dump(include=AUTHORING_FIELDS) == current.model_dump(include=AUTHORING_FIELDS)
    if patch.get("gizmo_move") is not None:
        assert response.json()["protein_constraint"]["mode"] == "two_ball_joint"
        assert response.json()["changed_helix_ids"] == ["oh_helix"]
    else:
        assert "protein_constraint" not in response.json()
    assert state.revision() == revision + 1 and state.undo_depth() == undo + 1
    state.undo()
    assert state.get_or_404().model_dump(include=AUTHORING_FIELDS) == before.model_dump(include=AUTHORING_FIELDS)
    state.redo()
    assert state.get_or_404().model_dump(include=AUTHORING_FIELDS) == current.model_dump(include=AUTHORING_FIELDS)


@pytest.mark.parametrize("failure", ["missing_binder", "shared_binder", "dependent_extension", "residue_transform"])
def test_known_delete_failure_never_falls_back_and_preserves_document(client, monkeypatch, failure):
    design = state.get_or_404().model_copy(deep=True)
    if failure == "missing_binder":
        design.strands = [item for item in design.strands if item.id != "binder"]
    elif failure == "shared_binder":
        design.protein_attachments.append(m.ProteinAttachment(id="shared", asset_id="asset",
            target=m.ProteinTargetFree(), binder_strand_id="binder"))
    elif failure == "dependent_extension":
        design.extensions = [m.StrandExtension(id="dependent", strand_id="binder", end="five_prime", sequence="TT")]
    else:
        design.nucleotide_transforms = [m.NucleotideTransform(id="dependent", kind="base",
            helix_id="oh_helix", bp_index=3, direction=m.Direction.REVERSE)]
    state.set_design(design)
    before = state.get_or_404().model_dump_json()
    revision, undo = state.revision(), state.undo_depth()
    response = _request(client, "delete")
    assert response.status_code == 422, response.text
    detail = response.json()["detail"]
    assert detail["status"] == "failed" and detail["code"] in {"missing_reference", "invalid_selection"}
    assert detail["references"][0]["parameter_path"] == ["binder_strand_id"]
    _assert_unchanged(before, revision, undo)


def test_locked_callback_rechecks_current_binder_ownership(client, monkeypatch):
    original = state.mutate_with_feature_log
    captured = {}

    def change_owner(*args, **kwargs):
        current = state.get_or_404().model_copy(deep=True)
        current.protein_attachments[0].binder_strand_id = "replaced-binder"
        state.set_design(current)
        captured.update(before=state.get_or_404().model_dump_json(), revision=state.revision(), undo=state.undo_depth())
        return original(*args, **kwargs)

    monkeypatch.setattr(state, "mutate_with_feature_log", change_owner)
    response = _request(client, "patch", visible=False)
    assert response.status_code == 422, response.text
    assert response.json()["detail"]["code"] == "invalid_selection"
    _assert_unchanged(**captured)


@pytest.mark.parametrize("action", ["patch", "delete"])
def test_recording_failure_rolls_back_candidate_and_receipt(client, monkeypatch, action):
    before = state.get_or_404().model_dump_json()
    revision, undo = state.revision(), state.undo_depth()
    original = state.encode_design_snapshot
    calls = 0

    def fail_post(design):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("owned conjugate post-state failure")
        return original(design)

    monkeypatch.setattr(state, "encode_design_snapshot", fail_post)
    with pytest.raises(RuntimeError, match="post-state failure"):
        _request(client, action, visible=False)
    _assert_unchanged(before, revision, undo)


@pytest.mark.parametrize("patch", [
    {"pose": m.Mat4x4().values}, {"conjugation_atom_serial": 9}, {"handle_spacer_nt": 2},
])
def test_unsupported_absolute_site_and_handle_edits_remain_legacy(client, monkeypatch, patch):
    monkeypatch.setattr(commands, "evaluate", lambda *_a: pytest.fail("Unsupported edit entered native contract"))
    response = _request(client, "patch", **patch)
    assert response.status_code == 200, response.text
    entry = state.get_or_404().feature_log[-1]
    assert "conjugation_version" not in entry.params
    assert not dependencies(entry.op_kind, entry.params).known


def test_free_conjugate_visibility_remains_legacy(client, monkeypatch):
    current = state.get_or_404().model_copy(deep=True)
    current.protein_attachments[0].target = m.ProteinTargetFree()
    state.set_design(current)
    monkeypatch.setattr(commands, "evaluate", lambda *_a: pytest.fail("Free conjugate entered native contract"))
    response = _request(client, "patch", visible=False)
    assert response.status_code == 200, response.text
    entry = state.get_or_404().feature_log[-1]
    assert "conjugation_version" not in entry.params and not dependencies(entry.op_kind, entry.params).known


@pytest.mark.parametrize("misleading_history", [False, True])
def test_opaque_ownership_stays_legacy_and_current_binder_wins_over_history(client, monkeypatch, misleading_history):
    current = state.get_or_404().model_copy(deep=True)
    # The legacy animation blob has no typed ownership grammar. Admission must
    # stay explicitly unverified before mutation, not retry a failed builder.
    current.overhangs[0].strand_anim_setup = {"legacy_owner": "opaque"}
    other = current.find_strand("binder").model_copy(deep=True, update={"id": "other-binder"})
    other.domains[0].start_bp, other.domains[0].end_bp = 40, 42
    current.strands.append(other)
    if misleading_history:
        current.feature_log = [m.SnapshotLogEntry(op_kind="protein-conjugate", label="Misleading legacy owner",
            design_snapshot_gz_b64="unused", params={"asset_id": "asset", "overhang_id": "oh_5p",
            "attachment_id": "placement", "binder_strand_id": "other-binder"})]
    state.set_design(current)
    monkeypatch.setattr(commands, "evaluate", lambda *_a: pytest.fail("Opaque ownership entered native evaluator"))
    response = _request(client, "delete")
    assert response.status_code == 200, response.text
    updated = state.get_or_404()
    assert updated.find_strand("binder") is None and updated.find_strand("other-binder") == other
    entry = updated.feature_log[-1]
    assert entry.params["binder_strand_id"] == "binder" and "conjugation_version" not in entry.params
    assert not dependencies(entry.op_kind, entry.params).known
