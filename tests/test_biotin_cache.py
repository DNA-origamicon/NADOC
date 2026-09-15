"""Cache correctness: unchanged molecular frames reuse, edits/version changes refit."""
import concurrent.futures
import numpy as np
import pytest
from backend.core import biotin_atomistic as b


@pytest.fixture
def cache(tmp_path, monkeypatch):
    b._fit_teg.cache_clear()
    monkeypatch.setattr(b, '_fit_cache_path', lambda: tmp_path / 'fits.sqlite3')
    calls = []
    def solve(endpoint, oxygen):
        calls.append(endpoint)
        names, elements, xyz, pairs = b._unconnected_teg()
        return names, elements, xyz, [*pairs, (27,28)]
    monkeypatch.setattr(b, '_solve_teg', solve)
    yield calls
    b._fit_teg.cache_clear()


def test_survives_restart_but_endpoint_or_solver_version_changes_invalidate(cache, monkeypatch):
    a = b._fit_teg((1.,2.,3.), (1.,2.,3.16))
    b._fit_teg.cache_clear()
    assert np.array_equal(b._fit_teg((1.,2.,3.), (1.,2.,3.16))[2], a[2])
    assert len(cache) == 1
    b._fit_teg((1.,2.,3.1), (1.,2.,3.26))
    assert len(cache) == 2
    monkeypatch.setattr(b, '_FIT_VERSION', 'new chemistry')
    b._fit_teg.cache_clear()
    b._fit_teg((1.,2.,3.), (1.,2.,3.16))
    assert len(cache) == 3


def test_simultaneous_views_solve_once(cache):
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda _: b._fit_teg((1.,2.,3.), (1.,2.,3.16)), range(8)))
    assert len(cache) == 1


def test_corrupt_disk_is_disposable_and_failed_fits_are_cached(cache, monkeypatch):
    b._fit_cache_path().write_bytes(b'not a sqlite file')
    assert b._fit_teg((1.,2.,3.), (1.,2.,3.16)) is not None
    b._fit_cache_path().unlink()
    monkeypatch.setattr(b, '_solve_teg', lambda *_: None)
    assert b._fit_teg((10.,2.,3.), (10.,2.,3.16)) is None
    b._fit_teg.cache_clear()
    monkeypatch.setattr(b, '_solve_teg', lambda *_: pytest.fail('failed fit solved twice'))
    assert b._fit_teg((10.,2.,3.), (10.,2.,3.16)) is None
