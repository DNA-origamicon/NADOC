#!/usr/bin/env python3
"""Launch one registered local case with integrity checks and an exclusive lock."""
from __future__ import annotations

import argparse
import fcntl
import json
import os
import resource
import shutil
import subprocess
import sys
import time
from pathlib import Path

from reassess import ROOT, inventory, preflight, read, digest

QM_ENV = Path('/home/jojo/miniforge3/envs/nadoc-qm/bin')


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('campaign_root', type=Path)
    parser.add_argument('case_id')
    args = parser.parse_args()
    root = args.campaign_root.resolve()
    hold_path = root / 'local_execution_hold.json'
    if hold_path.exists():
        hold = read(hold_path)
        if (hold.get('schema') != 'nadoc.local-qm-execution-hold.v1'
                or hold.get('status') != 'active'):
            raise ValueError('local execution hold is malformed')
        raise ValueError(f"local QM execution is held: {hold.get('reason')}")
    _, jobs = inventory(root)
    matches = [j for j in jobs if j['id'] == args.case_id and j['stage'] in {'A', 'B', 'C', 'D'}]
    if len(matches) != 1:
        raise ValueError('select one exact registered local A/B/C/D case ID')
    item = matches[0]
    directory = Path(item['job_dir'])
    authorization_path = root / 'continuation_authorization.json'
    parallel = False
    if authorization_path.exists():
        authorization = read(authorization_path)
        if authorization.get('enabled') is True and digest(root / 'continuation_policy.json') == authorization['policy_sha256']:
            parallel = read(root / 'continuation_policy.json').get('maximum_parallel_core_jobs') == 3
    # Existing serial launchers retain their lock; explicit parallel admission counts
    # them through their durable launch receipts, without touching their processes.
    lock_path = directory / '.execution.lock' if parallel else root.parent / '.local-qm-fragment-execution.lock'
    with lock_path.open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        job = preflight(item)
        if item['stage'] == 'D':
            if not authorization_path.exists():
                raise ValueError('frequency execution needs an assessed scope')
            authorization = read(authorization_path)
            if (authorization.get('enabled') is not True
                    or digest(root / 'frequency_scope_v1.json') != authorization.get('frequency_scope_sha256')
                    or item['id'] not in authorization.get('frequency_order', [])
                    or job.get('job_kind') != 'frequency' or not job.get('parent_manifest')):
                raise ValueError('frequency job is not in the authorized parent-linked scope')
            scope_matches = [entry for entry in read(root / 'frequency_scope_v1.json')['jobs']
                             if entry['id'] == item['id']]
            if scope_matches != [item]:
                raise ValueError('frequency registration differs from the assessed scope')
        for name in ('output.dat', 'run_manifest.json', 'campaign_launch.json'):
            if (directory / name).exists():
                raise FileExistsError(f'refusing to overwrite prior attempt: {directory / name}')
        memory = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
        available_gib = int(memory['MemAvailable'].split()[0]) / 1024**2
        if available_gib < job['memory_gib'] + 4:
            raise ValueError('insufficient available RAM for requested Psi4 memory plus 4 GiB headroom')
        if shutil.disk_usage(root).free < 50 * 2**30:
            raise ValueError('Archive has less than 50 GiB free')
        if not os.access(QM_ENV / 'psi4', os.X_OK) or not os.access(QM_ENV / 'python', os.X_OK):
            raise ValueError('QM environment is unavailable')
        scratch_root = root / 'scratch' / item['id']
        scratch_root.mkdir(parents=True, exist_ok=True)
        receipt = {'started_epoch': time.time(), 'pid': os.getpid(),
                   'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                   'case_id': item['id'], 'job_manifest': item['job_manifest']}
        with (root.parent / '.local-qm-admission.lock').open('a') as admission:
            fcntl.flock(admission, fcntl.LOCK_EX)
            if parallel:
                running = []
                for other in jobs:
                    path = Path(other['job_dir']) / 'campaign_launch.json'
                    if not path.exists() or (path.parent / 'campaign_finish.json').exists():
                        continue
                    started = read(path)
                    if started.get('boot_id') == receipt['boot_id'] and Path(f"/proc/{started['pid']}").exists():
                        running.append(other)
                if running and (item['stage'] != 'A' or any(j['stage'] != 'A' for j in running)):
                    raise ValueError('boundary and frequency work remain serial until their benchmarks are assessed')
                if len(running) >= 3:
                    raise ValueError('three core jobs already admitted')
            with (directory / 'campaign_launch.json').open('x') as stream:
                json.dump(receipt, stream, indent=2)
        command = [str(QM_ENV / 'python'), str(ROOT / 'scripts/photoproduct_workflow.py'),
                   'run-qm-job', '--job-dir', str(directory), '--psi4', str(QM_ENV / 'psi4'),
                   '--scratch-dir', str(scratch_root)]
        try:
            result = subprocess.run(command, check=False)
            with (directory / 'campaign_finish.json').open('x') as stream:
                json.dump({'elapsed_seconds': time.time() - receipt['started_epoch'],
                           'returncode': result.returncode,
                           'peak_child_rss_kib': resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss},
                          stream, indent=2)
        finally:
            # Timer also catches SIGKILL/reboot when this callback cannot run.
            subprocess.run([sys.executable, str(Path(__file__).with_name('reassess.py')),
                            '--campaign-root', str(root), '--notify'], check=False)
        return result.returncode


if __name__ == '__main__':
    raise SystemExit(main())
