"""Event-driven audit of one real managed ramp; no completion/status polling.

Watches atomic job.json replacement with inotify. Journals every block verdict,
alerts on stage completion, retries, terminal failure, or a stalled worker, and
verifies GPU/unguarded stage inputs. Existing molecular files are read only.
"""
import argparse
import ctypes
import hashlib
import json
import os
from pathlib import Path
import select
import time


def monitor(directory, output, *, idle_seconds=1200):
    directory, output = Path(directory).resolve(), Path(output).resolve()
    output.mkdir(parents=True, exist_ok=True)
    libc = ctypes.CDLL(None, use_errno=True)
    fd = libc.inotify_init1(os.O_NONBLOCK | os.O_CLOEXEC)
    if fd < 0:
        raise OSError(ctypes.get_errno(), 'inotify_init1')
    if libc.inotify_add_watch(fd, str(directory).encode(), 0x8 | 0x80) < 0:
        os.close(fd)
        raise OSError(ctypes.get_errno(), 'inotify_add_watch')
    events = output / 'events.jsonl'
    seen = {}; done = {}; previous_retry = None
    def emit(kind, value, alert=True):
        record = {'time': time.time(), 'event': kind, **value}
        with events.open('a') as stream:
            stream.write(json.dumps(record) + '\n')
        if alert:
            print(json.dumps(record), flush=True)
    try:
        last_change = time.monotonic()
        while True:
            job = json.loads((directory / 'job.json').read_text())
            specs = json.loads((directory / 'stages_spec.json').read_text())
            assert job['backend'] == 'CUDA'
            assert all(s['backend'] == 'CUDA' and s['interaction'] == 'CpdDNA2'
                       and s['min_bp_retained'] == 0 and not s['thermal_ramp'].get('check_pairing', False)
                       for s in specs)
            retry = job.get('production_retries', 0)
            if previous_retry is not None and retry != previous_retry:
                emit('numerical_retry', {'retry': retry, 'stage_index': job['current_stage_idx']})
            previous_retry = retry
            reports = job.get('run_config', {}).get('thermal_progress', {})
            for stage, spec in zip(job['stages'], specs, strict=True):
                name = stage['name']; report = reports.get(name, {})
                signature = (report.get('evaluated_steps'), report.get('decision'), stage['status'])
                if seen.get(name) != signature:
                    seen[name] = signature
                    emit('stage_state', {'stage': name, 'status': stage['status'], 'report': report}, False)
                if stage['status'] == 'done' and name not in done:
                    assert report['decision'] == 'done'
                    native = (directory / name / 'input.txt').read_text()
                    log = (directory / name / 'oxdna.log').read_text()
                    assert 'backend = CUDA' in native and 'interaction_type = CpdDNA2' in native
                    assert 'use_edge = true' in native and 'NADOC_CPD_CUDA_V1' in log
                    assert 'END OF THE SIMULATION, everything went OK!' in log
                    checkpoint = directory / name / 'last_conf.dat'
                    health = next(h for h in reversed(job['health_samples']) if h['stage'] == name)
                    assert health['passed'], health
                    done[name] = {'temperature': spec['temperature'], 'steps': spec['steps'],
                                  'check': report, 'health': health,
                                  'checkpoint_sha256': hashlib.sha256(checkpoint.read_bytes()).hexdigest()}
                    emit('stage_passed', {'stage': name, **done[name]})
            receipt = {'job_id': job['job_id'], 'status': job['status'], 'error': job.get('error'),
                       'completed': done, 'expected_stages': len(specs), 'production_retries': retry}
            temporary = output / 'receipt.tmp'
            temporary.write_text(json.dumps(receipt, indent=2) + '\n')
            temporary.replace(output / 'receipt.json')
            if job['status'] in {'completed', 'failed', 'stopped'}:
                if job['status'] == 'completed':
                    assert len(done) == len(specs) == 13
                emit('terminal', receipt)
                return 0 if job['status'] == 'completed' else 2
            remaining = idle_seconds - (time.monotonic() - last_change)
            if remaining <= 0:
                emit('stalled_worker', {'job_id': job['job_id'], 'idle_seconds': idle_seconds})
                return 3
            # Blocking kernel event wait. No timed re-reading of simulation status.
            if select.select([fd], [], [], remaining)[0]:
                os.read(fd, 65536)
                last_change = time.monotonic()
            else:
                emit('stalled_worker', {'job_id': job['job_id'], 'idle_seconds': idle_seconds})
                return 3
    except Exception as exc:
        emit('monitor_error', {'type': type(exc).__name__, 'message': str(exc)})
        raise
    finally:
        os.close(fd)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    raise SystemExit(monitor(args.directory, args.output))
