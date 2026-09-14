#!/usr/bin/env python3
"""Run one control tick: assess completed work, launch at most one eligible job."""
from __future__ import annotations

import fcntl
import json
import subprocess
import sys
import time
from pathlib import Path

from reassess import DEFAULT, ROOT, atomic, digest, inventory, read, preflight

QM_PYTHON = '/home/jojo/miniforge3/envs/nadoc-qm/bin/python'
HERE = Path(__file__).resolve().parent


def unit_name(item: dict) -> str:
    return f"nadoc-local-qm-case-{item['id']}.service"


def active(item: dict) -> bool:
    result = subprocess.run(['systemctl', '--user', 'show', unit_name(item), '-p', 'ActiveState', '--value'],
                            capture_output=True, text=True, check=True)
    return result.stdout.strip() in {'active', 'activating', 'deactivating', 'reloading'}


def disposition(root: Path, state: str, **details) -> dict:
    report = {'schema': 'nadoc.local-qm-continuation.v1', 'status': state,
              'checked_epoch': time.time(), 'gate_effect': 'none', 'simulation_ready': False, **details}
    atomic(root / 'review/continuation.json', report)
    return report


def tick(root: Path) -> dict:
    hold_path = root / 'local_execution_hold.json'
    if hold_path.exists():
        hold = read(hold_path)
        if (hold.get('schema') != 'nadoc.local-qm-execution-hold.v1'
                or hold.get('status') != 'active'):
            raise ValueError('local execution hold is malformed')
        return disposition(root, 'local_execution_held',
                           reason=hold.get('reason'),
                           replacement=hold.get('replacement'))
    authorization = read(root / 'continuation_authorization.json')
    if authorization.get('enabled') is not True:
        return disposition(root, 'disabled')
    policy_path = root / 'continuation_policy.json'
    if digest(policy_path) != authorization['policy_sha256']:
        raise ValueError('continuation policy changed; assessment must be revisited')
    _, all_jobs = inventory(root)
    by_id = {item['id']: item for item in all_jobs}
    jobs = [by_id[name] for name in authorization['geometry_order']]
    frequency_ids = authorization.get('frequency_order', [])
    if frequency_ids:
        scope_path = root / 'frequency_scope_v1.json'
        if digest(scope_path) != authorization.get('frequency_scope_sha256'):
            raise ValueError('frequency scope changed since assessment')
        scope = read(scope_path)
        if frequency_ids != [j['id'] for j in scope['jobs']]:
            raise ValueError('frequency queue does not match the scoped cohort')
        for record in scope['jobs']:
            if by_id[record['id']] != record or record['stage'] != 'D':
                raise ValueError('frequency registration differs from scope')
            frequency_job = preflight(record)
            if frequency_job.get('job_kind') != 'frequency' or not frequency_job.get('parent_manifest'):
                raise ValueError('stage D scope requires parent-linked frequency jobs')
        jobs += [by_id[name] for name in frequency_ids]
    running = [item['id'] for item in all_jobs if active(item)]
    reports = []
    for stage in (('A', 'B', 'D') if frequency_ids else ('A', 'B')):
        members = [j for j in jobs if j['stage'] == stage]
        pending = []
        for item in members:
            directory = Path(item['job_dir'])
            preflight(item)
            if item['id'] in running:
                continue
            if not (directory / 'run_manifest.json').exists():
                if any((directory / n).exists() for n in ('output.dat', 'campaign_launch.json')):
                    return disposition(root, 'hold', case=item['id'], reason='interrupted attempt has no completion receipt')
                pending.append(item)
                continue
            report = assessment(root, item, policy_path)
            reports.append(report)
            if report['decision'] != 'continue':
                return disposition(root, 'hold', case=item['id'], reasons=report['issues'])
        limit = read(policy_path)['maximum_parallel_core_jobs'] if stage == 'A' else 1
        if pending and len(running) < limit:
            launch(pending[0], root)
            return disposition(root, 'launched', case=pending[0]['id'], already_running=running)
        if any(j['id'] in running for j in members) or pending:
            return disposition(root, 'running', jobs=running, pending=[j['id'] for j in pending])
        if members:
            atomic(root / 'review_inputs' / f"automatic-stage-{stage}.json",
                   {'status': 'favorable_for_next_evidence_set', 'gate_effect': 'none',
                    'assessments': [{'id': r['id'], 'run_sha256': r['run_sha256'], 'decision': r['decision']}
                                    for r in reports if r['stage'] == stage],
                    'limitation': 'candidate evidence only; frozen fit and transfer metrics still required before C'})
    # A/B deliver candidate geometries. A primary response/charge target specification
    # is a real scientific prerequisite; missing scope is not a favorable assessment.
    return disposition(root, 'hold_for_primary_fit' if frequency_ids else 'hold_for_response_and_fit_scope',
                       reason=('A/B and the scoped frequency cohort passed; reconcile reused core frequencies, '
                               'scope charges/scans, freeze primary fit and transfer metrics before C') if frequency_ids else
                              'A/B geometry evidence passed; scope and benchmark D, freeze primary fit/transfer metrics before C',
                       completed_geometry_jobs=[j['id'] for j in jobs])


def assessment(root: Path, item: dict, policy_path: Path) -> dict:
    cache = root / 'review_inputs' / f"automatic-{item['id']}.json"
    job_dir = Path(item['job_dir'])
    signature = {'run': digest(job_dir / 'run_manifest.json'), 'policy': digest(policy_path),
                 'assessor': digest(HERE / 'assess_candidate.py')}
    # Always validate outputs before considering cached scientific decisions.
    run = read(job_dir / 'run_manifest.json')
    for name, record in run.get('outputs', {}).items():
        if Path(name).name != name or digest(job_dir / name) != record['sha256']:
            raise ValueError(f'changed output: {item["id"]}/{name}')
    if cache.exists():
        old = read(cache)
        if old.get('assessment_signature') == signature:
            audit = old['domain_audit']
            if digest(Path(audit['path'])) != audit['sha256']:
                raise ValueError('domain audit changed since assessment')
            return old
    item_path = root / 'review' / f"assessment-item-{item['id']}.json"
    atomic(item_path, item)
    result = subprocess.run([QM_PYTHON, str(HERE / 'assess_candidate.py'), '--item', str(item_path),
                             '--policy', str(policy_path)], capture_output=True, text=True, timeout=120)
    if result.returncode:
        raise ValueError(f"assessment failed for {item['id']}: {result.stderr[-3000:]}")
    report = json.loads(result.stdout)
    report['assessment_signature'] = signature
    atomic(cache, report)
    return report


def launch(item: dict, root: Path) -> None:
    job = preflight(item)
    subprocess.run(['systemd-run', '--user', '--collect', f'--unit={unit_name(item)}',
                    f'--property=WorkingDirectory={ROOT}', f"--property=MemoryMax={job['memory_gib']+(2 if item['stage']=='A' else 4)}G",
                    f"--property=CPUQuota={job['threads']*100}%", '--property=Nice=10', '--property=Restart=no',
                    str(ROOT / '.venv/bin/python'), str(HERE / 'run_case.py'), str(root), item['id']], check=True)


def main() -> int:
    root = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    with (root / 'review/.continuation.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        try:
            report = tick(root)
        except Exception as exc:
            report = disposition(root, 'hold', reason=str(exc))
        print(json.dumps(report))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
