"""Pinned imported bytes survive cold proof, edits and portable transfer."""

import json
from types import SimpleNamespace
import zipfile

import pytest

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_input_sources import EmbeddedInput, SourceContractError, describe, embed
from backend.core.part_verification_capture import capture
from backend.core.project_revisions import ProjectRevisionStore
from tests.test_protein import _SYNTH_PROT_DNA


def imported_part():
    raw = _SYNTH_PROT_DNA.encode()
    descriptor = describe(raw, format="pdb", media_type="chemical/x-pdb")
    design = create_empty_part("Pinned protein", "HONEYCOMB").copy_with(
        input_sources={descriptor.sha256: embed(descriptor, raw)})
    params = {"_proof_version": 1, "protein_version": 1, "importer_version": 1,
              "source": descriptor.model_dump(), "asset_id": "protein-one",
              "name": "Original name", "source_filename": "source.pdb", "exclude_dna": False}
    design = execute("protein-import", design, params)
    entry = SnapshotLogEntry(op_kind="protein-import", label="Import pinned source", params=params,
        design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned output")
    return design.copy_with(feature_log=[entry]), descriptor


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


def test_import_from_empty_root_is_reproduced_import_not_native_construction():
    design, descriptor = imported_part()
    result = proof(design)
    assert result["status"] == "reproduced_import", result
    assert not result["native_editable"]
    assert result["imported_sources"] == [{"kind": "input_source", "identity": descriptor.sha256}]
    assert design.recipe_root.kind == "empty"
    worker = VerificationWorker(capture(Design.from_json(design.to_json())))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "reproduced_import", result
        assert result["checked_commands"] == 1
    finally:
        worker.close()


def test_history_edit_reparses_inputs_and_preserves_source_identity_and_undo():
    design, _ = imported_part()
    token = set_current_doc("pinned-protein-edit")
    try:
        state.load_design(design)
        crud.edit_feature(0, crud.EditFeatureBody(params={"name": "Edited name", "exclude_dna": True,
                                                       "asset_id": "attempted-identity-change"}))
        changed = state.get_or_404()
        assert changed.protein_assets[0].id == "protein-one"
        assert changed.protein_assets[0].name == "Edited name"
        assert len(changed.protein_assets[0].atoms) == 9 < len(design.protein_assets[0].atoms)
        assert changed.input_sources == design.input_sources
        assert proof(changed)["status"] == "reproduced_import"
        state.undo()
        assert state.get_or_404().protein_assets == design.protein_assets
        assert state.get_or_404().input_sources == design.input_sources
    finally:
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize("field,value", [("bonds", []), ("default_conjugation_atom_serial", None)])
def test_parsed_asset_mutation_cannot_be_certified_by_source_digest(field, value):
    design, _ = imported_part()
    assert getattr(design.protein_assets[0], field) != value
    design.protein_assets[0] = design.protein_assets[0].model_copy(update={field: value})
    result = proof(design)
    assert result["status"] == "mismatch"
    assert result["issues"][0]["fields"] == ["protein_assets"]


@pytest.mark.parametrize("corrupt", [False, True])
def test_unavailable_sources_remain_unverified_and_cannot_cascade_delete(corrupt):
    design, descriptor = imported_part()
    design.input_sources = ({descriptor.sha256: EmbeddedInput(data_b64="AAAA")} if corrupt else {})
    result = proof(design)
    assert result["status"] == "unverified", result
    assert result["issues"][0]["code"] == ("source_integrity_mismatch" if corrupt else "source_unavailable")
    assert result["issues"][0]["feature_id"] == design.feature_log[0].id
    assert result["issues"][0]["references"][0]["identity"] == descriptor.sha256
    token = set_current_doc("unavailable-protein-input")
    try:
        from fastapi import HTTPException
        state.load_design(design)
        original, revision = state.get_design_with_revision()
        with pytest.raises(HTTPException) as error:
            crud.delete_feature(0, cascade=True)
        assert error.value.status_code == 409
        assert state.get_design_with_revision() == (original, revision)
    finally:
        state.close_session()
        reset_current_doc(token)


def test_revision_peer_transfer_contains_and_verifies_source_closure(tmp_path):
    design, descriptor = imported_part()
    sender = ProjectRevisionStore(tmp_path / "sender")
    receiver = ProjectRevisionStore(tmp_path / "receiver")
    revision = sender.commit(design, loadout_id="main", loadout_name="Main",
                             parent_revision_id=None, expected_head=None)
    compressed = sender.snapshot_path(design.id, revision.snapshot_sha256).read_bytes()
    receiver.ingest_snapshot(design.id, revision.snapshot_sha256, compressed)
    receiver.ingest_revision(sender.export_revision(design.id, revision.revision_id))
    receiver.advance_branch(design.id, "main", revision.revision_id, expected_head=None, name="Main")
    restored = receiver.load_design(design.id, revision.revision_id)
    assert proof(restored)["status"] == "reproduced_import"
    assert receiver.read_input(design.id, descriptor) == _SYNTH_PROT_DNA.encode()


def test_missing_source_cannot_advance_a_project_branch(tmp_path):
    design, _ = imported_part()
    design.input_sources = {}
    store = ProjectRevisionStore(tmp_path)
    with pytest.raises(SourceContractError):
        store.commit(design, loadout_id="main", loadout_name="Main",
                     parent_revision_id=None, expected_head=None)
    assert store.branch_head(design.id, "main") is None
    assert not store.root.exists()


@pytest.mark.parametrize("mode", ["thin", "selected", "full"])
def test_all_package_modes_include_pinned_inputs(tmp_path, monkeypatch, mode):
    from backend.core import native_part_package as package

    design, descriptor = imported_part()
    workspace = tmp_path / "source"
    workspace.mkdir()
    (workspace / "part.nadoc").write_text(design.to_json())
    jobdir = workspace / "oxdna_jobs/job-one"
    jobdir.mkdir(parents=True)
    (jobdir / "job.json").write_text("{}")
    job = SimpleNamespace(job_id="job-one", status="completed")
    monkeypatch.setattr(package, "associated_job_dirs", lambda *_: [("oxdna_jobs", job, jobdir)])
    archive = tmp_path / "part.nadocpkg"
    manifest = package.create_package(workspace, "part.nadoc", archive, mode=mode,
                                      selected_job_ids={"job-one"})
    assert manifest["authoring_inputs"] == [descriptor.model_dump()]
    destination = tmp_path / "destination"
    package.import_package(destination, archive, "part.nadoc")
    restored = Design.from_json((destination / "part.nadoc").read_text())
    assert restored.input_sources == design.input_sources
    assert proof(restored)["status"] == "reproduced_import"
    assert ProjectRevisionStore(destination).read_input(design.id, descriptor) == _SYNTH_PROT_DNA.encode()


def test_package_rejects_missing_source_before_installation(tmp_path):
    from backend.core import native_part_package as package

    design, _ = imported_part()
    design.input_sources = {}
    archive = tmp_path / "broken.nadocpkg"
    with zipfile.ZipFile(archive, "w") as output:
        output.writestr("manifest.json", json.dumps({"format": package.FORMAT, "version": 1,
            "part": {"archive_path": "part/part.nadoc"}, "simulations": []}))
        output.writestr("part/part.nadoc", design.to_json())
    destination = tmp_path / "destination"
    with pytest.raises(ValueError, match="invalid NADOC part"):
        package.import_package(destination, archive, "part.nadoc")
    assert not destination.exists()


def test_native_placement_and_pose_edit_replay_from_pinned_source():
    design, _ = imported_part()
    attach = {"_proof_version": 1, "protein_version": 1, "attachment_id": "placed",
              "asset_id": "protein-one", "target": {"kind": "free"},
              "conjugation_atom_serial": 9, "handle_complement_bp": 0,
              "handle_spacer_nt": 0}
    pose = [1., 0., 0., 7., 0., 1., 0., 2., 0., 0., 1., 3., 0., 0., 0., 1.]
    patch = {"_proof_version": 1, "protein_version": 1, "attachment_id": "placed", "pose": pose}
    for kind, params in [("protein-attach", attach), ("protein-attach-patch", patch)]:
        design = execute(kind, design, params)
        design.feature_log.append(SnapshotLogEntry(op_kind=kind, label=kind, params=params,
            design_snapshot_gz_b64="unusable recovery", post_state_gz_b64="unusable output"))
    worker = VerificationWorker(capture(Design.from_json(design.to_json())))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "reproduced_import", result
        assert result["checked_commands"] == 3
        assert design.protein_attachments[0].pose.values == pose
    finally:
        worker.close()


def test_valid_inline_input_restores_corrupt_derived_project_cache(tmp_path):
    design, descriptor = imported_part()
    store = ProjectRevisionStore(tmp_path)
    cache = store.stage_input(design.id, descriptor, _SYNTH_PROT_DNA.encode())
    cache.write_bytes(b"damaged cache")
    with pytest.raises(SourceContractError):
        store.read_input(design.id, descriptor)
    revision = store.commit(design, loadout_id="main", loadout_name="Main",
                            parent_revision_id=None, expected_head=None)
    assert store.read_input(design.id, descriptor) == _SYNTH_PROT_DNA.encode()
    assert proof(store.load_design(design.id, revision.revision_id))["status"] == "reproduced_import"


def test_recipe_deletion_removes_presentation_links_and_undo_restores_them():
    from backend.core.models import RepresentationOverride, RepresentationSegment

    design, _ = imported_part()
    params = {"_proof_version": 1, "protein_version": 1, "attachment_id": "placed",
              "asset_id": "protein-one", "target": {"kind": "free"},
              "conjugation_atom_serial": 9, "handle_complement_bp": 0, "handle_spacer_nt": 0}
    design = execute("protein-attach", design, params)
    design.feature_log.append(SnapshotLogEntry(op_kind="protein-attach", label="Place", params=params))
    overrides = [RepresentationOverride(id="removed", protein_attachment_ids=["placed"]),
                 RepresentationOverride(id="old-missing", protein_attachment_ids=["prior-missing"]),
                 RepresentationOverride(id="mixed", protein_attachment_ids=["placed"],
                     segments=[RepresentationSegment(helix_id="prior-missing", bp_start=0, bp_end=1)])]
    design.representation_overrides = overrides
    original_json = design.model_dump_json()
    token = set_current_doc("protein-history-delete-display")
    try:
        state.load_design(design)
        crud.delete_feature(1, cascade=True)
        result = state.get_or_404()
        assert not result.protein_attachments
        assert [item.id for item in result.representation_overrides] == ["old-missing", "mixed"]
        assert result.representation_overrides[0] == overrides[1]
        assert result.representation_overrides[1].segments == overrides[2].segments
        assert not result.representation_overrides[1].protein_attachment_ids
        assert design.model_dump_json() == original_json
        assert proof(result)["status"] == "reproduced_import"
        state.undo()
        assert state.get_or_404().representation_overrides == overrides
    finally:
        state.close_session()
        reset_current_doc(token)


def test_unwritable_derived_cache_cannot_block_portable_revision(tmp_path):
    design, descriptor = imported_part()
    store = ProjectRevisionStore(tmp_path)
    # A directory at the blob path cannot be atomically replaced by a file.
    store.input_path(design.id, descriptor.sha256).mkdir(parents=True)
    revision = store.commit(design, loadout_id="main", loadout_name="Main",
                            parent_revision_id=None, expected_head=None)
    restored = store.load_design(design.id, revision.revision_id)
    assert restored.input_sources == design.input_sources
    assert proof(restored)["status"] == "reproduced_import"
    with pytest.raises(SourceContractError):
        store.read_input(design.id, descriptor)
