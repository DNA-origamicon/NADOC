"""Refresh four candidate operation timings before ranking the next three.

Run under validation_guard with TMPDIR pointing to mounted Archive scratch.
No app lifespan, scientific engine, user design or user job is opened.
"""
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/benchmarks/desktop'
BASELINE = '2f3b962966b4917d9f626e486d56680306600363'


def main():
    if os.environ.get('NADOC_VALIDATION_SCOPE') != '1':
        raise SystemExit('Use scripts/validation_guard.sh')
    archive = Path('/media/jojo/Archive')
    scratch = Path(os.environ['TMPDIR']).resolve()
    if not archive.is_mount() or not scratch.is_relative_to(archive):
        raise SystemExit('TMPDIR must resolve onto mounted Archive')
    workspace = scratch / 'round2-workspace'
    workspace.mkdir(exist_ok=True)
    env = dict(os.environ, NADOC_WORKSPACE=str(workspace), NADOC_DISABLE_SESSION_CACHE='1',
               NADOC_SURFACE_GPU='0', PYTHONDONTWRITEBYTECODE='1', PYTHONPATH=str(ROOT))
    commands = [
        ('geometry', [sys.executable, '-m', 'scripts.benchmark_desktop_core']),
        ('playback', ['node', 'frontend/scripts/benchmark-atomistic-playback.mjs', BASELINE]),
        ('surface', [sys.executable, '-m', 'scripts.benchmark_surface_generation', '--baseline', BASELINE, '--repeats', '3']),
        ('history', [sys.executable, '-m', 'scripts.benchmark_feature_evaluation', '--repeats', '5', '--iterations', '5', '--output', str(OUT/'round2_history_screen.json')]),
    ]
    sources = ['backend/core/design_geometry.py','backend/core/models.py','backend/core/surface.py',
               'backend/api/crud.py','frontend/src/scene/atomistic_renderer.js']
    report = dict(scope='Candidate screening only. CPU components and synthetic fixtures; no usage-frequency weighting or E2E claim. Existing baseline controls are not new speedups.',
                  python=platform.python_version(), platform=platform.platform(),
                  source_sha256={p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in sources}, runs=[])
    for name, command in commands:
        print('Screening '+name, flush=True)
        start=time.perf_counter()
        try:
            result=subprocess.run(command,cwd=ROOT,env=env,text=True,capture_output=True,timeout=180)
            row=dict(operation=name,command=command,exit_code=result.returncode,wall_seconds=time.perf_counter()-start,
                     stdout=result.stdout,stderr=result.stderr[-10000:])
        except subprocess.TimeoutExpired:
            row=dict(operation=name,command=command,exit_code=None,error='180 second timeout')
        report['runs'].append(row)
        (OUT/'round2_screen.json').write_text(json.dumps(report,indent=2)+'\n')
        print(name,row['exit_code'],flush=True)
    return int(any(r['exit_code'] != 0 for r in report['runs']))


if __name__=='__main__':
    raise SystemExit(main())
