import pytest
from backend.core.md_flex_range import flex_frame_indices


def test_default_last_200_and_short_trajectory():
    assert list(flex_frame_indices(1000, {})) == list(range(800, 1000))
    assert list(flex_frame_indices(12, {})) == list(range(12))
    assert len(flex_frame_indices(1000, None)) == 1000  # internal all-frame callers


def test_one_based_inclusive_range_and_interval():
    assert list(flex_frame_indices(100, dict(start=4, end=13, interval=3))) == [3, 6, 9, 12]
    assert list(flex_frame_indices(100, dict(start=9, end=9, interval=10))) == [8]


@pytest.mark.parametrize('selection', [dict(start=0), dict(interval=0), dict(start=10, end=9),
                                      dict(end=101), dict(start=1.5), dict(interval=True)])
def test_invalid_ranges_fail(selection):
    with pytest.raises(ValueError):
        flex_frame_indices(100, selection)
