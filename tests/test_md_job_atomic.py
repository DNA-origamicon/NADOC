"""Status readers may backfill metadata concurrently with preparation completion."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import threading

from backend.core.md_job import new_job


def test_concurrent_job_saves_publish_complete_records(tmp_path, monkeypatch):
    from backend.core import trajectory_precompute
    import os
    monkeypatch.setattr(trajectory_precompute, 'schedule', lambda *args: None)
    job = new_job('first', 'equilibrium_aware_namd', 'run', 'package')
    job.save(tmp_path)
    other = replace(job, design_name='second')
    barrier = threading.Barrier(2)
    original = os.replace
    def synchronized_replace(source, target):
        if Path(target).name == 'job.json':
            barrier.wait(timeout=5)
        return original(source, target)
    monkeypatch.setattr(os, 'replace', synchronized_replace)
    with ThreadPoolExecutor(max_workers=2) as workers:
        futures = [workers.submit(item.save, tmp_path) for item in (job, other)]
        for future in futures:
            future.result()
    saved = json.loads((job.job_dir(tmp_path) / 'job.json').read_text())
    assert saved['design_name'] in ('first', 'second')
    assert not list(job.job_dir(tmp_path).glob('job.json.*'))
