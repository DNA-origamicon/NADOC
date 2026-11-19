"""Small, advisory progress receipts shared by local and remote SNUPI jobs."""
import json
import math
from pathlib import Path
import shlex
import time

DYNAMICS_STEPS = 60_000
REMOTE_PROGRESS = 'remote-progress.json'
MAX_PROGRESS_BYTES = 16_384


def _number(value):
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (ValueError, TypeError):
        return None


def load_receipt(directory, *, remote=False):
    try:
        path = Path(directory) / (REMOTE_PROGRESS if remote else 'progress.json')
        if path.stat().st_size > MAX_PROGRESS_BYTES:
            return {}
        result = json.loads(path.read_text())
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError):
        return {}


async def sync_remote_progress(engine, job, workspace, conn):
    """Bounded read; missing/partial telemetry must not terminate a paid solve.

    Keep receipts separate from job.json so a progress poll cannot overwrite a
    concurrent cancellation or completion. A failed sync retains the last sample.
    """
    if engine != 'snupi' or not job.remote.get('directory'):
        return False
    source = f"{job.remote['directory']}/workspace/{engine}_jobs/{job.job_id}/progress.json"
    try:
        result = await conn.run(f'head -c {MAX_PROGRESS_BYTES + 1} -- {shlex.quote(source)}', timeout=10)
        if result.rc or len(result.stdout.encode()) > MAX_PROGRESS_BYTES:
            return False
        sample = json.loads(result.stdout)
        if not isinstance(sample, dict) or not isinstance(sample.get('phase'), str):
            return False
        target = job.job_dir(workspace) / REMOTE_PROGRESS
        temp = target.with_suffix('.tmp')
        temp.write_text(json.dumps({'sample': sample, 'retrieved_at': time.time()}))
        temp.replace(target)
        return True
    except Exception:
        return False


def dynamics_progress(job, receipt, *, remote=False, now=None):
    """Dynamics percent is completed integrator steps, never a weighted setup ETA."""
    now = time.time() if now is None else now
    sample = receipt.get('sample', {}) if remote else receipt
    if not isinstance(sample, dict):
        sample = {}
    total = _number(sample.get('n_steps'))
    total = int(total) if total and total >= 1 else DYNAMICS_STEPS
    step = _number(sample.get('step'))
    step = min(total, max(0, int(step))) if step is not None else None
    completed = job.status.value == 'completed'
    phase = str(sample.get('phase') or 'Waiting for solver progress')
    if completed:
        step, phase = total, 'Completed'
    elif (job.remote or {}).get('downloading'):
        phase = 'Downloading results'
    elif job.status.value in {'preparing', 'queued'}:
        phase = (job.remote or {}).get('scheduler_state') or 'Preparing solver'
    retrieved = _number(receipt.get('retrieved_at')) if remote else None
    stale = bool(remote and sample and (retrieved is None or now - retrieved > 30))
    rate = _number(sample.get('steps_per_s'))
    integrating = phase.startswith('trajectory') and step is not None and step < total
    eta = (total - step) / rate if integrating and rate and rate > 0 and not stale else None
    return {
        'status': job.status.value,
        'overall': step / total if step is not None else 0.0,
        'current_step': step, 'total_steps': total,
        'step': step, 'n_steps': total,
        'phase': phase, 'progress_indeterminate': job.status.value in {'preparing', 'queued', 'running'} and (step is None or (step == 0 and not integrating)),
        'progress_last_known': stale, 'progress_retrieved_at': retrieved,
        'progress_reported_at': _number(sample.get('at')),
        'eta_seconds': eta, 'steps_per_s': rate if integrating and not stale else None,
        'attempt': sample.get('attempt', 0),
    }
