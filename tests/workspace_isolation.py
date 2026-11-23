"""Private startup state, including fixtures that precede function-scoped tests."""
from contextlib import contextmanager
import logging
import sys

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
        # Routes imported during collection retain their own workspace aliases.
        # Startup/polling must not reconcile the developer's live remote jobs
        # from a test process whose in-memory controller registry is empty.
        for name, module in tuple(sys.modules.items()):
            if name.startswith('backend.api.') and hasattr(module, '_WORKSPACE_DIR'):
                patch.setattr(module, '_WORKSPACE_DIR', path)
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
