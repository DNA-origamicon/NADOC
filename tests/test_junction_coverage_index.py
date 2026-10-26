"""Interval lookup preserves junction occupancy without per-query domain scans."""
from copy import deepcopy
from random import Random

from backend.core.topology_integrity import _coverage_index, _covered


def test_interval_index_matches_exhaustive_occupancy_with_gaps_overlap_and_directions():
    random = Random(7183)
    for _ in range(100):
        ranges = {(helix, direction): [tuple(sorted((random.randint(-30, 30), random.randint(-30, 30))))
                  for _ in range(random.randint(0, 8))]
                  for helix in ('a', 'b') for direction in ('FORWARD', 'REVERSE')}
        original = deepcopy(ranges)
        index = _coverage_index(ranges)
        for helix in ('a', 'b', 'missing'):
            for direction in ('FORWARD', 'REVERSE'):
                expected = {bp for lo, hi in ranges.get((helix, direction), ()) for bp in range(lo, hi + 1)}
                for bp in range(-32, 33):
                    assert _covered((helix, bp, direction), index) == (bp in expected)
        assert ranges == original


def test_large_coordinates_do_not_expand_material_or_bridge_a_missing_base():
    key = ('helix', 'FORWARD')
    index = _coverage_index({key: [(-10**12, -1), (1, 10**12)]})
    assert len(index[key][0]) == 2
    for bp in (-10**12, -1, 1, 10**12):
        assert _covered(('helix', bp, 'FORWARD'), index)
    for bp in (-10**12 - 1, 0, 10**12 + 1):
        assert not _covered(('helix', bp, 'FORWARD'), index)
    assert not _covered(('helix', 1, 'REVERSE'), index)
