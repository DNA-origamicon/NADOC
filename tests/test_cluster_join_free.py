"""Free movement: wide faces, exact poses, routing, exports and atomic history."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from fastapi.testclient import TestClient

from backend.api import state
from backend.core.cluster_join import propose_cluster_join
from backend.core.cluster_join_free import FreeClusterJoinRequest, propose_free_cluster_join
from tests.test_cluster_join_api import make_join_design, assert_geometry_equal, assert_original_bases_preserved, assert_exported_join
from tests.test_cluster_join_core import request, edges, paths, key


@pytest.fixture(scope="module")
def wide_join():
    design = make_join_design(2, n_helices=12)
    _, aligned = propose_cluster_join(design, request(design, kinds=("side", "end"), gap=2))
    delta = np.array(aligned["donor_world_delta"]).reshape(4, 4, order="F")
    body = dict(mode="free", moving_cluster_id="join_cluster_1", world_translation=delta[:3, 3].tolist(),
                world_rotation=Rotation.from_matrix(delta[:3, :3]).as_quat().tolist(), reach_nm=6,
                expected_design_id=design.id, expected_revision=1)
    return design, body


def test_wide_end_to_side_finds_multiple_jointly_valid_connections(wide_join, tmp_path):
    design, body = wide_join
    snapshot = design.model_dump_json()
    after, report = propose_free_cluster_join(design, body)
    assert report["connection_count"] >= 3
    assert len(report["bridges"]) == report["connection_count"] * 2
    assert len({c["fixed"] for c in report["connections"]}) == report["connection_count"]
    assert len({c["moving"] for c in report["connections"]}) == report["connection_count"]
    assert report["minimum_backbone_clearance_nm"] >= .65
    assert report["minimum_connector_clearance_nm"] >= .30
    assert design.model_dump_json() == snapshot
    assert_original_bases_preserved(design, after, report["added_connector_nt"])
    assert_exported_join(design, after, report["added_connector_nt"], tmp_path)
    assert len(paths(after)) == len(paths(design)) - 1
    assert after.cluster_transforms[0] == design.cluster_transforms[0]
    expected_rotation = Rotation.from_quat(body["world_rotation"]) * Rotation.from_quat(design.cluster_transforms[1].rotation)
    np.testing.assert_allclose(Rotation.from_quat(after.cluster_transforms[1].rotation).as_matrix(), expected_rotation.as_matrix(), atol=1e-10)
    # Every original edge remains, except exactly the edges exchanged at ports.
    removed = edges(design) - edges(after)
    assert len(removed) == 2 * report["connection_count"]
    assert all(key(b["from"])[0] in {h.id for h in design.helices} for b in report["bridges"])
    assert [s for s in after.strands if not s.is_scaffold] == [s for s in design.strands if not s.is_scaffold]


def test_movement_changes_connection_count_and_never_snaps(wide_join):
    design, body = wide_join
    _, near = propose_free_cluster_join(design, body)
    moved = {**body, "world_translation": [body["world_translation"][0]+100, *body["world_translation"][1:]]}
    with pytest.raises(ValueError, match="No compatible connections"):
        propose_free_cluster_join(design, moved)
    narrower = {**body, "reach_nm": 3}
    _, small = propose_free_cluster_join(design, narrower)
    assert small["connection_count"] < near["connection_count"]
    assert small["donor_world_delta"] == near["donor_world_delta"]


def test_pose_schema_rejects_nonrigid_or_nonfinite_input(wide_join):
    _, body = wide_join
    for invalid in ({"world_rotation": [0, 0, 0, 0]}, {"world_translation": [float('nan'), 0, 0]}, {"reach_nm": 0}):
        with pytest.raises(ValueError):
            FreeClusterJoinRequest.model_validate({**body, **invalid})


def test_batch_apply_token_history_and_stale_rejection(wide_join, monkeypatch):
    from backend.api.main import app
    monkeypatch.setattr(state, '_sessions', {})
    design, original = wide_join
    state.set_design(design.model_copy(deep=True))
    # Native poses are asserted from state below; response geometry is unused.
    client = TestClient(app, headers={"X-NADOC-Skip-Geometry": "1"})
    body = {**original, "expected_revision": state.revision()}
    before = state.get_or_404().model_copy(deep=True)
    response = client.post('/api/design/cluster-join/preview', json=body)
    assert response.status_code == 200, response.text
    preview = response.json(); assert preview['valid'], preview
    apply = {**body, 'preview_token': preview['preview_token']}
    wrong_pose = {**apply, 'reach_nm': 4}
    assert client.post('/api/design/cluster-join/apply', json=wrong_pose).status_code == 409
    assert_geometry_equal(state.get_or_404(), before)
    response = client.post('/api/design/cluster-join/apply', json=apply)
    assert response.status_code == 200, response.text
    after = state.get_or_404().model_copy(deep=True)
    assert after.feature_log[-1].op_kind == 'cluster-join'
    assert response.json()['join']['connection_count'] == preview['connection_count']
    assert client.post('/api/design/cluster-join/apply', json=apply).status_code == 409
    assert client.post('/api/design/undo').status_code == 200
    assert_geometry_equal(state.get_or_404(), before)
    assert client.post('/api/design/redo').status_code == 200
    assert_geometry_equal(state.get_or_404(), after)
