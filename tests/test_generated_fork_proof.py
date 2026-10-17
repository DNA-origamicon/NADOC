"""A composed fork remains a cold-replayable recipe after a dimensional edit."""

from uuid import uuid4

import numpy as np

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.generated_branch_steps import apply_fork_steps, encode_fork_curvature
from backend.api.generated_history import GeneratedHistory
from backend.api.part_branch_commands import compile_partition_params, compile_sparse_seed_params
from backend.api.part_proof_commands import execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from backend.core.curved_branches import _candidate
from backend.core.part_verification_capture import capture
from backend.core.two_np_generator import GeneratorSettings


def cold_proof(design):
    isolated = Design.model_validate_json(design.model_dump_json())
    for entry in isolated.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned saved output"
        entry.diff_added_b64 = entry.diff_modified_b64 = "poisoned delta"
    worker = VerificationWorker(capture(isolated))
    try:
        worker.start()
        assert worker.wait(5), "Small generated fork exceeded ordinary proof allowance"
        report = worker.result()
        assert report["status"] == "verified", report.get("issues", report)
        assert report["checked_commands"] == len(design.feature_log)
    finally:
        worker.close()


def test_composed_fork_cold_replay_radius_edit_and_semantic_noop():
    token = set_current_doc("generated-fork-proof")
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[25, 25]], length_bp=21))
        independent = state.get_or_404().model_copy(deep=True)
        history = GeneratedHistory(independent, GeneratorSettings())
        summary = _candidate(
            np.array([[-23, 0, -50], [23, 0, -50], [-23, 0, 50], [23, 0, 50]]),
            np.eye(3), True,
        )
        before = Design(lattice_type=independent.lattice_type)
        params = compile_sparse_seed_params(summary, uuid4())
        current = execute("branch-seed", before, params)
        history.record(before, current, "branch-seed", "Fork tracks", params, "seed")
        current = apply_fork_steps(current, summary, history)
        params = compile_partition_params(current, summary, uuid4())
        routed = execute("auto-scaffold-sections", current, params)
        history.record(current, routed, "auto-scaffold-sections", "Route fork", params, "route")
        encoded = encode_fork_curvature(routed, history, "encode-first")
        # A currently redundant command is still a recipe operation. Downstream
        # edits may make it effective; recording must preserve that intent.
        encode_fork_curvature(encoded, history, "encode-again")
        state.set_design(history.design)
        original = state.get_or_404()
        assert [entry.op_kind for entry in original.feature_log[-2:]] == [
            "encode-sweep-curvature", "encode-sweep-curvature",
        ]
        cold_proof(original)
        path_index = next(i for i, entry in enumerate(original.feature_log) if entry.op_kind == "fork-path")
        old_path = original.feature_log[path_index]
        old_ids = [operation.id for operation in original.deformations]
        crud.edit_feature(path_index, crud.EditFeatureBody(params={
            "radius_nm": old_path.params["radius_nm"] * 1.01,
        }))
        updated = state.get_or_404()
        assert updated.deformations != original.deformations
        assert [operation.id for operation in updated.deformations] == old_ids
        assert [entry.id for entry in updated.feature_log] == [entry.id for entry in original.feature_log]
        assert updated.find_helix(independent.helices[0].id) == independent.helices[0]
        cold_proof(updated)
        state.undo()
        assert state.get_or_404().deformations == original.deformations
    finally:
        state.close_session()
        reset_current_doc(token)
