"""Input discovery is a bounded definition read, not a replay or publication."""

from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from backend.api import doc_context, part_repair_input_metadata as metadata, state
from backend.api.routes_feature_log import router
from backend.core.models import MinorMutationLogEntry, RoutingClusterLogEntry, SnapshotLogEntry
from backend.core.part_history_contract import create_empty_part
from backend.core.part_input_sources import describe


def gold(kind="nanoparticle-patch", **changes):
    return {"_proof_version": 1, "nanoparticle_version": 1, "nanoparticle_id": "missing",
            **({"diameter_nm": 12.0} if kind != "nanoparticle-delete" else {}), **changes}


def protein():
    return {"_proof_version": 1, "protein_version": 1, "importer_version": 1,
        "asset_id": "asset", "name": "Protein", "source_filename": "source.pdb", "exclude_dna": True,
        "source": describe(b"original", format="pdb", media_type="chemical/x-pdb").model_dump(mode="json")}


@pytest.fixture
def document():
    doc = f"__repair_inputs__{uuid4()}"
    token = doc_context.set_current_doc(doc)
    revision, entry = doc_context.current_request_revision(), doc_context.current_request_feature_log_entry_id()
    design = create_empty_part("Input inspection", "HONEYCOMB")
    design.feature_log = [SnapshotLogEntry(id="target", label="Broken target", op_kind="nanoparticle-patch", params=gold())]
    state.load_design(design)
    try:
        yield doc
    finally:
        state.drop_doc(doc)
        doc_context.reset_current_doc(token)
        doc_context.set_request_revision(revision)
        doc_context.set_request_feature_log_entry_id(entry)


def selection(**changes):
    design, revision = state.get_design_with_revision()
    return {"expected_design_id": design.id, "expected_revision": revision, "feature_id": "target", **changes}


def test_missing_target_has_exact_typed_reference_and_scalar_editors(document, monkeypatch):
    import backend.api.part_proof_commands as commands
    import backend.core.part_history_proof as proof
    import backend.core.part_input_sources as sources

    fail = lambda *a, **k: pytest.fail("Definition inspection executed proof, geometry or source acquisition")
    monkeypatch.setattr(commands, "execute", fail)
    monkeypatch.setattr(proof, "digest", fail)
    monkeypatch.setattr(sources, "decode", fail)
    before, revision = state.get_design_with_revision()
    before.feature_log[0].post_state_gz_b64 = object()
    before.helices = object()
    before.input_sources = object()
    result = metadata.inspect_inputs(selection())
    assert result["definition_supported"] and result["assessment"] == "inputs_only"
    assert result["references_checked"] is False
    assert result["revision"] == revision and result["feature_id"] == "target"
    fields = {field["parameter_path"][0]: field for field in result["fields"]}
    assert fields["nanoparticle_id"]["expected_old"] == "missing"
    assert fields["nanoparticle_id"]["reference_selection"]["resource_kind"] == "nanoparticle"
    assert fields["diameter_nm"]["expected_old"] == 12.0
    assert set(fields) == {"nanoparticle_id", "diameter_nm"}
    assert state.get_or_404() is before and state.revision() == revision and state.undo_depth() == 0


def test_response_owns_nested_values_and_never_invents_absent_defaults(document):
    source = state.get_or_404()
    source.feature_log[0].params["pose"] = [1.0] * 16
    result = metadata.inspect_inputs(selection())
    pose = next(field for field in result["fields"] if field["parameter_path"] == ["pose"])
    pose["expected_old"][0] = 999
    assert source.feature_log[0].params["pose"][0] == 1.0
    assert not any(field["parameter_path"] == ["gizmo_move"] for field in result["fields"])


@pytest.mark.parametrize("changes", [{"_proof_version": True}, {"_proof_version": 2},
    {"nanoparticle_version": "1"}, {"unknown": "value"},
    {"_generated_scope": {}}, {"coating_version": 1}, {"thiol_version": 1}])
def test_legacy_unknown_owned_and_invalid_contracts_do_not_gain_editors(changes):
    result = metadata.describe_inputs("nanoparticle-patch", gold(**changes))
    assert result["definition_supported"] is False and result["fields"] == [] and result["reason"]


def test_output_identity_and_generator_metadata_are_not_editors():
    result = metadata.describe_inputs("nanoparticle-create", gold("nanoparticle-create",
        _generator={"editable": ["nanoparticle_id", "_proof_version"]}))
    assert result["definition_supported"]
    assert [field["parameter_path"] for field in result["fields"]] == [["diameter_nm"]]


def test_source_editor_reports_exact_original_descriptor_and_shared_family_limit():
    params = protein()
    result = metadata.describe_inputs("protein-import", params)
    source = next(field for field in result["fields"] if field["input_type"] == "source")
    assert source["expected_old"] == params["source"]
    assert source["source_binding"] == {"parameter": "source", "source": params["source"],
        "max_size_bytes": 250_000, "replacement_supported": True,
        "operation": "restore_published", "inspection_required": True}
    assert "asset_id" not in {field["parameter_path"][0] for field in result["fields"]}


def test_unadmitted_source_does_not_get_an_upload_action():
    params = protein()
    params["source"]["size_bytes"] = 250_001
    result = metadata.describe_inputs("protein-import", params)
    assert not result["definition_supported"] and result["fields"] == []


def test_copy_references_preserve_integer_array_positions_and_protect_outputs():
    result = metadata.describe_inputs("element-paste", {"_proof_version": 1, "copy_version": 1,
        "protein_ids": ["p"], "protein_output_ids": ["new-p"],
        "nanoparticle_ids": ["n"], "nanoparticle_output_ids": ["new-n"], "paste_index": 1})
    assert result["definition_supported"]
    assert [field["parameter_path"] for field in result["fields"]] == [
        ["protein_ids", 0], ["nanoparticle_ids", 0], ["paste_index"]]


@pytest.mark.parametrize("change,code,status", [
    ({"expected_revision": 999}, "repair_input_conflict", 409),
    ({"expected_design_id": "different"}, "repair_input_conflict", 409),
    ({"feature_id": "gone"}, "missing_feature", 404),
    ({"child_id": "not-child"}, "invalid_repair_target", 422)])
def test_stale_and_invalid_target_is_explicit(document, change, code, status):
    with pytest.raises(HTTPException) as error:
        metadata.inspect_inputs(selection(**change))
    assert error.value.status_code == status and error.value.detail["code"] == code


def test_closed_document_read_cannot_recreate_session(document):
    request = selection()
    state.drop_doc(document)
    with pytest.raises(HTTPException) as error:
        metadata.inspect_inputs(request)
    assert error.value.status_code == 404 and document not in state._sessions


def test_duplicate_child_identity_cannot_select_an_arbitrary_row(document):
    source = state.get_or_404()
    source.feature_log.append(RoutingClusterLogEntry(id="group", label="Group", children=[
        MinorMutationLogEntry(id="target", label="Duplicate", op_subtype="helix-add", params={})]))
    with pytest.raises(HTTPException) as error:
        metadata.inspect_inputs(selection())
    assert error.value.detail["code"] == "ambiguous_feature_identity"


def test_child_cannot_promote_snapshot_source_contract_by_carrying_its_parameters(document):
    source = state.get_or_404()
    child = MinorMutationLogEntry.model_construct(id="child", label="Invalid source child",
        op_subtype="protein-import", params=protein())
    source.feature_log = [RoutingClusterLogEntry(id="group", label="Group", children=[child])]
    with pytest.raises(HTTPException) as error:
        metadata.inspect_inputs(selection(feature_id="group", child_id="child"))
    assert error.value.detail["code"] == "unsupported_repair_target"


@pytest.mark.parametrize("scope", ["rows", "child_rows", "bytes", "nodes", "history_cursor"])
def test_explicit_inspection_has_bounded_capture(document, scope):
    source = state.get_or_404()
    if scope == "rows":
        source.feature_log *= 2001
    elif scope == "child_rows":
        source.feature_log.append(RoutingClusterLogEntry(id="group", label="Group", children=[]))
        source.feature_log[-1].children = [source.feature_log[0]] * 2000
    elif scope == "bytes":
        source.feature_log[0].params["_generator"] = "x" * 256_000
    elif scope == "nodes":
        source.feature_log[0].params["_generator"] = [0] * 10_001
    else:
        source.feature_log_cursor = 0
    with pytest.raises(HTTPException) as error:
        metadata.inspect_inputs(selection())
    assert error.value.status_code == (409 if scope == "history_cursor" else 413)


def test_http_target_schema_forbids_caller_supplied_definitions(document):
    app = FastAPI()
    app.add_middleware(doc_context.DocContextMiddleware)
    app.include_router(router, prefix="/api")
    with TestClient(app) as client:
        path, headers = "/api/design/features/repair-inputs", {"X-NADOC-Doc": document}
        result = client.post(path, headers=headers, json=selection())
        assert result.status_code == 200 and result.json()["definition_supported"]
        assert client.post(path, headers=headers, json=selection(params=gold())).status_code == 422
