"""Unit tests for the single-flight atomistic-model cache.

Guards the fix for the ~20 GB worker blow-up: the live-MD WebSocket rebuilt the
full all-atom model on every load with no cache and no concurrency guard, so
rapid re-opens piled up dozens of concurrent multi-GB builds.  These tests pin
that (1) repeat loads of the same design build once, (2) concurrent loads of the
same design collapse to a single build (single-flight), (3) distinct designs each
build, and (4) the cache is bounded.

The underlying ``build_atomistic_model`` is stubbed with a counting/sleeping fake
so the tests are fast and assert *build invocation count*, not model contents.
"""

from __future__ import annotations

import sys
import threading
import time
from pathlib import Path

REPO = Path(__file__).parent.parent
sys.path.insert(0, str(REPO))

import backend.core.atomistic as atomistic_mod
from backend.core import atomistic_cache
from backend.core.atomistic_cache import (
    atomistic_fingerprint,
    build_atomistic_model_cached,
    cache_size,
    clear_atomistic_cache,
)

from tests.conftest import make_minimal_design


class _Counter:
    def __init__(self, delay: float = 0.0):
        self.calls = 0
        self.delay = delay
        self._lock = threading.Lock()

    def __call__(self, design, *args, **kwargs):
        with self._lock:
            self.calls += 1
        if self.delay:
            time.sleep(self.delay)
        # A distinct object per build so identity-equality proves a cache hit.
        return object()


def _install_stub(monkeypatch, delay: float = 0.0) -> _Counter:
    clear_atomistic_cache()
    counter = _Counter(delay=delay)
    # build_atomistic_model_cached does `from backend.core.atomistic import
    # build_atomistic_model` at call time, so patching the attribute here works.
    monkeypatch.setattr(atomistic_mod, "build_atomistic_model", counter)
    return counter


def test_repeat_load_builds_once(monkeypatch):
    counter = _install_stub(monkeypatch)
    d = make_minimal_design()

    m1 = build_atomistic_model_cached(d)
    m2 = build_atomistic_model_cached(d)

    assert counter.calls == 1, "second load should hit the cache, not rebuild"
    assert m1 is m2, "cache must return the same model object"
    clear_atomistic_cache()


def test_distinct_designs_each_build(monkeypatch):
    counter = _install_stub(monkeypatch)
    d1 = make_minimal_design(helix_length_bp=42)
    d2 = make_minimal_design(helix_length_bp=64)

    assert atomistic_fingerprint(d1) != atomistic_fingerprint(d2)
    m1 = build_atomistic_model_cached(d1)
    m2 = build_atomistic_model_cached(d2)

    assert counter.calls == 2
    assert m1 is not m2
    clear_atomistic_cache()


def test_concurrent_same_design_single_flight(monkeypatch):
    # A slow build so all threads arrive while the first is still building; a
    # correct single-flight lets only one through and hands the rest the result.
    counter = _install_stub(monkeypatch, delay=0.25)
    d = make_minimal_design()

    results: list[object] = []
    res_lock = threading.Lock()
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()  # release all threads simultaneously
        m = build_atomistic_model_cached(d)
        with res_lock:
            results.append(m)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert counter.calls == 1, f"single-flight violated: {counter.calls} builds"
    assert len(results) == 8
    assert all(m is results[0] for m in results), "all threads must share one model"
    clear_atomistic_cache()


def test_cache_is_bounded(monkeypatch):
    counter = _install_stub(monkeypatch)
    # More distinct designs than the cache holds → size stays bounded.
    designs = [make_minimal_design(helix_length_bp=40 + i) for i in range(5)]
    for d in designs:
        build_atomistic_model_cached(d)

    assert counter.calls == 5
    assert cache_size() <= atomistic_cache._CACHE_MAX
    # The most recent design is still warm (no rebuild on immediate re-load).
    build_atomistic_model_cached(designs[-1])
    assert counter.calls == 5
    clear_atomistic_cache()


def test_fingerprint_stable_and_sensitive():
    d = make_minimal_design()
    assert atomistic_fingerprint(d) == atomistic_fingerprint(d)
    d2 = make_minimal_design(n_helices=2)
    assert atomistic_fingerprint(d) != atomistic_fingerprint(d2)


def test_reclaim_cache_if_low_frees_only_under_pressure(monkeypatch):
    from backend.core import md_vram

    _install_stub(monkeypatch)
    build_atomistic_model_cached(make_minimal_design())
    assert cache_size() >= 1

    # Plenty of RAM → nothing dropped (roomy machine: no viewer thrash).
    monkeypatch.setattr(md_vram, "detect_host_ram_mb", lambda: 32_000)
    assert atomistic_cache.reclaim_cache_if_low(4096) == 0
    assert cache_size() >= 1

    # RAM below the floor → cache released so NAMD gets pinning headroom.
    monkeypatch.setattr(md_vram, "detect_host_ram_mb", lambda: 1_000)
    freed = atomistic_cache.reclaim_cache_if_low(4096)
    assert freed >= 1
    assert cache_size() == 0


def test_reclaim_cache_if_low_no_ram_reading_is_noop(monkeypatch):
    from backend.core import md_vram

    _install_stub(monkeypatch)
    build_atomistic_model_cached(make_minimal_design())
    monkeypatch.setattr(md_vram, "detect_host_ram_mb", lambda: None)
    assert atomistic_cache.reclaim_cache_if_low(4096) == 0  # don't reclaim on a guess
    assert cache_size() >= 1
    clear_atomistic_cache()
