"""Axis sticks must follow saved residue moves and reset with them."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation
from backend.core.models import NucleotideTransform
from backend.core.deformation import deformed_helix_axes
from backend.core.design_geometry import _straight_helix_axes
from tests.conftest import make_minimal_design


def test_partial_scaffold_rotation_splits_axis_and_preserves_unmoved_part():
    d = make_minimal_design(helix_length_bp=12, with_staple=False)
    before = deformed_helix_axes(d)[0]['segments'][0]
    q = Rotation.from_euler('x', 70, degrees=True)
    d.nucleotide_transforms = [NucleotideTransform(kind='base', helix_id='h0', bp_index=bp,
        direction='FORWARD', pivot=[0, 1, 2], translation=[3, 4, 5], rotation=q.as_quat().tolist())
        for bp in range(6)]
    axis = deformed_helix_axes(d)[0]
    moved, unchanged = axis['segments']
    assert [(s['bp_lo'], s['bp_hi']) for s in axis['segments']] == [(0, 5), (6, 11)]
    midpoint = (np.array(before['start']) + before['end']) / 2
    expected = q.apply(np.array([before['start'], midpoint]) - [0, 1, 2]) + [0, 1, 2] + [3, 4, 5]
    np.testing.assert_allclose([moved['start'], moved['end']], expected)
    np.testing.assert_allclose(unchanged['start'], midpoint)
    np.testing.assert_allclose(unchanged['end'], before['end'])
    assert _straight_helix_axes(d) == [axis]
    assert deformed_helix_axes(type(d).from_json(d.to_json())) == [axis]


def test_single_base_pose_does_not_drag_paired_axis():
    d = make_minimal_design(with_staple=True)
    before = deformed_helix_axes(d)
    d.nucleotide_transforms = [NucleotideTransform(kind='base', helix_id='h0', bp_index=5,
        direction='FORWARD', translation=[0, 30, 0], pivot=[0, 0, 0], rotation=[0, 0, 0, 1])]
    assert deformed_helix_axes(d) == before


@pytest.mark.parametrize('batch', [False, True])
def test_edit_and_reset_responses_include_axes(batch):
    from backend.api import state
    from backend.api.doc_context import set_current_doc, reset_current_doc
    from backend.api.routes_nucleotide_transforms import (
        NucleotideTransformBody, NucleotideTransformBatchBody,
        put_nucleotide_transform, put_nucleotide_transforms, delete_nucleotide_transform)
    token = set_current_doc('residue-axis-test')
    try:
        state.set_design(make_minimal_design(with_staple=False))
        body = NucleotideTransformBody(kind='base', helix_id='h0', bp_index=5,
            direction='FORWARD', translation=[0, 30, 0], pivot=[0, 0, 0], rotation=[0, 0, 0, 1])
        response = (put_nucleotide_transforms(NucleotideTransformBatchBody(transforms=[body]))
                    if batch else put_nucleotide_transform(body))
        assert response['partial_geometry']
        assert response['helix_axes'][0]['residue_transformed']
        identity = state.get_or_404().nucleotide_transforms[0].id
        reset = delete_nucleotide_transform(identity)
        assert 'residue_transformed' not in reset['helix_axes'][0]
        assert len(reset['helix_axes'][0]['segments']) == 1
    finally:
        state.close_session()
        reset_current_doc(token)
