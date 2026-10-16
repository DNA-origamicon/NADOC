"""Recorded dissolve preserves placement owners and refuses atomic publication.

Tiny memory-only route tests also cover rootless compatibility: recording the
new operation preserves the absent recipe root rather than blessing old state.
"""

import pytest
from fastapi import HTTPException

from backend.api import doc_context, routes_clusters as routes, state
from backend.core import part_structure_gate, validator
from backend.core.lattice_frame_model import LatticeFrame
from backend.core.models import ClusterRigidTransform, Design, Helix, Vec3
from backend.core.part_structure import assess_structure


def source():
    # This is the valid state after all members leave a placement-owner group:
    # the empty owner still controls the frame and must remain addressable.
    return Design(
        helices=[Helix(id="h", length_bp=3, grid_pos=(0, 0), lattice_frame_id="frame",
                      axis_start=Vec3(x=0, y=0, z=0), axis_end=Vec3(x=0, y=0, z=1))],
        lattice_frames=[LatticeFrame(id="frame", placement_cluster_id="placement")],
        cluster_transforms=[
            ClusterRigidTransform(id="placement", name="Placement", is_default=True),
            ClusterRigidTransform(id="members", name="Members", helix_ids=["h"]),
            ClusterRigidTransform(id="spare", name="Unreferenced"),
        ],
    )


@pytest.fixture
def document():
    design = source()
    request_revision = doc_context.current_request_revision()
    request_entry = doc_context.current_request_feature_log_entry_id()
    token = doc_context.set_current_doc("cluster-delete-structure-test")
    try:
        state.load_design(design)
        # Retain a real redo entry so a refusal cannot silently clear it.
        state.set_design(design.copy_with(cluster_transforms=[
            *design.cluster_transforms, ClusterRigidTransform(id="redo-only"),
        ]))
        state.undo()
        yield state.get_or_404()
    finally:
        try:
            state.close_session()
        finally:
            doc_context.reset_current_doc(token)
            doc_context.set_request_revision(request_revision)
            doc_context.set_request_feature_log_entry_id(request_entry)


def snapshot():
    session = state._session()
    return {
        "source": session.design,
        "stored": session.design.model_dump(mode="json") if session.design else None,
        "history": list(session.history), "redo": list(session.redo),
        "revision": session.revision,
        "request_revision": doc_context.current_request_revision(),
        "request_entry": doc_context.current_request_feature_log_entry_id(),
    }


def unchanged(before):
    after = snapshot()
    assert after.pop("source") is before["source"]
    assert after == {key: value for key, value in before.items() if key != "source"}


def test_retained_empty_frame_owner_delete_is_typed_and_failure_atomic(document):
    before = snapshot()
    with pytest.raises(HTTPException) as caught:
        routes.delete_cluster("placement")
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "invalid_selection"
    assert caught.value.detail["references"] == [{
        "kind": "cluster", "identity": "placement", "parameter_path": ["cluster_ids", 0],
        "model_path": ["lattice_frames", 0, "placement_cluster_id"],
        "owner": {"kind": "lattice_frame", "identity": "frame"},
    }]
    unchanged(before)


def test_unreferenced_dissolve_records_one_row_without_inventing_a_root(document):
    before = snapshot()
    response = routes.delete_cluster("spare")
    updated = state.get_or_404()
    assert [group.id for group in updated.cluster_transforms] == ["placement", "members"]
    assert updated.helices == document.helices
    assert updated.lattice_frames == document.lattice_frames
    assert document.feature_log == []
    assert len(updated.feature_log) == 1
    entry = updated.feature_log[0]
    assert entry.feature_type == "snapshot" and entry.op_kind == "cluster-dissolve"
    assert entry.params == {"_proof_version": 1, "cluster_ids": ["spare"]}
    assert entry.design_snapshot_gz_b64 and entry.post_state_gz_b64
    assert updated.recipe_root is document.recipe_root is None
    assert state.undo_depth() == len(before["history"]) + 1
    assert state.redo_depth() == 0
    assert response["revision"] == state.revision() == before["revision"] + 1
    assert document.model_dump(mode="json") == before["stored"]
    assert Design.model_validate_json(updated.model_dump_json()) == updated
    expected = updated.model_dump(mode="json")
    restored, _ = state.undo()
    assert restored.model_dump(mode="json") == before["stored"]
    restored, _ = state.redo()
    assert restored.model_dump(mode="json") == expected


def test_missing_group_refuses_without_publication(document):
    before = snapshot()
    with pytest.raises(HTTPException) as caught:
        routes.delete_cluster("absent")
    assert caught.value.status_code == 404
    unchanged(before)


def test_absent_document_refuses_without_creating_undo(document):
    state.load_design(None)
    before = snapshot()
    with pytest.raises(HTTPException) as caught:
        routes.delete_cluster("spare")
    assert caught.value.status_code == 404
    unchanged(before)


def test_incomplete_structure_assessment_refuses_before_publication(document, monkeypatch):
    before = snapshot()
    monkeypatch.setattr(part_structure_gate, "assess_structure",
                        lambda design, **kwargs: assess_structure(design, max_items=0))
    with pytest.raises(HTTPException) as caught:
        routes.delete_cluster("spare")
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "structure_incomplete"
    assert caught.value.detail["structure"]["complete"] is False
    unchanged(before)


def test_candidate_validation_failure_is_before_publication(document, monkeypatch):
    before = snapshot()

    def reject(_candidate):
        raise RuntimeError("delete candidate validation failed")

    with monkeypatch.context() as faults:
        faults.setattr(validator, "validate_design", reject)
        faults.setattr(state, "validate_design", reject)
        with pytest.raises(RuntimeError, match="delete candidate validation failed"):
            routes.delete_cluster("spare")
    unchanged(before)


@pytest.mark.parametrize("changed_revision", [True, False], ids=["revision-race", "source-object-aba"])
def test_candidate_cannot_overwrite_a_concurrent_source(document, monkeypatch, changed_revision):
    original_validate = state.validate_design
    concurrent = []

    def check_then_replace(candidate):
        result = original_validate(candidate)
        replacement = document.model_copy(deep=True)
        replacement.cluster_transforms[-1].name = "Concurrent name"
        # The route already owns state._lock. Simulate a hostile same-lock
        # callback without reacquiring that non-reentrant lock via set_design.
        session = state._session()
        session.design = replacement
        if changed_revision:
            session.revision += 1
        concurrent.append(snapshot())
        return result

    monkeypatch.setattr(state, "validate_design", check_then_replace)
    monkeypatch.setattr(validator, "validate_design", check_then_replace)
    with pytest.raises(HTTPException) as caught:
        routes.delete_cluster("spare")
    assert caught.value.status_code == 409 and caught.value.detail["code"] == "source_changed"
    assert len(concurrent) == 1
    unchanged(concurrent[0])


def test_publication_failure_preserves_source_and_both_stacks(document, monkeypatch):
    before = snapshot()
    bump = state._bump_revision

    def fail_after_bump(session):
        bump(session)
        raise RuntimeError("delete publication failed")

    with monkeypatch.context() as faults:
        faults.setattr(state, "_bump_revision", fail_after_bump)
        with pytest.raises(RuntimeError, match="delete publication failed"):
            routes.delete_cluster("spare")
    unchanged(before)
