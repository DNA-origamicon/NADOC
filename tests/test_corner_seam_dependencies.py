"""A fit may survive distant edits only with an exact trajectory certificate."""
from types import SimpleNamespace
import numpy as np
from scipy.spatial import cKDTree

from backend.core.corner_seam_cache import clear_fit_cache, export_fits, import_fits
from backend.core.corner_seam_dependencies import find_dependency, remember_dependency


def problem(points):
    return SimpleNamespace(original=np.arange(18.).reshape(6, 3),
        bridges=np.array([[0, 1, 2, 3, 4]]), free=np.array([1, 2, 3]),
        pairs=np.array([[0, 5]]), branches=[(2, 5)], bodies=[np.array([2, 3, 4, 5])],
        environment=cKDTree(np.asarray(points, dtype=float).reshape(-1, 3)),
        query_bounds=np.array([[0., 0., 0.], [1., 1., 1.]]))


def test_distant_removal_reuses_but_near_removal_addition_motion_or_order_invalidates():
    clear_fit_cache()
    source = problem([[.1, .1, .1], [100, 100, 100], [.2, .2, .2]])
    remember_dependency(source, 400, source.original, {'iterations': 17})
    cut = problem([[.1, .1, .1], [.2, .2, .2]])
    hit = find_dependency(cut, 400)
    np.testing.assert_array_equal(hit[0], source.original)
    hit[0][:] = -1
    assert find_dependency(cut, 400)[1]['iterations'] == 17
    np.testing.assert_array_equal(find_dependency(cut, 400)[0], source.original)
    assert find_dependency(cut, 399) is None
    for points in ([[.1, .1, .1]], [[.1, .1, .1], [.2, .2, .2], [.5, .5, .5]],
                   [[.2, .2, .2], [.1, .1, .1]], [[.1, .1, .1], [.2, .2, np.nextafter(.2, 1)]]):
        assert find_dependency(problem(points), 400) is None
    cut.original[0, 0] += 1
    assert find_dependency(cut, 400) is None
    clear_fit_cache()


def test_empty_environment_certificate_also_detects_new_neighbours_and_survives_transport():
    import json
    clear_fit_cache()
    source = problem([])
    remember_dependency(source, 400, source.original, {'iterations': 2})
    rows = json.loads(json.dumps(export_fits()))
    clear_fit_cache()
    assert find_dependency(source, 400) is None
    import_fits(rows)
    assert find_dependency(problem([[10, 10, 10]]), 400) is not None
    assert find_dependency(problem([[1.19, 1., 1.]]), 400) is None
    clear_fit_cache()
