"""Producer edits regenerate consumers; failed candidates never replace documents."""

import pytest
from fastapi import HTTPException

from backend.api import state
from backend.api.crud import (
    BundleRequest,
    EditFeatureBody,
    create_bundle,
    edit_feature,
    delete_feature,
)
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.part_history_verification import verify_current_part
from backend.api.routes_cluster_joints import _build_add_joint


@pytest.fixture(autouse=True)
def document():
    token = set_current_doc("recipe-edit-test")
    try:
        create_bundle(BundleRequest(cells=[[0, 0]], length_bp=21))
        d = state.get_or_404()
        params = {
            "joint_id": "joint",
            "cluster_id": d.cluster_transforms[0].id,
            "local_axis_origin": [0, 0, 0],
            "local_axis_direction": [0, 0, 1],
        }
        state.mutate_with_minor_log(
            op_subtype="joint-place",
            label="Joint",
            params=params,
            fn=lambda d: _build_add_joint(d, params),
        )
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def test_producer_edit_regenerates_joint_and_recovery_data():
    before = state.get_or_404()
    ids = [e.id for e in before.feature_log]
    old_payload = before.feature_log[1].post_state_gz_b64
    # Poison stored outputs: regeneration must use native commands only.
    before.feature_log[0].design_snapshot_gz_b64 = "not-a-snapshot"
    edit_feature(0, EditFeatureBody(params={"length_bp": 32}))
    after = state.get_or_404()
    assert after.helices[0].length_bp == 32
    assert after.cluster_joints == before.cluster_joints
    assert [e.id for e in after.feature_log] == ids
    assert after.feature_log[1].post_state_gz_b64 != old_payload
    restored = state.decode_design_snapshot(after.feature_log[1].post_state_gz_b64)
    assert restored.helices == after.helices
    assert restored.cluster_joints == after.cluster_joints
    assert verify_current_part()["status"] == "verified"
    state.undo()
    assert state.get_or_404().helices[0].length_bp == 21
    state.redo()
    assert verify_current_part()["status"] == "verified"


def test_delete_producer_warns_then_cascades_consumers():
    before, revision = state.get_design_with_revision()
    response = delete_feature(0)
    assert response["needs_cascade_decision"]
    assert response["dependents"][0]["index"] == 1
    assert state.get_design_with_revision() == (before, revision)
    delete_feature(0, cascade=True)
    after = state.get_or_404()
    assert not after.helices and not after.cluster_joints and not after.feature_log
    assert verify_current_part()["status"] == "verified"


def test_deleted_domain_producer_has_structured_cascade_diagnostics():
    from backend.api.crud import DomainShiftRequest, domain_shift

    strand = state.get_or_404().strands[0]
    domain_shift(DomainShiftRequest(entries=[
        {"strand_id": strand.id, "domain_index": 0, "delta_bp": 2}
    ]))
    # Fine Routing records the domain by position (proof v2); the missing target
    # is that (helix, bp, direction) slot.
    first = strand.domains[0]
    slot = f"{first.helix_id}:{first.start_bp}:{first.direction.value}"
    source, revision = state.get_design_with_revision()
    response = delete_feature(0)
    assert response["needs_cascade_decision"]
    issues = [issue for row in response["dependents"] for issue in row["issues"].values()]
    missing = [issue for issue in issues if issue["code"] == "missing_reference"]
    assert any(ref == {"kind": "position", "identity": slot, "parameter_path": ["entries", 0, "at"]}
               for issue in missing for ref in issue["references"])
    assert state.get_design_with_revision() == (source, revision)
    delete_feature(0, cascade=True)
    assert not state.get_or_404().strands
    assert verify_current_part()["status"] == "verified"


def test_delete_routing_child_removes_actual_joint():
    delete_feature(1, sub_index=0)
    assert not state.get_or_404().cluster_joints
    assert len(state.get_or_404().feature_log) == 1
    assert verify_current_part()["status"] == "verified"


def test_broken_downstream_reference_is_atomic():
    before, revision = state.get_design_with_revision()
    depth = state.undo_depth()
    with pytest.raises(HTTPException):
        edit_feature(0, EditFeatureBody(params={"cells": [[4, 4]]}))
    assert state.get_design_with_revision() == (before, revision)
    assert state.undo_depth() == depth


def test_unlogged_changes_cannot_be_discarded_by_edit():
    before = state.get_or_404()
    before.helices[0].length_bp = 45
    with pytest.raises(HTTPException) as exc:
        edit_feature(0, EditFeatureBody(params={"length_bp": 32}))
    assert exc.value.detail["code"] == "recipe_not_reproducible"
    assert state.get_or_404() is before
    assert before.helices[0].length_bp == 45


def test_concurrent_publication_rejects_candidate(monkeypatch):
    from backend.api import part_recipe_edit

    original = part_recipe_edit.regenerate

    def concurrent(*args, **kwargs):
        candidate = original(*args, **kwargs)
        state.set_design(state.get_or_404().copy_with())
        return candidate

    monkeypatch.setattr(part_recipe_edit, "regenerate", concurrent)
    with pytest.raises(HTTPException) as exc:
        edit_feature(0, EditFeatureBody(params={"length_bp": 32}))
    assert exc.value.status_code == 409
    assert state.get_or_404().helices[0].length_bp == 21


def test_late_edit_executes_verified_prefix_once_and_repairs_its_recovery(monkeypatch):
    from backend.api import part_recipe_edit

    calls = []
    original = part_recipe_edit.execute

    def counted(kind, design, params):
        calls.append(kind)
        return original(kind, design, params)

    monkeypatch.setattr(part_recipe_edit, "execute", counted)
    state.get_or_404().feature_log[0].post_state_gz_b64 = "poisoned recovery bytes"
    edit_feature(1, EditFeatureBody(params={"min_angle_deg": -20}), sub_index=0)
    assert calls.count("bundle-create") == 1
    assert calls.count("joint-place") == 2
    repaired = state.decode_design_snapshot(
        state.get_or_404().feature_log[0].post_state_gz_b64
    )
    assert repaired.helices == state.get_or_404().helices
    assert verify_current_part()["status"] == "verified"
