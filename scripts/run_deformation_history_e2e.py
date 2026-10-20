"""Run only S03 under `just validate-safe` with machine-local scratch selection.

Persistent inventory (all beneath one freshly allocated root): workspace files,
project stores and logs; TMPDIR browser profiles/downloads; Vite cache; Playwright
output/.last-run. No screenshots/traces/video, viewer credentials or share service.
Session caching and production background startup are disabled. The outer finally
removes the entire owned root after servers exit, including failed/startup runs.
SIGKILL/power loss cannot run cleanup: the printed exact root must then be reviewed.
"""

import os
import argparse
import json
from pathlib import Path
import shutil
import signal
import subprocess
import tempfile
import time

import psutil

REPO = Path(__file__).resolve().parents[1]
# Operational headroom for this tiny, capture-free spec, not a scientific gate
# or a guarantee of peak usage. Larger campaigns must budget their own output.
MIN_FREE_BYTES = 1024 ** 3


def storage_parent():
    configured = os.environ.get('NADOC_TEST_SCRATCH_ROOT')
    legacy = os.environ.get('NADOC_HISTORY_E2E_OUTPUT_PARENT')
    if configured is not None and legacy is not None and configured != legacy:
        raise RuntimeError('Conflicting scratch roots; set only NADOC_TEST_SCRATCH_ROOT')
    selected = configured if configured is not None else legacy
    if selected is None:
        selected = tempfile.gettempdir()
    path = Path(selected).expanduser()
    if not selected or not path.is_absolute():
        raise RuntimeError('Scratch root must be an existing absolute directory')
    try:
        parent = path.resolve(strict=True)
    except OSError as error:
        raise RuntimeError(f'Scratch root unavailable: {path}; no fallback') from error
    if not parent.is_dir():
        raise RuntimeError(f'Scratch root is not a directory: {parent}')
    required = os.environ.get('NADOC_TEST_SCRATCH_MOUNT')
    if required is not None:
        mount = Path(required).expanduser()
        if not required or not mount.is_absolute() or not mount.is_mount():
            raise RuntimeError(f'Required scratch mount unavailable: {required}; no fallback')
        mount = mount.resolve(strict=True)
        if not parent.is_relative_to(mount) or parent.stat().st_dev != mount.stat().st_dev:
            raise RuntimeError(f'Scratch root must reside on configured mount: {mount}')
    if shutil.disk_usage(parent).free < MIN_FREE_BYTES:
        raise RuntimeError(f'Scratch root needs at least 1 GiB free: {parent}; no fallback')
    # Exercise actual creation, not os.access (which can misreport ACL/root access).
    try:
        with tempfile.TemporaryFile(dir=parent) as probe:
            probe.write(b'scratch preflight\n')
            probe.flush()
    except OSError as error:
        raise RuntimeError(f'Scratch root is not writable: {parent}; no fallback') from error
    return parent


def browser_installation():
    """Resolve installed Playwright's platform/env rules before isolating XDG.

    Registry access is read-only: no browser launch, download or cache creation.
    Using the installed registry also preserves relative paths, npm overrides and
    PLAYWRIGHT_BROWSERS_PATH=0 without duplicating platform/revision rules.
    """
    script = """
const path = require('node:path');
const base = path.dirname(require.resolve('playwright-core/package.json'));
const { registry, registryDirectory } = require(path.join(base, 'lib/server/registry/index.js'));
console.log(JSON.stringify({directory: registryDirectory,
  executable: registry.findExecutable('chromium-headless-shell').executablePath()}));
"""
    try:
        result = subprocess.run(['node', '-e', script], cwd=REPO / 'frontend',
                                capture_output=True, text=True, check=True, timeout=15)
        resolved = json.loads(result.stdout)
        directory = Path(resolved['directory'])
        executable = Path(resolved['executable'])
        if not directory.is_absolute() or not executable.is_absolute():
            raise ValueError('Expected absolute browser installation paths')
    except (OSError, subprocess.SubprocessError, ValueError, KeyError, TypeError) as error:
        raise RuntimeError('Cannot resolve installed Playwright headless Chromium; no services started') from error
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise RuntimeError(f'Installed headless Chromium unavailable: {executable}; no fallback or download')
    return str(directory)


def owned_processes(root):
    """Playwright servers may detach; process-group membership is insufficient."""
    found = []
    current_user = psutil.Process().username()
    # Ignore pre-existing protected processes owned by the same user. They cannot
    # carry this fresh run's marker. Allow one second for OS timestamp granularity.
    earliest = (Path(root) / '.owner-start').stat().st_mtime - 1
    for process in psutil.process_iter():
        try:
            username = process.username()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        try:
            if (username != current_user or process.create_time() < earliest
                    or process.status() == psutil.STATUS_ZOMBIE):
                continue
            if process.environ().get('NADOC_HISTORY_E2E_ROOT') == str(root):
                found.append(process)
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied:
            # Protected unrelated processes are not ours to inspect or signal.
            # A denied terminate/kill on an identified owned process propagates
            # from stop_owned_processes and prevents deletion.
            continue
    return found


def stop_owned_processes(root):
    for action in ('terminate', 'kill'):
        for process in owned_processes(root):
            try:
                getattr(process, action)()
            except psutil.NoSuchProcess:
                pass
        deadline = time.monotonic() + 10
        while owned_processes(root) and time.monotonic() < deadline:
            time.sleep(.1)
        if not owned_processes(root):
            return
    raise RuntimeError(f'Owned processes still active; preserve and review {root}')


def main(*, check_storage=False, smoke=False):
    parent = storage_parent()
    print(f'Scratch parent: {parent} ({shutil.disk_usage(parent).free // (1024 ** 3)} GiB free)', flush=True)
    if check_storage:
        print('Storage preflight passed; no services or browser launched', flush=True)
        return 0
    browsers = browser_installation()
    print(f'Installed browser directory: {browsers}', flush=True)
    root = Path(tempfile.mkdtemp(prefix='__e2e__smoke-' if smoke else '__e2e__history-', dir=parent))
    (root / '.owner-start').touch()
    print(f'Owned output inventory root: {root}', flush=True)
    child = None
    def interrupt(_signal, _frame):
        raise KeyboardInterrupt
    previous = signal.signal(signal.SIGTERM, interrupt)
    try:
        for name in ('workspace', 'tmp', 'cache'):
            (root / name).mkdir()
        env = {**os.environ, 'PLAYWRIGHT_BROWSERS_PATH': browsers,
               'NADOC_HISTORY_E2E_ROOT': str(root),
               'NADOC_WORKSPACE': str(root / 'workspace'), 'TMPDIR': str(root / 'tmp'),
               'TEMP': str(root / 'tmp'), 'TMP': str(root / 'tmp'),
               'XDG_CACHE_HOME': str(root / 'cache'), 'NADOC_DISABLE_SESSION_CACHE': '1',
               'UV_CACHE_DIR': str(root / 'cache' / 'uv'),
               'PWTEST_CACHE_DIR': str(root / 'cache' / 'playwright'),
               'NADOC_RUNPOD_AUTOCONNECT': '0', 'PYTHONDONTWRITEBYTECODE': '1',
               'NADOC_MD_PLAYBACK_CACHE_DIR': str(root / 'workspace' / 'playback')}
        if smoke:
            env.update({'NADOC_SMOKE_E2E_ROOT': str(root), 'UV_NO_SYNC': '1',
                        'npm_config_offline': 'true', 'NADOC_SHARE_AUTOSTART': '0',
                        'NADOC_SHARE_CONTROL_FILE': str(root / 'share-control.json'),
                        'CUDA_CACHE_PATH': str(root / 'cache' / 'cuda'),
                        'TORCH_HOME': str(root / 'cache' / 'torch')})
        command = (['just', 'smoke'] if smoke else
                   ['node', 'node_modules/@playwright/test/cli.js', 'test',
                    '--config', 'playwright.deformation-history.config.js'])
        child = subprocess.Popen(command, cwd=REPO if smoke else REPO / 'frontend',
                                 env=env, start_new_session=(os.name == 'posix'))
        return child.wait()
    finally:
        if child is not None:
            # Let Playwright close servers first, then find any detached survivors.
            if child.poll() is None:
                child.terminate()
            try:
                child.wait(timeout=10)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()
        signal.signal(signal.SIGTERM, previous)
        stop_owned_processes(root)
        shutil.rmtree(root)
        if root.exists():
            raise RuntimeError(f'Cleanup failed: {root}')
        print(f'Cleanup verified absent: {root}', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-storage', action='store_true', help='Check scratch without launching services/browser')
    parser.add_argument('--smoke', action='store_true', help='Run guarded just smoke with isolated workspace and caches')
    args = parser.parse_args()
    raise SystemExit(main(check_storage=args.check_storage, smoke=args.smoke))
