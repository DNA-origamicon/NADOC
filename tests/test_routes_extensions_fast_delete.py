"""Recorded deletes retain synthetic-only display updates and skip reconciliation."""

import pytest

from backend.api import crud, routes_extensions as routes, state
from tests.test_part_extension_history import add, recipe
from tests.test_part_transform_preview_sessions import document  # noqa: F401


@pytest.mark.parametrize("batch", [False, True])
def test_recorded_delete_skips_topology_and_real_geometry(document, monkeypatch, batch):  # noqa: F811
    source = recipe()
    state.load_design(source)
    identity = add(source)["extension"]["id"]
    before = state.get_or_404().model_copy(deep=True)
    depth = state.undo_depth()
    monkeypatch.setattr(
        state,
        "reconcile_cluster_membership",
        lambda *_: pytest.fail("Extension deletion reconciled topology"),
    )
    monkeypatch.setattr(
        state,
        "_retry_pending_ligations",
        lambda *_: pytest.fail("Extension deletion retried ligations"),
    )
    monkeypatch.setattr(
        crud,
        "_geometry_for_helices",
        lambda *_a, **_k: pytest.fail("Extension deletion rebuilt real helix geometry"),
    )
    response = (
        routes.delete_strand_extensions_batch(
            routes.StrandExtensionBatchDeleteRequest(ext_ids=[identity, identity])
        )
        if batch
        else routes.delete_strand_extension(identity)
    )
    assert response["partial_geometry"] is True
    assert response["changed_helix_ids"] == [f"__ext_{identity}"]
    assert response["nucleotides"] == []
    current = state.get_or_404()
    assert not current.extensions
    assert (
        current.strands == before.strands
        and current.cluster_transforms == before.cluster_transforms
    )
    assert current.feature_log[-1].op_kind == "extension-delete"
    assert state.undo_depth() == depth + 1
