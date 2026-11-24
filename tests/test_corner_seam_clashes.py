import numpy as np

from backend.core.atomistic_validation import _find_clashes
from backend.core.corner_seam_clashes import find_clashes


def test_corner_clash_query_retains_native_order_exclusions_and_report_cap():
    rng = np.random.default_rng(987)
    points = rng.normal(size=(800, 3)) * .1
    points[2] = [np.nan, 0, 0]
    points[7] = [np.inf, 0, 0]
    points[20:24] = [[0, 0, 0], [.08, 0, 0],
                     [np.nextafter(.08, 0), 0, 0], [np.nextafter(.08, 1), 0, 0]]
    finite = np.isfinite(points).all(axis=1)
    bonds = [(i, i+1) for i in range(0, 700, 2)] + [(i, i+2) for i in range(0, 700, 2)]
    for cap in (1, 20, 200, 20000):
        assert find_clashes(points, finite, bonds, .08, cap) == _find_clashes(points, finite, bonds, .08, cap)
    assert find_clashes(points, np.zeros(len(points), dtype=bool), bonds, .08, 200) == []
