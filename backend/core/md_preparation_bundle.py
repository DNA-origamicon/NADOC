"""Content-addressed, credential-free preparation code and native tools."""
from __future__ import annotations

import hashlib
from importlib.metadata import version
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import tempfile


def digest(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def _native_libraries(binary):
    result = subprocess.run(['ldd', str(binary)], capture_output=True, text=True, check=True)
    for line in result.stdout.splitlines():
        fields = line.split()
        if '=>' not in fields or len(fields) < 3 or not fields[2].startswith('/'):
            continue
        name, path = fields[0], Path(fields[2])
        # Use the host's loader/libc family; shipping a partial glibc causes crashes.
        if name.startswith(('libc.so', 'libm.so', 'libpthread.so', 'libdl.so', 'librt.so', 'libresolv.so', 'libutil.so')):
            continue
        yield name, path


def build_bundle(destination, payload):
    """Snapshot the installed scientific code/tools, never a user's home or credentials."""
    import cloudpickle
    from backend.core.gromacs_package import _find_gmx, _find_top_dir
    from backend.core.namd_topology import find_psfgen, _psfgen_candidates, _resolve_psfgen
    root = Path(__file__).resolve().parents[2]
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.prep-bundle-', dir=destination.parent) as tmp:
        stage = Path(tmp)
        for dirname in ('backend', 'experiments/peg_namd', 'experiments/peg_wall'):
            for source in (root / dirname).rglob('*'):
                if not source.is_file() or '__pycache__' in source.parts:
                    continue
                if source.suffix not in ('.py', '.txt') and not (dirname == 'backend' and 'data' in source.parts):
                    continue
                target = stage / source.relative_to(root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        # Validate imports against the snapshot, with no fallback to this checkout.
        checked = subprocess.run([sys.executable, '-c',
            'from backend.core import pdb_export, namd_topology; from backend.api import routes_md'],
            cwd=stage, env={**os.environ, 'PYTHONPATH': str(stage), 'NADOC_WORKSPACE': str(stage / 'workspace')},
            capture_output=True, text=True, timeout=120)
        if checked.returncode:
            raise RuntimeError('Preparation runtime snapshot is incomplete: ' + checked.stderr[-4000:])
        uv = shutil.which('uv')
        if not uv:
            raise RuntimeError('The NADOC Python environment manager (uv) is unavailable')
        shutil.copy2(uv, stage / 'uv')
        native = stage / 'native'
        (native / 'bin').mkdir(parents=True)
        (native / 'lib').mkdir()
        candidates = [find_psfgen(), *filter(None, (_resolve_psfgen(p) for p in _psfgen_candidates()))]
        for i, binary in enumerate(p for p in dict.fromkeys(candidates) if Path(p).is_file()):
            target = native / f'psfgen-{i}'
            shutil.copy2(binary, target)
        gmx = Path(shutil.which(_find_gmx())).resolve()
        shutil.copy2(gmx, native / 'gmx.real')
        for name, source in _native_libraries(gmx):
            shutil.copy2(source, native / 'lib' / name)
        shutil.copytree(_find_top_dir(), native / 'top', symlinks=False)
        (native / 'bin' / 'gmx').write_text(
            '#!/bin/sh\nHERE=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)\n'
            'export GMXLIB="$HERE/top"\nexport LD_LIBRARY_PATH="$HERE/lib:${LD_LIBRARY_PATH:-}"\n'
            'exec "$HERE/gmx.real" "$@"\n')
        (native / 'bin' / 'gmx').chmod(0o755)
        packages = ('fastapi', 'httpx', 'numpy', 'scipy', 'pydantic', 'sqlmodel', 'orjson',
                    'psutil', 'networkx', 'MDAnalysis', 'parmed', 'pandas', 'threadpoolctl',
                    'watchdog', 'openpyxl', 'appdirs', 'asyncssh', 'boto3', 'matplotlib',
                    'uvicorn', 'numba', 'scikit-image', 'pillow', 'websockets', 'cloudpickle')
        (stage / 'requirements.txt').write_text('\n'.join(f'{p}=={version(p)}' for p in packages) + '\n')
        (stage / 'request.pkl').write_bytes(cloudpickle.dumps(payload))
        hashes = {str(p.relative_to(stage)): digest(p) for p in stage.rglob('*') if p.is_file()}
        (stage / 'inputs.json').write_text(json.dumps(hashes, sort_keys=True))
        with tarfile.open(destination, 'w:gz', compresslevel=3) as archive:
            for p in sorted(stage.iterdir()):
                archive.add(p, arcname=p.name)
    return digest(destination)


def bootstrap_command(minimum_free_gb=30):
    # uv provisions portable Python 3.12; Python package versions match the client.
    # User settings are never evaluated as shell code.
    return '''set -eu
export NADOC_PREP_OUTPUT_DIR="$PWD"
local_root=""
finish_preparation() {
  code=$?
  if [ "$code" -ne 0 ] && [ ! -f "$NADOC_PREP_OUTPUT_DIR/status.json" ]; then
    printf '{"state":"failed","error":"Preparation runtime exited with code %s"}\\n' "$code" > "$NADOC_PREP_OUTPUT_DIR/status.tmp"
    mv "$NADOC_PREP_OUTPUT_DIR/status.tmp" "$NADOC_PREP_OUTPUT_DIR/status.json"
  fi
  if [ -n "$local_root" ]; then rm -rf -- "$local_root"; fi
}
trap finish_preparation EXIT
trap 'exit 143' TERM INT HUP
printf '{"phase":"topology","fraction":0,"message":"Preparing remote runtime…"}\\n' > progress.tmp
mv progress.tmp progress.json
# Keep many small imports and temporary solvation files off shared filesystems
# when the node has enough scratch. Otherwise retain the scheduler workdir.
free_kb=$(df -Pk "${TMPDIR:-/tmp}" | awk 'NR==2 {print $4}')
if [ "$free_kb" -ge __MINIMUM_KIB__ ]; then
  local_root=$(mktemp -d "${TMPDIR:-/tmp}/nadoc-preparation.XXXXXXXX")
  tar -xzf "$PWD/bundle.tar.gz" -C "$local_root"
  cd "$local_root"
else
  tar -xzf bundle.tar.gz
fi
export OPENBLAS_NUM_THREADS=1 OMP_NUM_THREADS=1 MKL_NUM_THREADS=1
export UV_CACHE_DIR="$PWD/.uv-cache"
export UV_PYTHON_INSTALL_DIR="$PWD/.python"
./uv python install 3.12
./uv venv --python 3.12 .venv
./uv pip install --python .venv/bin/python -r requirements.txt
export PATH="$PWD/native/bin:$PATH"
unset NADOC_PSFGEN_BIN
for candidate in "$PWD"/native/psfgen-*; do
  if printf 'quit\\n' | "$candidate" >/dev/null 2>&1; then
    export NADOC_PSFGEN_BIN="$candidate"
    break
  fi
done
: "${NADOC_PSFGEN_BIN:?No compatible psfgen binary is available}"
gmx --version
.venv/bin/python -m backend.core.md_preparation_worker
'''.replace('__MINIMUM_KIB__', str(max(1, int(minimum_free_gb)) * 1024**2))


def import_result(archive_path, job_dir, *, expected_input_manifest=None):
    """Admit only hash-verified relative files from this preparation's output."""
    job_dir = Path(job_dir)
    with tempfile.TemporaryDirectory(prefix='.prep-result-', dir=job_dir) as tmp:
        stage = Path(tmp)
        with tarfile.open(archive_path) as archive:
            archive.extractall(stage, filter='data')
        result = json.loads((stage / 'result.json').read_text())
        if expected_input_manifest is not None and result.get('input_manifest_sha256') != expected_input_manifest:
            raise ValueError('Preparation result belongs to different frozen inputs')
        files = result['files']
        for relative, expected in files.items():
            path = (stage / relative).resolve()
            if not path.is_relative_to(stage.resolve()) or not path.is_file() or digest(path) != expected:
                raise ValueError(f'Preparation output hash mismatch: {relative}')
        subdir = result['package_subdir']
        package = (stage / subdir).resolve()
        if not package.is_relative_to(stage.resolve()) or not package.is_dir():
            raise ValueError('Invalid prepared package path')
        actual = {str(p.relative_to(stage)) for p in package.rglob('*') if p.is_file()}
        if actual != set(files):
            raise ValueError('Prepared package has missing or unrecorded files')
        target = (job_dir / subdir).resolve()
        if not target.is_relative_to(job_dir.resolve()):
            raise ValueError('Invalid local preparation destination')
        if target.exists():
            existing = {str(p.relative_to(job_dir)): digest(p) for p in target.rglob('*') if p.is_file()}
            if existing != files:
                raise ValueError('Existing package differs; refusing to replace it')
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(package, target)
        return result
