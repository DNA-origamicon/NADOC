"""Provision the NADOC-managed SNUPI environment on a persistent RunPod volume.

Custom Python paths and external mrDNA/ARBD installations remain user managed.
Installation runs inside the existing pod budget and watchdog lifetime.
"""
import hashlib
import shlex

DEFAULT_PYTHON = '/workspace/nadoc-solver-env/bin/python'
# CPU worker dependencies pinned to the repository's validated uv.lock versions.
REQUIREMENTS = (
    'appdirs==1.4.4', 'fastapi==0.135.1', 'networkx==3.6.1',
    'numba==0.64.0', 'numpy==2.4.3', 'orjson==3.11.8',
    'psutil==7.2.2', 'pydantic==2.12.5', 'scipy==1.17.1',
    'sqlmodel==0.0.37', 'threadpoolctl==3.6.0',
)


def setup_script():
    """Idempotent, serialized setup; never clear or replace an existing environment."""
    revision = hashlib.sha256(('python3.12 uv0.10.9 ' + ' '.join(REQUIREMENTS)).encode()).hexdigest()
    return '\n'.join([
        'set -euo pipefail',
        'mkdir -p /workspace/.nadoc-solver-tools',
        'exec 9>/workspace/.nadoc-solver-tools/setup.lock',
        'flock -w 600 9',
        f'if test -x {DEFAULT_PYTHON} && test "$(cat /workspace/nadoc-solver-env/.nadoc-ready 2>/dev/null)" = {revision}; then exit 0; fi',
        'export UV_PYTHON_INSTALL_DIR=/workspace/.nadoc-solver-tools/python',
        'export UV_CACHE_DIR=/workspace/.nadoc-solver-tools/cache',
        'if ! test -x /workspace/.nadoc-solver-tools/uv/bin/uv; then',
        '  python3 -m pip install --disable-pip-version-check --no-cache-dir --target /workspace/.nadoc-solver-tools/uv uv==0.10.9',
        'fi',
        f'if ! test -x {DEFAULT_PYTHON}; then',
        '  /workspace/.nadoc-solver-tools/uv/bin/uv venv --python 3.12 /workspace/nadoc-solver-env',
        'fi',
        f'/workspace/.nadoc-solver-tools/uv/bin/uv pip install --python {DEFAULT_PYTHON} ' + ' '.join(REQUIREMENTS),
        f'{DEFAULT_PYTHON} -c "import numpy, scipy, pydantic, numba, networkx, orjson, psutil, fastapi, sqlmodel, appdirs, threadpoolctl"',
        f'printf "%s\\n" {revision} > /workspace/nadoc-solver-env/.nadoc-ready',
    ])


async def ensure_environment(conn, engine, config):
    if engine != 'snupi' or config.python != DEFAULT_PYTHON:
        return
    result = await conn.run('bash -c ' + shlex.quote(setup_script()), timeout=900)
    if result.rc:
        raise RuntimeError('RunPod SNUPI environment setup failed: ' + (result.stderr or result.stdout)[-3000:])
