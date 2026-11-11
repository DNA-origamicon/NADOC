"""Numerical selection and fail-closed patching contracts for the isolated pilot."""
import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from experiments.oxdna_submodel.build_md import replace_once
from experiments.oxdna_submodel.production import inside_box, duplex_box


def test_rotated_box_membership_uses_center_and_inverse_orientation():
    box={'min_corner':[9,19,29],'max_corner':[11,21,31],
         'rotation':Rotation.from_euler('z',45,degrees=True).as_quat()}
    # World x=1.2 offset is inside the rotated square but outside the unrotated one.
    points=np.array([[11.2,20,30],[11,21,30],[10,20,31.01]])
    assert inside_box(points,box).tolist()==[True,False,False]


def test_fit_selects_only_requested_index_band_after_tilt():
    bp=np.repeat(np.arange(42),2)
    points=np.column_stack([np.tile([-1.,1.],42),np.zeros(84),bp*.34])
    points=points@Rotation.from_euler('y',8,degrees=True).as_matrix().T
    selection=duplex_box(points,bp).model_dump(mode='json')['box']
    np.testing.assert_array_equal(inside_box(points,selection),(bp>=14)&(bp<=27))


def test_fit_refuses_nonseparable_selection():
    bp=np.repeat(np.arange(42),2)
    with pytest.raises(ValueError,match='cannot be separated'):
        duplex_box(np.zeros((84,3)),bp)


def test_patch_refuses_upstream_drift_or_multiple_matches():
    assert replace_once('a needle b','needle','mask')=='a mask b'
    for text in ('missing','needle needle'):
        with pytest.raises(ValueError,match='changed'):
            replace_once(text,'needle','mask')
