"""Fast watcher failure-path tests; no messages or simulations are launched."""

import json
import subprocess
from unittest.mock import patch
import pytest
from experiments.cpd_anti_additive.watch import deliver, resolve_codex, terminal_event


def test_dead_supervisor_is_not_success():
    assert terminal_event({"state": "running"}, False) == "supervisor_stopped"
    assert terminal_event({"state": "running"}, True) is None
    assert terminal_event({"state": "failed"}, True) == "failed"
    assert terminal_event({"state": "complete"}, True) == "complete"


def test_pinned_executable_works_without_path(tmp_path, monkeypatch):
    (tmp_path / "watcher_config.json").write_text(
        json.dumps({"codex_executable": "/usr/bin/true"})
    )
    monkeypatch.setenv("PATH", "")
    assert resolve_codex(tmp_path) == "/usr/bin/true"


def test_missing_executable_fails_before_arming(tmp_path):
    (tmp_path / "watcher_config.json").write_text(
        json.dumps({"codex_executable": "/nonexistent/codex"})
    )
    with pytest.raises(RuntimeError, match="Pin"):
        resolve_codex(tmp_path)


@pytest.mark.parametrize(
    "error", [FileNotFoundError("gone"), subprocess.TimeoutExpired("codex", 30)]
)
def test_queue_exceptions_return_persistable_failure(error):
    with patch("subprocess.run", side_effect=error):
        result = deliver("/fake/codex", "thread", "message")
    assert result["returncode"] == -1
    assert result["stderr"]
    json.dumps(result)


def test_receipt_survives_retry_and_deduplicates(tmp_path):
    import os
    from experiments.cpd_anti_additive.watch import main

    (tmp_path / "watcher_config.json").write_text(
        json.dumps({"codex_executable": "/usr/bin/true"})
    )
    (tmp_path / "status.json").write_text(
        json.dumps({"state": "failed", "pid": os.getpid()})
    )
    with patch(
        "experiments.cpd_anti_additive.watch.deliver",
        return_value={"returncode": 1, "stderr": "temporary outage", "stdout": ""},
    ):
        with pytest.raises(RuntimeError, match="delivery failed"):
            main(tmp_path, "thread")
    first = json.loads((tmp_path / "completion_wake.json").read_text())
    assert first["state"] == "delivery_failed"
    with patch(
        "experiments.cpd_anti_additive.watch.deliver",
        return_value={"returncode": 0, "stderr": "", "stdout": "queued"},
    ) as delivery:
        main(tmp_path, "thread")
        main(tmp_path, "thread")
        assert delivery.call_count == 1
    last = json.loads((tmp_path / "completion_wake.json").read_text())
    assert last["token"] == first["token"]
    assert len(last["deliveries"]) == 2
    assert last["state"] == "queued"


def test_exit_race_rereads_final_atomic_status(tmp_path):
    from experiments.cpd_anti_additive.watch import observed_event

    with (
        patch(
            "pathlib.Path.read_text",
            side_effect=[
                json.dumps({"state": "running"}),
                json.dumps({"state": "complete"}),
            ],
        ),
        patch(
            "experiments.cpd_anti_additive.watch.process_identity", return_value=None
        ),
    ):
        assert observed_event(tmp_path, 123, "old-start-time") == "complete"


def test_review_deadline_has_its_own_notification():
    from experiments.cpd_anti_additive.watch import overdue_was_delivered

    old = [{"event": "overdue", "returncode": 0}]
    assert overdue_was_delivered(old, "initial")
    assert not overdue_was_delivered(old, "review-2")
    revised = old + [{"event": "overdue", "returncode": 0, "deadline_id": "review-2"}]
    assert overdue_was_delivered(revised, "review-2")


def test_pidfd_exit_overrides_lingering_process_identity(tmp_path):
    from experiments.cpd_anti_additive.watch import observed_event

    (tmp_path / "status.json").write_text(json.dumps({"state": "running"}))
    with patch("experiments.cpd_anti_additive.watch.process_identity", return_value="same"):
        assert observed_event(tmp_path, 123, "same", process_exited=True) == "supervisor_stopped"
