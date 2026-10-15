"""Pinned protein import and native binder placement survive independent replay."""

import pytest

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history
from backend.core.part_history_proof import import_root
from backend.core.part_input_sources import describe, embed
from backend.core.part_verification_capture import capture
from tests.test_protein import _SYNTH_PDB, _design_with_overhang


def recipe():
    design = _design_with_overhang()
    design.overhangs[0].sequence = "ACGTACGT"
    # Initial DNA is an explicitly imported basis. Protein atoms and binder
    # topology must still be derived from their two following commands.
    design.recipe_root = import_root(design)
    data = _SYNTH_PDB.encode()
    source = describe(data, format="pdb", media_type="chemical/x-pdb")
    design.input_sources = {source.sha256: embed(source, data)}
    commands = [
        ("protein-import", {"_proof_version": 1, "protein_version": 1, "importer_version": 1,
            "source": source.model_dump(), "asset_id": "asset", "name": "synth",
            "source_filename": "protein.pdb", "exclude_dna": False}),
        ("protein-conjugate", {"_proof_version": 1, "protein_version": 1, "conjugation_version": 1,
            "asset_id": "asset", "overhang_id": "oh_5p", "conjugation_atom_serial": 9,
            "azide_end": "5p", "attachment_id": "attached", "binder_strand_id": "binder",
            "group_id": "group"}),
    ]
    for kind, params in commands:
        design = execute(kind, design, params)
        design.feature_log.append(SnapshotLogEntry(op_kind=kind, label=kind, params=params,
            design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned output"))
    return design


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


def test_pinned_import_then_native_conjugation_cold_replays_without_saved_outputs():
    design = recipe()
    worker = VerificationWorker(capture(Design.from_json(design.to_json())))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "reproduced_import", result
        assert result["checked_commands"] == 2
        assert not result["native_editable"]
        assert len(result["imported_sources"]) == 1
    finally:
        worker.close()


def test_native_conjugation_edit_preserves_outputs_and_import_deletion_cascades_exactly():
    design = recipe()
    token = set_current_doc("native-protein-conjugation-edit")
    try:
        state.load_design(design)
        crud.edit_feature(1, crud.EditFeatureBody(params={"azide_end": "3p", "attachment_id": "wrong",
            "binder_strand_id": "wrong", "group_id": "wrong", "conjugation_version": 99}))
        edited = state.get_or_404()
        assert edited.protein_attachments[0].id == "attached"
        assert edited.protein_attachments[0].binder_strand_id == "binder"
        assert edited.protein_attachments[0].azide_end == "3p"
        assert edited.staple_groups[-1].id == "group"
        assert proof(edited)["status"] == "reproduced_import"
        state.undo()
        assert state.get_or_404().protein_attachments == design.protein_attachments
        preview = crud.delete_feature(0)
        assert preview["needs_cascade_decision"]
        assert preview["dependents"][0]["feature_ids"] == [design.feature_log[1].id]
        crud.delete_feature(0, cascade=True)
        result = state.get_or_404()
        assert not result.protein_assets and not result.protein_attachments
        assert not result.staple_groups
        assert result.find_strand("binder") is None
        assert result.find_strand("oh_strand") is not None
        assert proof(result)["status"] == "reproduced_import"
        state.undo()
        assert proof(state.get_or_404())["status"] == "reproduced_import"
    finally:
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize("field", ["strands", "protein_attachments"])
def test_saved_binder_or_attachment_tampering_is_not_validated_by_source_hash(field):
    design = recipe()
    if field == "strands":
        design.find_strand("binder").sequence = "AAAAAAAA"
    else:
        design.protein_attachments[0].pose.values[3] += 5
    result = proof(design)
    assert result["status"] == "mismatch", result
    assert field in result["issues"][0]["fields"]


@pytest.mark.parametrize("deleted", [False, True])
def test_owned_conjugate_lifecycle_cold_replay_and_upstream_edit(deleted):
    from backend.api import routes_protein as routes

    token = set_current_doc("owned-conjugate-history")
    try:
        state.load_design(recipe())
        response = routes.patch_protein_attachment("attached", routes.ProteinAttachPatchRequest(
            gizmo_move={"pivot": [0, 0, 0], "translation": [.2, .3, .1], "rotation": [0, 0, 0, 1]},
            visible=False))
        assert response["protein_constraint"]["mode"] == "two_ball_joint"
        moved = state.get_or_404()
        assert moved.feature_log[-1].params["conjugation_version"] == 1
        crud.edit_feature(0, crud.EditFeatureBody(params={"name": "Edited input name"}))
        edited = state.get_or_404()
        assert edited.protein_assets[0].name == "Edited input name"
        assert edited.protein_attachments[0] == moved.protein_attachments[0]
        assert edited.overhangs == moved.overhangs
        if deleted:
            routes.delete_protein_attachment("attached")
            assert state.get_or_404().protein_attachments == []
            assert state.get_or_404().find_strand("binder") is None
            state.undo()
            assert state.get_or_404().protein_attachments == edited.protein_attachments
            state.redo()
        isolated = Design.from_json(state.get_or_404().to_json())
        for entry in isolated.feature_log:
            entry.design_snapshot_gz_b64 = entry.post_state_gz_b64 = "poisoned recovery"
        worker = VerificationWorker(capture(isolated))
        try:
            worker.start()
            assert worker.wait(5)
            result = worker.result()
            assert result["status"] == "reproduced_import", result
            assert result["checked_commands"] == 3 + deleted
        finally:
            worker.close()
    finally:
        state.close_session()
        reset_current_doc(token)
