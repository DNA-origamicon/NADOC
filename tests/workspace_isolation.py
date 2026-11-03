"""Private startup state, including fixtures that precede function-scoped tests."""
from contextlib import contextmanager
import logging

import pytest


@contextmanager
def isolated_startup_workspace(path):
    from backend.api import assembly, main
    from backend.core import alpine_operations

    logger = logging.Logger('nadoc.test.alpine.operations', level=logging.INFO)
    logger.propagate = False
    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(assembly, '_WORKSPACE_DIR', path)
        patch.setattr(main, '_WORKSPACE_DIR', path)
        patch.setenv('NADOC_WORKSPACE', str(path))
        # Reservations are process-shared state too. Keep test workers and their
        # children out of the user's live simulation/analysis registry.
        patch.setenv('NADOC_MEMORY_BUDGET_DIR', str(path / '.memory-budget'))
        patch.setattr(alpine_operations, '_LOGGER', logger)
        patch.setattr(alpine_operations, '_PATH', None)
        try:
            yield path
        finally:
            for handler in tuple(logger.handlers):
                handler.close()
                logger.removeHandler(handler)
