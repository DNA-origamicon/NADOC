"""Persistent named-group visibility is presentation, not placement or topology.

Memory-only host and HTTP checks; no workspace, application lifespan or solver.
"""

from copy import deepcopy

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from pydantic import ValidationError
import pytest

from backend.api import crud, doc_context, state
from backend.api import part_immutable_preservation as preservation
from backend.core import models as m
from backend.core.part_command_errors import CommandContractError
from backend.core.part_history_contract import FIELD_ROLES
from backend.core.part_recipe_publication import preserve_document_state
from tests.test_group_organization_recording import apply, before, unchanged
from tests.test_group_organization_recording import document as document


LEGACY = {"hidden_base_keys": ["h:0:FORWARD"], "shown_base_keys": ["h:1:REVERSE"],
          "hidden_cluster_ids": ["placement"]}


def visibility(ids, **changes):
    return {**deepcopy(LEGACY), "hidden_part_group_ids": ids, **changes}


def authoring(design):
    return design.model_dump(mode="json", include={key for key, role in FIELD_ROLES.items()
                                                  if role in {"authoring", "history", "recipe"}})


def save(session, body):
    return apply(session, "visibility-update", {"visibility_state": body})


def test_old_three_field_visibility_loads_with_independent_empty_group_mask():
    model = m.VisibilityState.model_validate(deepcopy(LEGACY))
    assert model.hidden_part_group_ids == []
    assert model.model_dump(exclude={"hidden_part_group_ids"}) == LEGACY
    other = m.VisibilityState()
    model.hidden_part_group_ids.append("local")
    assert other.hidden_part_group_ids == []


def test_new_identity_mask_roundtrips_without_inferring_current_members(document):
    source = document.design
    expected = visibility(["placement", "absent-at-this-history-stage"])
    source.visibility_state = m.VisibilityState.model_validate(expected)
    saved = source.to_json()
    restored = m.Design.from_json(saved)
    assert restored.visibility_state.model_dump() == expected
    assert restored.group_organization is None  # Dormant IDs are legal presentation.
    assert restored.cluster_transforms == source.cluster_transforms
    assert authoring(restored) == authoring(source)


@pytest.mark.parametrize("ids", [None, "group", ("group",), [True], [1], [""],
                                  ["x" * 513], [f"g-{i}" for i in range(2001)]])
def test_group_mask_has_exact_bounded_identity_shape(ids):
    with pytest.raises(ValidationError):
        m.VisibilityState.model_validate(visibility(ids))


def test_group_mask_accepts_declared_identity_and_count_boundaries():
    ids = ["x" * 512, *[f"g-{i}" for i in range(1999)]]
    assert m.VisibilityState.model_validate(visibility(ids)).hidden_part_group_ids == ids


def test_owned_visibility_is_one_undo_with_no_feature_or_authoring_mutation(document):
    apply(document)
    source, serialized, revision, history, *_ = before(document)
    source_authoring = authoring(source)
    body = visibility(["placement", "missing", "placement"])
    candidate, _, entry = save(document, body)
    expected = visibility(["placement", "missing"])
    assert entry is None and candidate.visibility_state.model_dump() == expected
    assert candidate.feature_log is source.feature_log
    assert authoring(candidate) == source_authoring
    assert source.model_dump_json() == serialized
    assert document.revision == revision + 1 and len(document.history) == len(history) + 1
    assert body["hidden_part_group_ids"] == ["placement", "missing", "placement"]
    restored, _ = state.undo()
    assert restored.visibility_state == source.visibility_state
    redone, _ = state.redo()
    assert redone.visibility_state.model_dump() == expected
    saved, _, _ = state.copy_for_workspace_save()
    loaded = m.Design.from_json(saved.to_json())
    crud._install_loaded_design(loaded)
    assert document.design.visibility_state.model_dump() == expected


def test_legacy_three_field_request_remains_exact_and_clears_named_mask(document):
    apply(document)
    save(document, visibility(["placement"]))
    candidate, _, entry = save(document, deepcopy(LEGACY))
    assert entry is None
    assert candidate.visibility_state.hidden_part_group_ids == []
    assert candidate.visibility_state.model_dump() == LEGACY


def test_membership_dissolve_and_seek_keep_dormant_group_intent_separate_from_placements(document):
    apply(document)
    wanted = visibility(["placement", "not-created-yet"], hidden_cluster_ids=[])
    save(document, wanted)
    placements = deepcopy(document.design.cluster_transforms)
    apply(document, "group-update", {"group_id": "placement", "fields": {
        "helix_ids": [document.design.helices[1].id]}})
    assert document.design.visibility_state.model_dump() == wanted
    apply(document, "group-dissolve", {"group_ids": ["placement"]})
    dissolved = document.design
    assert dissolved.visibility_state.model_dump() == wanted
    assert dissolved.cluster_transforms == placements
    restored = crud._seek_feature_log(dissolved, 3)
    assert any(group.id == "placement" for group in restored.group_organization.groups)
    assert restored.visibility_state.model_dump() == wanted
    state.undo()
    assert document.design.visibility_state.model_dump() == wanted


@pytest.mark.parametrize("body", [
    visibility(None), visibility([True]), visibility([""]), visibility(["x" * 513]),
    visibility([f"g-{i}" for i in range(2001)]),
    {**visibility([]), "hidden_groups": []},
    {"hidden_part_group_ids": ["group"]},
])
def test_malformed_owned_visibility_refuses_without_source_or_undo_mutation(document, monkeypatch, body):
    apply(document)
    checkpoint = before(document)
    monkeypatch.setattr(state, "encode_design_snapshot", lambda *_: pytest.fail("Visibility encoded feature recovery"))
    with pytest.raises(HTTPException) as caught:
        save(document, body)
    assert caught.value.status_code == 422
    unchanged(document, checkpoint)


def test_visibility_noop_and_stale_request_preserve_exact_source(document):
    apply(document)
    body = visibility(["placement", "dormant"])
    save(document, body)
    checkpoint = before(document)
    candidate, _, entry = save(document, body)
    assert candidate is checkpoint[0] and entry is None
    unchanged(document, checkpoint)
    with pytest.raises(HTTPException) as caught:
        apply(document, "visibility-update", {"visibility_state": visibility([])},
              revision=document.revision - 1)
    assert caught.value.status_code == 409
    unchanged(document, checkpoint)


def test_legacy_display_endpoint_preserves_new_field_without_feature_entry(document):
    from backend.api.routes_display_metadata import router

    app = FastAPI()
    app.include_router(router, prefix="/api")
    app.add_middleware(doc_context.DocContextMiddleware)
    expected = visibility(["placement", "future"])
    source = document.design
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.put("/api/design/visibility", json=expected,
                              headers={"X-NADOC-Doc": doc_context.get_current_doc()})
    assert response.status_code == 200, response.text
    assert document.design.visibility_state.model_dump() == expected
    assert document.design.feature_log == source.feature_log
    assert document.design.cluster_transforms == source.cluster_transforms


def test_recipe_publication_preserves_group_visibility_without_authoring_identity(document):
    source = document.design
    source.visibility_state = m.VisibilityState.model_validate(visibility(["dormant"]))
    candidate = source.model_copy(deep=True)
    candidate.visibility_state = m.VisibilityState()
    result = preserve_document_state(source, candidate)
    assert result.visibility_state.hidden_part_group_ids == ["dormant"]
    assert result.visibility_state is source.visibility_state


def test_strict_default_catalog_carries_empty_new_field_and_refuses_nonempty_mask(monkeypatch):
    source = m.Design()
    assert source.visibility_state.hidden_part_group_ids == []
    baseline = preservation.preservation_digest(source)
    assert len(baseline) == 64
    source.visibility_state.hidden_part_group_ids = ["group"]
    monkeypatch.setattr(m.Design, "model_dump", lambda *_a, **_k: pytest.fail("Nonempty preservation serialized"))
    with pytest.raises(CommandContractError) as caught:
        preservation.preservation_digest(source)
    assert caught.value.code == "unsupported_revision_preservation"


def test_owned_oxdna_archive_preserves_dormant_mask_without_aliasing():
    from backend.core.oxdna_preparation_inputs import capture_archive
    from tests.test_oxdna_preparation_capture import source

    original = source()
    original.visibility_state = m.VisibilityState.model_validate(visibility(["absent", "same"]))
    copied = capture_archive(original)
    assert copied.visibility_state.hidden_part_group_ids == ["absent", "same"]
    original.visibility_state.hidden_part_group_ids.append("later")
    assert copied.visibility_state.hidden_part_group_ids == ["absent", "same"]
