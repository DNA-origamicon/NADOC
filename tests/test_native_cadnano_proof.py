"""Registered caDNAno imports regenerate from bytes, never saved model output."""

import json

from fastapi import HTTPException
import pytest

from backend.api import crud, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design, SnapshotLogEntry
from backend.core.part_history_contract import assess_part_history
from backend.core.part_input_sources import EmbeddedInput, describe, embed
from backend.core.part_verification_capture import capture
from tests.test_part_cadnano_commands import inputs, module_source, source


def imported_part(data=None):
    initial, params, _resolver = inputs(source() if data is None else data)
    design = execute("cadnano-import", initial, params)
    return design.copy_with(feature_log=[SnapshotLogEntry(op_kind="cadnano-import", label="Pinned caDNAno",
        params=params, design_snapshot_gz_b64="poisoned recovery", post_state_gz_b64="poisoned output")])


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


def test_fresh_worker_rebuilds_complete_import_from_pinned_source_after_reload():
    design = imported_part(module_source())
    reloaded = Design.from_json(design.to_json())
    result = proof(reloaded)
    assert result["status"] == "reproduced_import", result
    assert result["native_editable"] is False
    assert result["imported_sources"] == [{"kind": "input_source", "identity": next(iter(design.input_sources))}]
    worker = VerificationWorker(capture(reloaded))
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
    token = set_current_doc("native-cadnano-edit")
    try:
        design = imported_part()
        state.load_design(design)
        yield design
    finally:
        state.close_session()
        reset_current_doc(token)


def test_name_edit_replays_import_keeps_all_output_identity_and_is_undoable(authored):
    from backend.core.part_history_proof import AUTHORING_FIELDS

    crud.edit_feature(0, crud.EditFeatureBody(params={"name_override": "Renamed import", "history_seed": "ignored"}))
    updated = state.get_or_404()
    assert updated.metadata.name == "Renamed import"
    assert updated.model_dump(include=AUTHORING_FIELDS - {"metadata"}) == authored.model_dump(include=AUTHORING_FIELDS - {"metadata"})
    assert proof(updated)["status"] == "reproduced_import"
    state.undo()
    assert state.get_or_404().metadata == authored.metadata
    assert state.get_or_404().helices == authored.helices


@pytest.mark.parametrize("field", ["lattice_import_version", "importer_version", "identity_policy"])
def test_unsupported_contract_edit_is_atomic(authored, field):
    before, revision = state.get_or_404().model_dump_json(), state.revision()
    with pytest.raises(HTTPException):
        crud.edit_feature(0, crud.EditFeatureBody(params={field: "nearest-geometry" if field == "identity_policy" else 2}))
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision


@pytest.mark.parametrize("corrupt", [False, True])
def test_unavailable_or_corrupt_bytes_remain_unverified_even_with_full_live_geometry(corrupt):
    design = imported_part()
    digest = next(iter(design.input_sources))
    design.input_sources = {digest: EmbeddedInput(data_b64="AAAA")} if corrupt else {}
    result = proof(design)
    assert result["status"] == "unverified", result
    assert any(issue["code"] in {"source_unavailable", "source_integrity_mismatch"} for issue in result["issues"])


def test_mutating_live_geometry_is_not_certified_by_original_source_hash():
    design = imported_part()
    design.helices[0].axis_start.x += 0.01
    result = proof(design)
    assert result["status"] == "mismatch", result


def test_changed_source_bytes_issue_new_identity_without_guessing_correspondence(authored):
    raw = json.dumps(source(), indent=1).encode()
    descriptor = describe(raw, format="cadnano-v2", media_type="application/json")
    current = state.get_or_404()
    current.input_sources = {**current.input_sources, descriptor.sha256: embed(descriptor, raw)}
    crud.edit_feature(0, crud.EditFeatureBody(params={"source": descriptor.model_dump(mode="json")}))
    updated = state.get_or_404()
    assert {helix.id for helix in authored.helices}.isdisjoint(helix.id for helix in updated.helices)
    assert {strand.id for strand in authored.strands}.isdisjoint(strand.id for strand in updated.strands)
    assert proof(updated)["status"] == "reproduced_import"


def test_changed_source_cannot_silently_retarget_existing_cluster_consumer(authored):
    from backend.api.routes_clusters import PatchClusterBody, update_cluster

    cluster_id = authored.cluster_transforms[0].id
    update_cluster(cluster_id, PatchClusterBody(translation=[1, 2, 3], commit=True))
    raw = json.dumps(source(), indent=1).encode()
    descriptor = describe(raw, format="cadnano-v2", media_type="application/json")
    current = state.get_or_404()
    current.input_sources = {**current.input_sources, descriptor.sha256: embed(descriptor, raw)}
    before, revision = current.model_dump_json(), state.revision()
    with pytest.raises(HTTPException) as caught:
        crud.edit_feature(0, crud.EditFeatureBody(params={"source": descriptor.model_dump(mode="json")}))
    assert "missing" in str(caught.value.detail).lower() or "reference" in str(caught.value.detail).lower()
    assert state.get_or_404().model_dump_json() == before
    assert state.revision() == revision
