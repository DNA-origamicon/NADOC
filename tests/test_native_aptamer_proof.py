"""Registered aptamer history proves pinned inputs across reload and edits."""

import pytest
from fastapi import HTTPException

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_input_sources import EmbeddedInput, describe, embed
from backend.core.part_verification_capture import capture
from tests.test_part_aptamer_commands import inputs, tiny_pdb


def imported_part():
    params, source, resolver = inputs(initialize_metadata=True)
    design = create_empty_part(params["name"], "HONEYCOMB").copy_with(
        input_sources={source.sha256: embed(source, resolver(source))})
    design = execute("aptamer-import", design, params)
    return design.copy_with(feature_log=[SnapshotLogEntry(op_kind="aptamer-import", label="Pinned aptamer",
        params=params, design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned output")]), source


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


def test_fresh_worker_reproduces_import_without_saved_outputs_or_template_lookup(monkeypatch):
    from backend.core import aptamer

    design, source = imported_part()
    monkeypatch.setattr(aptamer, "template_content", lambda *_: pytest.fail("Replay used mutable catalog"))
    result = proof(design)
    assert result["status"] == "reproduced_import", result
    assert result["native_editable"] is False
    assert result["imported_sources"] == [{"kind": "input_source", "identity": source.sha256}]
    worker = VerificationWorker(capture(Design.from_json(design.to_json())))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "reproduced_import", result
        assert result["checked_commands"] == 1
    finally:
        worker.close()


@pytest.fixture
def authored():
    token = set_current_doc("native-aptamer-edit")
    try:
        design, source = imported_part()
        state.load_design(design)
        yield design, source
    finally:
        state.close_session()
        reset_current_doc(token)


def test_parameter_edit_reparses_pinned_source_and_preserves_identity_and_undo(authored):
    original, _ = authored
    crud.edit_feature(0, crud.EditFeatureBody(params={"name": "Edited aptamer", "source_label": "Edited annotation",
        "_helix_id": "do-not-change", "_strand_id": "do-not-change", "history_seed": "do-not-change"}))
    updated = state.get_or_404()
    assert updated.helices[0].id == original.helices[0].id
    assert updated.strands[0].id == original.strands[0].id
    assert updated.cluster_transforms[0].id == original.cluster_transforms[0].id
    assert updated.helices[0].native_residues == original.helices[0].native_residues
    assert updated.helices[0].native_source == "Edited annotation"
    assert updated.metadata.name == "Edited aptamer"
    assert proof(updated)["status"] == "reproduced_import"
    state.undo()
    assert state.get_or_404().helices == original.helices
    assert state.get_or_404().metadata == original.metadata


def test_source_replacement_uses_new_bytes_with_stable_output_ids(authored):
    original, _ = authored
    # An explicit replacement file changes deposited coordinates. The unchanged
    # importer derives the output; no generated coordinates enter the recipe.
    lines = tiny_pdb().splitlines()
    lines = [line[:30] + f"{float(line[30:38]) + 1.0:8.3f}" + line[38:]
             if line.startswith("ATOM") else line for line in lines]
    raw = ("\n".join(lines) + "\n").encode()
    source = describe(raw, format="pdb", media_type="chemical/x-pdb")
    current = state.get_or_404()
    current.input_sources = {**current.input_sources, source.sha256: embed(source, raw)}
    crud.edit_feature(0, crud.EditFeatureBody(params={"source": source.model_dump(mode="json")}))
    updated = state.get_or_404()
    assert updated.helices[0].id == original.helices[0].id
    assert updated.helices[0].native_residues != original.helices[0].native_residues
    assert proof(updated)["status"] == "reproduced_import"


@pytest.mark.parametrize("field", ["aptamer_version", "importer_version"])
def test_unsupported_version_edit_is_atomic(authored, field):
    before, revision = state.get_or_404().model_dump_json(), state.revision()
    with pytest.raises(HTTPException):
        crud.edit_feature(0, crud.EditFeatureBody(params={field: 2}))
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision


@pytest.mark.parametrize("corrupt", [False, True])
def test_missing_or_corrupt_source_is_unverified_not_geometry_recovery(corrupt):
    design, source = imported_part()
    design.input_sources = {source.sha256: EmbeddedInput(data_b64="AAAA")} if corrupt else {}
    result = proof(design)
    assert result["status"] == "unverified", result
    assert any(issue["code"] in {"source_unavailable", "source_integrity_mismatch"}
               for issue in result["issues"])


def test_native_residue_mutation_cannot_be_certified_by_matching_source_hash():
    design, _ = imported_part()
    site = design.helices[0].native_residues[0]
    site.atoms["C1'"].x += 0.01
    result = proof(design)
    assert result["status"] == "mismatch", result


def test_deleting_import_exposes_cluster_consumer_and_cascade_preserves_other_import(authored):
    from backend.api.routes_clusters import PatchClusterBody, update_cluster

    first, _ = authored
    params, _, _ = inputs(_helix_id="apt_other", _strand_id="other-strand")
    state.mutate_with_feature_log("aptamer-import", "Independent aptamer", params,
        lambda design: execute("aptamer-import", design, params))
    cid = first.cluster_transforms[0].id
    update_cluster(cid, PatchClusterBody(translation=[1, 2, 3], commit=True))
    before = state.get_or_404().model_dump_json()
    result = crud.delete_feature(0)
    assert result["needs_cascade_decision"]
    assert state.get_or_404().model_dump_json() == before
    crud.delete_feature(0, cascade=True)
    remaining = state.get_or_404()
    assert [helix.id for helix in remaining.helices] == ["apt_other"]
    assert proof(remaining)["status"] == "reproduced_import"
