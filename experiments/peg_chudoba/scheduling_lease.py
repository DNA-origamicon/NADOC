"""Temporary, recoverable suspension of the historical PEG queue (system Python).

No simulation is created here. PID/start identities and pidfds protect signals.
The watchdog restores the old scheduler if the owning orchestration process dies.
New task trees are frozen before restoration, preserving their state for review.
"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import time

from experiments.peg_chudoba.serialize_existing import STATE, alive, process, send, tree


def write(path, data):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(data, indent=2) + '\n')
    temporary.replace(path)


def freeze(root):
    before = process(root['pid']) if alive(root) else None
    send(root, signal.SIGSTOP)
    deadline = time.monotonic() + 10
    while alive(root) and process(root['pid'])['state'] not in ('T', 't'):
        if time.monotonic() > deadline:
            raise RuntimeError(f'Cannot freeze {root["pid"]}')
        time.sleep(.02)
    members = {}
    for _ in range(2):
        for member in tree(root):
            members.setdefault((member['pid'], member['start']), member)
            send(member, signal.SIGSTOP)
    if before:
        members[(before['pid'], before['start'])] = before
    return list(members.values())


def restore(path, state):
    # Freeze any still-live new runs before restoring the original scheduler.
    for root in state.get('new_tasks', []):
        if alive(root):
            freeze(root)
    for member in reversed(state.get('previously_running', [])):
        send(member, signal.SIGCONT)
    if state.get('controller'):
        send(state['controller'], signal.SIGCONT)
    state.update(status='restored', restored_unix=time.time())
    write(path, state)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('action', choices=['park', 'restore', 'register', 'resume', 'resume-task', 'watch', 'handover'])
    ap.add_argument('--state', type=Path, required=True)
    ap.add_argument('--pid', type=int)
    ap.add_argument('--previous-owner', type=int)
    args = ap.parse_args()
    path = args.state.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if args.action == 'watch':
        while True:
            time.sleep(5)
            with path.with_suffix('.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                state = json.loads(path.read_text())
                if state['status'] == 'restored':
                    return
                if not alive(state['owner']):
                    restore(path, state)
                    return
    with path.with_suffix('.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if args.action == 'park':
            if path.exists() and json.loads(path.read_text())['status'] != 'restored':
                raise RuntimeError('Existing lease requires recovery')
            old = json.loads(STATE.read_text())
            controller = old.get('controller')
            if controller and alive(controller) and process(controller['pid'])['state'] in ('T', 't'):
                raise RuntimeError('Historical controller already suspended; inspect another lease before takeover')
            owner = process(args.pid)
            if not owner:
                raise ValueError('Owner is not live')
            state = dict(status='parking', owner=owner, controller=old.get('controller'),
                         roots=old['queue'], previously_running=[], new_tasks=[], created_unix=time.time())
            write(path, state)
            # Stop the controller before its launchers; keep it stopped throughout.
            if state['controller']:
                freeze(state['controller'])
            # Re-read after stopping the controller, in case it advanced a campaign.
            old = json.loads(STATE.read_text())
            state['roots'] = old['queue']
            for root in state['roots']:
                if not alive(root):
                    continue
                members = freeze(root)
                state['previously_running'].extend(p for p in members if p['state'] not in ('T', 't', 'Z'))
                write(path, state)
            state['status'] = 'parked'
            write(path, state)
            subprocess.Popen(['/usr/bin/python3', '-m', __spec__.name, 'watch', '--state', str(path)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL, start_new_session=True)
        else:
            state = json.loads(path.read_text())
            caller = process(os.getppid())
            caller_is_owner = caller and caller['pid'] == state['owner']['pid'] and caller['start'] == state['owner']['start']
            if args.action == 'handover':
                old = state['owner']
                if (not caller or args.previous_owner != old['pid'] or not alive(old)
                    or state['status'] != 'parked'
                    or 'experiments.peg_chudoba.run_bounded' not in old['command']
                    or 'experiments.peg_chudoba.scale_cpu' not in caller['command']):
                    raise RuntimeError('Handover requires the expected live bounded driver and scale_cpu caller')
                record = dict(previous_owner=old,new_owner=caller,unix=time.time(),frozen=[])
                record['frozen'].extend(freeze(old))
                for root in state['roots'] + state.get('new_tasks',[]):
                    if alive(root):
                        record['frozen'].extend(freeze(root))
                state.setdefault('handovers',[]).append(record)
                state['owner'] = caller
                write(path,state)
                # Ownership is durable before the retired driver exits. Native
                # children remain paused and are adopted without restarting.
                send(old,signal.SIGTERM)
                send(old,signal.SIGCONT)
                return
            if alive(state['owner']) and not caller_is_owner:
                raise RuntimeError('Only the live lease owner may change its scheduling state')
            if args.action == 'restore':
                if state['status'] != 'restored':
                    restore(path, state)
            elif args.action == 'register':
                root = process(args.pid)
                if root:
                    state['new_tasks'].append(root)
                    write(path, state)
            elif args.action in ('resume', 'resume-task'):
                candidates = state['roots'] if args.action == 'resume' else [p for r in state['roots'] + state.get('new_tasks',[]) for p in tree(r)]
                root = next(r for r in candidates if r['pid'] == args.pid)
                state['new_tasks'].append(root)
                write(path, state)
                for child in reversed(tree(root)):
                    send(child, signal.SIGCONT)


if __name__ == '__main__':
    main()
