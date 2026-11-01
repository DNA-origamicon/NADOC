"""Pending alternatives preserve the exact active graph and replay from inputs."""

from copy import deepcopy

import pytest
from pydantic import ValidationError

from backend.api import part_np_application_commands as application
from backend.api import part_np_pending_context_commands as commands
from backend.api import routes_nanoparticles as routes, state
from backend.api.part_proof_commands import dependencies
from backend.api.part_recipe_edit import prepare_change, regenerate
from backend.core.models import Design
from backend.core.part_command_errors import ReferenceResolutionError
from backend.core.part_dependencies import Resource
from backend.core.part_edit_identity import preserve_proof_identity
from backend.core.part_history_proof import AUTHORING_FIELDS
from backend.core.part_verification_capture import capture
from scripts.benchmark_np_application_route import cold_proof
from tests.test_np_connection_application_routes import opened_document, request, create_body, state_signature
from tests.test_part_np_application_commands import application_params, version
from tests.test_part_pending_np_connections import (
    CREATE, PATCH, DELETE, append, creation, native_prefix as native_prefix, owner_inputs, proof,
)


@pytest.fixture
def active(native_prefix):
    return append(native_prefix, CREATE, application_params(native_prefix), "active")


def values(source, kind=CREATE, *, handle=0, **updates):
    current = version(source)
    result = {**owner_inputs(source, version_id="alternative"),
        "nanoparticle_pending_context_version": 1,
        "active_version_id": current.id, "active_duplex_id": current.duplex_id}
    if kind == CREATE:
        result = {**creation(source), **result,
            "strand_id": source.nanoparticle_conjugations[0].surface_strands[handle].strand_id}
    elif kind == PATCH:
        result["name"] = "Renamed alternative"
    return {**result, **updates}


@pytest.mark.parametrize("handle", [0, 1])
def test_pending_crud_preserves_every_live_owner_and_position(active, handle):
    source = active
    for kind in (CREATE, PATCH, DELETE):
        inputs = values(source, kind, handle=handle,
            strand_id=active.nanoparticle_conjugations[0].surface_strands[handle].strand_id)
        before = source.model_dump_json()
        candidate = commands.build(kind, source, inputs)
        assert source.model_dump_json() == before
        for field in AUTHORING_FIELDS - {"nanoparticle_connection_versions"}:
            assert getattr(candidate, field) is getattr(source, field), field
        assert version(candidate) is version(source)
        if kind != DELETE:
            assert not version(candidate, "alternative").applied
        else:
            assert candidate.nanoparticle_connection_versions == active.nanoparticle_connection_versions
        source = candidate


@pytest.mark.parametrize("field,value", [("active_version_id", "missing"), ("active_duplex_id", "missing"),
    ("conjugation_id", "foreign"), ("strand_id", "missing"), ("overhang_id", "missing")])
def test_exact_context_selectors_refuse_drift_without_touching_source(active, field, value):
    before = active.model_dump_json()
    with pytest.raises(ReferenceResolutionError) as error:
        commands.build(CREATE, active, values(active, **{field: value}))
    assert any(reference["parameter_path"] == [field] for reference in error.value.references)
    assert active.model_dump_json() == before


@pytest.mark.parametrize("change", [{"active_version_id": None}, {"active_duplex_id": None},
    {"nanoparticle_pending_context_version": True}, {"nanoparticle_pending_context_version": 2},
    {"saved_topology": {}}, {"applied": True}])
def test_context_grammar_cannot_hide_geometry_or_change_contract(active, change):
    with pytest.raises(ValidationError):
        commands.parse_command(CREATE, values(active, **change))


def test_pending_context_reads_active_resources_and_protects_contract(active):
    inputs = values(active)
    reads = dependencies(CREATE, inputs).reads
    assert Resource("nanoparticle_connection_version", "candidate") in reads
    assert Resource("duplex", version(active).duplex_id) in reads
    edited = preserve_proof_identity(inputs, {**inputs, "version_id": "other",
        "nanoparticle_pending_context_version": 2}, kind=CREATE)
    assert edited["version_id"] == "alternative" and edited["nanoparticle_pending_context_version"] == 1


def test_registered_alternative_survives_upstream_edit_and_independent_replay(active):
    result = append(active, CREATE, values(active), "alternative-create")
    result = append(result, PATCH, values(result, PATCH), "alternative-rename")
    assert proof(result)["status"] == "verified"
    original = result.model_dump_json()
    gold = next(index for index, row in enumerate(result.feature_log) if row.op_kind == "nanoparticle-create")
    result, _ = prepare_change(result, capture(result, preserve_entry_types=True), gold,
                               lambda: None, params={"diameter_nm": 14.0})
    assert result.nanoparticles[0].diameter_nm == 14.0
    assert version(result).applied and version(result).duplex_id == version(active).duplex_id
    assert version(result, "alternative").name == "Renamed alternative"
    assert cold_proof(result)["status"] == "verified"
    assert original != result.model_dump_json()


def test_removing_active_creator_lists_the_pending_context_dependency(active):
    result = append(active, CREATE, values(active), "alternative-create")
    response = prepare_change(result, capture(result, preserve_entry_types=True),
                              len(active.feature_log) - 1, lambda: None)
    assert response["needs_cascade_decision"]
    issue = next(item["issues"]["alternative-create"] for item in response["dependents"]
                 if "alternative-create" in item["issues"])
    assert issue["code"] == "missing_reference"
    assert any(reference["parameter_path"] == ["active_version_id"] for reference in issue["references"])


@pytest.mark.parametrize("action", ["create", "rename", "delete", "explicit_pending"])
def test_ordinary_pending_context_is_one_metadata_edit_with_exact_active_graph(active, monkeypatch, action):
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True)
    if action != "create":
        active = append(active, CREATE, values(active), "alternative-create")
    with opened_document(active) as client:
        source = state.get_or_404()
        before, revision, depth = source.model_dump_json(), state.revision(), state.undo_depth()
        if action == "create":
            result = request(client, "post", body=create_body(source, applied=False))
            expected = 201
        elif action == "delete":
            result = request(client, "delete", identity="alternative")
            expected = 200
        else:
            result = request(client, "patch", identity="alternative",
                body={"applied": False} if action == "explicit_pending" else {"name": "New name"})
            expected = 200
        assert result.status_code == expected, result.text
        current = state.get_or_404()
        assert current.feature_log[-1].params["nanoparticle_pending_context_version"] == 1
        assert current.feature_log[-1].params["active_duplex_id"] == version(source).duplex_id
        assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
        assert source.model_dump_json() == before
        assert current.model_dump(include=AUTHORING_FIELDS - {"nanoparticle_connection_versions"}) == source.model_dump(
            include=AUTHORING_FIELDS - {"nanoparticle_connection_versions"})
        assert version(current) == version(source)
        assert proof(current)["status"] == "verified"
        state.undo()
        assert state.get_or_404() == source
        state.redo()
        assert state.get_or_404() == current
        assert proof(Design.from_json(current.to_json()))["status"] == "verified"


def test_native_private_restoration_failure_cannot_fall_back_or_publish(active, monkeypatch):
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True)

    def fail(*_args, **_kwargs):
        raise RuntimeError("private restoration failed")

    monkeypatch.setattr(application, "set_version_applied", fail)
    monkeypatch.setattr(routes, "NanoparticleConnectionVersion", lambda **_kw: pytest.fail("Legacy fallback"))
    with opened_document(active) as client:
        before = state_signature()
        with pytest.raises(RuntimeError, match="private restoration failed"):
            request(client, "post", body=create_body(active, applied=False))
        assert state_signature() == before


def test_new_alternative_switches_then_deletes_with_complete_cold_proof(active, monkeypatch):
    monkeypatch.setattr(routes, "OWNED_NP_APPLICATION_ENABLED", True)
    with opened_document(active) as client:
        result = request(client, "post", body=create_body(active, applied=False, name="Alternative"))
        assert result.status_code == 201, result.text
        identity = result.json()["version_id"]
        before = deepcopy(state.get_or_404())
        result = request(client, "patch", identity=identity, body={"applied": True})
        assert result.status_code == 200, result.text
        current = state.get_or_404()
        assert not version(current).applied and version(current, identity).applied
        assert len(current.duplexes) == 1
        assert cold_proof(current)["status"] == "verified"
        state.undo()
        assert state.get_or_404() == before
        state.redo()
        assert request(client, "delete", identity=identity).status_code == 200
        assert not state.get_or_404().duplexes
        assert proof(state.get_or_404())["status"] == "verified"


def test_three_prime_handle_context_uses_existing_root_to_root_chemistry(native_prefix):
    graft = native_prefix.feature_log[-1]
    source = regenerate(native_prefix, [*native_prefix.feature_log[:-1], graft.model_copy(update={
        "params": {**graft.params, "attach_end": "3p"}})], lambda: None)
    active = append(source, CREATE, application_params(source, direct_variant="root-to-root"), "active")
    candidate = append(active, CREATE, values(active, direct_variant="root-to-root"), "alternative")
    assert candidate.model_dump(include=AUTHORING_FIELDS - {"nanoparticle_connection_versions"}) == active.model_dump(
        include=AUTHORING_FIELDS - {"nanoparticle_connection_versions"})
    assert version(candidate, "alternative").nanoparticle_attach == "free_end"
    applied = append(candidate, PATCH, application_params(candidate, PATCH, version_id="alternative",
        duplex_id="replacement-duplex"), "switch")
    assert version(applied, "alternative").applied and not version(applied).applied
    assert proof(applied)["status"] == "verified"


def test_guarded_http_history_edit_adopts_complete_geometry_once(active):
    from backend.api import crud
    source = append(active, CREATE, values(active), "alternative")
    source = append(source, PATCH, application_params(source, PATCH, version_id="alternative",
        duplex_id="replacement-duplex"), "later-apply")
    with opened_document(source) as client:
        client.app.include_router(crud.router, prefix="/api")
        current = state.get_or_404()
        before, revision, depth = current.model_dump_json(), state.revision(), state.undo_depth()
        index = len(current.feature_log) - 1
        body = {"expected_design_id": current.id, "expected_revision": revision,
                "expected_feature_id": current.feature_log[index].id, "params": {"name": "Chosen alternative"}}
        response = client.post(f"/api/design/features/{index}/edit", json=body)
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["nucleotides"] and not payload.get("partial_geometry") and not payload.get("geometry_skipped")
        assert payload.get("diff_kind") not in {"positions_only", "cluster_only"}
        assert state.revision() == revision + 1 and state.undo_depth() == depth + 1
        assert current.model_dump_json() == before
        assert version(state.get_or_404(), "alternative").name == "Chosen alternative"
        saved = state_signature()
        assert client.post(f"/api/design/features/{index}/edit", json=body).status_code == 409
        assert state_signature() == saved
