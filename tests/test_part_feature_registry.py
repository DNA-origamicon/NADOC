"""Executable capability declarations and standard-part replay boundaries."""
from importlib import import_module
from typing import get_args

import pytest
from fastapi import HTTPException
from pydantic import BaseModel, ValidationError

from backend.api.part_feature_commands import replay_minor, replay_snapshot
from backend.core.feature_dependencies import REPLAYABLE_SNAPSHOT_OPS
from backend.core.feature_registry import PART_MINOR_COMMANDS, PART_SNAPSHOT_COMMANDS
from backend.core.models import Design, MinorOpSubtype, SnapshotOpKind


@pytest.mark.parametrize("kind,spec", list(PART_SNAPSHOT_COMMANDS.items()) + list(PART_MINOR_COMMANDS.items()))
def test_advertised_executor_resolves_to_builder_and_request_schema(kind, spec):
    module = import_module(spec.module)
    assert callable(getattr(module, spec.builder))
    if spec.schema:
        assert issubclass(getattr(module, spec.schema), BaseModel)
    assert kind in get_args(SnapshotOpKind) or kind in get_args(MinorOpSubtype)
    assert not kind.startswith("assembly-")


def test_dependency_capability_is_derived_from_executable_registry():
    assert REPLAYABLE_SNAPSHOT_OPS == PART_SNAPSHOT_COMMANDS.keys()
    with pytest.raises(TypeError):
        PART_SNAPSHOT_COMMANDS["opaque-state"] = next(iter(PART_SNAPSHOT_COMMANDS.values()))


def test_bundle_and_nick_replay_are_independent_of_live_document():
    from backend.api import state
    from backend.api.doc_context import reset_current_doc, set_current_doc
    token = set_current_doc("registry-replay-isolation-test")
    try:
        live = Design()
        state.load_design(live)
        revision = state.revision()
        source = Design()
        bundle = replay_snapshot("bundle-create", source, {"cells": [[0, 0]], "length_bp": 32})
        before = bundle.model_dump()
        result = replay_minor("nick", bundle, {
            "helix_id": bundle.helices[0].id, "bp_index": 7, "direction": "FORWARD",
        })
        assert len(result.strands) == len(bundle.strands) + 1
        assert bundle.model_dump() == before
        assert not source.helices
        assert state.get_or_404() is live
        assert state.revision() == revision
        assert state.undo_depth() == 0
    finally:
        state.close_session()
        reset_current_doc(token)


def test_unknown_and_malformed_commands_never_restore_saved_geometry():
    source = Design()
    with pytest.raises(HTTPException) as error:
        replay_snapshot("assembly-add-instance", source, {})
    assert error.value.status_code == 400
    with pytest.raises(NotImplementedError):
        replay_minor("opaque-state", source, {"post_state": source.model_dump()})
    with pytest.raises(ValidationError):
        replay_snapshot("extrude-segment", source, {"length_bp": -1})
    assert not source.feature_log
    assert not source.helices


def test_capabilities_endpoint_does_not_claim_history_verification():
    from fastapi.testclient import TestClient
    from backend.api.main import app
    response = TestClient(app).get("/api/design/features/capabilities")
    assert response.status_code == 200
    payload = response.json()
    assert payload["scope"] == "part"
    assert payload["certifies_history"] is False
    assert set(payload["snapshot_commands"]) == set(PART_SNAPSHOT_COMMANDS)
    assert set(payload["minor_commands"]) == set(PART_MINOR_COMMANDS)
