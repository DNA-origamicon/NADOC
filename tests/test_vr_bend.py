"""VR bend poses use the same frames, geometry and feature history as desktop."""
import math
import numpy as np
import pytest
from fastapi.testclient import TestClient
from backend.api.main import app
from backend.api import state
from backend.core.models import BendParams, DeformationOp, ClusterRigidTransform
from backend.core.lattice import make_bundle_design
from backend.core.deformation import _frame_at_bp, _precompute_arm_frames


def test_bend_endpoints_and_midpoint_preserve_contour_and_frame_agreement():
    design = make_bundle_design([(0, 0)], length_bp=101)
    length = 100 * .334
    theta = math.pi / 2
    radius = length / theta
    # Rotate the whole arc; this is the controller's free-end pose.
    a = np.array([10., 20., 30.])
    b = a + np.array([0., radius, radius])
    midpoint = a + np.array([0., radius*(1-math.cos(theta/2)), radius*math.sin(theta/2)])
    op = DeformationOp(type="bend", plane_a_bp=0, plane_b_bp=100,
        params=BendParams(curvature_deg_per_bp=.9, endpoints=(a,b), midpoint=midpoint))
    bent = design.copy_with(deformations=[op])
    assert np.allclose(_frame_at_bp(bent,0)[0],a)
    assert np.allclose(_frame_at_bp(bent,100)[0],b)
    assert np.allclose(_frame_at_bp(bent,50)[0],midpoint)
    restored = type(bent).model_validate_json(bent.model_dump_json())
    assert np.allclose(_frame_at_bp(restored,50)[0],midpoint)
    spines, rotations, tangents = _precompute_arm_frames(bent, list(bent.helices),0,100)
    assert abs(np.linalg.norm(np.diff(spines,axis=0),axis=1).sum()-length)<.001
    for bp in (0,25,50,100):
        p,r,t = _frame_at_bp(bent,bp)
        assert np.allclose(p,spines[bp])
        assert np.allclose(r,rotations[bp])
        assert np.allclose(t,tangents[bp])


def test_rotated_cluster_pose_is_inverted_before_frame_propagation():
    design = make_bundle_design([(0,0)], length_bp=101)
    c = ClusterRigidTransform(helix_ids=[h.id for h in design.helices], translation=[10,20,30],
        rotation=[0,0,math.sin(math.pi/4),math.cos(math.pi/4)])
    radius=100*.334/(math.pi/2)
    op=DeformationOp(type='bend',plane_a_bp=0,plane_b_bp=100,cluster_ids=[c.id],
        params=BendParams(curvature_deg_per_bp=.9,endpoints=([10,20,30],[10,20+radius,30+radius])))
    bent=design.copy_with(cluster_transforms=[c],deformations=[op])
    assert np.allclose(_frame_at_bp(bent,0)[0],[0,0,0],atol=1e-8)
    assert np.allclose(_frame_at_bp(bent,100)[0],[radius,0,radius])


def test_bend_feature_log_undo_and_revision_guard():
    client=TestClient(app)
    design=make_bundle_design([(0,0)],length_bp=101)
    state.set_design(design)
    body=dict(type='bend',plane_a_bp=0,plane_b_bp=100,
        params=dict(curvature_deg_per_bp=.9,direction_deg=0),
        expected_design_id=design.id,expected_revision=state.revision())
    response=client.post('/api/design/deformation',json=body)
    assert response.status_code==200,response.text
    saved=state.get_or_404()
    assert saved.deformations[-1].params.curvature_deg_per_bp==.9
    assert saved.feature_log[-1].deformation_id==saved.deformations[-1].id
    assert response.json()['vr_transaction']['feature_log_entry_id']==saved.feature_log[-1].id
    assert client.post('/api/design/deformation',json=body).status_code==409
    assert client.post('/api/design/undo').status_code==200
    assert not state.get_or_404().deformations


def test_nonfinite_endpoints_rejected():
    with pytest.raises(ValueError):
        BendParams(endpoints=((0,0,0),(math.nan,0,0)))


def test_endpoint_commit_is_exact_or_refuses_without_mutating():
    client = TestClient(app)
    design = make_bundle_design([(0,0)], length_bp=101)
    state.set_design(design)
    radius = 100*.334/(math.pi/2)
    body = dict(type='bend', plane_a_bp=0, plane_b_bp=100, params=dict(
        curvature_deg_per_bp=.9, endpoints=[[10,20,30],[10+radius,20,30+radius]],
        midpoint=[10+radius*(1-math.cos(math.pi/4)),20,30+radius*math.sin(math.pi/4)]))
    response = client.post('/api/design/deformation', json=body)
    assert response.status_code == 200, response.text
    saved = state.get_or_404()
    assert np.allclose(_frame_at_bp(saved,100)[0],body['params']['endpoints'][1])
    revision = state.revision()
    # Adding the same curvature again would change reach; no misleading commit.
    response = client.post('/api/design/deformation',json=body)
    assert response.status_code == 422
    assert state.revision() == revision
    assert state.get_or_404().deformations == saved.deformations


def test_unclustered_element_uses_its_own_centroid():
    from backend.core.deformation import _arm_helices_for, deformed_nucleotide_arrays
    design = make_bundle_design([(0,0),(0,1)],length_bp=101)
    h = design.helices[1]
    a = h.axis_start.to_array()
    radius = 100*.334/(math.pi/2)
    op = DeformationOp(type='bend',plane_a_bp=0,plane_b_bp=100,affected_helix_ids=[h.id],
        params=BendParams(curvature_deg_per_bp=.9,endpoints=(a,a+np.array([radius,0,radius]))))
    bent = design.copy_with(deformations=[op])
    assert [axis.id for axis in _arm_helices_for(bent,h.id)] == [h.id]
    before = deformed_nucleotide_arrays(design.helices[0],design)
    after = deformed_nucleotide_arrays(design.helices[0],bent)
    assert np.allclose(before['positions'],after['positions'])
    selected_before = deformed_nucleotide_arrays(h,design)
    selected_after = deformed_nucleotide_arrays(h,bent)
    first = selected_before['bp_indices'] == 0
    assert np.allclose(selected_before['positions'][first],selected_after['positions'][first])


@pytest.mark.parametrize('fixed_end', [0, 1])
@pytest.mark.parametrize('degrees', [35, 90, 220])
def test_vr_plane_normals_match_desktop_committed_frames(fixed_end, degrees):
    design = make_bundle_design([(0, 0)], length_bp=101)
    angle = math.radians(degrees)
    radius = 100*.334/angle
    tangent = np.array([0., 0., 1.])
    direction = np.array([math.cos(.7), math.sin(.7), 0.])
    anchor = _frame_at_bp(design, fixed_end*100)[0]
    def raw(t):
        return radius*(tangent*math.sin(angle*t)+direction*(1-math.cos(angle*t)))
    def point(t):
        return anchor+raw(t) if fixed_end == 0 else anchor-raw(1-t)
    op = DeformationOp(type='bend', plane_a_bp=0, plane_b_bp=100,
        params=BendParams(curvature_deg_per_bp=degrees/100, direction_deg=math.degrees(.7),
            endpoints=(point(0), point(1)), midpoint=point(.5)))
    bent = design.copy_with(deformations=[op])
    for bp in (0, 25, 50, 75, 100):
        position, _, normal = _frame_at_bp(bent, bp)
        phase = angle*(bp/100 if fixed_end == 0 else 1-bp/100)
        assert np.allclose(position, point(bp/100), atol=1e-7)
        assert np.allclose(normal, tangent*math.cos(phase)+direction*math.sin(phase), atol=1e-7)
    assert np.allclose(_frame_at_bp(bent, fixed_end*100)[2], tangent)
