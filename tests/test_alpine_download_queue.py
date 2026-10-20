"""Multi-job transfers must never hold up discovery of scheduler completion."""
import asyncio

from backend.core import alpine_download_queue as queue
from backend.core import alpine_restart, md_executor as ex
from backend.core.md_job import MdJob, MdStatus, new_job


def make_job(workspace, number):
    job = new_job(design_name=f"queue-{number}", protocol="test",
                  name_stem="queue", package_subdir="namd")
    job.execution_target = "alpine"
    job.slurm_job_id = str(number)
    job.status = MdStatus.running
    job.save(workspace)
    return job


class Connection:
    def is_connected(self):
        return True


def test_discovery_and_repeated_passes_continue_while_transfer_blocked(tmp_path, monkeypatch):
    jobs = [make_job(tmp_path, n) for n in range(3)]
    entered, release = asyncio.Event(), asyncio.Event()
    seen, downloads = [], []

    async def observe(*args):
        pass

    async def poll(job, **kwargs):
        seen.append(job.job_id)
        return ("RUNNING", "running") if job.job_id == jobs[2].job_id else ("COMPLETED", "completed")

    async def progress(*args, **kwargs):
        return False

    async def complete(job, workspace, **kwargs):
        async with queue.transfer_slot(job, workspace):
            downloads.append(job.job_id)
            entered.set()
            await release.wait()

    monkeypatch.setattr(alpine_restart, "observe", observe)
    monkeypatch.setattr(ex, "poll_status", poll)
    monkeypatch.setattr(ex, "poll_remote_progress", progress)
    monkeypatch.setattr(ex, "_complete_remote_job", complete)

    async def scenario():
        await asyncio.wait_for(ex.poll_remote_jobs(tmp_path, conn=Connection()), 1)
        await entered.wait()
        assert set(seen) == {j.job_id for j in jobs}
        assert len(downloads) == 1
        for job in jobs[:2]:
            loaded = MdJob.load(job.job_id, tmp_path)
            assert loaded.slurm_state == "COMPLETED"
            assert loaded.download_status["state"] in {"queued", "downloading"}
        assert sum(MdJob.load(j.job_id, tmp_path).download_status["state"] == "queued"
                   for j in jobs[:2]) == 1
        await asyncio.wait_for(ex.poll_remote_jobs(tmp_path, conn=Connection()), 1)
        assert len(downloads) == 1
        release.set()
        await asyncio.gather(*list(queue._state()["tasks"].values()))
        assert len(downloads) == 2

    asyncio.run(scenario())


def test_fifo_failure_releases_slot_and_duplicate_schedule_is_ignored(tmp_path):
    jobs = [make_job(tmp_path, n) for n in range(3)]
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []

    async def operation(job):
        async with queue.transfer_slot(job, tmp_path):
            seen.append(job.job_id)
            if job == jobs[0]:
                entered.set()
                await release.wait()
                raise RuntimeError("broken inventory")

    async def scenario():
        for job in jobs:
            assert queue.schedule(job, tmp_path, lambda job=job: operation(job))
        assert not queue.schedule(jobs[0], tmp_path, lambda: operation(jobs[0]))
        await entered.wait()
        assert seen == [jobs[0].job_id]
        release.set()
        await asyncio.gather(*list(queue._state()["tasks"].values()))
        assert seen == [job.job_id for job in jobs]

    asyncio.run(scenario())


def test_worker_queues_second_job_and_client_cancellation_does_not_cancel_it(tmp_path, monkeypatch):
    from backend.core.alpine_worker import Worker
    jobs = [make_job(tmp_path, n) for n in range(2)]
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []

    async def fetch(job, workspace, **kwargs):
        seen.append(job.job_id)
        if job.job_id == jobs[0].job_id:
            entered.set()
            await release.wait()
        job.download_status = {"state": "verified"}
        job.save(workspace)
        return True

    monkeypatch.setattr(ex, "_fetch_outputs_locked", fetch)

    async def scenario():
        worker = Worker(tmp_path / "owner", Connection())
        def request(job):
            return worker.dispatch("fetch_outputs", {
                "job_id": job.job_id, "workspace": str(tmp_path),
            })
        first = asyncio.create_task(request(jobs[0]))
        await entered.wait()
        second = asyncio.create_task(request(jobs[1]))
        for _ in range(5):
            await asyncio.sleep(0)
        queued = MdJob.load(jobs[1].job_id, tmp_path)
        assert queued.download_status["state"] == "queued"
        queued.error = "user metadata changed while waiting"
        queued.save(tmp_path)
        second.cancel()
        await asyncio.gather(second, return_exceptions=True)
        assert seen == [jobs[0].job_id]
        release.set()
        await first
        await asyncio.gather(*worker.transfers.values())
        assert seen == [j.job_id for j in jobs]
        assert MdJob.load(jobs[1].job_id, tmp_path).download_status["state"] == "verified"
        assert MdJob.load(jobs[1].job_id, tmp_path).error == "user metadata changed while waiting"

    asyncio.run(scenario())


def test_recovery_schedules_durable_queue_without_blocking_discovery(tmp_path, monkeypatch):
    from backend.core.alpine_transfer_state import recover_downloads
    job = make_job(tmp_path, 1)
    job.status = MdStatus.stopped
    job.download_status = {"state": "queued", "enqueued_at": 1}
    job.save(tmp_path)
    entered, release = asyncio.Event(), asyncio.Event()

    async def fetch(*args, **kwargs):
        entered.set()
        await release.wait()

    monkeypatch.setattr(ex, "fetch_outputs", fetch)

    async def scenario():
        await asyncio.wait_for(recover_downloads(tmp_path, Connection()), 1)
        await entered.wait()
        assert queue.pending(job, tmp_path)
        release.set()
        await asyncio.gather(*queue._state()["tasks"].values())

    asyncio.run(scenario())


def test_changed_allocation_never_downloads_stale_queued_submission(tmp_path):
    jobs = [make_job(tmp_path, n) for n in range(2)]
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []

    async def transfer(job):
        async with queue.transfer_slot(job, tmp_path):
            seen.append(job.job_id)
            entered.set()
            await release.wait()

    async def scenario():
        first = asyncio.create_task(transfer(jobs[0]))
        await entered.wait()
        second = asyncio.create_task(transfer(jobs[1]))
        await asyncio.sleep(0)
        changed = MdJob.load(jobs[1].job_id, tmp_path)
        changed.slurm_job_id = "new-allocation"
        changed.save(tmp_path)
        release.set()
        result = await asyncio.gather(first, second, return_exceptions=True)
        assert isinstance(result[1], ValueError)
        assert seen == [jobs[0].job_id]

    asyncio.run(scenario())


def test_api_waiter_cancellation_retains_slot_and_duplicate_joins_transfer(tmp_path, monkeypatch):
    jobs = [make_job(tmp_path, n) for n in range(2)]
    entered, release = asyncio.Event(), asyncio.Event()
    seen = []

    async def fetch(job, workspace, **kwargs):
        seen.append(job.job_id)
        if job.job_id == jobs[0].job_id:
            entered.set()
            await release.wait()
        job.download_status = {"state": "verified", "verified_bytes": 42}
        job.save(workspace)
        return True

    monkeypatch.setattr(ex, "_fetch_outputs_locked", fetch)

    async def scenario():
        first = asyncio.create_task(ex.fetch_outputs(jobs[0], tmp_path, conn=Connection()))
        await entered.wait()
        duplicate_job = MdJob.load(jobs[0].job_id, tmp_path)
        duplicate = asyncio.create_task(ex.fetch_outputs(duplicate_job, tmp_path, conn=Connection()))
        following = asyncio.create_task(ex.fetch_outputs(jobs[1], tmp_path, conn=Connection()))
        await asyncio.sleep(0)
        first.cancel()
        await asyncio.gather(first, return_exceptions=True)
        assert seen == [jobs[0].job_id]
        assert not following.done()
        release.set()
        await asyncio.gather(duplicate, following)
        assert seen == [j.job_id for j in jobs]
        assert duplicate_job.download_status["verified_bytes"] == 42

    asyncio.run(scenario())
