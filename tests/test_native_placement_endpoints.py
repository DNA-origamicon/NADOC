"""No auxiliary API may serialize provisional construction beads."""
import numpy as np
import pytest
from fastapi.testclient import TestClient

from backend.api import state
from backend.api.main import app
from backend.api.routes import _demo_design
from backend.core.design_geometry import _geometry_for_design
from backend.core.models import BendParams, DeformationOp, NucleotideTransform
from backend.core.native_slab_placement import authoritative_slab_pose
from tests.conftest import make_minimal_design

pytestmark = pytest.mark.native_placement


def test_demo_and_per_helix_routes_share_full_authority(native_placement_evidence):
    client = TestClient(app)
    demo = client.get('/api/design/demo/geometry')
    assert demo.status_code == 200, demo.text
    assert demo.json() == _geometry_for_design(_demo_design())
    design = make_minimal_design().copy_with(deformations=[DeformationOp(
        type='bend', plane_a_bp=5, plane_b_bp=35,
        params=BendParams(curvature_deg_per_bp=3.1, direction_deg=37))])
    state.set_design(design)
    response = client.get('/api/design/helices/h0')
    assert response.status_code == 200, response.text
    expected = _geometry_for_design(design)
    native_placement_evidence(expected=expected, actual=response.json()['geometry'])
    assert response.json()['geometry'] == expected
    for record in expected:
        assert authoritative_slab_pose(record) is not None


@pytest.mark.parametrize('populate', [False, True])
def test_added_lattice_helix_serializes_only_real_canonical_nucleotides(populate):
    state.set_design(make_minimal_design())
    client = TestClient(app)
    response = client.post('/api/design/helix-at-cell', json={
        'row': 3, 'col': 4, 'length_bp': 42, 'populate_strands': populate})
    assert response.status_code == 201, response.text
    records = response.json()['nucleotides']
    expected = _geometry_for_design(state.get_or_404())
    if not populate:
        assert records == []
    else:
        assert len(records) == 84
        for record in records:
            assert record in expected
            assert authoritative_slab_pose(record) is not None


@pytest.mark.parametrize('posed', [False, True])
def test_overhang_joint_frame_uses_exact_final_native_residue(posed):
    from tests.test_subdomain_rotation import _fresh_design_with_overhang

    design, oh_id, sd_id = _fresh_design_with_overhang(length_bp=8)
    oh = next(o for o in design.overhangs if o.id == oh_id)
    strand = next(s for s in design.strands if s.id == oh.strand_id)
    di, domain = next((i, d) for i, d in enumerate(strand.domains) if d.overhang_id == oh_id)
    junction = domain.end_bp if di == 0 else domain.start_bp
    if posed:
        design = design.copy_with(nucleotide_transforms=[NucleotideTransform(
            kind='base', helix_id=oh.helix_id, bp_index=junction,
            direction=domain.direction, copy_k=0, pivot=[0, 0, 0],
            translation=[1.25, -2.5, 3.75], rotation=[0, 0, 0, 1])])
        state.set_design(design)
    expected = next(n for n in _geometry_for_design(design)
                    if n['helix_id'] == oh.helix_id and n['bp_index'] == junction
                    and n['direction'] == domain.direction.value and n['copy_k'] == 0)
    response = TestClient(app).get(f'/api/design/overhang/{oh_id}/sub-domains/{sd_id}/frame')
    assert response.status_code == 200, response.text
    np.testing.assert_array_equal(response.json()['pivot'], expected['backbone_position'])
    np.testing.assert_allclose(response.json()['parent_axis'], expected['axis_tangent'], rtol=0, atol=1e-15)
