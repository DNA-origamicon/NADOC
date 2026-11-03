"""An early extrusion edit reruns automatic routing over the resized part."""

from uuid import uuid4

import pytest

from backend.api import doc_context, state
from backend.core.models import Design
from backend.api.part_proof_commands import execute
from backend.core.part_history_proof import root_design
from tests.test_part_extrusion_edit_routes import guards, install
from tests.test_group_organization_history import _verified


@pytest.fixture
def document():
    identity = f"__extrusion_auto_routing__{uuid4()}"
    token = doc_context.set_current_doc(identity)
    try:
        yield
    finally:
        state.drop_doc(identity)
        doc_context.reset_current_doc(token)


@pytest.mark.parametrize("routing", ["auto-scaffold-seamless", "auto-scaffold-seamed"])
def test_resize_routed_six_helix_bundle(document, routing):
    from backend.core.part_history_contract import create_empty_part

    session, client = install(create_empty_part("Routing resize", "HONEYCOMB"))
    response = client.post("/api/design/bundle", json={
        "cells": [[0, 0], [0, 1], [1, 0], [1, 1], [2, 0], [2, 1]],
        "length_bp": 84, "name": "Routing resize"})
    assert response.status_code == 201, response.text
    for route in (routing, "full-autostaple"):
        response = client.post(f"/api/design/{route}", json={})
        assert response.status_code == 200, response.text
    original = session.design
    rows = [(row.id, row.op_kind, row.params) for row in original.feature_log]
    assert [kind for _, kind, _ in rows] == [
        "bundle-create", routing, "full-autostaple"]
    for length in (126, 63):
        before = session.design
        response = client.post("/api/design/features/0/edit", json={
            "params": {"length_bp": length}, **guards(session, 0)})
        assert response.status_code == 200, response.text
        updated = session.design
        # Seamless routing adjusts helix ends. Compare with fresh construction
        # at the requested length, rather than assuming blunt routed ends.
        fresh = root_design(original.recipe_root, input_sources=original.input_sources)
        for _, kind, params in rows:
            fresh = execute(kind, fresh, {**params, "length_bp": length}
                            if kind == "bundle-create" else params)
        for field in ("helices", "strands", "crossovers", "forced_ligations"):
            assert getattr(updated, field) == getattr(fresh, field)
        assert updated.strands != before.strands
        assert updated.scaffolds()
        assert updated.staples()
        assert [(row.id, row.op_kind, row.params) for row in updated.feature_log[1:]] == rows[1:]
        _verified(Design.model_validate_json(updated.model_dump_json()))
        state.undo()
        assert session.design == before
        state.redo()
        assert session.design == updated
    # Invalid edits leave both the routed result and the undo stack intact.
    from tests.test_part_pattern_recording import saved, unchanged
    before = saved(session)
    response = client.post("/api/design/features/0/edit", json={
        "params": {"length_bp": 0}, **guards(session, 0)})
    assert response.status_code == 422, response.text
    unchanged(session, before)
