"""Normal unbound particle drag/resize remains reproducible after grafting."""

import pytest
from fastapi import HTTPException

from backend.api import crud, state, part_thiol_patch_commands as commands
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.api.routes_nanoparticles import NanoparticlePatch, patch_nanoparticle
from backend.core.models import Design, StrandExtension
from backend.core.nanoparticle import replace_gold_nanosphere
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_verification_capture import capture
from tests.test_native_thiol_proof import graft
from tests.test_part_thiol_patch_commands import move


@pytest.fixture
def document():
    token = set_current_doc("native-thiol-patch-proof")
    try:
        state.load_design(create_empty_part("Movable graft recipe", "HONEYCOMB"))
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


def test_live_graft_and_native_move_resize_cold_replay_without_saved_geometry(document):
    identity, response = graft()
    before = state.get_or_404()
    patch = {"diameter_nm": 14, "gizmo_move": move()}
    expected = replace_gold_nanosphere(before, identity, **patch)
    patch_nanoparticle(identity, NanoparticlePatch(**patch))
    design = state.get_or_404()
    assert design.model_dump(mode="json", include=AUTHORING_FIELDS) == expected.model_dump(
        mode="json", include=AUTHORING_FIELDS)
    entry = design.feature_log[-1]
    assert entry.params["thiol_version"] == entry.params["nanoparticle_version"] == 1
    assert entry.params["conjugation_ids"] == [response["conjugation_id"]]
    assert entry.op_kind == "nanoparticle-patch"
    assert proof(design)["status"] == "verified"
    isolated = Design.from_json(design.to_json())
    for entry in isolated.feature_log:
        entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
    worker = VerificationWorker(capture(isolated))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "verified", result
        assert result["checked_commands"] == 3 and result["native_editable"]
    finally:
        worker.close()


def test_upstream_and_motion_parameter_edits_regenerate_owned_geometry_and_keep_ids(document):
    identity, response = graft()
    patch_nanoparticle(identity, NanoparticlePatch(gizmo_move=move()))
    original = state.get_or_404()
    entry_ids = [entry.id for entry in original.feature_log]
    crud.edit_feature(0, crud.EditFeatureBody(params={"diameter_nm": 14}))
    resized = state.get_or_404()
    assert resized.helices != original.helices
    assert resized.nanoparticles[0].diameter_nm == 14
    assert [strand.id for strand in resized.strands] == response["strand_ids"]
    assert proof(resized)["status"] == "verified"
    crud.edit_feature(1, crud.EditFeatureBody(params={"count": 3, "sequence": "TTTT", "attach_end": "3p"}))
    regrafted = state.get_or_404()
    assert len(regrafted.helices) == 3 and all(helix.length_bp == 4 for helix in regrafted.helices)
    assert [strand.id for strand in regrafted.strands[:2]] == response["strand_ids"]
    assert regrafted.feature_log[-1].params["conjugation_ids"] == [response["conjugation_id"]]
    assert proof(regrafted)["status"] == "verified"
    changed_move = {**move(), "translation": [4, -2, 3]}
    crud.edit_feature(2, crud.EditFeatureBody(params={"gizmo_move": changed_move}))
    moved = state.get_or_404()
    assert moved.helices != regrafted.helices
    assert [entry.id for entry in moved.feature_log] == entry_ids
    assert moved.feature_log[-1].params["thiol_version"] == 1
    assert proof(moved)["status"] == "verified"
    state.undo()
    assert state.get_or_404().helices == regrafted.helices
    state.redo()
    assert state.get_or_404().helices == moved.helices


def test_invalid_thiol_version_edit_is_rejected_without_publication(document):
    identity, _ = graft()
    patch_nanoparticle(identity, NanoparticlePatch(gizmo_move=move()))
    before, revision = state.get_design_with_revision()
    with pytest.raises(HTTPException):
        crud.edit_feature(2, crud.EditFeatureBody(params={"thiol_version": 99}))
    assert state.get_design_with_revision() == (before, revision)
    assert state.get_or_404().feature_log[-1].params["thiol_version"] == 1


def test_feature_deletion_previews_and_cascades_the_graft_dependent_motion(document):
    identity, _ = graft()
    patch_nanoparticle(identity, NanoparticlePatch(gizmo_move=move()))
    original = state.get_or_404()
    preview = crud.delete_feature(1)
    assert preview["needs_cascade_decision"]
    assert preview["dependents"][0]["feature_ids"] == [original.feature_log[2].id]
    crud.delete_feature(1, cascade=True)
    result = state.get_or_404()
    assert len(result.nanoparticles) == 1
    assert not result.helices and not result.strands and not result.nanoparticle_conjugations
    assert proof(result)["status"] == "verified"
    state.undo()
    assert state.get_or_404().helices == original.helices


@pytest.mark.parametrize("broken", ["missing_endpoint", "incoming_consumer"])
def test_live_patch_rejects_supported_reference_failure_atomically(document, broken):
    identity, response = graft()
    design = state.get_or_404()
    if broken == "missing_endpoint":
        changed = design.copy_with(overhangs=[])
    else:
        changed = design.copy_with(extensions=[StrandExtension(
            strand_id=response["strand_ids"][0], end="five_prime", sequence="TT")])
    state.set_design(changed)
    before, revision = state.get_design_with_revision()
    with pytest.raises(HTTPException) as error:
        patch_nanoparticle(identity, NanoparticlePatch(gizmo_move=move()))
    assert error.value.status_code == (404 if broken == "missing_endpoint" else 422)
    assert error.value.detail["code"] == ("missing_reference" if broken == "missing_endpoint" else "invalid_selection")
    assert state.get_design_with_revision() == (before, revision)


def test_unsupported_opaque_ownership_retains_legacy_route_without_native_receipt(document, monkeypatch):
    identity, _ = graft()
    before = state.get_or_404().model_copy(deep=True)
    before.overhangs[0].strand_anim_setup = {"binder_strand_id": "legacy-animation"}
    state.set_design(before)
    monkeypatch.setattr(commands, "record", lambda *_a, **_kw: pytest.fail("Opaque source entered native recording"))
    patch_nanoparticle(identity, NanoparticlePatch(gizmo_move=move()))
    changed = state.get_or_404()
    assert changed.helices != before.helices
    assert changed.overhangs == before.overhangs
    assert "thiol_version" not in changed.feature_log[-1].params
    assert not dependencies("nanoparticle-patch", changed.feature_log[-1].params).known


def test_missing_thiol_discriminator_does_not_recertify_legacy_particle_move(document):
    identity, _ = graft()
    patch_nanoparticle(identity, NanoparticlePatch(gizmo_move=move()))
    design = state.get_or_404().model_copy(deep=True)
    design.feature_log[-1].params.pop("thiol_version")
    assert proof(design)["status"] == "unverified"
