"""Retained empty frame owners must not broaden a newly authored selection."""

import pytest
from fastapi import HTTPException

from backend.api import routes_deformation, state
from backend.api.doc_context import reset_current_doc, set_current_doc
from backend.core.models import ClusterRigidTransform
from tests.test_part_deformation_preview import native_source


@pytest.fixture
def document():
    token = set_current_doc("empty-group-deformation-guard")
    source = native_source()
    source = source.copy_with(feature_log=source.feature_log[:-1], deformations=[],
        cluster_transforms=[*source.cluster_transforms, ClusterRigidTransform(id="empty-owner", helix_ids=[])])
    state.set_design(source)
    try:
        yield source
    finally:
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize("kind,params", [("bend", {"radius_nm": 100}), ("twist", {"total_degrees": 15})])
@pytest.mark.parametrize("preview", [False, True])
@pytest.mark.parametrize("selection", [["empty-owner"], ["missing-owner"]])
def test_empty_or_missing_group_refuses_before_canonical_preview_or_commit(document, kind, params, preview, selection):
    session = state._session()
    revision = session.revision
    history, redo = list(session.history), list(session.redo)
    original = document.model_dump_json()
    with pytest.raises(HTTPException) as caught:
        routes_deformation.add_deformation(routes_deformation.AddDeformationBody(
            type=kind, plane_a_bp=0, plane_b_bp=35, cluster_ids=selection,
            params=params, preview=preview))
    assert caught.value.status_code == 409
    assert caught.value.detail["code"] == "invalid_selection"
    assert state.get_or_404() is document and session.revision == revision
    assert list(session.history) == history and list(session.redo) == redo
    assert document.model_dump_json() == original
