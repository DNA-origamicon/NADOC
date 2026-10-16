"""Actual desktop deformation preview requests against native part history.

This dossier reproduces the current feature_editor.js sequence; it does not
pretend preview DELETE/POST calls are a non-mutating preview API. Tests named
legacy_integration_characterization document the current broken UX, not its
desired contract. Replace those flows when isolated previews are integrated.
Fixtures are tiny, in memory, and use no application lifespan or scientific jobs.
"""

from dataclasses import dataclass
from uuid import uuid4

import pytest
from fastapi import HTTPException

from backend.api import crud, doc_context, part_recipe_edit, state
from backend.api.part_proof_commands import dependencies, execute
from backend.api.routes_deformation import (
    AddDeformationBody,
    UpdateDeformationBody,
    add_deformation,
    delete_deformation,
    update_deformation,
)
from backend.api.routes_feature_log import SeekFeaturesBody, seek_features
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import AUTHORING_FIELDS


@dataclass(frozen=True)
class EditorCase:
    kind: str
    original_params: dict
    edited_params: dict
    feature_index: int
    operation_id: str

    def edit_body(self):
        # Exactly the edit-confirm fields assembled by feature_editor.js.
        return crud.EditFeatureBody(params={
            "type": self.kind,
            "plane_a_bp": 4,
            "plane_b_bp": 32,
            "params": self.edited_params,
            "cluster_ids": [],
        })


@pytest.fixture(params=["bend", "twist"])
def editor_case(request):
    kind = request.param
    original = ({"kind": "bend", "curvature_deg_per_bp": 0.25, "direction_deg": 0.0}
                if kind == "bend" else {"kind": "twist", "total_degrees": 8.0})
    edited = ({"kind": "bend", "curvature_deg_per_bp": 0.5, "direction_deg": 20.0}
              if kind == "bend" else {"kind": "twist", "total_degrees": 16.0})
    doc_id = f"geometry-preview-lifecycle-{uuid4()}"
    old_revision = doc_context.current_request_revision()
    old_entry = doc_context.current_request_feature_log_entry_id()
    token = doc_context.set_current_doc(doc_id)
    # All fallible setup is inside cleanup from the first context mutation.
    try:
        crud.create_bundle(crud.BundleRequest(
            cells=[[0, 0], [0, 1]], length_bp=42, name="Preview lifecycle",
        ))
        add_deformation(AddDeformationBody(
            type=kind, plane_a_bp=4, plane_b_bp=32, params=original,
        ))
        source = state.get_or_404()
        assert len(source.feature_log) == 2
        assert source.recipe_root.kind == "empty"
        assert source.feature_log[-1].proof_version == 1
        _assert_reproducible(source)
        yield EditorCase(kind, original, edited, 1, source.deformations[0].id)
    finally:
        try:
            state.drop_doc(doc_id)
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(old_revision)
            doc_context.set_request_feature_log_entry_id(old_entry)


def _assert_reproducible(design):
    # Input-only oracle; no worker/process, disk, cached receipt or recovery seek.
    report = assess_part_history(
        design.model_copy(deep=True), execute=execute, dependencies=dependencies,
    )
    assert report["status"] == "verified", report


def _checkpoint():
    source, revision = state.get_design_with_revision()
    with state._lock:
        session = state._session()
        history, redo = tuple(session.history), tuple(session.redo)
    return {
        "source": source,
        "document": source.model_dump(mode="json"),
        "revision": revision,
        "history": history,
        "redo": redo,
        "history_json": [item.model_dump(mode="json") for item in history],
        "redo_json": [item.model_dump(mode="json") for item in redo],
        "request_revision": doc_context.current_request_revision(),
        "request_entry": doc_context.current_request_feature_log_entry_id(),
    }


def _assert_stacks_unchanged(checkpoint):
    with state._lock:
        session = state._session()
        history, redo = tuple(session.history), tuple(session.redo)
    assert len(history) == len(checkpoint["history"])
    assert all(a is b for a, b in zip(history, checkpoint["history"]))
    assert [item.model_dump(mode="json") for item in history] == checkpoint["history_json"]
    assert len(redo) == len(checkpoint["redo"])
    assert all(a is b for a, b in zip(redo, checkpoint["redo"]))
    assert [item.model_dump(mode="json") for item in redo] == checkpoint["redo_json"]


def _assert_failed_call_atomic(checkpoint):
    source, revision = state.get_design_with_revision()
    assert source is checkpoint["source"]
    assert source.model_dump(mode="json") == checkpoint["document"]
    assert revision == checkpoint["revision"]
    assert doc_context.current_request_revision() == checkpoint["request_revision"]
    assert doc_context.current_request_feature_log_entry_id() == checkpoint["request_entry"]
    _assert_stacks_unchanged(checkpoint)


def _preview_then_discard(case):
    """Mirror peel, first preview, slider update, and awaited preview disposal."""
    before = _checkpoint()
    delete_deformation(case.operation_id, preview=True)
    assert state.get_or_404().deformations == []
    add_deformation(AddDeformationBody(
        type=case.kind, plane_a_bp=4, plane_b_bp=32,
        params=case.original_params, preview=True,
        source_operation_id=case.operation_id,
    ))
    preview_id = state.get_or_404().deformations[-1].id
    assert preview_id != case.operation_id
    update_deformation(preview_id, UpdateDeformationBody(params=case.edited_params))
    delete_deformation(preview_id, preview=True)
    after = state.get_or_404()
    assert after.deformations == []
    assert [e.model_dump(mode="json") for e in after.feature_log] == before["document"]["feature_log"]
    assert before["source"].model_dump(mode="json") == before["document"]
    _assert_stacks_unchanged(before)


def _assert_edit_committed(case, before):
    updated = state.get_or_404()
    assert [e.id for e in updated.feature_log] == [e["id"] for e in before["document"]["feature_log"]]
    assert len(updated.deformations) == 1
    operation = updated.deformations[0]
    assert operation.id == case.operation_id
    assert updated.feature_log[case.feature_index].op_snapshot == operation
    for key, value in case.edited_params.items():
        assert getattr(operation.params, key) == value
    assert updated.model_dump(mode="json", include=AUTHORING_FIELDS - {"deformations"}) == {
        key: value for key, value in before["document"].items()
        if key in AUTHORING_FIELDS - {"deformations"}
    }
    assert state.undo_depth() == len(before["history"]) + 1
    assert state.redo_depth() == 0
    _assert_reproducible(updated)
    state.undo()
    assert state.get_or_404().model_dump(mode="json") == before["document"]
    state.redo()
    assert state.get_or_404().deformations == updated.deformations
    _assert_reproducible(state.get_or_404())


def test_direct_history_edit_control_is_one_reproducible_undo(editor_case):
    before = _checkpoint()
    crud.edit_feature(editor_case.feature_index, editor_case.edit_body())
    assert state.revision() == before["revision"] + 1
    assert before["source"].model_dump(mode="json") == before["document"]
    _assert_edit_committed(editor_case, before)


def test_legacy_integration_characterization_preview_apply_rejects_peeled_source(editor_case):
    """Current Apply fails atomically, leaving the original overlay absent."""
    original = _checkpoint()
    _preview_then_discard(editor_case)
    before_apply = _checkpoint()
    with pytest.raises(HTTPException) as caught:
        crud.edit_feature(editor_case.feature_index, editor_case.edit_body())
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "recipe_not_reproducible"
    _assert_failed_call_atomic(before_apply)
    assert state.get_or_404().deformations == []
    assert state.get_or_404().feature_log[editor_case.feature_index].op_snapshot.id == editor_case.operation_id
    assert original["source"].model_dump(mode="json") == original["document"]


def test_preview_drag_and_discard_do_not_run_full_history_proof(editor_case, monkeypatch):
    def unexpected(*_args, **_kwargs):
        pytest.fail("Preview drag performed full history proof/regeneration")

    monkeypatch.setattr(part_recipe_edit, "assess_part_history", unexpected)
    monkeypatch.setattr(part_recipe_edit, "regenerate", unexpected)
    _preview_then_discard(editor_case)


def test_legacy_integration_characterization_cancel_adds_undo_and_discards_redo(editor_case):
    # Populate a real redo entry so cancellation cannot silently destroy it.
    crud.edit_feature(editor_case.feature_index, editor_case.edit_body())
    state.undo()
    original = _checkpoint()
    assert len(original["redo"]) == 1
    _preview_then_discard(editor_case)
    # feature_editor.js onExit waits for disposal, then seeks priorCursor.
    seek_features(SeekFeaturesBody(position=-1))
    assert state.get_or_404().model_dump(mode="json") == original["document"]
    _assert_reproducible(state.get_or_404())
    assert state.undo_depth() == len(original["history"]) + 1
    assert state.redo_depth() == 0
    # The new undo point is the temporary peeled source, not a committed edit.
    state.undo()
    assert state.get_or_404().deformations == []
    assert [entry.model_dump(mode="json") for entry in state.get_or_404().feature_log] == original["document"]["feature_log"]


def test_rejected_direct_edit_keeps_source_and_history_atomic(editor_case):
    before = _checkpoint()
    with pytest.raises(HTTPException):
        crud.edit_feature(editor_case.feature_index, crud.EditFeatureBody(params={
            "affected_helix_ids": ["missing-preview-lifecycle-helix"],
        }))
    _assert_failed_call_atomic(before)
