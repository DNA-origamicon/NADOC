"""Fast unit tests for the per-frame DISPLAY OUTPUT cache in oxdna_health.

The cache memoises the finished atomistic flat-XYZ list / surface JSON for a relaxed
or trajectory frame — the "≈ several seconds each" all-atom rebuild — so re-scrubbing to
a visited frame, or flipping the representation on the same frame, is free.  These tests
pin the pure store behaviour (get/put/LRU-evict/clear + element accounting); the actual
rebuild wiring is exercised by the slow oxDNA suite.
"""
import backend.core.oxdna_health as H


def _reset():
    H.display_out_cache_clear()


def test_get_miss_then_hit():
    _reset()
    assert H._display_out_get(("cta", "k", 0)) is None
    payload = [1.0, 2.0, 3.0]
    H._display_out_put(("cta", "k", 0), payload)
    assert H._display_out_get(("cta", "k", 0)) is payload   # same object, not a copy


def test_distinct_keys_do_not_collide():
    _reset()
    H._display_out_put(("cta", "k", 0), [0.0])
    H._display_out_put(("cta", "k", 1), [1.0])
    H._display_out_put(("cts", "k", 0, ("strand", 0.28, 0.2, 1.3, 15)), {"vertices": [0.0], "faces": [0]})
    assert H._display_out_get(("cta", "k", 0)) == [0.0]
    assert H._display_out_get(("cta", "k", 1)) == [1.0]
    assert H._display_out_get(("cts", "k", 0, ("strand", 0.28, 0.2, 1.3, 15)))["faces"] == [0]


def test_element_accounting_lists_and_surfaces():
    assert H._out_payload_elems([0.0, 1.0, 2.0]) == 3
    assert H._out_payload_elems({"vertices": [0, 1, 2], "faces": [0, 1, 2, 3]}) == 7
    assert H._out_payload_elems({"vertices": [0], "faces": [0], "vertex_rmsf": [0, 1]}) == 4
    assert H._out_payload_elems({"vertices": [0], "faces": [], "vertex_colors": [1, 2, 3]}) == 4
    assert H._out_payload_elems("nonsense") == 0


def test_lru_evicts_oldest_over_budget(monkeypatch):
    _reset()
    # Tiny budget so two 3-element frames overflow and force one eviction.
    monkeypatch.setattr(H, "_DISPLAY_OUT_MAX_ELEMS", 5)
    H._display_out_put(("cta", "k", 0), [0.0, 0.0, 0.0])   # 3 elems
    H._display_out_put(("cta", "k", 1), [1.0, 1.0, 1.0])   # +3 → 6 > 5 → evict oldest
    assert H._display_out_get(("cta", "k", 0)) is None      # oldest evicted
    assert H._display_out_get(("cta", "k", 1)) == [1.0, 1.0, 1.0]


def test_lru_touch_on_get_protects_recent():
    _reset()
    # Budget for exactly two 1-element frames; a third evicts the least-recently-USED.
    H._DISPLAY_OUT_MAX_ELEMS = 2
    try:
        H._display_out_put(("cta", "k", 0), [0.0])
        H._display_out_put(("cta", "k", 1), [1.0])
        H._display_out_get(("cta", "k", 0))                 # touch 0 → 1 is now oldest
        H._display_out_put(("cta", "k", 2), [2.0])          # evict oldest = 1
        assert H._display_out_get(("cta", "k", 1)) is None
        assert H._display_out_get(("cta", "k", 0)) == [0.0]
        assert H._display_out_get(("cta", "k", 2)) == [2.0]
    finally:
        H._DISPLAY_OUT_MAX_ELEMS = 6_000_000


def test_clear_empties_the_store():
    _reset()
    H._display_out_put(("cta", "k", 0), [0.0])
    H.display_out_cache_clear()
    assert H._display_out_get(("cta", "k", 0)) is None
