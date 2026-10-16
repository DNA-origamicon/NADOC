"""Joined generated overlays and paths survive cold replay and ordinary edits."""

from copy import deepcopy

import numpy as np

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.generated_history import GeneratedHistory
from backend.api.generated_joined_steps import build_joined_sections, route_joined_sections
from backend.api.part_verification_worker import VerificationWorker
from backend.core.joined_branches import _fit_stem
from backend.core.models import Design
from backend.core.part_history_contract import create_empty_part
from backend.core.part_verification_capture import capture
from backend.core.two_np_generator import GeneratorSettings
from tests.test_part_branch_commands import SEED
from tests.test_part_joined_path_commands import selected_plan


def cold_proof(design):
    isolated = Design.model_validate_json(design.model_dump_json())
    for entry in isolated.feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
            entry.diff_added_b64 = entry.diff_modified_b64 = "poisoned delta"
    worker = VerificationWorker(capture(isolated))
    try:
        worker.start()
        assert worker.wait(5), "Joined recipe exceeded the ordinary cold proof allowance"
        result = worker.result()
        assert result["status"] == "verified", result
        assert result["checked_commands"] == len(design.feature_log)
    finally:
        worker.close()


def test_generated_joined_path_edit_regenerates_without_samples_or_recovery():
    token = set_current_doc("generated-joined-path-proof")
    try:
        source = create_empty_part("Joined part", "HONEYCOMB")
        history = GeneratedHistory(source, GeneratorSettings())
        build_joined_sections(source, selected_plan(), history, history_seed=SEED)
        state.load_design(history.design)
        original = state.get_or_404()
        cold_proof(original)
        index = next(i for i, entry in enumerate(original.feature_log)
                     if getattr(entry, "op_kind", None) == "joined-crossbar-path")
        params = original.feature_log[index].params
        patch = {}
        for key in ("endpoint_a_nm", "endpoint_b_nm", "junction_nm"):
            patch[key] = deepcopy(params[key])
            patch[key][0] += 0.25
        crud.edit_feature(index, crud.EditFeatureBody(params=patch))
        updated = state.get_or_404()
        assert updated.deformations != original.deformations
        assert [op.id for op in updated.deformations] == [op.id for op in original.deformations]
        assert updated.helices == original.helices and updated.strands == original.strands
        assert updated.cluster_transforms == original.cluster_transforms
        assert [entry.id for entry in updated.feature_log] == [entry.id for entry in original.feature_log]
        cold_proof(updated)
        state.undo()
        assert state.get_or_404().deformations == original.deformations
    finally:
        state.close_session()
        reset_current_doc(token)


def test_generated_joined_route_cold_replay_and_upstream_path_edit():
    token = set_current_doc("generated-joined-route-proof")
    try:
        source = create_empty_part("Joined part", "HONEYCOMB")
        history = GeneratedHistory(source, GeneratorSettings())
        summary = selected_plan()
        _fit_stem(summary, source.lattice_type)
        local, summary = build_joined_sections(source, summary, history, history_seed=SEED)
        route_joined_sections(local, summary, history)
        state.load_design(history.design)
        original = state.get_or_404()
        cold_proof(original)
        index = next(i for i, entry in enumerate(original.feature_log) if entry.feature_type == "cluster_create")
        group_id = original.feature_log[index].cluster_id
        # Identity-shaped user text stays text through subsequent scoped replay.
        label = original.helices[0].id
        crud.edit_feature(index, crud.EditFeatureBody(params={"name": label}))
        updated = state.get_or_404()
        assert next(cluster for cluster in updated.cluster_transforms if cluster.id == group_id).name == label
        assert updated.helices == original.helices and updated.strands == original.strands
        assert updated.flexible_connections == original.flexible_connections
        assert [entry.id for entry in updated.feature_log] == [entry.id for entry in original.feature_log]
        cold_proof(updated)

        # Change actual geometry upstream of both Join operations. Translating
        # all three stations retains the native path's sampled extent, so this
        # checks downstream regeneration independently of coordinated seed edits.
        path_index = next(i for i, entry in enumerate(updated.feature_log)
                          if getattr(entry, "op_kind", None) == "joined-crossbar-path")
        path_entry = updated.feature_log[path_index]
        patch = {}
        for key in ("endpoint_a_nm", "endpoint_b_nm", "junction_nm"):
            patch[key] = deepcopy(path_entry.params[key])
            patch[key][0] += 0.01
        path_id = next(operation.id for operation in updated.deformations
                       if operation.id.endswith(path_entry.params["deformation_id"]))
        prior_path = next(operation for operation in updated.deformations if operation.id == path_id)
        joins = [entry for entry in updated.feature_log
                 if getattr(entry, "op_kind", None) == "cluster-join"]
        assert len(joins) == 2
        crud.edit_feature(path_index, crud.EditFeatureBody(params=patch))
        moved = state.get_or_404()
        moved_path = next(operation for operation in moved.deformations if operation.id == path_id)
        assert len(moved_path.params.bp_positions_nm) == len(prior_path.params.bp_positions_nm)
        np.testing.assert_allclose(
            moved_path.params.bp_positions_nm,
            np.asarray(prior_path.params.bp_positions_nm) + [0.01, 0, 0], rtol=0, atol=1e-9,
        )
        assert [operation for operation in moved.deformations if operation.id != path_id] == [
            operation for operation in updated.deformations if operation.id != path_id]
        assert [helix.id for helix in moved.helices] == [helix.id for helix in updated.helices]
        assert [strand.id for strand in moved.strands] == [strand.id for strand in updated.strands]
        assert [entry.id for entry in moved.feature_log] == [entry.id for entry in updated.feature_log]
        rebuilt_joins = [entry for entry in moved.feature_log
                         if getattr(entry, "op_kind", None) == "cluster-join"]
        assert len(rebuilt_joins) == len(joins)
        for old, rebuilt in zip(joins, rebuilt_joins):
            assert rebuilt.params == old.params
            assert rebuilt.design_snapshot_gz_b64 != old.design_snapshot_gz_b64
            prefix = state.decode_design_snapshot(rebuilt.design_snapshot_gz_b64)
            assert next(operation for operation in prefix.deformations if operation.id == path_id) == moved_path
        cold_proof(moved)
        state.undo()
        restored = state.get_or_404()
        assert restored.deformations == updated.deformations
        assert restored.flexible_connections == updated.flexible_connections
    finally:
        state.close_session()
        reset_current_doc(token)
