"""Independent section recipes survive cold replay, edits, and dependency repair."""

from copy import deepcopy
from uuid import uuid5

import pytest

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_history_verification import verify_current_part
from backend.api.part_proof_commands import execute
from backend.api.part_section_commands import compile_seed_params
from backend.api.part_verification_worker import VerificationWorker
from backend.api.routes_clusters import AddClusterBody, add_cluster
from backend.core.models import Design, LatticeType
from backend.core.part_history_contract import create_empty_part
from backend.core.part_verification_capture import capture
from tests.test_part_branch_commands import ROUTE, SEED
from tests.test_part_section_commands import sections


def record(kind, params):
    params = {**params, "_proof_version": 1}
    state.mutate_with_feature_log(kind, kind, params,
                                  lambda current: execute(kind, current, params))


@pytest.fixture
def constructed():
    token = set_current_doc("native-independent-section-proof")
    try:
        state.load_design(create_empty_part("Independent sections", "HONEYCOMB"))
        groups = []
        for index, (spec, identity) in enumerate(zip(sections(LatticeType.HONEYCOMB), (SEED, ROUTE))):
            old_ids = {helix.id for helix in state.get_or_404().helices}
            record("independent-section-seed", compile_seed_params(spec, index, identity))
            helix_ids = [helix.id for helix in state.get_or_404().helices if helix.id not in old_ids]
            add_cluster(AddClusterBody(name=f"Independent section {index + 1}", helix_ids=helix_ids, log=True))
            cluster = next(cluster for cluster in state.get_or_404().cluster_transforms
                           if cluster.name == f"Independent section {index + 1}")
            record("auto-scaffold-bounded-section", {
                "cluster_id": cluster.id, "history_seed": str(uuid5(identity, "bounded-route")),
                "lattice_column_offset": 1000 * index,
            })
            groups.append((cluster.id, helix_ids))
        yield groups
    finally:
        state.close_session()
        reset_current_doc(token)


def poison_recovery(design):
    for entry in design.feature_log:
        if entry.feature_type == "snapshot":
            entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
            entry.diff_added_b64 = entry.diff_modified_b64 = "poisoned recovery"


def cold_proof():
    source = Design.model_validate_json(state.get_or_404().model_dump_json())
    poison_recovery(source)
    worker = VerificationWorker(capture(source))
    try:
        worker.start()
        assert worker.wait(5), "Small section recipe exceeded cold proof allowance"
        result = worker.result()
        assert result["status"] == "verified", result
        assert result["checked_commands"] == len(source.feature_log)
    finally:
        worker.close()


def test_cold_section_replay_and_length_edit_keep_independent_work(constructed):
    cold_proof()
    original = state.get_or_404()
    identities = [entry.id for entry in original.feature_log]
    original_helices = [helix.id for helix in original.helices]
    independent_ids = set(constructed[0][1])
    independent_helices = [helix for helix in original.helices if helix.id in independent_ids]
    independent_strands = [strand for strand in original.strands
                           if all(domain.helix_id in independent_ids for domain in strand.domains)]
    tracks = deepcopy(original.feature_log[3].params["tracks"])
    for track in tracks:
        track["intervals"][0]["hi_bp"] = 104
    poison_recovery(original)
    crud.edit_feature(3, crud.EditFeatureBody(params={"nominal_length_bp": 105, "tracks": tracks}))
    updated = state.get_or_404()
    assert [entry.id for entry in updated.feature_log] == identities
    assert [helix.id for helix in updated.helices] == original_helices
    assert [updated.find_helix(helix.id) for helix in independent_helices] == independent_helices
    assert [updated.find_strand(strand.id) for strand in independent_strands] == independent_strands
    assert updated.cluster_transforms == original.cluster_transforms
    assert len(updated.scaffolds()) == 2
    assert updated.helices != original.helices
    seed_state = state.decode_design_snapshot(updated.feature_log[3].post_state_gz_b64)
    assert all(seed_state.find_helix(identity).length_bp == 105 for identity in constructed[1][1])
    recovered = state.decode_design_snapshot(updated.feature_log[-1].post_state_gz_b64)
    assert recovered.helices == updated.helices
    assert recovered.strands == updated.strands
    cold_proof()
    state.undo()
    assert state.get_or_404().helices == original.helices
    state.redo()
    assert state.get_or_404().helices == updated.helices
    assert verify_current_part()["status"] == "verified"


def test_deleted_section_group_reports_missing_route_and_cascades_only_dependents(constructed):
    original, revision = state.get_design_with_revision()
    preview = crud.delete_feature(4)
    assert preview["needs_cascade_decision"]
    issues = [issue for row in preview["dependents"] for issue in row["issues"].values()]
    assert any(issue["code"] == "missing_reference" and issue["references"] == [{
        "kind": "cluster", "identity": constructed[1][0], "parameter_path": ["cluster_id"],
    }] for issue in issues)
    assert state.get_design_with_revision() == (original, revision)
    crud.delete_feature(4, cascade=True)
    updated = state.get_or_404()
    assert len(updated.feature_log) == 4
    assert constructed[1][0] not in {cluster.id for cluster in updated.cluster_transforms}
    assert [updated.find_helix(identity) for identity in constructed[0][1]] == [
        original.find_helix(identity) for identity in constructed[0][1]]
    assert verify_current_part()["status"] == "verified"
    cold_proof()
