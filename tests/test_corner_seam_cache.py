"""Fit reuse cannot cross an environment, constraint or coordinate change."""

from types import SimpleNamespace
import numpy as np

from backend.core.corner_seam_cache import clear_fit_cache, fit_key, get_fit, put_fit


def test_exact_fit_cache_invalidation_and_return_ownership():
    clear_fit_cache()
    problem = SimpleNamespace(original=np.arange(18.).reshape(6, 3),
        bridges=np.array([[0, 1, 2, 3, 4]]), free=np.array([1, 2, 3]),
        pairs=np.array([[0, 5]]), branches=[(2, 5)], bodies=[np.array([2, 3, 4, 5])],
        environment=SimpleNamespace(data=np.array([[8., 9., 10.]])))
    key = fit_key(problem, 400)
    put_fit(key, problem.original, {'iterations': 20})
    coordinates, report = get_fit(key)
    coordinates[:] = -100
    report['iterations'] = -1
    np.testing.assert_array_equal(get_fit(key)[0], problem.original)
    assert get_fit(key)[1]['iterations'] == 20
    assert get_fit(fit_key(problem, 399)) is None
    for field in ('original', 'bridges', 'free', 'pairs'):
        array = getattr(problem, field)
        old = array.flat[0]
        array.flat[0] += 1
        assert get_fit(fit_key(problem, 400)) is None
        array.flat[0] = old
    problem.environment.data[0, 0] = np.nextafter(8., 9.)
    assert get_fit(fit_key(problem, 400)) is None
    clear_fit_cache()


def test_worker_cache_transport_preserves_exact_values_without_sharing_mutable_rows():
    import json
    from backend.core.corner_seam_cache import export_fits, import_fits
    clear_fit_cache()
    coordinates = np.array([[np.nextafter(1., 2.), -0., 1e-100]])
    key = bytes(range(32))
    put_fit(key, coordinates, {'iterations': 3})
    rows = json.loads(json.dumps(export_fits()))
    clear_fit_cache()
    import_fits(rows)
    rows[0][1][0][0] = 99
    np.testing.assert_array_equal(get_fit(key)[0], coordinates)
    assert np.signbit(get_fit(key)[0][0, 1])
    clear_fit_cache()
