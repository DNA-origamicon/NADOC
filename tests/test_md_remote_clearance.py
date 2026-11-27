"""The checkpoint inspected by Resume must be the one NAMD actually opens."""
import asyncio
import json
import shutil
import subprocess
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.core.md_remote_clearance import verify_resume_inputs
from backend.core import remote_alpine_restart as node
from tests.test_md_image_clearance import package


class LocalConn:
    async def run(self, command):
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        return SimpleNamespace(rc=result.returncode, stdout=result.stdout, stderr=result.stderr)

    async def sftp_get(self, source, dest):
        shutil.copyfile(source, dest)


@pytest.mark.parametrize("gap", [10, 40])
def test_review_pins_exact_checkpoint_and_node_honors_it(tmp_path, gap):
    job = package(tmp_path, gap=gap)
    pkg = job.package_dir(tmp_path)
    remote = tmp_path / "remote"
    remote.mkdir()
    (remote / "output").mkdir()
    for ext in ("coor", "xsc"):
        shutil.copyfile(pkg / f"equilibrated.{ext}", remote / f"equilibrated.{ext}")
    job.remote_scratch_dir = str(remote)
    text = (pkg / "start.conf").read_text()
    task = verify_resume_inputs(job, tmp_path, LocalConn(), "start", text,
                                expected_step=0)
    if gap == 10:
        with pytest.raises(HTTPException) as exc:
            asyncio.run(task)
        assert exc.value.status_code == 409
    else:
        reviewed = asyncio.run(task)
        (remote / "start.resume.conf").write_text(reviewed)
        # Old rolling files change; reviewed immutable files still control startup.
        (remote / "equilibrated.coor").write_bytes(b"changed")
        node.begin(remote)
        assert node.prepare(remote, "start", "start.resume", 1000) == "start.resume"
        record = json.loads((remote / node.JOURNAL).read_text())["attempts"][-1]["segments"][0]
        assert record["mode"] == "reviewed-continuation"
        pinned = next((remote / ".resume-inputs").glob("*/equilibrated.coor"))
        pinned.write_bytes(b"tampered")
        with pytest.raises(ValueError, match="changed"):
            node.prepare(remote, "start", "start.resume", 1000)
    assert not list(pkg.glob(".resume-review-*"))


def test_changed_checkpoint_step_is_not_submitted(tmp_path):
    job = package(tmp_path, gap=40)
    job.remote_scratch_dir = str(job.package_dir(tmp_path))
    text = (job.package_dir(tmp_path) / "start.conf").read_text()
    with pytest.raises(RuntimeError, match="changed"):
        asyncio.run(verify_resume_inputs(job, tmp_path, LocalConn(), "start", text,
                                         expected_step=20))


def test_resume_route_waits_for_previous_poll_and_reloads(tmp_path, monkeypatch):
    from backend.api import routes_md as routes
    from backend.core import md_executor
    job = package(tmp_path)
    monkeypatch.setattr(routes, '_workspace', lambda: tmp_path)
    monkeypatch.setattr(routes, '_load_job', lambda _: job)

    async def check():
        lock = asyncio.Lock()
        md_executor._REMOTE_RECONCILE_LOCKS[str(tmp_path.resolve())] = lock
        await lock.acquire()
        task = asyncio.create_task(routes.resume_md_job_remote('j', routes.ResumeRemoteRequest()))
        await asyncio.sleep(0)
        assert not task.done()
        # Another operation wins while the queued request waits. The second load
        # must see that this job is no longer resumable and refuse a second submit.
        job.resumable = False
        job.status = 'queued'
        lock.release()
        with pytest.raises(HTTPException) as exc:
            await task
        assert exc.value.status_code == 400
    asyncio.run(check())
