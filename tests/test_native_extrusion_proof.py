"""Extrusions replay with document-independent identities and native hints."""

import pytest

from backend.api import crud, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.part_history_verification import verify_current_part


@pytest.fixture(autouse=True)
def document():
    token = set_current_doc("native-extrusion-proof-test")
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[0, 0]], length_bp=42))
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


@pytest.mark.parametrize("separate", [False, True])
@pytest.mark.parametrize("kind", ["segment", "circle", "continuation", "deformed"])
def test_native_extrusions_replay_and_regenerate(kind, separate):
    common = dict(cells=[[4, 4]], separate_fresh_extrusions=separate)
    if kind == "circle":
        crud.add_circle_segment(crud.CircleSegmentRequest(**common, cell_lengths=[21]))
    elif kind == "segment":
        crud.add_bundle_segment(crud.BundleSegmentRequest(**common, length_bp=21))
    elif kind == "continuation":
        crud.add_bundle_continuation(
            crud.BundleContinuationRequest(**common, length_bp=21)
        )
    else:
        crud.add_bundle_deformed_continuation(
            crud.BundleDeformedContinuationRequest(
                **common,
                length_bp=21,
                grid_origin=[0, 0, 0],
                axis_dir=[0, 0, 1],
                frame_right=[1, 0, 0],
                frame_up=[0, 1, 0],
            )
        )
    current = state.get_or_404()
    ids = [c.id for c in current.cluster_transforms]
    # Prove independently of all cached geometry and saved result payloads.
    current.feature_log[1].design_snapshot_gz_b64 = "poison"
    current.feature_log[1].post_state_gz_b64 = "poison"
    result = verify_current_part()
    assert result["status"] == "verified", result
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert [c.id for c in state.get_or_404().cluster_transforms] == ids
    result = verify_current_part()
    assert result["status"] == "verified", result


@pytest.mark.parametrize("extend", [False, True])
def test_continuation_ligates_deterministically(extend):
    from backend.core.constants import BDNA_RISE_PER_BP

    crud.add_bundle_continuation(
        crud.BundleContinuationRequest(
            cells=[[0, 0]],
            length_bp=21,
            offset_nm=42 * BDNA_RISE_PER_BP,
            extend_inplace=extend,
        )
    )
    result = verify_current_part()
    assert result["status"] == "verified", result


@pytest.mark.parametrize("existing_frame", [False, True])
@pytest.mark.parametrize("separate", [False, True])
def test_frame_extrusion_identity(existing_frame, separate):
    from backend.api.routes_frame_extrusion import (
        FrameExtrusionRequest,
        commit_frame_extrusion,
    )

    design = state.get_or_404()
    commit_frame_extrusion(
        FrameExtrusionRequest(
            expected_design_id=design.id,
            expected_revision=state.revision(),
            source_frame_id=design.lattice_frames[0].id if existing_frame else None,
            cells=[[4, 4]],
            length_bp=21,
            plane="XY",
            separate_fresh_extrusions=separate,
        )
    )
    result = verify_current_part()
    assert result["status"] == "verified", result
    ids = [h.id for h in state.get_or_404().helices]
    crud.edit_feature(1, crud.EditFeatureBody(params={"length_bp": 28}))
    assert ids == [h.id for h in state.get_or_404().helices]
    result = verify_current_part()
    assert result["status"] == "verified", result
