"""Run a bounded, sequential desktop CPU baseline using existing correctness gates.

Run: scripts/validation_guard.sh .venv/bin/python scripts/benchmark_desktop_baseline.py
No app server, browser, user design, remote job or simulation is launched.
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
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'docs/benchmarks/desktop/current_baseline.json'


def main():
    if os.environ.get('NADOC_VALIDATION_SCOPE') != '1':
        raise SystemExit('Run through scripts/validation_guard.sh to serialize resource usage.')
    archive = Path('/media/jojo/Archive')
    if not archive.is_mount():
        raise SystemExit('Archive must be mounted before benchmark imports.')
    scratch = ROOT / '.development-artifacts/desktop-benchmark/tmp'
    if not (ROOT / '.development-artifacts').resolve().is_relative_to(archive):
        raise SystemExit('Development artifacts must resolve onto Archive.')
    scratch.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ, TMPDIR=str(scratch.resolve()), PYTHONPATH=str(ROOT), PYTHONDONTWRITEBYTECODE='1')
    commands = [
        [sys.executable, '-m', 'scripts.benchmark_desktop_core'],
        ['node', 'frontend/scripts/benchmark-loading-open.mjs'],
        *[[sys.executable, 'scripts/benchmark_assembly_fk.py', '--count', str(n), '--repeats', '15', '--topology', topology]
          for n, topology in [(100, 'chain'), (500, 'chain'), (1500, 'chain'), (500, 'star')]],
        [sys.executable, 'scripts/benchmark_assembly_shared_index.py', '--pairs', '500', '--repeats', '15'],
        [sys.executable, 'scripts/benchmark_part_inputs.py'],
    ]
    sources = sorted({p for command in commands for p in command if p.endswith(('.py', '.mjs'))} | {'scripts/benchmark_desktop_core.py'})
    report = dict(started_utc=datetime.now(timezone.utc).isoformat(), platform=platform.platform(),
                  python=platform.python_version(), node=subprocess.check_output(['node', '--version'], text=True).strip(),
                  cpu=next((line.split(':', 1)[1].strip() for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), platform.processor()),
                  git_head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
                  dirty_paths=subprocess.check_output(['git', 'status', '--short'], cwd=ROOT, text=True).splitlines(),
                  harness_sha256={p: hashlib.sha256((ROOT / p).read_bytes()).hexdigest() for p in sources},
                  scope='Synthetic CPU microbenchmarks; not HTTP, GPU, browser FPS or user-observed latency.', runs=[])
    for command in commands:
        print('Running ' + ' '.join(command), flush=True)
        start = time.perf_counter()
        try:
            result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, timeout=300)
            row = dict(command=command, exit_code=result.returncode, wall_seconds=time.perf_counter() - start)
            try:
                row['result'] = json.loads(result.stdout)
            except json.JSONDecodeError:
                row['stdout_tail'] = result.stdout[-16000:]
            if result.returncode:
                row['stderr_tail'] = result.stderr[-16000:]
        except subprocess.TimeoutExpired:
            row = dict(command=command, exit_code=None, wall_seconds=time.perf_counter() - start, error='300 second timeout')
        report['runs'].append(row)
        OUT.write_text(json.dumps(report, indent=2) + '\n')
        print(f"  exit={row['exit_code']} seconds={row['wall_seconds']:.2f}", flush=True)
    report['scratch_remaining'] = [str(p.relative_to(scratch)) for p in scratch.rglob('*')]
    if not report['scratch_remaining']:
        scratch.rmdir()
        scratch.parent.rmdir()
    report['finished_utc'] = datetime.now(timezone.utc).isoformat()
    OUT.write_text(json.dumps(report, indent=2) + '\n')
    return int(any(r['exit_code'] != 0 for r in report['runs']))


if __name__ == '__main__':
    raise SystemExit(main())
