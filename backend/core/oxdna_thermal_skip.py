"""Durable, detached handoff from an interrupted thermal plateau to the next one."""
from __future__ import annotations

import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import uuid

from backend.core import simulation_runtime as runtime
from backend.core.oxdna_job import OxdnaJob, OxdnaStatus


def _write(path, record):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(record, indent=2) + '\n')
    temporary.replace(path)


def validate_skip(job, expected_stage):
    idx = job.current_stage_idx
    if (job.execution_target or 'local') != 'local':
        raise ValueError('Skipping temperatures is supported for local oxDNA jobs.')
    if not (job.run_config or {}).get('thermal_ramp'):
        raise ValueError('This job is not a thermal ramp.')
    if job.status not in (OxdnaStatus.running, OxdnaStatus.stopped, OxdnaStatus.failed):
        raise ValueError('There is no active or interrupted temperature to skip.')
    if idx < 0 or idx + 1 >= len(job.stages):
        raise ValueError('This is the final temperature; there is no next stage.')
    if job.stages[idx].name != expected_stage:
        raise ValueError('The active temperature changed. Refresh the job before skipping.')
    return idx


def begin_skip(job_id, workspace, expected_stage):
    """Reserve this command separately from the running simulation's execution lease."""
    job = OxdnaJob.load(job_id, workspace)
    directory = job.job_dir(workspace)
    fd = os.open(directory / '.thermal-skip.lock', os.O_RDWR | os.O_CREAT, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError('A temperature skip is already in progress.') from None
        job = OxdnaJob.load(job_id, workspace)
        validate_skip(job, expected_stage)
        record = {'request_id': uuid.uuid4().hex, 'stage': expected_stage,
                  'generation': runtime.generation(directory), 'requested_at': time.time(),
                  'state': 'requested'}
        path = directory / f"thermal_skip_{record['request_id']}.json"
        _write(path, record)
        with (directory / 'thermal_skip.log').open('a') as log:
            proc = subprocess.Popen([sys.executable, '-m', __name__, str(Path(workspace).resolve()),
                                     job_id, str(path.resolve()), str(fd)],
                                    cwd=Path(__file__).resolve().parents[2], stdout=log,
                                    stderr=subprocess.STDOUT, start_new_session=True, pass_fds=(fd,))
        threading.Thread(target=proc.wait, daemon=True).start()
        return {'ok': True, 'request_id': record['request_id'], 'stage': expected_stage}
    finally:
        os.close(fd)  # The detached controller retains the command lock.


def wait_skip(job_id, workspace, request_id):
    """Return command acknowledgement; the controller survives a disconnected client."""
    path = runtime.job_path('oxdna_jobs', job_id, workspace) / f'thermal_skip_{request_id}.json'
    deadline = time.monotonic() + 45
    while time.monotonic() < deadline:
        record = json.loads(path.read_text())
        if record['state'] == 'error':
            raise ValueError(record['error'])
        if record['state'] == 'cancelled':
            raise ValueError('Skip cancelled by a later Stop request.')
        if record['state'] in ('applied', 'already_advanced'):
            return {'ok': True, **record}
        time.sleep(.1)
    raise ValueError('The skip controller is still working. Check the job status before retrying.')


def cancel_skip(directory):
    directory = Path(directory)
    if (directory / '.thermal-skip.lock').exists():
        _write(directory / '.thermal-skip-cancel.json', {'cancelled_at': time.time()})


def _cancelled(directory, record):
    path = directory / '.thermal-skip-cancel.json'
    return path.exists() and json.loads(path.read_text())['cancelled_at'] >= record['requested_at']


def apply_skip(job, workspace, record):
    """Caller owns the idle execution lease; preserve evidence and a valid checkpoint."""
    from backend.core.oxdna_runner import load_stage_specs, resume_point, _starting_conf, conf_is_restartable
    from backend.core.oxdna_thermal_metrics import energy_observations
    from backend.physics.oxdna_surface_strands import capture_bead_count

    idx = validate_skip(job, record['stage'])
    specs = load_stage_specs(job.job_dir(workspace))
    if not specs[idx].thermal_ramp or not specs[idx + 1].thermal_ramp:
        raise ValueError('The next stage is not a thermal temperature stage.')
    directory = job.stage_dir(workspace, record['stage'])
    particles = job.n_nucleotides + capture_bead_count(job)
    checkpoint, steps, note = resume_point(directory, specs[idx], particles)
    if checkpoint is None:
        incoming = _starting_conf(job, workspace, specs, idx, -1)
        if conf_is_restartable(incoming, particles):
            checkpoint, steps, note = incoming, 0, 'incoming configuration; no recoverable stage checkpoint'
    if checkpoint is None:
        raise ValueError('Cannot skip without a valid saved configuration: ' + note)
    # The normal next-stage start path consumes the previous stage's last_conf.
    if checkpoint != (directory / 'last_conf.dat').resolve():
        target = directory / 'last_conf.dat'
        if target.exists():
            target.replace(directory / f"last_conf.before_skip_{record['request_id']}.dat")
        temporary = directory / 'skip_checkpoint.tmp'
        temporary.write_bytes(checkpoint.read_bytes())
        temporary.replace(target)
    try:
        fit, _ = energy_observations(directory, evaluated_steps=steps)
    except Exception as error:
        # Explicit manual advancement does not depend on an energy diagnosis.
        # Keep the raw evidence and surface the diagnostic failure truthfully.
        fit = {'status': 'unavailable', 'reason': 'Energy observations unavailable: ' + str(error)}
    report = {'decision': 'skipped', 'temperature': specs[idx].temperature,
              'next_temperature': specs[idx + 1].temperature, 'evaluated_steps': steps,
              'stability_status': 'manually_skipped', 'metrics': {'energy': fit},
              'request_id': record['request_id'], 'requested_at': record['requested_at'],
              'checkpoint': note, 'skipped_at': time.time()}
    config = dict(job.run_config or {})
    progress = dict(config.get('thermal_progress') or {})
    if record['stage'] in progress:
        report['previous_decision'] = progress[record['stage']]
    progress[record['stage']] = report
    config['thermal_progress'] = progress
    job.run_config = config
    job.stages[idx].status = 'skipped'
    job.stages[idx].completed_steps = steps
    job.current_stage_idx = idx + 1
    job.status = OxdnaStatus.stopped
    job.error = None
    job.oxdna_pid = None
    job.save(workspace)
    _write(directory / 'thermal_skip.json', report)
    return specs


def execute(workspace, job_id, path):
    from backend.core.oxdna_runner import start_job, stop_job, load_stage_specs

    workspace, path = Path(workspace), Path(path)
    record = json.loads(path.read_text())
    directory = runtime.job_path('oxdna_jobs', job_id, workspace)
    try:
        job = OxdnaJob.load(job_id, workspace)
        validate_skip(job, record['stage'])
        if runtime.generation(directory) != record['generation']:
            raise ValueError('Execution changed before the skip could be applied.')
        record['state'] = 'stopping'
        _write(path, record)
        stop_job(job_id, workspace)
        deadline = time.monotonic() + 30
        # Bounded local shutdown coordination, not a simulation-completion poll.
        while True:
            with runtime.idle_stop_update(directory, record['generation']) as acquired:
                if acquired:
                    job = OxdnaJob.load(job_id, workspace)
                    if _cancelled(directory, record):
                        record['state'] = 'cancelled'
                        _write(path, record)
                        return
                    if (job.current_stage_idx >= len(job.stages)
                            or job.stages[job.current_stage_idx].name != record['stage']):
                        # It finished naturally during the request: never skip the new temperature.
                        specs = load_stage_specs(directory)
                        state = 'already_advanced'
                    else:
                        specs = apply_skip(job, workspace, record)
                        state = 'applied'
                    if _cancelled(directory, record):
                        state = 'cancelled'
                    elif job.status == OxdnaStatus.stopped:
                        start_job(job, workspace, specs)
                        if _cancelled(directory, record):
                            stop_job(job_id, workspace)
                            state = 'cancelled'
                    record['state'] = state
                    _write(path, record)
                    return
            if runtime.generation(directory) != record['generation']:
                raise ValueError('Execution changed during the skip; no stage was advanced.')
            if time.monotonic() >= deadline:
                raise ValueError('The current stage did not stop within 30 seconds; no stage was skipped.')
            time.sleep(.1)
    except Exception as error:
        record.update(state='error', error=str(error))
        with runtime.idle_stop_update(directory, record['generation']) as acquired:
            if acquired:
                job = OxdnaJob.load(job_id, workspace)
                if (job.status in (OxdnaStatus.stopped, OxdnaStatus.failed)
                        and job.current_stage_idx < len(job.stages)
                        and job.stages[job.current_stage_idx].name == record['stage']):
                    job.error = 'Skip to next stage failed: ' + str(error)
                    job.save(workspace)
        _write(path, record)
        raise


if __name__ == '__main__':
    try:
        with runtime.use_workspace(Path(sys.argv[1])):
            execute(*sys.argv[1:4])
    finally:
        os.close(int(sys.argv[4]))
