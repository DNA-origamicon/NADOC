"""Planar generator commands remain editable recipes across process boundaries."""

from uuid import uuid4

import pytest

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.generated_history import GeneratedHistory
from backend.api.part_branch_commands import compile_route_params, compile_seed_params
from backend.api.part_proof_commands import execute
from backend.api.part_history_verification import verify_current_part
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from backend.core.part_verification_capture import capture
from backend.core.two_np_generator import GeneratorSettings
from tests.test_part_branch_commands import plan


@pytest.fixture
def constructed():
    token = set_current_doc("native-branch-proof")
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[20, 20]], length_bp=21))
        independent = state.get_or_404().model_copy(deep=True)
        history = GeneratedHistory(independent, GeneratorSettings())
        raw = Design(lattice_type=independent.lattice_type)
        summary = plan()
        seed_params = compile_seed_params(summary, uuid4())
        seeded = execute("branch-seed", raw, seed_params)
        history.record(raw, seeded, "branch-seed", "Create sparse tracks", seed_params, "branched-sections")
        route_params = compile_route_params(seeded, summary, uuid4())
        routed = execute("auto-scaffold-sections", seeded, route_params)
        history.record(seeded, routed, "auto-scaffold-sections", "Route sections", route_params, "scaffold")
        state.set_design(history.design)
        yield independent
    finally:
        state.close_session()
        reset_current_doc(token)


def assert_cold_proof():
    source = Design.model_validate_json(state.get_or_404().model_dump_json())
    for entry in source.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
    worker = VerificationWorker(capture(source))
    try:
        worker.start()
        assert worker.wait(5), "Small branch recipe exceeded cold proof allowance"
        result = worker.result()
        assert result["status"] == "verified", result
    finally:
        worker.close()


def test_generated_branch_cold_replay_edit_and_undo(constructed):
    assert_cold_proof()
    before = state.get_or_404()
    identities = [h.id for h in before.helices]
    before.feature_log[1].post_state_gz_b64 = "poisoned recovery"
    crud.edit_feature(1, crud.EditFeatureBody(params={"nominal_length_bp": 273}))
    updated = state.get_or_404()
    assert [h.id for h in updated.helices] == identities
    assert updated.find_helix(constructed.helices[0].id) == constructed.helices[0]
    # The existing router sets routed extents from actual occupied sections;
    # the seed's editable nominal extent is still regenerated in its own state.
    seed_state = state.decode_design_snapshot(updated.feature_log[1].post_state_gz_b64)
    assert all(h.length_bp == 273 for h in seed_state.helices
               if h.id not in {v.id for v in constructed.helices})
    assert_cold_proof()
    state.undo()
    assert state.get_or_404().helices == before.helices
    state.redo()
    assert verify_current_part()["status"] == "verified"


def test_deleting_sparse_seed_reports_missing_route_targets_and_preserves_independent_part(constructed):
    source, revision = state.get_design_with_revision()
    preview = crud.delete_feature(1)
    assert preview["needs_cascade_decision"]
    issues = list(preview["dependents"][0]["issues"].values())
    assert any(issue["code"] == "missing_reference" for issue in issues)
    assert state.get_design_with_revision() == (source, revision)
    crud.delete_feature(1, cascade=True)
    assert state.get_or_404().helices == constructed.helices
    assert state.get_or_404().strands == constructed.strands
    assert verify_current_part()["status"] == "verified"
