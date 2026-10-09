"""Batched placement must retain scalar authority and corruption diagnostics."""
from copy import deepcopy

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from backend.core.design_geometry import _geometry_for_design
from backend.core.models import BendParams, DeformationOp, TwistParams
from backend.core.native_full_placement import NativePlacementError
from backend.core.native_slab_placement import (
    _expected_slab_pose, attach_native_slab_poses,
    authoritative_slab_pose, authoritative_slab_poses,
)
from tests.conftest import make_minimal_design


@pytest.mark.parametrize('kind', ['straight', 'bend', 'twist'])
def test_batch_matches_scalar_authority_for_both_directions_and_mixed_sources(kind):
    design = make_minimal_design()
    if kind != 'straight':
        design = design.copy_with(deformations=[DeformationOp(type=kind,
            plane_a_bp=5, plane_b_bp=35,
            params=BendParams(curvature_deg_per_bp=2, direction_deg=37) if kind == 'bend'
            else TwistParams(total_degrees=127))])
    records = _geometry_for_design(design)
    records[0]['placement_source'] = 'authored-residue-c1-v1'
    records[1].update(placement_source='native-full-extension-v1',
                      extension_id='extension', is_modification=False)
    expected = [_expected_slab_pose(record) for record in records]
    attach_native_slab_poses(records)
    actual = authoritative_slab_poses(records)
    for record, pose, reference in zip(records, actual, expected, strict=True):
        scalar = authoritative_slab_pose(record)
        if reference is None:
            assert pose is None and scalar is None
        else:
            np.testing.assert_allclose(pose[0], reference[0], rtol=0, atol=2e-14)
            np.testing.assert_allclose(pose[1], reference[1], rtol=0, atol=2e-14)
            np.testing.assert_array_equal(pose[0], scalar[0])
            np.testing.assert_array_equal(pose[1], scalar[1])
            np.testing.assert_allclose(Rotation.from_quat(record['slab_quaternion']).as_matrix(),
                                       reference[1], rtol=0, atol=2e-14)


@pytest.mark.parametrize('field,value', [
    ('base_position', None), ('base_position', [100, 0, 0]),
    ('base_position', [float('nan'), 0, 0]), ('backbone_position', ['bad', 0, 0]),
    ('base_normal', [0, 0, 0]), ('axis_tangent', [0, 0, 0]),
    ('direction', 'unknown'), ('placement_source', 'legacy'),
    ('slab_position', None), ('slab_position', [100, 0, 0]),
    ('slab_quaternion', [0, 0, 0, 0]), ('slab_quaternion', [1, 0, 0, 0]),
    ('slab_quaternion', [0, 0, float('inf'), 1]),
])
def test_batch_rejects_corruption_with_same_site_diagnostic(field, value):
    records = deepcopy(_geometry_for_design(make_minimal_design()))
    records[len(records)//2][field] = value
    with pytest.raises(NativePlacementError) as scalar:
        [authoritative_slab_pose(record) for record in records]
    with pytest.raises(NativePlacementError) as batch:
        authoritative_slab_poses(records)
    assert str(batch.value) == str(scalar.value)
    assert batch.value.details == scalar.value.details


def test_empty_batch():
    assert authoritative_slab_poses([]) == []
    assert attach_native_slab_poses([]) == []
