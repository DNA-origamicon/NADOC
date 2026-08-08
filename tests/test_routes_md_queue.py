"""The NAMD run-queue endpoints + the supervisor drain pass.

Exercises the handlers directly (no HTTP client) with the workspace monkeypatched to a
tmp dir, matching the rest of the MD route tests.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi import HTTPException

from backend.api import routes_md_queue as rq
from backend.core import md_queue
from backend.core.md_job import MdStatus, new_job


def _job(tmp_path, *, status=MdStatus.queued, name="demo"):
    job = new_job(name, "p", name_stem=name, package_subdir="pkg")
    job.status = status
    job.save(tmp_path)
    return job


@pytest.fixture
def ws(tmp_path, monkeypatch):
    monkeypatch.setattr(rq, "_WORKSPACE_DIR", tmp_path)
    return tmp_path


def test_enqueue_then_get_returns_it_in_order(ws):
    a, b = _job(ws), _job(ws)
    asyncio.run(rq.enqueue_md_job(rq.EnqueueRequest(job_id=a.job_id)))
    res = asyncio.run(rq.enqueue_md_job(rq.EnqueueRequest(job_id=b.job_id)))
    assert [e["job_id"] for e in res["queue"]] == [a.job_id, b.job_id]
    assert [e["position"] for e in res["queue"]] == [1, 2]
    assert res["busy"] is False


def test_enqueue_unknown_job_404s(ws):
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rq.enqueue_md_job(rq.EnqueueRequest(job_id="nope")))
    assert exc.value.status_code == 404


def test_a_running_job_cannot_be_queued(ws):
    job = _job(ws, status=MdStatus.running)
    with pytest.raises(HTTPException) as exc:
        asyncio.run(rq.enqueue_md_job(rq.EnqueueRequest(job_id=job.job_id)))
    assert exc.value.status_code == 400


def test_get_reports_busy_and_the_blocking_job(ws):
    running = _job(ws, status=MdStatus.running)
    waiting = _job(ws)
    md_queue.enqueue(ws, waiting.job_id)
    res = asyncio.run(rq.get_md_queue())
    assert res["busy"] is True
    assert res["running_job_id"] == running.job_id


def test_dequeue_removes_the_entry(ws):
    a = _job(ws)
    asyncio.run(rq.enqueue_md_job(rq.EnqueueRequest(job_id=a.job_id)))
    res = asyncio.run(rq.dequeue_md_job(a.job_id))
    assert res["queue"] == []


def test_reorder_replaces_the_order(ws):
    a, b = _job(ws), _job(ws)
    md_queue.save_queue(ws, [a.job_id, b.job_id])
    res = asyncio.run(
        rq.reorder_md_queue(rq.ReorderRequest(job_ids=[b.job_id, a.job_id]))
    )
    assert [e["job_id"] for e in res["queue"]] == [b.job_id, a.job_id]


def test_get_prunes_entries_whose_job_was_deleted(ws):
    md_queue.save_queue(ws, ["deleted-job"])
    res = asyncio.run(rq.get_md_queue())
    assert res["queue"] == []


# ── the drain pass ───────────────────────────────────────────────────────────────


def _spy(sink):
    async def _start(job_id):
        sink.append(job_id)
        return {"ok": True}

    return _start


def test_drain_starts_the_head_when_idle(ws, monkeypatch):
    a, b = _job(ws), _job(ws)
    md_queue.save_queue(ws, [a.job_id, b.job_id])
    started = []
    monkeypatch.setattr("backend.api.routes_md.start_md_job", _spy(started))
    assert asyncio.run(rq.advance_md_queue(ws)) == [a.job_id]
    assert started == [a.job_id]
    assert md_queue.load_queue(ws) == [b.job_id]


def test_drain_waits_while_a_job_is_running(ws, monkeypatch):
    _job(ws, status=MdStatus.running)
    waiting = _job(ws)
    md_queue.save_queue(ws, [waiting.job_id])
    started = []
    monkeypatch.setattr("backend.api.routes_md.start_md_job", _spy(started))
    assert asyncio.run(rq.advance_md_queue(ws)) == []
    assert started == []
    assert md_queue.load_queue(ws) == [waiting.job_id]


def test_drain_skips_past_an_entry_started_by_hand(ws, monkeypatch):
    """[a, b] queued, a completed behind our back → b still runs, a is dropped."""
    a = _job(ws, status=MdStatus.completed)
    b = _job(ws)
    md_queue.save_queue(ws, [a.job_id, b.job_id])
    started = []
    monkeypatch.setattr("backend.api.routes_md.start_md_job", _spy(started))
    assert asyncio.run(rq.advance_md_queue(ws)) == [b.job_id]
    assert md_queue.load_queue(ws) == []


def test_drain_drops_a_job_that_fails_to_start(ws, monkeypatch):
    a, b = _job(ws), _job(ws)
    md_queue.save_queue(ws, [a.job_id, b.job_id])

    async def _boom(job_id):
        raise RuntimeError("NAMD not found")

    monkeypatch.setattr("backend.api.routes_md.start_md_job", _boom)
    assert asyncio.run(rq.advance_md_queue(ws)) == []
    # a is gone (it can never start); b keeps its place for the next pass.
    assert md_queue.load_queue(ws) == [b.job_id]


def test_drain_is_a_noop_on_an_empty_queue(ws):
    assert asyncio.run(rq.advance_md_queue(ws)) == []
