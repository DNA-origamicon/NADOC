"""Scheduling tests use tiny fake tasks, never QM calculations."""

import json
import subprocess
import time
from pathlib import Path

import pytest
from experiments.cpd_anti_additive import adaptive_gradients as ag


def setup_case(tmp_path, monkeypatch, status):
    tasks = [{"id": str(i)} for i in range(12)]
    plan = tmp_path / "plan.json"
    plan.write_text(json.dumps({"tasks": tasks}))
    state = tmp_path / "opt.json"
    state.write_text(json.dumps(status))
    monkeypatch.setattr(ag, "_completion_state", lambda **kw: "pending")
    monkeypatch.setattr(ag.os, "sched_setaffinity", lambda *a: None)
    return plan, state


def test_completed_optimizer_releases_cores_and_computes_once(tmp_path, monkeypatch):
    plan, state = setup_case(
        tmp_path, monkeypatch, {"state": "complete", "pid": 99999999}
    )
    seen = []

    def task(**kw):
        seen.append((kw["task"]["id"], kw["threads"]))
        return {"task_id": kw["task"]["id"]}

    monkeypatch.setattr(ag, "_run_task", task)
    ag.run(
        plan,
        tmp_path,
        {"workers": 3, "threads": 3},
        {2: 3, 3: 2, 4: 1},
        Path("/unused"),
        state,
    )
    assert sorted(k for k, _ in seen) == sorted(str(i) for i in range(12))
    assert all(t == 4 for _, t in seen)
    report = json.loads((tmp_path / "adaptive_progress.json").read_text())
    assert report["completed_this_run"] == 12
    assert report["optimization_cores_reclaimed"]


def test_live_exit_wakes_scheduler_without_timer(tmp_path, monkeypatch):
    proc = subprocess.Popen(["/bin/sleep", "0.05"])
    try:
        plan, state = setup_case(
            tmp_path, monkeypatch, {"state": "running", "pid": proc.pid}
        )

        def task(**kw):
            time.sleep(0.025)
            return {"task_id": kw["task"]["id"]}

        monkeypatch.setattr(ag, "_run_task", task)
        ag.run(
            plan,
            tmp_path,
            {"workers": 3, "threads": 4},
            {2: 3, 3: 2, 4: 1},
            Path("/unused"),
            state,
        )
        report = json.loads((tmp_path / "adaptive_progress.json").read_text())
        assert report["completed_this_run"] == 12
        assert len(report["events"]) == 1
    finally:
        proc.wait(timeout=1)


def test_task_failure_is_not_accepted(tmp_path, monkeypatch):
    plan, state = setup_case(
        tmp_path, monkeypatch, {"state": "complete", "pid": 99999999}
    )

    def fail(**kw):
        raise RuntimeError("native gradient failed")

    monkeypatch.setattr(ag, "_run_task", fail)
    with pytest.raises(RuntimeError, match="native gradient failed"):
        ag.run(
            plan,
            tmp_path,
            {"workers": 3, "threads": 4},
            {2: 3, 3: 2, 4: 1},
            Path("/unused"),
            state,
        )
