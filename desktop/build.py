"""Build a self-contained Linux directory from pinned JS and installed Python deps.

Run under validation_guard.sh after npm ci, Electron installation, and Vite build.
Supply an unpacked python-build-standalone 3.12 runtime (e.g. `uv python install`).
No user workspace, credentials, development evidence or simulation jobs are bundled.
"""

import argparse
import ast
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def copy_tree(source, dest):
    shutil.copytree(source, dest, ignore_dangling_symlinks=True, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", "node_modules", ".pytest_cache", ".git", "build", "dist", "runtime", "payload"))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--python", type=Path, required=True, help="Standalone Python root containing bin/python3")
    args = parser.parse_args()
    out = args.output.resolve()
    runtime = args.python.resolve()
    if sys.platform != "linux":
        parser.error("This initial packager is validated for Linux only")
    if out.exists():
        parser.error("Output must be a new directory; existing releases are never overwritten")
    if not (runtime / "bin/python3").exists():
        parser.error("Standalone Python runtime missing bin/python3")
    if not (ROOT / "frontend/dist/index.html").exists():
        parser.error("Build frontend production assets first")
    out.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(out.parent).free < 8 * 1024**3:
        parser.error("At least 8 GiB free space required for release staging")
    out.mkdir()
    subprocess.run([str(ROOT / "desktop/node_modules/.bin/electron-packager"), str(ROOT / "desktop"),
                    "NADOC", "--platform=linux", "--arch=x64", "--out=" + str(out),
                    "--ignore=^/(node_modules|dist|runtime|payload|benchmark\\.cjs|.*\\.test\\.cjs|.*\\.py)$"], check=True)
    release = out / "NADOC-linux-x64"
    payload = release / "resources/payload"
    payload.mkdir()
    for name in ("backend", "tools", "scripts"):
        copy_tree(ROOT / name, payload / name)
    # Python runtime imports a few experiment-owned helpers. Bundle source code,
    # never scientific output trees, job state, or unreviewed molecular examples.
    for source_file in (ROOT / 'experiments').rglob('*.py'):
        target = payload / source_file.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source_file, target)
    (payload / "desktop").mkdir()
    for name in ("__init__.py", "backend.py"):
        shutil.copy2(ROOT / "desktop" / name, payload / "desktop" / name)
    from build_native import build
    native_library = build(payload / "backend/core/_domain_assignment_native.so")
    (payload / "native/desktop").mkdir(parents=True)
    shutil.copy2(ROOT / "native/desktop/domain_assignment.cpp", payload / "native/desktop/domain_assignment.cpp")
    # Placement audit source identities remain inspectable in the release.
    copy_tree(ROOT / "frontend/src", payload / "frontend/src")
    copy_tree(ROOT / "native/vr_viewer/src", payload / "native/vr_viewer/src")
    shutil.copy2(ROOT / "frontend/native_placement_reporter.js", payload / "frontend/native_placement_reporter.js")
    shutil.copytree(ROOT / "frontend/dist", payload / "frontend/dist")
    for name in ("pyproject.toml", "uv.lock"):
        shutil.copy2(ROOT / name, payload / name)
    python_dest = release / "resources/python"
    shutil.copytree(runtime, python_dest, symlinks=False)
    site = python_dest / "lib/python3.12/site-packages"
    site.mkdir(parents=True, exist_ok=True)
    installed_site = ROOT / ".venv/lib/python3.12/site-packages"
    vendored = {}
    for finder in installed_site.glob('__editable__*finder.py'):
        tree = ast.parse(finder.read_text())
        mapping = next(ast.literal_eval(node.value) for node in tree.body
                       if isinstance(node, ast.AnnAssign) and getattr(node.target, 'id', None) == 'MAPPING')
        for name, location in mapping.items():
            copy_tree(Path(location), site / name)
            vendored[name] = {'source': location, 'reason': 'Materialized editable installation; no host-path finder in release'}
            for license_name in ('LICENSE', 'LICENSE.txt', 'COPYING'):
                license_file = Path(location).parent / license_name
                if license_file.is_file():
                    shutil.copy2(license_file, site / f'{name}-{license_name}')
    for item in installed_site.iterdir():
        if item.name == "__pycache__" or item.name.startswith(('__editable__', '_virtualenv')):
            continue
        target = site / item.name
        if item.is_dir():
            shutil.copytree(item, target, dirs_exist_ok=True, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        else:
            shutil.copy2(item, target)
    launcher = release / "NADOC.sh"
    launcher.write_text('#!/bin/sh\nunset ELECTRON_RUN_AS_NODE PYTHONHOME PYTHONPATH\nexec "$(dirname "$(readlink -f "$0")")/NADOC" "$@"\n')
    launcher.chmod(0o755)
    shutil.copy2(ROOT / "desktop/icon.svg", release / "nadoc.svg")
    shutil.copy2(ROOT / "desktop/install.py", release / "install.py")
    # Bind the exact worktree bytes, including pre-existing uncommitted changes.
    files = {}
    for base in (payload, release / "resources/app"):
        for file in sorted(base.rglob("*")):
            if file.is_file():
                files[str(file.relative_to(release))] = hashlib.sha256(file.read_bytes()).hexdigest()
    version = subprocess.check_output([str(python_dest / "bin/python3"), "--version"], text=True).strip()
    deps = subprocess.check_output([str(ROOT / ".venv/bin/python"), "-m", "pip", "freeze"], text=True) if (ROOT / ".venv/bin/pip").exists() else subprocess.check_output(["uv", "pip", "freeze", "--python", str(ROOT / ".venv/bin/python")], text=True)
    (release / "python-dependencies.txt").write_text(deps)
    (release / "release-manifest.json").write_text(json.dumps({"schema": 1, "python": version,
        "platform": "linux-x64", "dependencies": "python-dependencies.txt", "native_domain_library": str(native_library.relative_to(release)), "vendored_editables": vendored, "files": files}, indent=2))
    print(release)


if __name__ == "__main__":
    main()
