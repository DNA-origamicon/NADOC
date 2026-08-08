"""Unit tests for the persistent NAMD run queue (backend/core/md_queue.py).

Pure decisions (who blocks, who starts next, what is stale) and the JSON round-trip.
The drain pass itself is covered in test_routes_md_queue.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from backend.core import md_queue
from backend.core.md_job import MdStatus


@dataclass
class FakeJob:
    job_id: str
    status: MdStatus = MdStatus.queued
    slurm_job_id: Optional[str] = None
    runpod_pod_id: Optional[str] = None
    execution_target: str = "local"
    design_name: str = "design"


# ── persistence ──────────────────────────────────────────────────────────────────


def test_missing_queue_file_reads_empty(tmp_path):
    assert md_queue.load_queue(tmp_path) == []


def test_save_then_load_round_trip(tmp_path):
    md_queue.save_queue(tmp_path, ["a", "b", "c"])
    assert md_queue.load_queue(tmp_path) == ["a", "b", "c"]


def test_corrupt_queue_file_reads_empty(tmp_path):
    md_queue.queue_path(tmp_path).write_text("{not json")
    assert md_queue.load_queue(tmp_path) == []


def test_enqueue_is_idempotent_and_keeps_the_original_place(tmp_path):
    md_queue.enqueue(tmp_path, "a")
    md_queue.enqueue(tmp_path, "b")
    md_queue.enqueue(tmp_path, "a")
    assert md_queue.load_queue(tmp_path) == ["a", "b"]


def test_dequeue_removes_one_entry(tmp_path):
    md_queue.save_queue(tmp_path, ["a", "b", "c"])
    assert md_queue.dequeue(tmp_path, "b") == ["a", "c"]


def test_reorder_replaces_the_whole_order(tmp_path):
    md_queue.save_queue(tmp_path, ["a", "b", "c"])
    assert md_queue.reorder(tmp_path, ["c", "a", "b"]) == ["c", "a", "b"]


def test_prune_drops_ids_with_no_job_but_keeps_a_running_one(tmp_path):
    md_queue.save_queue(tmp_path, ["gone", "live"])
    kept = md_queue.prune(tmp_path, [FakeJob("live", MdStatus.running)])
    assert kept == ["live"]


# ── who blocks ───────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("status", [MdStatus.running, MdStatus.preparing])
def test_running_and_preparing_block_the_queue(status):
    assert md_queue.job_is_running(FakeJob("a", status)) is True


@pytest.mark.parametrize(
    "status",
    [
        MdStatus.queued,
        MdStatus.stopped,
        MdStatus.failed,
        MdStatus.completed,
        MdStatus.draft,
    ],
)
def test_idle_statuses_do_not_block(status):
    assert md_queue.job_is_running(FakeJob("a", status)) is False


def test_a_submitted_remote_job_counts_as_running():
    assert (
        md_queue.job_is_running(FakeJob("a", MdStatus.queued, slurm_job_id="12345"))
        is True
    )
    assert (
        md_queue.job_is_running(FakeJob("a", MdStatus.queued, runpod_pod_id="pod1"))
        is True
    )


def test_running_job_returns_the_first_blocker_or_none():
    jobs = [FakeJob("a", MdStatus.completed), FakeJob("b", MdStatus.running)]
    assert md_queue.running_job(jobs).job_id == "b"
    assert md_queue.running_job([FakeJob("a", MdStatus.completed)]) is None


# ── what actually holds THIS machine ─────────────────────────────────────────────
#
# The bug this pins: `running_job` used the target-blind `job_is_running`, so a run on
# Alpine or a RunPod pod reported the machine busy.  The local queue then never drained
# and ▶ Run read ＋ Queue for the whole of every remote run, with the GPU idle.


@pytest.mark.parametrize("target", ["alpine", "runpod"])
@pytest.mark.parametrize("status", [MdStatus.running, MdStatus.preparing])
def test_a_remote_run_is_in_flight_but_does_not_occupy_this_machine(target, status):
    job = FakeJob("a", status, execution_target=target)
    assert md_queue.job_is_running(job) is True
    assert md_queue.job_occupies_local_machine(job) is False


def test_a_submitted_remote_job_does_not_occupy_this_machine():
    for job in (
        FakeJob("a", MdStatus.queued, slurm_job_id="12345", execution_target="alpine"),
        FakeJob("b", MdStatus.queued, runpod_pod_id="pod1", execution_target="runpod"),
    ):
        assert md_queue.job_is_running(job) is True
        assert md_queue.job_occupies_local_machine(job) is False


@pytest.mark.parametrize("status", [MdStatus.running, MdStatus.preparing])
def test_a_local_run_does_occupy_this_machine(status):
    assert md_queue.job_occupies_local_machine(FakeJob("a", status)) is True


def test_a_legacy_job_with_no_target_is_local():
    job = FakeJob("a", MdStatus.running)
    job.execution_target = None
    assert md_queue.job_occupies_local_machine(job) is True


def test_remote_runs_do_not_block_the_queue_but_a_local_one_does():
    remote = [
        FakeJob("alp", MdStatus.running, execution_target="alpine"),
        FakeJob("pod", MdStatus.running, execution_target="runpod"),
    ]
    assert md_queue.running_job(remote) is None
    assert (
        md_queue.running_job([*remote, FakeJob("loc", MdStatus.running)]).job_id
        == "loc"
    )


# ── who is startable ─────────────────────────────────────────────────────────────


def test_startable_is_prepared_and_unsubmitted():
    assert md_queue.job_is_startable(FakeJob("a", MdStatus.queued)) is True
    assert (
        md_queue.job_is_startable(FakeJob("a", MdStatus.queued, slurm_job_id="1"))
        is False
    )
    assert md_queue.job_is_startable(FakeJob("a", MdStatus.draft)) is False
    assert md_queue.job_is_startable(FakeJob("a", MdStatus.completed)) is False


# ── next_startable ───────────────────────────────────────────────────────────────


def test_queueable_covers_prepared_and_stopped_but_not_draft_or_paused():
    assert md_queue.job_is_queueable(FakeJob("a", MdStatus.queued)) is True
    assert md_queue.job_is_queueable(FakeJob("a", MdStatus.stopped)) is True
    assert md_queue.job_is_queueable(FakeJob("a", MdStatus.failed)) is True
    assert md_queue.job_is_queueable(FakeJob("a", MdStatus.draft)) is False
    assert md_queue.job_is_queueable(FakeJob("a", MdStatus.paused)) is False
    assert md_queue.job_is_queueable(FakeJob("a", MdStatus.completed)) is False


def test_the_queue_is_local_only():
    """An Alpine submit / RunPod rental is a review-card decision, never unattended."""
    for target in ("alpine", "runpod"):
        assert (
            md_queue.job_is_queueable(
                FakeJob("a", MdStatus.queued, execution_target=target)
            )
            is False
        )
        assert (
            md_queue.job_is_queueable(
                FakeJob("a", MdStatus.stopped, execution_target=target)
            )
            is False
        )


def test_a_prepared_remote_job_is_awaiting_submit_not_startable():
    assert (
        md_queue.remote_awaiting_submit(
            FakeJob("a", MdStatus.queued, execution_target="alpine")
        )
        is True
    )
    assert (
        md_queue.job_is_startable(
            FakeJob("a", MdStatus.queued, execution_target="alpine")
        )
        is False
    )
    assert md_queue.remote_awaiting_submit(FakeJob("a", MdStatus.queued)) is False


def test_next_startable_picks_the_head():
    jobs = [FakeJob("a"), FakeJob("b")]
    pick, stale = md_queue.next_startable(["a", "b"], jobs)
    assert (pick, stale) == ("a", [])


def test_next_startable_skips_past_a_stale_head():
    """Starting B by hand while [A, B, C] are queued must not strand C behind it."""
    jobs = [
        FakeJob("a", MdStatus.completed),
        FakeJob("b", MdStatus.running),
        FakeJob("c"),
    ]
    pick, stale = md_queue.next_startable(["a", "b", "c"], jobs)
    assert pick == "c"
    assert stale == ["a", "b"]


def test_next_startable_treats_a_deleted_job_as_stale():
    pick, stale = md_queue.next_startable(["gone"], [])
    assert (pick, stale) == (None, ["gone"])


def test_next_startable_on_an_empty_queue():
    assert md_queue.next_startable([], [FakeJob("a")]) == (None, [])


# ── the view the UI renders ──────────────────────────────────────────────────────


def test_queue_view_numbers_from_one_and_carries_status(tmp_path):
    md_queue.save_queue(tmp_path, ["a", "b"])
    view = md_queue.queue_view(
        tmp_path, [FakeJob("a", MdStatus.queued, design_name="6hb")]
    )
    assert [(v["job_id"], v["position"]) for v in view] == [("a", 1), ("b", 2)]
    assert view[0]["design_name"] == "6hb"
    assert view[0]["status"] == "queued"
    assert view[1]["status"] is None  # job not in the list → unknown, not a crash
