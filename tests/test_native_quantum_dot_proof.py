"""Pinned catalog input is sufficient for independent editable particle replay."""

import json

import pytest
from fastapi import HTTPException

from backend.api import crud, routes_nanoparticles as routes, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.api.part_proof_commands import dependencies, execute
from backend.api.part_quantum_dot_commands import MAX_CATALOG_BYTES, build, parse_command
from backend.api.part_verification_worker import VerificationWorker
from backend.core.models import Design
from backend.core.part_history_contract import assess_part_history, create_empty_part
from backend.core.part_input_sources import (
    EmbeddedInput, EmbeddedResolver, SourceContractError, describe, embed, portable_sources,
)
from backend.core.part_verification_capture import capture
from backend.core.quantum_dots import catalog_entry


@pytest.fixture
def document():
    token = set_current_doc("native-catalog-proof")
    try:
        state.load_design(create_empty_part("Pinned catalog", "HONEYCOMB"))
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def proof(design):
    return assess_part_history(design, execute=execute, dependencies=dependencies)


def imported():
    response = routes.import_quantum_dot(routes.QuantumDotCreate(catalog_id="nn-hecz-600"))
    return response["nanoparticle_id"], state.get_or_404()


def test_source_pinned_before_catalog_changes_and_cold_replay_needs_no_library(document, monkeypatch):
    _, design = imported()
    params = design.feature_log[0].params
    source = portable_sources(design)[params["source"]["sha256"]]
    assert json.loads(EmbeddedResolver(design.input_sources)(source)) == catalog_entry("nn-hecz-600")
    monkeypatch.setattr("backend.core.quantum_dots.catalog_entry",
                        lambda *_: (_ for _ in ()).throw(AssertionError("mutable library read")))
    isolated = Design.from_json(design.to_json())
    isolated.feature_log[0].design_snapshot_gz_b64 = "poisoned recovery"
    isolated.feature_log[0].post_state_gz_b64 = "poisoned output"
    direct = proof(isolated)
    assert direct["status"] == "reproduced_import", direct
    assert not direct["native_editable"]
    worker = VerificationWorker(capture(isolated))
    try:
        worker.start()
        assert worker.wait(5)
        result = worker.result()
        assert result["status"] == "reproduced_import", result
        assert result["checked_commands"] == 1
        assert result["imported_sources"] == [{"kind": "input_source", "identity": source.sha256}]
    finally:
        worker.close()


def test_move_resize_delete_replay_and_history_edit_keep_identity_and_source(document):
    identity, imported_design = imported()
    routes.patch_nanoparticle(identity, routes.NanoparticlePatch(
        gizmo_move=routes.GizmoMove(pivot=[1, 2, 3], translation=[4, -1, 2], rotation=[0, 0, .6, .8])))
    moved = state.get_or_404()
    assert proof(moved)["status"] == "reproduced_import"
    crud.edit_feature(0, crud.EditFeatureBody(params={"diameter_nm": 9.8,
        "nanoparticle_id": "attempted-change", "quantum_dot_version": 99}))
    edited = state.get_or_404()
    assert edited.nanoparticles[0].id == identity
    assert edited.nanoparticles[0].diameter_nm == 9.8
    assert edited.nanoparticles[0].pose == moved.nanoparticles[0].pose
    assert edited.feature_log[0].params["quantum_dot_version"] == 1
    assert edited.input_sources == imported_design.input_sources
    assert proof(edited)["status"] == "reproduced_import"
    state.undo()
    assert state.get_or_404().nanoparticles == moved.nanoparticles
    routes.delete_nanoparticle(identity)
    assert state.get_or_404().nanoparticles == []
    assert proof(state.get_or_404())["status"] == "reproduced_import"


def test_missing_input_is_unverified_and_blocks_portable_revision(document, tmp_path):
    from backend.core.project_revisions import ProjectRevisionStore

    _, design = imported()
    design.input_sources = {}
    result = proof(design)
    assert result["status"] == "unverified", result
    assert result["issues"][0]["code"] == "source_unavailable"
    with pytest.raises(SourceContractError):
        portable_sources(design)
    store = ProjectRevisionStore(tmp_path / "store")
    with pytest.raises(SourceContractError):
        store.commit(design, loadout_id="main", loadout_name="Main",
                     parent_revision_id=None, expected_head=None)
    assert not store.root.exists()


def test_catalog_hash_does_not_certify_unlogged_particle_metadata(document):
    _, design = imported()
    design.nanoparticles[0].quantum_dot.emission_peak_nm += 1
    result = proof(design)
    assert result["status"] == "mismatch", result
    assert result["issues"][0]["fields"] == ["nanoparticles"]


def test_existing_corrupt_input_and_stale_revision_reject_before_publication(document):
    _, design = imported()
    digest = design.feature_log[0].params["source"]["sha256"]
    design.input_sources[digest] = EmbeddedInput(data_b64="AAAA")
    original, revision = state.get_design_with_revision()
    for request, status in [(routes.QuantumDotCreate(catalog_id="nn-hecz-600"), 422),
                            (routes.QuantumDotCreate(catalog_id="nn-hecz-600", expected_revision=revision - 1), 409)]:
        with pytest.raises(HTTPException) as error:
            routes.import_quantum_dot(request)
        assert error.value.status_code == status
        assert state.get_design_with_revision() == (original, revision)
    assert len(original.nanoparticles) == 1


@pytest.mark.parametrize("field,value", [
    ("pose", [1.0]), ("gizmo_move", {"pivot": [0, 0, 0], "translation": [0, 0, 0], "rotation": [0, 0, 0, 0]}),
    ("diameter_nm", float("nan")), ("quantum_dot_version", True), ("source", {}),
])
def test_patch_contract_rejects_malformed_dimensions_versions_and_source_injection(field, value):
    params = {"_proof_version": 1, "quantum_dot_version": 1, "nanoparticle_id": "dot", field: value}
    with pytest.raises(ValueError):
        parse_command("nanoparticle-patch", params)
    assert not dependencies("nanoparticle-patch", params).known


@pytest.mark.parametrize("mutation", ["identity", "policy", "duplicate", "nan", "oversize", "format",
                                      "overflow", "infinite_string", "invalid_range"])
def test_invalid_catalog_source_fails_before_native_construction(monkeypatch, mutation):
    entry = json.loads(json.dumps(catalog_entry("nn-hecz-600")))
    if mutation == "identity":
        entry["catalog_id"] = "other"
    if mutation == "policy":
        entry["import_enabled"] = "true"
    if mutation == "infinite_string":
        entry["emission_tolerance_nm"] = "Infinity"
    if mutation == "invalid_range":
        entry["core_diameter_range_nm"] = [8, -1]
    raw = json.dumps(entry).encode()
    if mutation == "duplicate":
        raw = raw[:-1] + b', "catalog_id": "nn-hecz-600"}'
    if mutation == "nan":
        raw = raw[:-1] + b', "ignored": NaN}'
    if mutation == "overflow":
        raw = raw.replace(b'"emission_peak_nm": 600', b'"emission_peak_nm": 1e309')
    if mutation == "oversize":
        raw += b" " * MAX_CATALOG_BYTES
    source = describe(raw, format="pdb" if mutation == "format" else "quantum-dot-catalog",
                      media_type="application/json")
    params = {"_proof_version": 1, "quantum_dot_version": 1, "nanoparticle_id": "dot",
              "source": source.model_dump(), "catalog_id": "nn-hecz-600", "diameter_nm": 9.5}
    monkeypatch.setattr("backend.core.quantum_dots.create_quantum_dot_from_entry",
                        lambda *_a, **_kw: (_ for _ in ()).throw(AssertionError("builder reached")))
    with pytest.raises(SourceContractError):
        build("nanoparticle-create", Design(), params, resolver=EmbeddedResolver({source.sha256: embed(source, raw)}))


@pytest.mark.parametrize("remove", [False, True])
def test_ambiguous_live_qd_selection_is_structured_and_atomic(document, remove):
    identity, design = imported()
    design.nanoparticles.append(design.nanoparticles[0].model_copy(deep=True))
    original, revision = state.get_design_with_revision()
    with pytest.raises(HTTPException) as error:
        if remove:
            routes.delete_nanoparticle(identity)
        else:
            routes.patch_nanoparticle(identity, routes.NanoparticlePatch(diameter_nm=9.8))
    assert error.value.status_code == 422
    assert error.value.detail["references"][0]["identity"] == identity
    assert state.get_design_with_revision() == (original, revision)


def test_qd_package_rehydrates_catalog_source(document, tmp_path):
    from backend.core import native_part_package as package

    _, design = imported()
    workspace = tmp_path / "source"
    workspace.mkdir()
    (workspace / "dot.nadoc").write_text(design.to_json())
    archive = tmp_path / "dot.nadocpkg"
    manifest = package.create_package(workspace, "dot.nadoc", archive, mode="thin")
    assert manifest["authoring_inputs"] == [design.feature_log[0].params["source"]]
    target = tmp_path / "target"
    package.import_package(target, archive, "dot.nadoc")
    loaded = Design.from_json((target / "dot.nadoc").read_text())
    assert loaded.input_sources == design.input_sources
    assert proof(loaded)["status"] == "reproduced_import"
