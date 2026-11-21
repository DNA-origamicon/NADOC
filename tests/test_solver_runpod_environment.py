"""Managed environment setup is restricted to the default SNUPI interpreter."""
import asyncio
import subprocess
import tomllib
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.solver_runpod_environment import DEFAULT_PYTHON, REQUIREMENTS, ensure_environment, setup_script


@pytest.mark.parametrize('engine,python,expected', [
    ('snupi', DEFAULT_PYTHON, True),
    ('snupi', '/workspace/custom/bin/python', False),
    ('mrdna', DEFAULT_PYTHON, False),
])
def test_setup_only_managed_snupi(engine, python, expected):
    calls = []
    class Conn:
        async def run(self, command, **kw):
            calls.append((command, kw))
            return SimpleNamespace(rc=0)
    asyncio.run(ensure_environment(Conn(), engine, SimpleNamespace(python=python)))
    assert bool(calls) == expected
    if expected:
        assert calls[0][1]['timeout'] == 900


def test_setup_failure_is_actionable():
    class Conn:
        async def run(self, *args, **kwargs):
            return SimpleNamespace(rc=1, stderr='No space left on device', stdout='')
    with pytest.raises(RuntimeError, match='environment setup failed: No space left'):
        asyncio.run(ensure_environment(Conn(), 'snupi', SimpleNamespace(python=DEFAULT_PYTHON)))


def test_setup_shell_and_dependency_versions():
    script = setup_script()
    subprocess.run(['bash', '-n'], input=script, text=True, check=True)
    packages = tomllib.loads(Path('uv.lock').read_text())['package']
    locked = {f"{p['name']}=={p['version']}" for p in packages}
    assert set(REQUIREMENTS) <= locked
    assert 'flock -w 600' in script
    assert 'UV_PYTHON_INSTALL_DIR=/workspace/' in script
    assert script.index('pip install --python') < script.index('> /workspace/nadoc-solver-env/.nadoc-ready')
    assert '--clear' not in script
    assert 'torch==2.9.1 --index-url https://download.pytorch.org/whl/cu128' in script
    assert script.index('torch==2.9.1') < script.index('> /workspace/nadoc-solver-env/.nadoc-ready')
