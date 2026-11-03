"""Matrix conversion preserves scalar bits, ownership, ordering and validation."""
import warnings

import numpy as np
import pytest
from pydantic import field_validator

from backend.core.models import Mat4x4


def legacy(cls, arr):
    return cls(values=[float(v) for v in arr.flatten()])


@pytest.mark.parametrize('kind', ['c', 'fortran', 'transpose', 'strided', 'reverse', 'readonly', 'special'])
def test_float64_conversion_matches_original_bits_and_owns_values(kind):
    array = (np.arange(16, dtype=float) / 7).reshape(4, 4)
    if kind == 'fortran':
        array = np.asfortranarray(array)
    elif kind == 'transpose':
        array = array.T
    elif kind == 'strided':
        array = np.arange(64, dtype=float).reshape(8, 8)[::2, ::2]
    elif kind == 'reverse':
        array = array[::-1, ::-1]
    elif kind == 'readonly':
        array.flags.writeable = False
    elif kind == 'special':
        array.flat[:5] = [-0., np.nan, np.inf, -np.inf, np.nextafter(0., 1.)]
    before = array.tobytes()
    expected = legacy(Mat4x4, array)
    result = Mat4x4.from_array(array)
    assert result.to_array().tobytes() == expected.to_array().tobytes()
    assert all(type(v) is float for v in result.values)
    assert array.tobytes() == before
    result.values[0] = 777.
    assert array.tobytes() == before
    if array.flags.writeable:
        array.flat[1] = 999.
        assert result.values[1] != 999.


@pytest.mark.parametrize('dtype', [np.float16, np.float32, np.int64, np.uint64, bool, object, '>f8'])
def test_other_dtypes_keep_legacy_coercion(dtype):
    array = np.arange(16).reshape(4, 4).astype(dtype)
    assert Mat4x4.from_array(array).model_dump() == legacy(Mat4x4, array).model_dump()


def test_masked_subclass_keeps_legacy_behavior():
    array = np.ma.array(np.eye(4), mask=np.eye(4, dtype=bool))
    with warnings.catch_warnings():
        warnings.simplefilter('ignore', UserWarning)
        assert Mat4x4.from_array(array).to_array().tobytes() == legacy(Mat4x4, array).to_array().tobytes()


def test_invalid_object_values_still_rejected():
    with pytest.raises(ValueError):
        Mat4x4.from_array(np.array([['not a number']], dtype=object))


def test_subclass_validation_is_not_bypassed():
    class CheckedMatrix(Mat4x4):
        @field_validator('values')
        @classmethod
        def reject_negative(cls, values):
            if any(v < 0 for v in values):
                raise ValueError('negative values rejected')
            return values
    result = CheckedMatrix.from_array(np.eye(4))
    assert type(result) is CheckedMatrix
    with pytest.raises(ValueError, match='negative values rejected'):
        CheckedMatrix.from_array(-np.eye(4))
