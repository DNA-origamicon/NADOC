"""Native overlay inputs survive capture, reload and downstream regeneration."""

import pytest
from backend.api import crud, state
from backend.api.doc_context import set_current_doc, reset_current_doc
from backend.api.part_history_verification import verify_current_part
from backend.api.routes_clusters import (
    AddClusterBody,
    PatchClusterBody,
    add_cluster,
    update_cluster,
)
from backend.api.routes_deformation import AddDeformationBody, add_deformation


@pytest.fixture(autouse=True)
def document():
    token = set_current_doc("native-overlay-proof-test")
    try:
        crud.create_bundle(crud.BundleRequest(cells=[[0, 0], [0, 1]], length_bp=42))
        yield
    finally:
        state.close_session()
        reset_current_doc(token)


def verified():
    result = verify_current_part()
    assert result["status"] == "verified", result


def test_group_authored_edit_and_pose_preview_each_rebuild_from_inputs():
    hid = state.get_or_404().helices[0].id
    add_cluster(AddClusterBody(name="Arm", helix_ids=[hid], log=True))
    cid = state.get_or_404().cluster_transforms[-1].id
    verified()
    update_cluster(
        cid,
        PatchClusterBody(
            name="Moved", color="#123456", opacity=0.5
        ),
    )
    update_cluster(cid, PatchClusterBody(translation=[1, 2, 3]))
    update_cluster(cid, PatchClusterBody(commit=True))
    verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    verified()
    crud.edit_feature(3, crud.EditFeatureBody(params={"translation": [4, 5, 6]}))
    assert state.get_or_404().cluster_transforms[-1].translation == [4, 5, 6]
    verified()
    assert crud.delete_feature(1)["needs_cascade_decision"]
    crud.delete_feature(1, cascade=True)
    verified()


@pytest.mark.parametrize(
    "kind,params", [("twist", {"total_angle_deg": 15}), ("bend", {"radius_nm": 100})]
)
def test_deformation_edit_regenerates_downstream_extrusion(kind, params):
    d = state.get_or_404()
    add_deformation(
        AddDeformationBody(
            type=kind,
            plane_a_bp=0,
            plane_b_bp=35,
            affected_helix_ids=[h.id for h in d.helices],
            params=params,
        )
    )
    verified()
    crud.add_bundle_deformed_continuation(
        crud.BundleDeformedContinuationRequest(
            cells=[[4, 4]],
            length_bp=21,
            grid_origin=[0, 0, 0],
            axis_dir=[0, 0, 1],
            frame_right=[1, 0, 0],
            frame_up=[0, 1, 0],
            source_bp=35,
            ref_helix_id=d.helices[0].id,
        )
    )
    verified()
    crud.edit_feature(1, crud.EditFeatureBody(params={"plane_b_bp": 30}))
    assert state.get_or_404().deformations[0].plane_b_bp == 30
    verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    verified()


def test_native_cluster_paste_rebuilds_copied_identities():
    from backend.api.routes_clusters import ClusterPasteBody, cluster_paste

    cid = state.get_or_404().cluster_transforms[0].id
    cluster_paste(ClusterPasteBody(cluster_ids=[cid], delta_row=4, delta_col=4))
    identities = [s.id for s in state.get_or_404().strands]
    verified()
    crud.edit_feature(0, crud.EditFeatureBody(params={"length_bp": 48}))
    assert identities == [s.id for s in state.get_or_404().strands]
    verified()
