"""Atomic, revisioned progress transport for bounded flex workers."""
from pathlib import Path


def progress_reporter(progress_path, frame_range=None):
    import json
    import time

    path = Path(progress_path)
    started = time.monotonic()
    phase_started = started
    last_phase = None
    last_report = 0.0
    try:
        previous = json.loads(path.read_text())
    except (OSError, ValueError):
        previous = {}
    revision = int(previous.get('revision', 0))
    elapsed_before = float(previous.get('elapsed_seconds', 0))

    def report(phase, done, total):
        nonlocal last_phase, phase_started, last_report
        now = time.monotonic()
        if phase == last_phase and done != total and now - last_report < 0.25:
            return
        last_report = now
        if phase != last_phase:
            last_phase, phase_started = phase, now
        state = dict(frame_range=frame_range, phase=phase, done=done, total=total, revision=revision, updated_at=time.time(),
                     elapsed_seconds=elapsed_before + now - started,
                     phase_elapsed_seconds=now - phase_started)
        temporary = path.with_suffix('.tmp')
        temporary.write_text(json.dumps(state))
        temporary.replace(path)

    def publish(result, phase, done, total, average=None):
        nonlocal revision, last_report
        revision += 1
        partial = dict(result, preliminary=True, coverage=dict(
            phase=phase, processed_frames=done, total_frames=total,
            window='last_chunk' if phase == 'tail_preview' else 'chronological_prefix'))
        payload = dict(revision=revision, partial=partial)
        if average is not None:
            payload['representations'] = {'atomistic_average': {k: v for k, v in average.items() if k != 'model'},
                                          'atomistic_model': average.get('model')}
        temporary = path.with_suffix('.partial.tmp')
        temporary.write_text(json.dumps(payload))
        temporary.replace(path.with_suffix('.partial.json'))
        last_report = 0.0  # publish the new revision even inside the progress throttle
        report(phase, done, total)

    report.publish = publish
    report.slice_seconds = 20.0

    return report


def read_progress(path, since=0):
    import json
    import time

    try:
        state = json.loads(path.read_text())
        if state.get('revision', 0) > since:
            try:
                state.update(json.loads(path.with_suffix('.partial.json').read_text()))
            except (OSError, ValueError):
                pass
        updated = state.pop('updated_at', None)
        if updated is not None:
            state['elapsed_seconds'] = state.get('elapsed_seconds', 0) + max(0, time.time() - updated)
        return {'active': True, **state}
    except (OSError, ValueError):
        return {'active': True, 'phase': 'starting', 'done': 0, 'total': 1}


def selection_from_args(args):
    candidate = args[-1] if args else None
    return candidate if isinstance(candidate, dict) and 'interval' in candidate else None
