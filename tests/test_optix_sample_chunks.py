from types import SimpleNamespace
import pytest
from backend.rendering.optix_sampling import configure_sample_chunk


def test_modern_subsets_keep_total_and_do_not_repeat_samples():
    cycles = SimpleNamespace(use_sample_subset=False)
    for offset, count in [(0, 1), (1, 3), (4, 4), (8, 8)]:
        configure_sample_chunk(cycles, dict(samples=count, sample_offset=offset, sample_total=16))
        assert cycles.samples == 16 and cycles.use_sample_subset
        assert cycles.sample_offset == offset and cycles.sample_subset_length == count
    configure_sample_chunk(cycles, dict(samples=32))
    assert cycles.sample_offset == 0 and cycles.sample_subset_length == 32


def test_legacy_offset_and_invalid_subsets():
    cycles = SimpleNamespace()
    configure_sample_chunk(cycles, dict(samples=3, sample_offset=1, sample_total=16))
    assert cycles.samples == 3 and cycles.sample_offset == 1
    for change in [dict(sample_offset=-1), dict(sample_offset=15), dict(sample_total=513), dict(samples=True)]:
        with pytest.raises(ValueError, match='subset'):
            configure_sample_chunk(cycles, dict(samples=3, sample_offset=1, sample_total=16) | change)
