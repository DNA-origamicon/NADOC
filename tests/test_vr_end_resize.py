import numpy as np
import pytest
from fastapi import HTTPException
from backend.api.routes_vr import VREndResizeHandles, _end_resize_record, _parse_end_resize


def test_resize_handles_use_launch_view_rotation():
    body = VREndResizeHandles(version=7, minimum=-5, maximum=20,
        handles=[dict(position=[1, 2, 3], direction=[0, 0, -1])])
    rotation = [[0, 0, 1], [0, 1, 0], [-1, 0, 0]]
    lines = _end_resize_record(body, rotation).splitlines()
    assert lines[0] == 'NADOC_END_RESIZE_1 7 -5 20 1'
    assert list(map(float, lines[1].split())) == [3, 2, -1, -1, 0, 0, 0, 0, 0]


def test_invalid_handle_and_release_rejected():
    body = VREndResizeHandles(version=1, minimum=0, maximum=1,
        handles=[dict(position=[0, 0, 0], direction=[0, 0, 0])])
    with pytest.raises(HTTPException):
        _end_resize_record(body, np.eye(3))
    assert _parse_end_resize(dict(sequence=1, version=7, delta=-5)) == dict(sequence=1, version=7, delta=-5)
    for value in [None, {}, dict(sequence=True, version=1, delta=5), dict(sequence=1, version=1, delta=201)]:
        assert _parse_end_resize(value) is None
