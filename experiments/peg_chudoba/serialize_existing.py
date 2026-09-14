"""Serialize already allocated PEG campaign trees, preserving live process state.

Linux only. No simulations are created or restarted. SIGSTOP retains RAM/VRAM.
Run with --apply to adopt the current campaigns; without it, only inspect.
Restarting with --apply recovers the saved queue using PID start-time identities.
The state records pause intervals; run.json elapsed_seconds includes those pauses.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import time

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / 'experiments/peg_chudoba/serial_schedule.json'


def process(pid):
    try:
        p = Path('/proc') / str(pid)
        fields = (p / 'stat').read_text().split(') ', 1)[1].split()
        return dict(pid=int(pid), start=fields[19], state=fields[0],
                    name=(p / 'comm').read_text().strip(),
                    parent=int(fields[1]),
                    command=(p / 'cmdline').read_bytes().replace(b'\0', b' ').decode(),
                    cwd=str((p / 'cwd').resolve()),
                    stdout=str((p / 'fd/1').resolve()))
    except (OSError, ValueError):
        return None


def alive(record):
    now = process(record['pid'])
    return now and now['start'] == record['start'] and now['state'] != 'Z'


def send(record, sig):
    try:
        fd = os.pidfd_open(record['pid'])
    except ProcessLookupError:
        return
    try:
        if alive(record):
            signal.pidfd_send_signal(fd, sig)
    finally:
        os.close(fd)


def table():
    return {p['pid']: p for d in Path('/proc').iterdir()
            if d.name.isdigit() and (p := process(int(d.name)))}


def tree(root):
    rows = table()
    if not alive(root):
        return []
    found = [rows[root['pid']]]
    for parent in found:
        found.extend(p for p in rows.values() if p['parent'] == parent['pid'])
    return found


def discover():
    rows = table()
    candidates = {pid: p for pid, p in rows.items()
                  if p['cwd'] == str(ROOT) and p['name'].startswith('python') and
                  (' -m experiments.peg_chudoba.run_' in p['command'] or
                   (p['command'].strip() == 'python -u -' and
                    p['stdout'].startswith('/tmp/nadoc-peg-')))}
    roots = []
    for pid, p in candidates.items():
        parent = p['parent']
        while parent in rows and parent not in candidates:
            parent = rows[parent]['parent']
        if parent not in candidates:
            roots.append(p)
    # Existing extension 8 is close to completion. Delayed launchers follow
    # ordinary drivers, ensuring their predecessor checks can terminate.
    roots.sort(key=lambda p: (0 if 'round8' in p['command'] else
                             2 if p['command'].strip() == 'python -u -' else 1,
                             p['pid']))
    return roots


def save(state):
    state['updated_unix'] = time.time()
    temporary = STATE.with_suffix('.tmp')
    temporary.write_text(json.dumps(state, indent=2) + '\n')
    temporary.replace(STATE)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    if not args.apply:
        print(json.dumps(discover(), indent=2))
        return
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise SystemExit('Use /usr/bin/python3: this interpreter lacks Linux pidfd support.')
    with STATE.with_suffix('.lock').open('w') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = json.loads(STATE.read_text()) if STATE.exists() else {
            'created_unix': time.time(), 'policy': 'One existing PEG campaign at a time',
            'queue': discover(), 'events': [],
            'limitations': 'SIGSTOP retains RAM/VRAM; elapsed_seconds includes pauses. '
                          'Does not admit newly launched campaigns. Do not launch additional benchmarks.'}
        state['controller'] = process(os.getpid())
        save(state)
        # Freeze parents before children, then rescan to catch a child forked
        # just before its parent stopped. All campaign launchers are held first.
        for root in state['queue']:
            send(root, signal.SIGSTOP)
        while any(alive(root) and process(root['pid'])['state'] not in ('T', 't')
                  for root in state['queue']):
            time.sleep(.05)
        for root in state['queue']:
            for _ in range(2):
                for child in tree(root):
                    send(child, signal.SIGSTOP)
        state['events'].append({'event': 'all_campaigns_suspended', 'unix': time.time()})
        save(state)
        for root in state['queue']:
            if not alive(root):
                continue
            members = tree(root)
            state['active_campaign'] = root
            state['events'].append({'event': 'resume_campaign', 'pid': root['pid'], 'unix': time.time()})
            save(state)
            for child in reversed(members):
                send(child, signal.SIGCONT)
            while alive(root):
                known = {(child['pid'], child['start']) for child in members}
                members.extend(child for child in tree(root)
                               if (child['pid'], child['start']) not in known)
                time.sleep(5)
            state['events'].append({'event': 'campaign_exited', 'pid': root['pid'], 'unix': time.time()})
            # A failed launcher may leave native children. Never overlap those
            # with the next campaign; retain their identity and wait for exit.
            while any(alive(child) for child in members):
                time.sleep(5)
            save(state)
        state['active_campaign'] = None
        state['finished_unix'] = time.time()
        save(state)


if __name__ == '__main__':
    main()
