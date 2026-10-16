"""Strict publication preserves a closed small projection without decoding undo.

Tests first: the complete source stays authoritative bytes. Scalar indexes and a
positive preservation digest may avoid decoding those bytes, never widen scope
or establish recipe/publication authority. No native solver is executed here.
"""

from copy import copy
from dataclasses import replace
from importlib import import_module

from fastapi import HTTPException
from pydantic.fields import FieldInfo
import pytest

from backend.api import part_evaluation_jobs as jobs, state
from backend.api import part_immutable_evaluation as evaluation
from backend.api import part_immutable_revision as revisions
from backend.core.models import Design, VisibilityState
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_proof import digest
from backend.core.part_recipe_publication import preserve_document_state
from tests.test_part_immutable_evaluation import (  # noqa: F401 -- pytest fixture dependencies
    body, document, immediate, slot_available,
)
from tests.test_part_immutable_revision import retained_source, source


PRESERVED_ROLES = {
    "id": "document_identity",
    "plate_layout": "presentation", "representation_overrides": "presentation",
    "view_volumes": "presentation", "annotations": "presentation",
    "annotations_enabled": "presentation", "visibility_state": "presentation",
    "camera_poses": "presentation", "animations": "presentation",
    "chain_sim_projects": "physical", "loadouts": "physical", "atomistic_reference": "physical",
    "active_loadout_id": "physical", "last_editable_loadout_id": "physical",
    "repair_draft": "repair_draft",
}
EMPTY_LISTS = ("representation_overrides", "view_volumes", "annotations", "camera_poses",
               "animations", "chain_sim_projects", "loadouts")
ABSENT = ("plate_layout", "atomistic_reference", "active_loadout_id", "last_editable_loadout_id", "repair_draft")


def projection(design):
    # Independent oracle: same full field values carried by classic publication.
    return design.model_dump(mode="json", include=set(PRESERVED_ROLES))


@pytest.mark.parametrize("enabled", [False, True])
def test_metadata_is_derived_from_exact_bytes_and_positive_preservation_projection(enabled):
    original = source()
    original.annotations_enabled = enabled
    sealed = revisions.prepare_revision(original)
    metadata = revisions.revision_metadata(sealed)
    decoded = revisions.materialize_revision(sealed)
    assert metadata.annotations_enabled is enabled
    assert type(metadata.annotations_enabled) is bool
    assert metadata.preservation_version == 1
    assert metadata.preserved_document_sha256 == digest(projection(decoded))
    assert metadata.preserved_document_sha256 == digest(projection(original))


@pytest.mark.parametrize("enabled", [False, True])
def test_fast_preservation_matches_complete_legacy_publication_without_source_decode(monkeypatch, enabled):
    original = retained_source()
    original.annotations_enabled = enabled
    sealed = revisions.prepare_revision(original)
    candidate = source()
    candidate.id = "worker-generated-document-identity"
    candidate.annotations_enabled = not enabled
    candidate.metadata.name = "Authored candidate name"
    before = candidate.model_dump_json()
    expected = revisions.prepare_revision(preserve_document_state(original, candidate))
    original_decode, decodes = revisions._decoded_exact, []

    def candidate_decode_only(payload, checkpoint):
        assert payload is not sealed.payload and payload != sealed.payload, "Commit decoded the full source"
        decodes.append(payload)
        return original_decode(payload, checkpoint)

    monkeypatch.setattr(revisions, "_decoded_exact", candidate_decode_only)
    monkeypatch.setattr(revisions, "materialize_revision", lambda *_a, **_k: pytest.fail("Commit materialized undo"))
    actual = evaluation.prepare_candidate(sealed, candidate)
    assert actual.payload == expected.payload
    assert revisions.revision_metadata(actual).name == "Authored candidate name"
    assert revisions.revision_metadata(actual).design_id == original.id
    assert revisions.revision_metadata(actual).annotations_enabled is enabled
    assert decodes, "Candidate must still complete its own exact full roundtrip"
    assert candidate.model_dump_json() == before


def test_near_recovery_boundary_does_not_reparse_source_or_carry_recovery_into_candidate(monkeypatch):
    original = retained_source()
    original.annotations_enabled = False
    original.feature_log[0].design_snapshot_gz_b64 = "opaque:never-decompress:" + "x" * 7_900_000
    sealed = revisions.prepare_revision(original)
    assert 7_900_000 < len(sealed.payload) < 8_000_000
    original_bytes = sealed.payload
    candidate = source()
    original_decode, decoded_sizes = revisions._decoded_exact, []

    def small_candidate_only(payload, checkpoint):
        assert len(payload) < 100_000, "Publication reparsed retained recovery"
        decoded_sizes.append(len(payload))
        return original_decode(payload, checkpoint)

    monkeypatch.setattr(revisions, "_decoded_exact", small_candidate_only)
    monkeypatch.setattr(revisions, "materialize_revision", lambda *_a, **_k: pytest.fail("Commit decoded source"))
    actual = evaluation.prepare_candidate(sealed, candidate)
    assert decoded_sizes and len(actual.payload) < 100_000
    assert sealed.payload is original_bytes
    assert revisions.revision_metadata(actual).annotations_enabled is False


class OpaqueList(list):
    """An unsupported value that must be refused by shape, never visited."""

    def __len__(self):
        raise AssertionError("Traversed unadmitted list length")

    def __iter__(self):
        raise AssertionError("Traversed unadmitted list")

    def __eq__(self, other):
        raise AssertionError("Compared unadmitted list")


@pytest.mark.parametrize("field", EMPTY_LISTS)
def test_hostile_candidate_lists_refuse_before_serialization_or_default_equality(monkeypatch, field):
    sealed = revisions.prepare_revision(source())
    candidate = source()
    setattr(candidate, field, OpaqueList())
    monkeypatch.setattr(Design, "model_dump", lambda *_a, **_k: pytest.fail("Serialized an unadmitted candidate"))
    with pytest.raises(CommandContractError):
        evaluation.prepare_candidate(sealed, candidate)


@pytest.mark.parametrize("field", ABSENT)
def test_candidate_nondefault_optional_state_is_refused_not_silently_erased(field):
    sealed = revisions.prepare_revision(source())
    candidate = source()
    sentinel = object()
    setattr(candidate, field, sentinel)
    with pytest.raises(CommandContractError):
        evaluation.prepare_candidate(sealed, candidate)
    assert getattr(candidate, field) is sentinel


@pytest.mark.parametrize("field", ["hidden_base_keys", "shown_base_keys", "hidden_cluster_ids", "hidden_part_group_ids"])
def test_nested_visibility_is_checked_before_any_candidate_projection(monkeypatch, field):
    sealed = revisions.prepare_revision(source())
    candidate = source()
    setattr(candidate.visibility_state, field, OpaqueList())
    monkeypatch.setattr(Design, "model_dump", lambda *_a, **_k: pytest.fail("Serialized nested unadmitted state"))
    with pytest.raises(CommandContractError):
        evaluation.prepare_candidate(sealed, candidate)


@pytest.mark.parametrize("field,role", [("future_display_field", "presentation"),
    ("annotations_enabled", "authoring"), ("repair_draft", "history")])
def test_new_or_reclassified_preservation_roles_need_a_reviewed_contract(monkeypatch, field, role):
    sealed = revisions.prepare_revision(source())
    candidate = source()
    preservation = import_module("backend.api.part_immutable_preservation")
    monkeypatch.setattr(preservation, "FIELD_ROLES", {**preservation.FIELD_ROLES, field: role})
    monkeypatch.setattr(Design, "model_dump", lambda *_a, **_k: pytest.fail("Unreviewed preservation schema serialized"))
    with pytest.raises(CommandContractError):
        evaluation.prepare_candidate(sealed, candidate)


def test_new_nested_visibility_schema_is_refused_even_when_its_value_is_default(monkeypatch):
    sealed = revisions.prepare_revision(source())
    candidate = source()
    candidate.visibility_state = candidate.visibility_state.model_copy(update={"future_visibility": []})
    monkeypatch.setattr(VisibilityState, "__pydantic_fields__", {
        **VisibilityState.model_fields, "future_visibility": FieldInfo(annotation=list[str], default_factory=list)})
    monkeypatch.setattr(Design, "model_dump", lambda *_a, **_k: pytest.fail("New nested schema serialized"))
    with pytest.raises(CommandContractError):
        evaluation.prepare_candidate(sealed, candidate)


def test_broader_batch_scope_cannot_bypass_literal_preservation_defaults(monkeypatch):
    original = source()
    # Simulate a future host-envelope expansion. Preservation has its own closed
    # contract and must refuse the new state before any serializer can visit it.
    original.visibility_state.hidden_base_keys = ["unreviewed-default"]
    monkeypatch.setattr(revisions, "admit_batch_source", lambda *_a, **_k: None)
    monkeypatch.setattr(Design, "model_dump", lambda *_a, **_k: pytest.fail("Changed defaults serialized"))
    with pytest.raises(CommandContractError):
        revisions.prepare_revision(original)


@pytest.mark.parametrize("value", [0, 1, None, "false"])
def test_seal_indexes_only_an_exact_boolean_annotation_flag(monkeypatch, value):
    original = source()
    original.annotations_enabled = value
    monkeypatch.setattr(Design, "model_dump", lambda *_a, **_k: pytest.fail("Nonboolean flag serialized"))
    with pytest.raises(CommandContractError):
        revisions.prepare_revision(original)


def test_rebound_metadata_cannot_authorize_preservation_without_the_original_seal(monkeypatch):
    sealed = revisions.prepare_revision(source())
    duplicate = copy(sealed)
    replacement = replace(revisions.revision_metadata(sealed), annotations_enabled=False,
                          preserved_document_sha256="0" * 64)
    object.__setattr__(duplicate, "_metadata", replacement)
    monkeypatch.setattr(Design, "model_dump", lambda *_a, **_k: pytest.fail("Unsealed source used"))
    with pytest.raises((HTTPException, CommandContractError)):
        evaluation.prepare_candidate(duplicate, source())


def test_hostile_worker_presentation_cannot_publish_and_valid_candidate_remains_retryable(immediate):  # noqa: F811 -- imported fixture
    doc, sealed = immediate
    revision, original_bytes = state.revision(), sealed.payload
    identity = jobs.start(body(sealed))["job_id"]
    job = jobs._jobs[identity]
    candidate = job.result["candidate"]
    candidate["visibility_state"]["hidden_base_keys"] = ["worker-injected-key"]
    with pytest.raises(HTTPException) as error:
        jobs.commit(identity)
    assert error.value.status_code in {409, 422}
    assert state._sessions[doc].design is sealed and state.revision() == revision
    assert not state._sessions[doc].history and job.committed_revision is None
    assert sealed.payload is original_bytes
    assert job.result.get("candidate") is candidate
    candidate["visibility_state"]["hidden_base_keys"] = []
    committed = jobs.commit(identity)
    assert committed["revision"] == revision + 1
    assert list(state._sessions[doc].history) == [sealed]
    slot_available()
