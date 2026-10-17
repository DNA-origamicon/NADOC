"""Registered same-part copy can cold-replay and repair sources without outputs."""

import json

import pytest

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_input_sources import describe, embed
from backend.core.part_verification_capture import capture
from backend.core.quantum_dots import catalog_entry
from tests.test_protein import _SYNTH_PDB


def copy_inputs(**changes):
    return {"_proof_version": 1, "copy_version": 1, "protein_ids": [], "protein_output_ids": [],
        "nanoparticle_ids": ["first"], "nanoparticle_output_ids": ["copy"], "paste_index": 1, **changes}


def append(design, kind, params):
    result = execute(kind, design, params)
    return result.copy_with(feature_log=[*design.feature_log, SnapshotLogEntry(op_kind=kind,
        label=kind, params=params, design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned output")])


def recipe(imported=False):
    design = create_empty_part("Native copies", "HONEYCOMB")
    for identity, diameter in (("first", 10.0), ("second", 15.0)):
        design = append(design, "nanoparticle-create", {"_proof_version": 1, "nanoparticle_version": 1,
            "nanoparticle_id": identity, "diameter_nm": diameter})
    params = copy_inputs()
    if imported:
        pdb = _SYNTH_PDB.encode()
        protein_source = describe(pdb, format="pdb", media_type="chemical/x-pdb")
        catalog = json.dumps(catalog_entry("nn-hecz-600"), sort_keys=True).encode()
        catalog_source = describe(catalog, format="quantum-dot-catalog", media_type="application/json")
        design.input_sources = {protein_source.sha256: embed(protein_source, pdb),
                                catalog_source.sha256: embed(catalog_source, catalog)}
        design = append(design, "protein-import", {"_proof_version": 1, "protein_version": 1,
            "importer_version": 1, "asset_id": "asset", "source": protein_source.model_dump(),
            "name": "Pinned protein", "source_filename": "test.pdb", "exclude_dna": False})
        design = append(design, "protein-attach", {"_proof_version": 1, "protein_version": 1,
            "asset_id": "asset", "attachment_id": "protein", "target": {"kind": "free"},
            "conjugation_atom_serial": 9, "handle_complement_bp": 0, "handle_spacer_nt": 0})
        design = append(design, "nanoparticle-create", {"_proof_version": 1, "quantum_dot_version": 1,
            "nanoparticle_id": "dot", "source": catalog_source.model_dump(),
            "catalog_id": "nn-hecz-600", "diameter_nm": 9.5})
        params = copy_inputs(protein_ids=["protein"], protein_output_ids=["protein-copy"],
            nanoparticle_ids=["first", "dot"], nanoparticle_output_ids=["copy", "dot-copy"])
    return append(design, "element-paste", params)


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


@pytest.mark.parametrize("imported", [False, True])
def test_copy_survives_cold_transport_poisoned_outputs_and_retains_source_provenance(imported, monkeypatch):
    design = recipe(imported)
    monkeypatch.setattr("backend.core.quantum_dots.catalog_entry",
                        lambda *_a: pytest.fail("Copy replay consulted catalog"))
    transported = Design.from_json(design.to_json())
    expected = "reproduced_import" if imported else "verified"
    assert proof(transported)["status"] == expected
    worker = VerificationWorker(capture(transported))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == expected, result
        assert result["checked_commands"] == (6 if imported else 3)
        assert result["native_editable"] is (not imported)
        if imported:
            assert len(result["imported_sources"]) == 2
    finally:
        worker.close()


def test_upstream_edits_and_source_repair_keep_explicit_copy_identity():
    token = set_current_doc("native-element-copy-edit")
    try:
        state.load_design(recipe())
        crud.edit_feature(0, crud.EditFeatureBody(params={"diameter_nm": 12.0}))
        copied = state.get_or_404().nanoparticles[-1]
        assert copied.id == "copy" and copied.diameter_nm == 12.0
        assert copied.pose.values[3] == 17.0
        assert proof(state.get_or_404())["status"] == "verified"
        crud.edit_feature(2, crud.EditFeatureBody(params={"nanoparticle_ids": ["second"],
            "nanoparticle_output_ids": ["attempted-change"], "copy_version": 99, "paste_index": 2}))
        current = state.get_or_404()
        copied = current.nanoparticles[-1]
        assert copied.id == "copy" and copied.diameter_nm == 15.0
        assert copied.pose.values[3] == 40.0
        assert current.feature_log[2].params["copy_version"] == 1
        assert proof(current)["status"] == "verified"
        state.undo()
        assert state.get_or_404().nanoparticles[-1].diameter_nm == 12.0
    finally:
        state.close_session()
        reset_current_doc(token)


def test_copied_protein_gold_and_dot_use_normal_move_delete_and_cold_replay_without_changing_sources():
    design = recipe(imported=True)
    source = design.model_dump(include=AUTHORING_FIELDS)
    source["protein_attachments"] = [item for item in source["protein_attachments"] if item["id"] != "protein-copy"]
    source["nanoparticles"] = [item for item in source["nanoparticles"] if item["id"] not in {"copy", "dot-copy"}]
    for family, identity, version, field, collection in (
        ("protein-attach", "protein-copy", "protein_version", "attachment_id", "protein_attachments"),
        ("nanoparticle", "copy", "nanoparticle_version", "nanoparticle_id", "nanoparticles"),
        ("nanoparticle", "dot-copy", "quantum_dot_version", "nanoparticle_id", "nanoparticles"),
    ):
        old = next(item for item in getattr(design, collection) if item.id == identity)
        params = {"_proof_version": 1, version: 1, field: identity}
        design = append(design, f"{family}-patch", {**params, "gizmo_move": {
            "pivot": [0.0, 0.0, 0.0], "translation": [1.25, -2.0, 3.0], "rotation": [0.0, 0.0, 0.0, 1.0]}})
        moved = next(item for item in getattr(design, collection) if item.id == identity)
        assert [moved.pose.values[index] - old.pose.values[index] for index in (3, 7, 11)] == pytest.approx([1.25, -2, 3])
        assert moved.model_dump(exclude={"pose"}) == old.model_dump(exclude={"pose"})
        design = append(design, f"{family}-delete", params)
        assert all(item.id != identity for item in getattr(design, collection))
    assert design.model_dump(include=AUTHORING_FIELDS) == source
    worker = VerificationWorker(capture(Design.from_json(design.to_json())))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "reproduced_import", result
        assert result["checked_commands"] == 12
    finally:
        worker.close()


def test_missing_upstream_source_has_typed_repair_target_and_cascade_preview():
    design = recipe()
    broken = design.copy_with(feature_log=design.feature_log[1:])
    result = proof(broken)
    assert result["status"] == "failed", result
    assert result["issues"][0]["references"] == [{"kind": "nanoparticle", "identity": "first",
                                                 "parameter_path": ["nanoparticle_ids", 0]}]
    token = set_current_doc("native-element-copy-delete")
    try:
        state.load_design(design)
        preview = crud.delete_feature(0)
        assert preview["needs_cascade_decision"]
        crud.delete_feature(0, cascade=True)
        updated = state.get_or_404()
        assert [item.id for item in updated.nanoparticles] == ["second"]
        assert proof(updated)["status"] == "verified"
        state.undo()
        assert state.get_or_404().nanoparticles[-1].id == "copy"
    finally:
        state.close_session()
        reset_current_doc(token)


def test_unlogged_copy_pose_cannot_be_verified_by_saved_source_or_output():
    design = recipe()
    design.nanoparticles[-1].pose.values[3] += 1
    result = proof(design)
    assert result["status"] == "mismatch"
    assert result["issues"][0]["fields"] == ["nanoparticles"]


def test_legacy_snapshot_paste_and_malformed_version_are_not_native_contracts():
    assert not dependencies("element-paste", {"protein_ids": [], "nanoparticle_ids": ["first"]}).known
    assert not dependencies("element-paste", copy_inputs(copy_version=2)).known
    assert not dependencies("element-paste", {**copy_inputs(), "source": {}}).known
