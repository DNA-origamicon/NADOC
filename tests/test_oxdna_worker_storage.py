"""Exercise the real detached worker handoff for a job on another storage drive."""
import asyncio
import os
from pathlib import Path
import time

from backend.core import job_archive, simulation_runtime as runtime
from backend.core.oxdna_job import OxdnaJob, OxdnaStatus
from backend.core.oxdna_runner import stop_job


def test_stored_job_start_ownership_and_stop(tmp_path, monkeypatch):
    workspace = tmp_path / 'workspace'
    directory = tmp_path / 'storage' / 'job'
    directory.mkdir(parents=True)
    job_archive._write_index(workspace, 'oxdna_jobs', {'job': str(directory)})
    # Stale local lock files must not redirect ownership away from the real job.
    local = workspace / 'oxdna_jobs' / 'job'
    local.mkdir()
    (local / '.runtime.lock').touch()
    job = OxdnaJob('job', 'stored job', OxdnaStatus.stopped, time.time(),
                   archived=True, archive_path=str(directory))
    monkeypatch.setattr('backend.core.trajectory_precompute.schedule', lambda *a: None)
    job.save(workspace)
    wrapper = tmp_path / 'stored_worker_fixture.py'
    wrapper.write_text('''
import asyncio, sys
from backend.core import oxdna_worker as worker
from backend.core.oxdna_job import OxdnaStatus
async def execute(job, workspace, lease):
    (job.job_dir(workspace) / 'entered').touch()
    for _ in range(500):
        if lease.stop_requested():
            job.status = OxdnaStatus.stopped
            job.save(workspace)
            return
        await asyncio.sleep(.01)
    raise RuntimeError('Stop request never arrived')
worker.execute = execute
worker.main(*sys.argv[1:])
''')
    monkeypatch.setenv('PYTHONPATH', os.pathsep.join([str(tmp_path), str(Path(__file__).resolve().parents[1])]))
    processes = []

    @runtime.start_request(lambda: workspace, 'oxdna_jobs')
    async def start(job_id):
        processes.append(runtime.launch_detached(job, workspace, wrapper.stem, tmp_path,
                                                 initialize_stage=False))

    asyncio.run(start('job'))
    process = processes[0]
    try:
        deadline = time.monotonic() + 10
        while not (directory / 'entered').exists() and time.monotonic() < deadline and process.poll() is None:
            time.sleep(.02)
        assert (directory / 'entered').exists(), (directory / 'worker.log').read_text()
        assert runtime.owned_job('oxdna_jobs', 'job', workspace)
        asyncio.run(start('job'))
        assert len(processes) == 1, 'A duplicate start must not launch another worker'
        assert stop_job('job', workspace)
        process.wait(timeout=10)
        assert process.returncode == 0, (directory / 'worker.log').read_text()
        assert OxdnaJob.load('job', workspace).status == OxdnaStatus.stopped
        assert not runtime.owned_job('oxdna_jobs', 'job', workspace)
        assert not (local / '.runtime.json').exists()
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
