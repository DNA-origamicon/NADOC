"""Integer ownership oracle: overlaps, loop copies, unoccupied rows and fallback."""
import numpy as np
import pytest

from backend.core import domain_assignment as module


@pytest.fixture(autouse=True)
def native_kernel(tmp_path, monkeypatch):
    import shutil
    from desktop.build_native import build
    if not shutil.which('g++'):
        pytest.skip('C++ integration test requires g++')
    library = build(tmp_path / 'domain.so')
    monkeypatch.setenv('NADOC_NATIVE_DOMAIN_LIBRARY', str(library))
    monkeypatch.setenv('NADOC_NATIVE_DOMAINS', '1')
    cached_kernel = module._kernel
    cached_kernel.cache_clear()
    yield
    cached_kernel.cache_clear()


def test_compiled_kernel_matches_independent_interval_oracle():
    assert module.native_domains_available(), 'Build desktop native kernel for this focused native test'
    rng = np.random.default_rng(734)
    for count in (0, 1, 2, 71, 700):
        bp = rng.integers(-20, 200, count, dtype=np.int64)
        directions = rng.integers(0, 2, count, dtype=np.int64)
        domains = np.array([(-11, 31, 0), (15, 92, 1), (20, 50, 0), (72, 120, 0), (160, 150, 1)], dtype=np.int64)
        owner, opposite = module.assign_domains(bp, directions, domains)
        expected = [max((j for j, (lo, hi, d) in enumerate(domains) if lo <= b <= hi and side == d), default=-1) for b, side in zip(bp, directions)]
        paired = [any(lo <= b <= hi and side != d for lo, hi, d in domains) for b, side in zip(bp, directions)]
        np.testing.assert_array_equal(owner, expected)
        np.testing.assert_array_equal(opposite, paired)
        for actual, reference in zip((owner, opposite), module.assign_domains_numpy(bp, directions, domains)):
            np.testing.assert_array_equal(actual, reference)


def test_no_domains_and_non_contiguous_rows():
    bp = np.arange(30, dtype=np.int64)[::2]
    owner, opposite = module.assign_domains(bp, bp % 2, [])
    assert (owner == -1).all() and not opposite.any()
    with pytest.raises(ValueError):
        module.assign_domains(bp, [0], [])


def test_fallback_retains_last_domain_semantics(monkeypatch):
    monkeypatch.setattr(module, '_kernel', lambda: None)
    owner, opposite = module.assign_domains([1, 1, 2, 3], [0, 0, 1, 1], [(1, 2, 0), (1, 1, 0), (2, 3, 1)])
    assert owner.tolist() == [1, 1, 2, 2]
    assert opposite.tolist() == [False, False, True, False]
