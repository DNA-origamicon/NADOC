"""Storage refusal and failure cleanup without launching browsers or services."""

from pathlib import Path
from types import SimpleNamespace
import os
import subprocess
import sys

import pytest

from scripts import run_deformation_history_e2e as launcher


@pytest.fixture(autouse=True)
def isolated_storage_environment(monkeypatch):
    for key in ('NADOC_TEST_SCRATCH_ROOT', 'NADOC_HISTORY_E2E_OUTPUT_PARENT', 'NADOC_TEST_SCRATCH_MOUNT'):
        monkeypatch.delenv(key, raising=False)


def test_default_uses_os_temporary_directory_without_archive(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher.tempfile, 'gettempdir', lambda: str(tmp_path))
    assert launcher.storage_parent() == tmp_path
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('variable', ['NADOC_TEST_SCRATCH_ROOT', 'NADOC_HISTORY_E2E_OUTPUT_PARENT'])
def test_explicit_root_is_used(monkeypatch, tmp_path, variable):
    monkeypatch.setenv(variable, str(tmp_path))
    assert launcher.storage_parent() == tmp_path


@pytest.mark.parametrize('value', ['', 'relative', '/definitely-missing-nadoc-scratch'])
def test_invalid_explicit_root_never_falls_back(monkeypatch, value):
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', value)
    monkeypatch.setattr(launcher.tempfile, 'gettempdir', lambda: pytest.fail('Fell back'))
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('Launched'))
    with pytest.raises(RuntimeError):
        launcher.main()


def test_conflicting_roots_refuse(monkeypatch, tmp_path):
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    monkeypatch.setenv('NADOC_HISTORY_E2E_OUTPUT_PARENT', str(tmp_path / 'other'))
    with pytest.raises(RuntimeError, match='Conflicting'):
        launcher.storage_parent()


def test_file_is_not_a_scratch_directory(monkeypatch, tmp_path):
    file = tmp_path / 'file'
    file.write_text('preserve')
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(file))
    with pytest.raises(RuntimeError, match='not a directory'):
        launcher.storage_parent()
    assert file.read_text() == 'preserve'


def test_missing_required_mount_refuses_existing_directory(monkeypatch, tmp_path):
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    monkeypatch.setenv('NADOC_TEST_SCRATCH_MOUNT', str(tmp_path))
    monkeypatch.setattr(Path, 'is_mount', lambda _p: False)
    with pytest.raises(RuntimeError, match='Required scratch mount unavailable'):
        launcher.storage_parent()


def test_required_mount_must_contain_resolved_root(monkeypatch, tmp_path):
    mount = tmp_path / 'mount'
    mount.mkdir()
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    monkeypatch.setenv('NADOC_TEST_SCRATCH_MOUNT', str(mount))
    monkeypatch.setattr(Path, 'is_mount', lambda p: p == mount)
    with pytest.raises(RuntimeError, match='must reside on configured mount'):
        launcher.storage_parent()
    root = mount / 'scratch'
    root.mkdir()
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(root))
    assert launcher.storage_parent() == root


def test_low_space_refuses_before_output(monkeypatch, tmp_path):
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    monkeypatch.setattr(launcher.shutil, 'disk_usage', lambda _p: SimpleNamespace(free=launcher.MIN_FREE_BYTES - 1))
    with pytest.raises(RuntimeError, match='1 GiB free'):
        launcher.storage_parent()
    assert list(tmp_path.iterdir()) == []


def test_unwritable_root_refuses(monkeypatch, tmp_path):
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    def denied(**_kwargs):
        raise PermissionError('test ACL')
    monkeypatch.setattr(launcher.tempfile, 'TemporaryFile', denied)
    with pytest.raises(RuntimeError, match='not writable'):
        launcher.storage_parent()


def test_preflight_does_not_launch(monkeypatch, tmp_path):
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    monkeypatch.setattr(launcher.subprocess, 'Popen', lambda *_a, **_k: pytest.fail('Launched'))
    assert launcher.main(check_storage=True) == 0
    assert list(tmp_path.iterdir()) == []


def test_startup_failure_cleans_only_new_root(monkeypatch, tmp_path):
    monkeypatch.setattr(launcher, 'browser_installation', lambda: '/installed/browser-cache')
    preserved = tmp_path / 'existing'
    preserved.write_text('preserve')
    monkeypatch.setattr(launcher, 'storage_parent', lambda: tmp_path)
    def fail(*_args, **kwargs):
        env = kwargs['env']
        root = Path(env['NADOC_HISTORY_E2E_ROOT'])
        assert Path(env['TMPDIR']).is_relative_to(root)
        assert Path(env['NADOC_WORKSPACE']).is_relative_to(root)
        assert env['NADOC_DISABLE_SESSION_CACHE'] == '1'
        (root / 'workspace' / '__e2e__test.nadoc').write_text('disposable')
        raise RuntimeError('startup failure')
    monkeypatch.setattr(launcher.subprocess, 'Popen', fail)
    with pytest.raises(RuntimeError, match='startup failure'):
        launcher.main()
    assert list(tmp_path.iterdir()) == [preserved]
    assert preserved.read_text() == 'preserve'


@pytest.mark.parametrize('exit_code', [0, 1])
def test_finished_run_cleans_output_and_preserves_exit_code(monkeypatch, tmp_path, exit_code):
    monkeypatch.setattr(launcher, 'browser_installation', lambda: '/installed/browser-cache')
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    def launch(*_args, **kwargs):
        assert kwargs['env']['PLAYWRIGHT_BROWSERS_PATH'] == '/installed/browser-cache'
        root = Path(kwargs['env']['NADOC_HISTORY_E2E_ROOT'])
        assert kwargs['env']['XDG_CACHE_HOME'] == str(root / 'cache')
        (root / 'workspace' / '__e2e__result.nadoc').write_text('disposable')
        assert all(kwargs['env'][key] == str(root / 'tmp') for key in ('TMPDIR', 'TEMP', 'TMP'))
        return SimpleNamespace(wait=lambda **_k: exit_code, poll=lambda: exit_code)
    monkeypatch.setattr(launcher.subprocess, 'Popen', launch)
    assert launcher.main() == exit_code
    assert list(tmp_path.iterdir()) == []


def test_live_process_refusal_preserves_output(monkeypatch):
    monkeypatch.setattr(launcher, 'owned_processes', lambda _root: [SimpleNamespace(terminate=lambda: None, kill=lambda: None)])
    clock = iter([0, 11, 20, 31])
    monkeypatch.setattr(launcher.time, 'monotonic', lambda: next(clock))
    with pytest.raises(RuntimeError, match='preserve and review'):
        launcher.stop_owned_processes('/never-delete-live-output')


def test_cleanup_stops_only_exact_owned_process(tmp_path):
    root = str(tmp_path / 'owned')
    Path(root).mkdir()
    (Path(root) / '.owner-start').touch()
    children = []
    try:
        for marker in (root, root + '-unrelated'):
            child = subprocess.Popen(
                [sys.executable, '-u', '-c', 'import time; print("ready"); time.sleep(30)'],
                env={**os.environ, 'NADOC_HISTORY_E2E_ROOT': marker},
                stdout=subprocess.PIPE, text=True,
            )
            children.append(child)
            assert child.stdout.readline().strip() == 'ready'
        assert [p.pid for p in launcher.owned_processes(root)] == [children[0].pid]
        launcher.stop_owned_processes(root)
        assert children[0].wait(timeout=2) is not None
        assert children[1].poll() is None
        assert launcher.owned_processes(root) == []
    finally:
        for child in children:
            if child.poll() is None:
                child.kill()
            child.wait(timeout=2)
            child.stdout.close()


@pytest.mark.parametrize('setting', [None, 'explicit', 'relative', '0'])
def test_installed_registry_resolution_respects_environment(monkeypatch, tmp_path, setting):
    # Actual Node registry resolution, no browser launch or download. Check the
    # resolved path even when the deliberately empty installation refuses.
    for key in ('PLAYWRIGHT_BROWSERS_PATH', 'npm_config_playwright_browsers_path',
                'npm_package_config_playwright_browsers_path'):
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv('XDG_CACHE_HOME', str(tmp_path))
    monkeypatch.setenv('INIT_CWD', str(tmp_path))
    if setting is not None:
        monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(tmp_path / 'explicit') if setting == 'explicit' else setting)
    seen = []
    monkeypatch.setattr(Path, 'is_file', lambda p: seen.append(p) or True)
    monkeypatch.setattr(launcher.os, 'access', lambda *_a: True)
    directory = Path(launcher.browser_installation())
    if setting == '0':
        assert directory == launcher.REPO / 'frontend/node_modules/playwright-core/.local-browsers'
    elif setting is None:
        if sys.platform != 'linux':
            pytest.skip('XDG default is Linux-specific')
        assert directory == tmp_path / 'ms-playwright'
    else:
        assert directory == tmp_path / setting
    assert seen[0].is_relative_to(directory)
    assert 'chromium_headless_shell-' in str(seen[0])


def test_missing_browser_refuses_before_allocation_or_services(monkeypatch, tmp_path):
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    monkeypatch.setenv('PLAYWRIGHT_BROWSERS_PATH', str(tmp_path / 'missing-browser'))
    monkeypatch.setattr(launcher.tempfile, 'mkdtemp', lambda **_k: pytest.fail('Allocated'))
    with pytest.raises(RuntimeError, match='no fallback or download'):
        launcher.main()
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize('exit_code', [0, 1])
def test_smoke_uses_real_guarded_recipe_and_isolated_cleanup(monkeypatch, tmp_path, exit_code):
    monkeypatch.setattr(launcher, 'browser_installation', lambda: '/installed/browser-cache')
    monkeypatch.setenv('NADOC_TEST_SCRATCH_ROOT', str(tmp_path))
    def launch(command, **kwargs):
        assert command == ['just', 'smoke']
        assert kwargs['cwd'] == launcher.REPO
        env = kwargs['env']
        root = Path(env['NADOC_SMOKE_E2E_ROOT'])
        assert env['NADOC_HISTORY_E2E_ROOT'] == str(root)
        assert env['NADOC_WORKSPACE'] == str(root / 'workspace')
        assert env['NADOC_RUNPOD_AUTOCONNECT'] == '0'
        assert env['UV_NO_SYNC'] == '1'
        assert env['npm_config_offline'] == 'true'
        (root / 'share-control.json').write_text('disposable')
        return SimpleNamespace(wait=lambda **_k: exit_code, poll=lambda: exit_code)
    monkeypatch.setattr(launcher.subprocess, 'Popen', launch)
    assert launcher.main(smoke=True) == exit_code
    assert list(tmp_path.iterdir()) == []
