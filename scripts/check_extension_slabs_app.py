"""Run with: just validate-safe uv run python -m scripts.check_extension_slabs_app

Inventory: a published specimen OUTSIDE the isolated library, the backend
workspace/cache, and child-process temporary files live in one owned scratch
root. TemporaryDirectory removes it on failure too. Vite credentials are removed
by Playwright global teardown and checked here. Screenshots/alignment metrics
remain only in the configured .development-artifacts/extension-slabs/app output.
"""
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from scripts.run_deformation_history_e2e import storage_parent

ROOT = Path(__file__).resolve().parents[1]


def main():
    # Browser scratch isolation must not isolate the machine-wide RAM registry.
    memory_registry = os.environ.get('NADOC_MEMORY_BUDGET_DIR',
        str(Path(tempfile.gettempdir()) / f'nadoc-memory-{os.getuid()}'))
    with tempfile.TemporaryDirectory(prefix='nadoc-extension-slabs-', dir=storage_parent()) as scratch:
        workspace = Path(scratch) / 'workspace'
        workspace.mkdir()
        temporary = Path(scratch) / 'tmp'
        temporary.mkdir()
        source = Path(scratch) / '__e2e__extension-slabs.nadoc'
        env = dict(os.environ, SCRYWRITE_TEST_WORKSPACE=str(workspace), NADOC_WORKSPACE=str(workspace),
                   NADOC_DISABLE_SESSION_CACHE='1', TMPDIR=str(temporary),
                   NADOC_MEMORY_BUDGET_DIR=memory_registry,
                   SCRYWRITE_FRONTEND_PORT='5293', SCRYWRITE_BACKEND_PORT='8193',
                   NADOC_E2E_FRONTEND_PORT='5293', NADOC_E2E_API_BASE='http://127.0.0.1:8193',
                   NADOC_EXTENSION_SLAB_FIXTURE=str(source))
        subprocess.run([sys.executable, '-m', 'scripts.extension_slab_fixture', str(source)],
                       cwd=ROOT, env=env, check=True)
        result = subprocess.run(['node', 'frontend/node_modules/@playwright/test/cli.js', 'test',
                                 '--config', 'frontend/playwright.extension-slabs.config.js'], cwd=ROOT, env=env)
        print('Owned scratch files to remove:', sum(p.is_file() for p in Path(scratch).rglob('*')))
    assert not Path(scratch).exists()
    print('Isolated fixture, workspace and temporary files removed.')
    return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
