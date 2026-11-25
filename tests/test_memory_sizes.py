"""Cache charges retain conservative ownership while scalar leaves stay cheap."""

from dataclasses import dataclass
import sys

import numpy as np

from backend.core.memory_sizes import retained_bytes


def test_scalar_containers_and_dataclasses_charge_every_shared_leaf():
    @dataclass(slots=True)
    class Record:
        label: str
        coordinates: tuple

    xyz = (1., 2., 3.)
    label = 'shared atom label'
    row = Record(label, xyz)
    scalar_leaves = [label, b'bytes', 10**100, -1.5, True, None]
    assert retained_bytes(scalar_leaves) == sys.getsizeof(scalar_leaves) + sum(map(sys.getsizeof, scalar_leaves))
    row_size = sys.getsizeof(row) + sys.getsizeof(label) + sys.getsizeof(xyz) + sum(map(sys.getsizeof, xyz))
    data = {'first': row, 'second': row}
    assert retained_bytes(data) == sys.getsizeof(data) + sum(map(sys.getsizeof, data)) + 2*row_size


def test_scalar_subclasses_keep_array_payload_and_depth_bound():
    class ArrayLeaf(float):
        dtype = np.dtype(object)
        nbytes = 10000
        flat = ['owned payload', None]

    row = ArrayLeaf(1.)
    assert retained_bytes(row) == 10128 + sum(map(sys.getsizeof, row.flat))
    assert retained_bytes([row], depth=9) == sys.getsizeof([row])
    array = np.array([['a', None]], dtype=object)
    assert retained_bytes(array) == max(sys.getsizeof(array), array.nbytes+128) + sum(map(sys.getsizeof, array.flat))
