"""Registered path features regenerate from inputs and keep repairable references."""

import pytest
from fastapi import HTTPException

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_verification_capture import capture


def record(kind, params):
    params = {**params, "_proof_version": 1}
    return state.mutate_with_feature_log(
        kind, kind, params, lambda current: execute(kind, current, params),
    )[2]


@pytest.fixture
def constructed():
    token = set_current_doc("native-path-proof")
    try:
        state.load_design(create_empty_part("Fork recipe", "HONEYCOMB"))
        # Modern bundle-create owns lattice frames. This path contract deliberately
        # uses native unframed seed tracks, as the curved generator does.
        record("branch-seed", {
            "history_seed": "1be57c22-90c0-48b2-8ed1-ce8c03784a3d",
            "nominal_length_bp": 113,
            "tracks": [
                {"key": key, "cell": cell,
                 "intervals": [{"key": "full", "lo_bp": 0, "hi_bp": 112}]}
                for key, cell in (("a", [0, 0]), ("b", [0, 1]), ("other", [3, 5]))
            ],
        })
        ids = [helix.id for helix in state.get_or_404().helices]
        record("fork-path", {
            "deformation_id": "native-fork", "helix_ids": ids[:2],
            "radius_nm": 12.0, "stem_bp": 42, "arc_bp": 56, "tail_bp": 7,
            "double": False, "mirror": 1,
        })
        for identity, intervals in (("rule-a", []), ("rule-b", [[7, 21]])):
            record("crossover-constraint-create", {
                "constraint_id": identity, "helix_ids_a": ids[:2],
                "helix_ids_b": ids[2:], "allowed_bp_intervals": intervals,
            })
        record("encode-sweep-curvature", {"op_ids": ["native-fork"]})
        yield ids
    finally:
        state.close_session()
        reset_current_doc(token)


def cold_proof():
    source = Design.model_validate_json(state.get_or_404().model_dump_json())
    for entry in source.feature_log:
        entry.design_snapshot_gz_b64 = "invalid input snapshot"
        entry.post_state_gz_b64 = "invalid saved output"
        entry.diff_added_b64 = entry.diff_modified_b64 = "invalid delta"
    worker = VerificationWorker(capture(source))
    try:
        worker.start()
        assert worker.wait(5), "Small fork recipe exceeded the ordinary worker allowance"
        result = worker.result()
        assert result["status"] == "verified", result
        assert result["checked_commands"] == len(source.feature_log)
    finally:
        worker.close()


def test_cold_path_replay_and_radius_edit_rebuild_outputs_with_stable_identity(constructed):
    cold_proof()
    before = state.get_or_404()
    feature_ids = [entry.id for entry in before.feature_log]
    old_points = before.deformations[0].params.points_nm
    other = before.find_helix(constructed[-1])
    placement = before.cluster_transforms
    assert len(placement) == 1
    assert set(placement[0].helix_ids) == set(constructed)
    for entry in before.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
    crud.edit_feature(1, crud.EditFeatureBody(params={
        "radius_nm": 14.0, "deformation_id": "must-not-replace-authored-identity",
    }))
    updated = state.get_or_404()
    assert updated.deformations[0].id == "native-fork"
    assert updated.feature_log[1].params["deformation_id"] == "native-fork"
    assert updated.feature_log[1].params["radius_nm"] == 14.0
    assert updated.deformations[0].params.points_nm != old_points
    assert updated.find_helix(constructed[-1]) == other
    assert [entry.id for entry in updated.feature_log] == feature_ids
    assert updated.crossover_constraints == before.crossover_constraints
    assert updated.cluster_transforms == placement
    recovered = state.decode_design_snapshot(updated.feature_log[-1].post_state_gz_b64)
    assert recovered.deformations == updated.deformations
    assert recovered.helices == updated.helices
    assert recovered.cluster_transforms == updated.cluster_transforms
    cold_proof()
    state.undo()
    assert state.get_or_404().deformations == before.deformations
    state.redo()
    assert state.get_or_404().deformations == updated.deformations


def test_missing_path_reference_is_structured_and_failed_edit_is_atomic(constructed):
    original, revision = state.get_design_with_revision()
    undo_depth = state.undo_depth()
    with pytest.raises(HTTPException):
        crud.edit_feature(1, crud.EditFeatureBody(params={"helix_ids": ["deleted-helix"]}))
    assert state.get_design_with_revision() == (original, revision)
    assert state.undo_depth() == undo_depth

    isolated = capture(original)
    isolated.feature_log[1].params["helix_ids"] = ["deleted-helix"]
    report = assess_part_history(isolated, execute=execute, dependencies=dependencies)
    assert report["status"] == "failed", report
    issue = report["issues"][0]
    assert issue["code"] == "missing_reference"
    assert issue["feature_id"] == original.feature_log[1].id
    assert issue["references"] == [{
        "kind": "helix", "identity": "deleted-helix", "parameter_path": ["helix_ids", 0],
    }]
    assert original.feature_log[1].params["helix_ids"] == constructed[:2]


def test_delete_constraint_reference_can_be_retargeted_after_two_creations(constructed):
    record("crossover-constraint-delete", {"constraint_id": "rule-a"})
    before = state.get_or_404()
    assert [rule.id for rule in before.crossover_constraints] == ["rule-b"]
    entry_id = before.feature_log[-1].id
    crud.edit_feature(5, crud.EditFeatureBody(params={"constraint_id": "rule-b"}))
    updated = state.get_or_404()
    assert updated.feature_log[-1].id == entry_id
    assert updated.feature_log[-1].params["constraint_id"] == "rule-b"
    assert [rule.id for rule in updated.crossover_constraints] == ["rule-a"]
    assert updated.crossover_constraints[0].allowed_bp_intervals == []
    assert updated.deformations == before.deformations
    cold_proof()
