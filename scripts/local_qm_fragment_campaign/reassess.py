#!/usr/bin/env python3
"""Reassess campaign evidence; durable, deduplicated review requests, never launch QM."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import shutil
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DEFAULT = Path('/media/jojo/Archive/NADOC_archive/photoproduct_evidence/tt-cpd-local-fragment-campaign-v1')
PASSED_IDENTITY = {'passed_identity_and_chirality', 'passed_candidate_identity_and_chirality'}


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(block)
    return result.hexdigest()


def valid(record: dict) -> bool:
    path = Path(record.get('path', ''))
    return path.is_file() and digest(path) == record.get('sha256')


def atomic(path: Path, value: dict) -> None:
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, indent=2) + '\n')
    temporary.replace(path)


def inventory(root: Path) -> tuple[dict, list[dict]]:
    preparation = read(root / 'review_preparation.json')
    if not valid(preparation['campaign']):
        raise ValueError('campaign manifest changed since review preparation')
    jobs = list(preparation['jobs'])
    extension = root / 'review_extensions.json'
    if extension.exists():
        extra = read(extension)
        if extra.get('schema') != 'nadoc.local-qm-review-extensions.v1':
            raise ValueError('invalid review extensions schema')
        for job in extra['jobs']:
            if job['stage'] not in {'D', 'E'} or not valid(job['job_manifest']):
                raise ValueError('invalid deferred-stage job registration')
            jobs.append(job)
    if len({j['id'] for j in jobs}) != len(jobs):
        raise ValueError('duplicate campaign job ID')
    return preparation, jobs


def preflight(item: dict) -> dict:
    directory = Path(item['job_dir'])
    if not valid(item['job_manifest']) or Path(item['job_manifest']['path']).resolve() != (directory / 'job_manifest.json').resolve():
        raise ValueError('registered job manifest missing or changed')
    job = read(directory / 'job_manifest.json')
    if digest(directory / 'input.dat') != job['input']['sha256']:
        raise ValueError('input digest mismatch')
    for key in ('source_xyz', 'model_manifest', 'parent_manifest'):
        if job.get(key) and not valid(job[key]):
            raise ValueError(f'{key} missing or changed')
    protocol = ROOT / 'backend/data/forcefield' / f"photoproduct_qm_protocol_v{job['protocol_version']}.json"
    if not protocol.is_file() or digest(protocol) != job['protocol_sha256']:
        raise ValueError('pinned protocol missing or changed')
    if len(job['atom_map']) != job['atom_count'] or len(set(job['atom_map'])) != job['atom_count']:
        raise ValueError('invalid atom map')
    return job


def job_state(item: dict, now: float) -> dict:
    directory = Path(item['job_dir'])
    result = {'id': item['id'], 'stage': item['stage'], 'state': 'prepared', 'alerts': []}
    try:
        job = preflight(item)
        launch_path = directory / 'campaign_launch.json'
        output = directory / 'output.dat'
        run_path = directory / 'run_manifest.json'
        audit_name = 'frequency_audit.json' if job['job_kind'] == 'frequency' else 'optimized_model_audit.json'
        audit_path = directory / audit_name
        launch = read(launch_path) if launch_path.exists() else None
        if run_path.exists():
            run = read(run_path)
            result['run_sha256'] = digest(run_path)
            if run.get('job_manifest_sha256') != digest(directory / 'job_manifest.json'):
                raise ValueError('run/job digest mismatch')
            for name, record in run.get('outputs', {}).items():
                if Path(name).name != name or not (directory / name).is_file() or digest(directory / name) != record['sha256']:
                    raise ValueError(f'run output digest mismatch: {name}')
            result['state'] = 'completed_unreviewed' if run.get('status') == 'completed_unreviewed' else 'failed'
            if result['state'] == 'failed':
                result['alerts'].append('execution_failed')
            elif audit_path.exists():
                audit = read(audit_path)
                result['audit_sha256'] = digest(audit_path)
                if job['job_kind'] == 'geometry_optimization':
                    if not valid(audit.get('effective_run_record', {})) or not valid(audit.get('optimized_xyz', {})):
                        raise ValueError('identity audit provenance mismatch')
                    if audit.get('product_id') != job['product_id'] or audit.get('model_id') != job['model_id']:
                        raise ValueError('identity audit belongs to another model')
                    if audit.get('status') in PASSED_IDENTITY and audit.get('chirality_audit', {}).get('passed') is True:
                        result['state'] = 'identity_passed_minimum_unconfirmed'
                    else:
                        result['alerts'].append('identity_or_chirality_failed')
                elif job['job_kind'] == 'frequency':
                    for key in ('effective_run_record', 'output', 'parent_optimized_model_audit'):
                        if not valid(audit.get(key, {})):
                            raise ValueError(f'frequency audit {key} mismatch')
                    if audit.get('product_id') != job['product_id'] or audit.get('model_id') != job['model_id']:
                        raise ValueError('frequency audit belongs to another model')
                    result['domain_audit_status'] = audit.get('status')
                    if audit.get('status') not in {'passed_harmonic_minimum', 'passed_candidate_harmonic_minimum'}:
                        result['alerts'].append('harmonic_minimum_failed')
                result['alerts'].append('scientific_review_required')
            else:
                result['alerts'].append('domain_audit_required')
        elif output.exists() or launch:
            result['state'] = 'started_without_completion_receipt'
            if output.exists() and now - output.stat().st_mtime > 2 * 3600:
                result['alerts'].append('no_output_progress_2h')
            if not launch:
                result['alerts'].append('untracked_or_interrupted_execution')
            else:
                elapsed = (now - launch['started_epoch']) / 3600
                result['elapsed_hours'] = round(elapsed, 2)
                if elapsed > item.get('wall_hours', 18):
                    result['alerts'].append('wall_budget_exceeded')
                elif elapsed > item.get('wall_hours', 18) / 2:
                    result['alerts'].append('half_wall_budget_review')
                if not output.exists() and elapsed > 0.25:
                    result['alerts'].append('no_output_15min_after_launch')
                if not Path(f"/proc/{launch['pid']}").exists() or launch.get('boot_id') != Path('/proc/sys/kernel/random/boot_id').read_text().strip():
                    result['alerts'].append('launcher_gone_without_receipt')
        if launch and run_path.exists():
            result['elapsed_hours'] = round((run_path.stat().st_mtime - launch['started_epoch']) / 3600, 2)
        finish = directory / 'campaign_finish.json'
        if finish.exists():
            result['measured_resources'] = read(finish)
    except (OSError, ValueError, KeyError, TypeError) as exc:
        result['state'] = 'invalid_evidence'
        result['alerts'].append(str(exc))
    return result


def assess(root: Path, now: float | None = None) -> dict:
    now = time.time() if now is None else now
    preparation, jobs = inventory(root)
    states = [job_state(job, now) for job in jobs]
    events = []
    for state in states:
        if state['state'] != 'prepared':
            stable = {k: v for k, v in state.items() if k != 'elapsed_hours'}
            events.append({'kind': 'job_checkpoint', 'subject': state['id'], 'evidence': stable})
        if state['id'] in preparation['benchmarks'] and 'run_sha256' in state:
            events.append({'kind': 'benchmark_review', 'subject': state['id'], 'evidence': state})
    stages = {}
    for stage in 'ABCDE':
        members = [s for s in states if s['stage'] == stage]
        terminal = bool(members) and all('run_sha256' in s and s['state'] != 'invalid_evidence' for s in members)
        stages[stage] = {'registered_jobs': len(members), 'execution_finished': terminal,
                         'scientific_status': 'review_required' if terminal else 'pending',
                         'job_ids': [s['id'] for s in members]}
        if terminal:
            events.append({'kind': 'stage_finished_review', 'subject': stage,
                           'evidence': [{k: v for k, v in s.items() if k != 'elapsed_hours'} for s in members]})
    for filename in preparation.get('observed_receipts', []):
        path = Path(filename)
        if path.exists():
            events.append({'kind': 'external_collection_review', 'subject': str(path),
                           'evidence': {'sha256': digest(path), 'status': read(path).get('status')}})
    watched = list(root.parent.glob('alpine-qm-*boundary*/collection_report.json'))
    watched += list((root / 'review_inputs').glob('*.json'))
    for path in sorted(set(watched)):
        events.append({'kind': 'review_receipt_changed', 'subject': str(path),
                       'evidence': {'sha256': digest(path), 'status': read(path).get('status')}})
    continuation_path = root / 'review/continuation.json'
    if continuation_path.exists():
        continuation = read(continuation_path)
        if continuation.get('status', '').startswith('hold'):
            events.append({'kind': 'continuation_hold', 'subject': continuation['status'],
                           'evidence': {k: v for k, v in continuation.items() if k != 'checked_epoch'}})
    free_gib = shutil.disk_usage(root).free / 2**30
    if free_gib < 50:
        events.append({'kind': 'resource_review', 'subject': 'archive_free_below_50GiB', 'evidence': {}})
    meminfo = dict(line.split(':', 1) for line in Path('/proc/meminfo').read_text().splitlines())
    if int(meminfo['MemAvailable'].split()[0]) < 4 * 1024**2:
        events.append({'kind': 'resource_review', 'subject': 'available_RAM_below_4GiB', 'evidence': {}})
    return {'schema': 'nadoc.local-qm-reassessment.v1', 'checked_epoch': now,
            'gate_effect': 'none', 'simulation_ready': False, 'jobs': states, 'stages': stages,
            'archive_free_gib': round(free_gib, 1), 'events': events}


def persist(root: Path, report: dict, notify: bool = False) -> list[dict]:
    review = root / 'review'
    review.mkdir(exist_ok=True)
    event_dir = review / 'events'
    event_dir.mkdir(exist_ok=True)
    new = []
    for event in report['events']:
        key = hashlib.sha256(json.dumps(event, sort_keys=True).encode()).hexdigest()
        path = event_dir / f'{key}.json'
        if not path.exists():
            atomic(path, {**event, 'detected_epoch': report['checked_epoch'],
                          'action': 'Reassess using docs/cpd_qm_fragment_campaign.md before dependent work; no automatic advance.'})
            new.append(event)
    continuation_path = review / 'continuation.json'
    if continuation_path.exists():
        report['continuation'] = read(continuation_path)
    atomic(review / 'latest.json', report)
    lines = ['# Local QM campaign reassessment', '',
             'Evidence only; stage completion never grants scientific acceptance.', '',
             '| Job | State | Review signals |', '|---|---|---|']
    lines += [f"| {s['id']} | {s['state']} | {', '.join(s['alerts']) or 'none'} |" for s in report['jobs']]
    lines += ['', 'Stage execution: ' + ', '.join(f"{k}={v['scientific_status']}" for k, v in report['stages'].items()),
              '', 'Review requests are retained in `events/`. No AI session is scheduled by this monitor.']
    if report.get('continuation'):
        continuation = report['continuation']
        lines += ['', f"Continuation controller: **{continuation['status']}**.",
                  continuation.get('reason', ''),
                  'Current cases: ' + ', '.join(continuation.get('jobs') or [continuation.get('case', '')])]
    (review / 'latest.md').write_text('\n'.join(lines) + '\n')
    if new and notify and shutil.which('notify-send'):
        subprocess.run(['notify-send', 'NADOC QM campaign: reassessment due',
                        f"{len(new)} new checkpoint(s). Read {review / 'latest.md'}"], check=False, timeout=10)
    return new


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--campaign-root', type=Path, default=DEFAULT)
    parser.add_argument('--notify', action='store_true')
    args = parser.parse_args()
    review = args.campaign_root / 'review'
    review.mkdir(exist_ok=True)
    with (review / '.monitor.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            report = assess(args.campaign_root)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            report = {'checked_epoch': time.time(), 'gate_effect': 'none', 'simulation_ready': False,
                      'jobs': [], 'stages': {}, 'events': [{'kind': 'monitor_error', 'subject': str(exc), 'evidence': {}}]}
        new = persist(args.campaign_root, report, args.notify)
        print(json.dumps({'new_review_requests': len(new), 'report': str(review / 'latest.md')}))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
