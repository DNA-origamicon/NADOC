"""Attach a pidfd completion trigger to an already-running bounded diagnostic.

This observes process exit, then publishes its assessment for the existing durable
campaign watcher. It neither polls nor starts/restarts a scientific calculation.
"""
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import time

REPO = Path(os.environ.get('NADOC_REPO_ROOT', Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(REPO))
from experiments.cpd_published_comparator.trigger_dna_review import save


def properties(unit):
    out = subprocess.run(['systemctl', '--user', 'show', unit, '-p', 'MainPID',
                          '-p', 'ActiveState', '-p', 'ExecMainStatus', '-p', 'Result'],
                         text=True, capture_output=True)
    # A transient unit may be collected immediately after its process exits.
    # Retain the observation failure instead of losing the completion trigger.
    if out.returncode:
        return {'query_returncode': out.returncode, 'query_error': out.stderr}
    return dict(line.split('=', 1) for line in out.stdout.splitlines() if '=' in line)


def main(root):
    plan = json.loads((root/'attachment_plan.json').read_text())
    native = properties(plan['native_unit'])
    pid = int(native.get('MainPID', '0'))
    pidfd = None
    if pid:
        try:
            pidfd = os.pidfd_open(pid)
        except ProcessLookupError:
            pass
    state = dict(state='running', pid=os.getpid(), started_at=time.time(),
                 native_pid=pid, native_initial_properties=native,
                 observation='Blocking pidfd wait, no periodic polling',
                 minimum_certified=False, simulation_ready=False)
    save(root/'status.json', state)
    subprocess.run(['systemd-run', '--user', f"--unit={plan['unit']}-watch",
                    f'--setenv=PYTHONPATH={REPO}', '--property=Restart=on-failure',
                    '--property=RestartSec=30', '--property=StartLimitIntervalSec=300',
                    '--property=StartLimitBurst=5', '/usr/bin/python3',
                    str(root/'watcher.py'), '--root', str(root), '--thread', plan['thread']],
                   check=True)
    try:
        if pidfd is not None:
            select.select([pidfd], [], [])
        terminal = properties(plan['native_unit'])
        assessment_path = Path(plan['diagnostic_root'])/'assessment.json'
        assessment = json.loads(assessment_path.read_text()) if assessment_path.exists() else None
        complete = bool(assessment and assessment.get('completed'))
        code = terminal.get('ExecMainStatus')
        if code and code != '0':
            complete = False
        state.update(state='complete' if complete else 'failed',
                     native_terminal_properties=terminal,
                     assessment_path=str(assessment_path),
                     native_calculations_completed=bool(assessment and assessment.get('completed')),
                     scientific_reproducibility_pass=None if assessment is None else assessment.get('reproducibility_pass'),
                     completion_semantics='Native completion and reproducibility are distinct; independently audit before continuation.')
        log = subprocess.run(['journalctl', '--user', '-u', plan['native_unit'],
                              '--no-pager', '-o', 'short-iso'], capture_output=True, text=True)
        (root/'native_service_journal.txt').write_text(log.stdout+log.stderr)
    except BaseException as exc:
        state.update(state='failed', error=repr(exc))
        raise
    finally:
        if pidfd is not None:
            os.close(pidfd)
        state['finished_at'] = time.time()
        save(root/'status.json', state)


if __name__ == '__main__':
    main(Path(sys.argv[1]).resolve())
