"""Generated connectivity steps use the registered commands, including cold replay."""

from copy import deepcopy

import pytest
from fastapi import HTTPException

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.generated_connectivity_steps import build_connectivity_steps, compile_connectivity_steps
from backend.api.generated_history import GeneratedHistory
from backend.api.part_branch_commands import compile_sparse_seed_params
from backend.api.part_proof_commands import dependencies, execute
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_verification_capture import capture
from backend.core.two_np_generator import GeneratorSettings
from tests.test_native_path_proof import cold_proof, record
from tests.test_part_branch_commands import SEED
from tests.test_part_connectivity_commands import connectivity_plan


def test_registered_connectivity_pipeline_cold_replay_and_endpoint_edit():
    token = set_current_doc("native-connectivity-proof")
    try:
        source = create_empty_part("Connectivity recipe", "HONEYCOMB")
        _, summary = connectivity_plan(False)
        summary.update(scaffold_size=7249, scaffold_name="M13mp18")
        # Evaluated candidate paths cannot rescue a missing native contract.
        summary["connectivity_paths"] = [{"poisoned": True}]
        history = GeneratedHistory(source, GeneratorSettings())
        build_connectivity_steps(source, summary, history)
        assert history.unverified_steps == []
        state.load_design(history.design)
        before = state.get_or_404()
        kinds = [entry.op_kind for entry in before.feature_log]
        assert kinds == ["branch-seed", "connectivity-path", "auto-scaffold-connectivity-section",
                         "encode-sweep-curvature", "full-autostaple", "encode-sweep-curvature",
                         "assign-scaffold-sequence", "assign-staple-sequences"]
        cold_proof()
        segments = before.feature_log[1].params["segments"]
        segments = [{**segment, "end_nm": [*segment["end_nm"]]} for segment in segments]
        segments[-1]["end_nm"][0] += 0.2
        original_id = before.deformations[0].id
        crud.edit_feature(1, crud.EditFeatureBody(params={
            "segments": segments, "deformation_id": "replacement-not-allowed",
        }))
        after = state.get_or_404()
        assert after.deformations[0].id == original_id
        assert after.deformations[0].params != before.deformations[0].params
        assert [entry.id for entry in after.feature_log] == [entry.id for entry in before.feature_log]
        cold_proof()
    finally:
        state.close_session()
        reset_current_doc(token)


def test_two_face_cold_replay_endpoint_edit_and_changed_shared_junction_repair():
    token = set_current_doc("native-connectivity-parent-proof")
    try:
        state.load_design(create_empty_part("Connectivity shared junction", "HONEYCOMB"))
        _, summary = connectivity_plan(two_faces=True)
        record("branch-seed", compile_sparse_seed_params(summary, SEED))
        for kind, _, params, _ in compile_connectivity_steps(state.get_or_404(), summary):
            record(kind, params)
        before = state.get_or_404()
        assert len(before.deformations) == 2
        assert before.feature_log[2].params["parent_deformation_id"] == before.deformations[0].id
        cold_proof()

        child_segments = deepcopy(before.feature_log[2].params["segments"])
        child_segments[-1]["end_nm"][0] -= 0.2
        crud.edit_feature(2, crud.EditFeatureBody(params={"segments": child_segments}))
        updated = state.get_or_404()
        assert updated.deformations[0] == before.deformations[0]
        assert updated.deformations[1].id == before.deformations[1].id
        assert updated.deformations[1].params != before.deformations[1].params
        lo, hi = updated.feature_log[2].params["shared_interval"]
        # Editing the terminal endpoint keeps every inherited junction station.
        assert updated.deformations[1].params.bp_positions_nm[:hi - lo + 2] == (
            before.deformations[1].params.bp_positions_nm[:hi - lo + 2])
        cold_proof()

        parent_segments = deepcopy(updated.feature_log[1].params["segments"])
        assert len(parent_segments) == 2
        parent_segments[0]["end_nm"][0] += 0.1
        parent_segments[1]["start_nm"][0] += 0.1
        isolated = capture(updated)
        isolated.feature_log[1].params["segments"] = parent_segments
        report = assess_part_history(isolated, execute=execute, dependencies=dependencies)
        assert report["status"] == "failed", report
        assert report["issues"][0]["feature_id"] == updated.feature_log[2].id
        assert report["issues"][0]["references"] == [{
            "kind": "deformation", "identity": updated.deformations[0].id,
            "parameter_path": ["parent_deformation_id"],
        }]
        original, revision = state.get_design_with_revision()
        undo_depth = state.undo_depth()
        with pytest.raises(HTTPException):
            crud.edit_feature(1, crud.EditFeatureBody(params={"segments": parent_segments}))
        assert state.get_design_with_revision() == (original, revision)
        assert state.undo_depth() == undo_depth
    finally:
        state.close_session()
        reset_current_doc(token)
