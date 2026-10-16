"""Native gold and thiol recipes survive cold replay and geometry edits."""

import pytest
from fastapi import HTTPException

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.api.routes_nanoparticles import (
    GoldNanosphereCreate, ThiolConjugationRequest, create_nanosphere,
    delete_conjugation, put_conjugation,
)
from backend.core.models import Design, StrandExtension
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_verification_capture import capture


@pytest.fixture
def document():
    token = set_current_doc("native-thiol-proof")
    try:
        state.load_design(create_empty_part("Thiol recipe", "HONEYCOMB"))
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


def graft():
    identity = create_nanosphere(GoldNanosphereCreate(diameter_nm=10))["nanoparticle_id"]
    result = put_conjugation(identity, ThiolConjugationRequest(sequence="ACGTACGT", count=2, seed=17))
    return identity, result


def test_empty_root_native_graft_cold_replays_without_saved_outputs(document):
    identity, response = graft()
    design = state.get_or_404()
    assert design.recipe_root.kind == "empty"
    assert response["conjugation_id"] == design.nanoparticle_conjugations[0].id
    assert response["strand_ids"] == [item.id for item in design.strands]
    assert design.feature_log[-1].params["thiol_version"] == 1
    assert design.feature_log[-1].params["replace_conjugation_ids"] == []
    assert design.feature_log[-1].params["nanoparticle_id"] == identity
    isolated = Design.from_json(design.to_json())
    for entry in isolated.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
    worker = VerificationWorker(capture(isolated))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "verified", result
        assert result["checked_commands"] == 2
        assert result["native_editable"]
    finally:
        worker.close()


def test_particle_and_graft_edits_regenerate_geometry_with_stable_ids_and_undo(document):
    _, response = graft()
    original = state.get_or_404()
    ids = [item.id for item in original.feature_log]
    positions = [item.axis_start for item in original.helices]
    crud.edit_feature(0, crud.EditFeatureBody(params={"diameter_nm": 14}))
    resized = state.get_or_404()
    assert resized.nanoparticles[0].diameter_nm == 14
    assert [item.axis_start for item in resized.helices] != positions
    assert [item.id for item in resized.strands] == response["strand_ids"]
    assert proof(resized)["status"] == "verified"
    crud.edit_feature(1, crud.EditFeatureBody(params={"count": 3, "sequence": "TTTT",
        "attach_end": "3p", "seed": 19, "conjugation_id": "attempted-change", "thiol_version": 99}))
    edited = state.get_or_404()
    assert edited.nanoparticle_conjugations[0].id == response["conjugation_id"]
    assert edited.feature_log[-1].params["thiol_version"] == 1
    assert [item.id for item in edited.strands[:2]] == response["strand_ids"]
    assert all(item.length_bp == 4 for item in edited.helices)
    assert all(item.sequence == "TTTT" for item in edited.strands)
    assert edited.helices[0].axis_start != resized.helices[0].axis_start
    assert [item.id for item in edited.feature_log] == ids
    assert proof(edited)["status"] == "verified"
    state.undo()
    assert state.get_or_404().helices == resized.helices
    state.redo()
    assert state.get_or_404().helices == edited.helices


def test_replacement_then_delete_is_replayable_and_particle_deletion_cascades(document):
    identity, first = graft()
    second = put_conjugation(identity, ThiolConjugationRequest(sequence="TTTT", count=3, attach_end="3p"))
    replaced = state.get_or_404()
    assert replaced.feature_log[-1].params["replace_conjugation_ids"] == [first["conjugation_id"]]
    assert set(first["strand_ids"]).isdisjoint(second["strand_ids"])
    assert proof(replaced)["status"] == "verified"
    delete_conjugation(identity)
    deleted = state.get_or_404()
    assert not deleted.helices and not deleted.strands and not deleted.overhangs
    assert not deleted.nanoparticle_conjugations and not deleted.staple_groups
    assert proof(deleted)["status"] == "verified"
    state.undo()
    assert proof(state.get_or_404())["status"] == "verified"
    preview = crud.delete_feature(0)
    assert preview["needs_cascade_decision"]
    crud.delete_feature(0, cascade=True)
    empty = state.get_or_404()
    assert not empty.nanoparticles and not empty.strands and not empty.helices
    assert proof(empty)["status"] == "verified"


def test_route_refuses_removal_with_incoming_consumer_without_publication(document):
    identity, response = graft()
    design = state.get_or_404()
    state.set_design(design.copy_with(extensions=[StrandExtension(
        strand_id=response["strand_ids"][0], end="five_prime", sequence="TT")]))
    before, revision = state.get_design_with_revision()
    with pytest.raises(HTTPException) as error:
        delete_conjugation(identity)
    assert error.value.status_code == 422
    assert error.value.detail["code"] == "invalid_selection"
    assert state.get_design_with_revision() == (before, revision)


def test_saved_geometry_tampering_is_not_blessed_by_graft_ownership(document):
    graft()
    design = state.get_or_404().model_copy(deep=True)
    design.helices[0].axis_start.x += 1
    result = proof(design)
    assert result["status"] == "mismatch", result
    assert "helices" in result["issues"][0]["fields"]


def test_legacy_receipt_without_thiol_contract_remains_unknown(document):
    graft()
    design = state.get_or_404().model_copy(deep=True)
    design.feature_log[-1].params.pop("thiol_version")
    result = proof(design)
    assert result["status"] == "unverified", result
