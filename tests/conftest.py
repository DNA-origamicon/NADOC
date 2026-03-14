"""
Shared pytest fixtures and hooks.
"""

import pytest
from backend.core.crossover_positions import clear_cache as clear_crossover_cache


@pytest.fixture(autouse=True)
def reset_crossover_cache():
    """Clear the crossover position cache before every test.

    The cache is module-level and keyed only by helix-ID pair.  Tests that
    reuse the same helix IDs with different lengths (e.g. different length_bp
    values) would otherwise see stale cached results.
    """
    clear_crossover_cache()
    yield
    clear_crossover_cache()
