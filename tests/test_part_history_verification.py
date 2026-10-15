"""Proof must fail closed, stay isolated, and never trust recovery payloads."""
import pytest
from fastapi import HTTPException

from backend.core.models import Design, RoutingClusterLogEntry, SnapshotLogEntry
from backend.core.part_history_contract import FIELD_ROLES, PartRecipeRoot, assess_part_history


def test_every_design_field_has_an_explicit_proof_role():
    assert FIELD_ROLES.keys() == Design.model_fields.keys()


def test_legacy_empty_document_is_not_implicitly_certified():
    result = assess_part_history(Design())
    assert result["status"] == "unverified"
    assert result["issues"] == [{"code": "missing_recipe_root"}]


@pytest.mark.parametrize("lattice", ["HONEYCOMB", "SQUARE"])
def test_explicit_empty_root_survives_save_reload_and_verifies(lattice):
    design = Design(lattice_type=lattice, recipe_root=PartRecipeRoot(lattice_type=lattice))
    reloaded = Design.model_validate_json(design.model_dump_json())
    assert reloaded.recipe_root == design.recipe_root
    assert assess_part_history(reloaded)["status"] == "verified"


def test_empty_root_does_not_certify_unlogged_geometry():
    from backend.core.lattice import make_bundle_design
    design = make_bundle_design([(0, 0)], length_bp=21)
    design.recipe_root = PartRecipeRoot()
    before = design.model_dump()
    result = assess_part_history(design)
    assert result["status"] == "mismatch"
    assert {"helices", "strands"} <= set(result["issues"][0]["fields"])
    assert design.model_dump() == before


def test_nested_authoring_settings_are_compared_not_only_geometry():
    design = Design(recipe_root=PartRecipeRoot())
    design.metadata.primitive_kind = "circle"
    result = assess_part_history(design)
    assert result["status"] == "mismatch"
    assert result["issues"][0]["fields"] == ["metadata"]


def test_presentation_is_explicitly_outside_authoring_proof():
    design = Design(recipe_root=PartRecipeRoot(), annotations_enabled=False)
    assert assess_part_history(design)["status"] == "verified"


def test_future_root_version_is_unverified_not_assumed_compatible():
    result = assess_part_history(Design(recipe_root=PartRecipeRoot(version=2)))
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "unsupported_root_version"


def test_root_cannot_smuggle_saved_model_output():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        PartRecipeRoot.model_validate({"kind": "empty", "helices": [{"id": "opaque"}]})


def test_unknown_future_fields_fail_closed():
    class FutureDesign(Design):
        new_authoring_field: str = ""
    result = assess_part_history(FutureDesign(recipe_root=PartRecipeRoot()))
    assert result["status"] == "unverified"
    assert result["issues"][0]["fields"] == ["new_authoring_field"]


@pytest.mark.parametrize("cursor,sub", [(0, None), (-2, None), (-1, 0)])
def test_historical_cursor_cannot_certify_current_recipe(cursor, sub):
    result = assess_part_history(Design(recipe_root=PartRecipeRoot(),
                                       feature_log_cursor=cursor, feature_log_sub_cursor=sub))
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "historical_cursor"


def test_available_executor_and_saved_output_are_not_proof():
    design = Design(recipe_root=PartRecipeRoot(), feature_log=[SnapshotLogEntry(
        op_kind="bundle-create", label="Bundle", params={"cells": [[0, 0]]},
        design_snapshot_gz_b64="deliberately-not-gzip", post_state_gz_b64="deliberately-not-gzip",
    )])
    result = assess_part_history(design)
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "missing_proof_contract"
    assert result["issues"][0]["kind"] == "bundle-create"


def test_empty_routing_cluster_cannot_be_treated_as_empty_recipe():
    result = assess_part_history(Design(recipe_root=PartRecipeRoot(), feature_log=[RoutingClusterLogEntry()]))
    assert result["status"] == "unverified"
    assert result["issues"][0]["code"] == "empty_routing_cluster"


def test_diagnostic_count_is_bounded():
    design = Design(recipe_root=PartRecipeRoot(), feature_log=[
        SnapshotLogEntry(op_kind="bundle-create", label="Bundle") for _ in range(5)
    ])
    result = assess_part_history(design, max_entries=2)
    assert len(result["issues"]) == 3
    assert result["issues"][-1]["code"] == "entry_limit"


def test_empty_clusters_also_consume_the_diagnostic_budget():
    design = Design(recipe_root=PartRecipeRoot(), feature_log=[RoutingClusterLogEntry() for _ in range(5)])
    result = assess_part_history(design, max_entries=2)
    assert len(result["issues"]) == 3
    assert result["issues"][-1]["code"] == "entry_limit"


def test_root_survives_existing_recovery_snapshot_codec():
    from backend.api.state import decode_design_snapshot, encode_design_snapshot
    design = Design(recipe_root=PartRecipeRoot())
    encoded, _ = encode_design_snapshot(design)
    assert decode_design_snapshot(encoded).recipe_root == design.recipe_root


@pytest.fixture
def document():
    from backend.api import state
    from backend.api.doc_context import reset_current_doc, set_current_doc
    token = set_current_doc("part-proof-test")
    state.load_design(Design(recipe_root=PartRecipeRoot()))
    try:
        yield state
    finally:
        state.close_session()
        reset_current_doc(token)


def test_api_check_preserves_live_design_revision_and_undo(document):
    from backend.api.part_history_verification import verify_current_part
    live = document.get_or_404()
    before = live.model_dump()
    revision = document.revision()
    result = verify_current_part()
    assert result["status"] == "verified"
    assert result["source_revision"] == revision
    assert not result["stale"]
    assert document.get_or_404() is live
    assert live.model_dump() == before
    assert document.revision() == revision
    assert document.undo_depth() == document.redo_depth() == 0


def test_mutating_checker_cannot_mutate_live_document(document, monkeypatch):
    from backend.api import part_history_verification as api
    def inspect(copy, **kwargs):
        copy.metadata.name = "Changed inside isolated check"
        return {"status": "unverified", "issues": []}
    monkeypatch.setattr(api, "assess_part_history", inspect)
    api.verify_current_part()
    assert document.get_or_404().metadata.name == "Untitled"


def test_revision_change_during_check_discards_green_result(document, monkeypatch):
    from backend.api import part_history_verification as api
    def inspect(copy, **kwargs):
        document.mutate_and_validate(lambda d: setattr(d.metadata, "name", "User edit"))
        return {"status": "verified", "issues": []}
    monkeypatch.setattr(api, "assess_part_history", inspect)
    result = api.verify_current_part()
    assert result["stale"]
    assert result["status"] == "unverified"
    assert result["issues"][-1]["code"] == "source_changed"


def test_slot_released_after_checker_exception(document, monkeypatch):
    from backend.api import part_history_verification as api
    def fail(copy, **kwargs):
        raise RuntimeError("failed check")
    monkeypatch.setattr(api, "assess_part_history", fail)
    with pytest.raises(RuntimeError):
        api.verify_current_part()
    monkeypatch.setattr(api, "assess_part_history", assess_part_history)
    assert api.verify_current_part()["status"] == "verified"


def test_different_document_with_same_revision_invalidates_result(document, monkeypatch):
    from backend.api import part_history_verification as api
    revision = document.revision()
    monkeypatch.setattr(document, "get_design_with_revision", lambda: (Design(), revision))
    result = api.verify_current_part()
    assert result["stale"]
    assert result["status"] == "unverified"


def test_busy_check_fails_without_copying_or_waiting(document, monkeypatch):
    from backend.api import part_history_verification as api
    def unexpected():
        pytest.fail("Must not copy document when audit slot is busy")
    monkeypatch.setattr(document, "capture_design_for_verification", unexpected)
    assert api._slot.acquire(blocking=False)
    try:
        with pytest.raises(HTTPException) as exc:
            api.verify_current_part()
        assert exc.value.status_code == 429
    finally:
        api._slot.release()


def test_verification_route_is_registered_and_read_only(document):
    from fastapi.testclient import TestClient
    from backend.api.main import app
    response = TestClient(app).post("/api/design/features/verification", headers={"X-NADOC-Doc": "part-proof-test"})
    assert response.status_code == 200
    assert response.json()["status"] == "verified"


def test_new_empty_document_route_records_explicit_named_root(document):
    from backend.api.crud import CreateDesignRequest, create_design
    create_design(CreateDesignRequest(name="Named new part", lattice_type="SQUARE"))
    design = document.get_or_404()
    assert design.recipe_root.initial_name == "Named new part"
    assert design.recipe_root.lattice_type == "SQUARE"
    assert assess_part_history(design)["status"] == "verified"
