import pytest
from backend.core.trajectory_selection import select_composite_range


def test_interval_is_global_across_segment_boundaries():
    result, start, total = select_composite_range([list(range(7)), list(range(7, 15))], 3, 13, 4)
    assert result == [[3], [7, 11]]
    assert (start, total) == (3, 15)


def test_selection_count_and_indices_agree_with_python_slice():
    groups = [list(range(11)), [], list(range(11, 28)), list(range(28, 35))]
    for first in range(35):
        for step in (1, 2, 7, 100):
            actual, _, _ = select_composite_range(groups, first, 32, step)
            assert sum(actual, []) == list(range(35))[first:max(first + 1, 33):step]


def test_empty_and_invalid_interval():
    assert select_composite_range([[], []]) == ([[], []], 0, 0)
    with pytest.raises(ValueError):
        select_composite_range([[1]], step=0)
