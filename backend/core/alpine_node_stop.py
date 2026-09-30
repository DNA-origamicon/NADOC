"""Strictly scoped compute-node stop helper, also executable via SSH using stdlib only.

Used only after a scheduler cancellation fails. Refuses missing/ambiguous identity,
multiple process groups, foreign owners, or a different working directory.
"""

import json
import os
from pathlib import Path
import signal
import sys
import time


def snapshot(proc, uid):
    records = []
    for directory in proc.iterdir():
        if not directory.name.isdigit():
            continue
        try:
            owned = directory.stat().st_uid == uid
            fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
            record = dict(
                pid=int(directory.name), pgid=int(fields[2]), start=fields[19],
                command=[], environment=[], cgroup='', cwd='', state=fields[0], owned=owned,
            )
            if not owned:
                records.append(record)
                continue
            try:
                record.update(
                    command=(directory / 'cmdline').read_bytes().split(b'\0'),
                    environment=(directory / 'environ').read_bytes().split(b'\0'),
                    cgroup=(directory / 'cgroup').read_text(),
                    cwd=str((directory / 'cwd').resolve()),
                )
            except PermissionError:
                # Unreadable processes remain visible to the group check, which
                # refuses them if they belong to the candidate group.
                pass
            records.append(record)
        except (FileNotFoundError, ProcessLookupError):
            continue
    return records


def verified_group(records, job_id, scratch, observer_pgid=None):
    expected_env = f'SLURM_JOB_ID={job_id}'.encode()
    batch_path = f'/var/spool/slurmd/job{job_id}/slurm_script'.encode()
    roots = [r for r in records if batch_path in r['command']]
    if len(roots) != 1 or roots[0]['pgid'] != roots[0]['pid']:
        raise RuntimeError('No unique batch-shell process group for this SLURM job')
    pgid = roots[0]['pgid']
    members = [r for r in records if r['pgid'] == pgid]
    # pam_slurm_adopt puts this SSH helper in the allocation's extern step and
    # may set SLURM_JOB_ID. It is not part of the batch workload we are stopping.
    related = [r for r in records if expected_env in r['environment']
               and not (r['pgid'] == observer_pgid and '/step_extern' in r['cgroup'])]
    if any(r['pgid'] != pgid for r in related):
        raise RuntimeError('Job spans multiple process groups; refusing direct stop')
    for r in members:
        if (not r['owned'] or expected_env not in r['environment'] or f'/job_{job_id}/' not in r['cgroup']
                or r['cwd'] != scratch):
            raise RuntimeError('Process identity does not match the requested job and directory')
    return pgid, sorted(r['pid'] for r in members)


def stop(job_id, scratch):
    if not job_id.isdigit() or not Path(scratch).is_absolute():
        raise ValueError('Expected numeric SLURM job ID and absolute scratch directory')
    proc = Path('/proc')
    records = snapshot(proc, os.getuid())
    observer_pgid = os.getpgrp()
    pgid, pids = verified_group(records, job_id, str(Path(scratch).resolve()), observer_pgid)
    # Recheck identities immediately before signalling to reject exited/reused PIDs.
    again = snapshot(proc, os.getuid())
    if verified_group(again, job_id, str(Path(scratch).resolve()), observer_pgid) != (pgid, pids):
        raise RuntimeError('Job process group changed during verification')
    original = {r['pid']: r['start'] for r in records if r['pid'] in pids}
    if any(r['start'] != original[r['pid']] for r in again if r['pid'] in pids):
        raise RuntimeError('Process identity changed during verification')
    os.killpg(pgid, signal.SIGTERM)
    time.sleep(3)
    remaining = [r['pid'] for r in snapshot(proc, os.getuid()) if r['pgid'] == pgid]
    if remaining:
        raise RuntimeError(f'Job process group still exists after SIGTERM: {remaining}')
    return dict(job_id=job_id, method='verified_node_sigterm', pids=pids,
                processes_stopped=True, allocation_release_confirmed=False, checked_at=time.time())


if __name__ == '__main__':
    print(json.dumps(stop(sys.argv[1], sys.argv[2])))
