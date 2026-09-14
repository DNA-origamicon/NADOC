"""Exact-pod watchdog behavior and systemd launch safety."""

from __future__ import annotations

import argparse
import asyncio
from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.core.runpod_oxdna import CampaignLedger
from backend.core import runpod_watchdog as watchdog


SCRIPT = Path(__file__).parents[1] / "scripts" / "runpod_pod_watchdog.py"
SPEC = importlib.util.spec_from_file_location("runpod_pod_watchdog", SCRIPT)
assert SPEC and SPEC.loader
SCRIPT_MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(SCRIPT_MODULE)


def test_decision_is_exact_and_fail_safe() -> None:
    now = datetime(2026, 9, 4, tzinfo=timezone.utc)
    future = now + timedelta(minutes=5)
    assert watchdog.decide_watchdog_action(
        pod_present=False, owner_alive=False, now=now, deadline=future
    ).action == "complete_provider_absent"
    assert watchdog.decide_watchdog_action(
        pod_present=True, owner_alive=True, now=now, deadline=future
    ).action == "wait"
    assert watchdog.decide_watchdog_action(
        pod_present=True, owner_alive=False, now=now, deadline=future
    ).action == "terminate_owner_lost"
    assert watchdog.decide_watchdog_action(
        pod_present=True,
        owner_alive=True,
        now=future,
        deadline=future,
    ).action == "terminate_deadline"


def test_deadline_requires_an_explicit_timezone() -> None:
    assert watchdog.parse_utc_deadline("2026-09-04T18:00:00Z").tzinfo == timezone.utc
    with pytest.raises(ValueError, match="timezone"):
        watchdog.parse_utc_deadline("2026-09-04T18:00:00")


def test_process_identity_rejects_pid_reuse(tmp_path: Path) -> None:
    proc = tmp_path / "proc" / "42"
    proc.mkdir(parents=True)
    # Fields following the command begin at proc-stat field 3; starttime is field 22.
    (proc / "stat").write_text("42 (controller with spaces) " + " ".join(["S"] * 19 + ["9876"]))
    assert watchdog.process_start_ticks(42, proc_root=tmp_path / "proc") == 9876
    assert watchdog.process_identity_alive(42, 9876, proc_root=tmp_path / "proc")
    assert not watchdog.process_identity_alive(42, 1234, proc_root=tmp_path / "proc")
    assert watchdog.process_start_ticks(99, proc_root=tmp_path / "proc") is None


def test_systemd_launcher_binds_exact_pod_and_controller_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    python = tmp_path / "python"
    script = tmp_path / "watchdog.py"
    python.write_text("")
    script.write_text("")
    seen = {}

    def fake_run(command, **kwargs):
        seen["command"] = command
        seen["kwargs"] = kwargs
        return SimpleNamespace(returncode=0, stdout="Running as unit", stderr="")

    monkeypatch.setattr(watchdog, "process_start_ticks", lambda _pid: 2468)
    monkeypatch.setattr(watchdog.subprocess, "run", fake_run)
    unit = watchdog.start_watchdog_service(
        pod_id="pod123",
        owner_pid=77,
        deadline="2026-09-04T18:00:00Z",
        audit_dir=tmp_path / "audit",
        campaign_ledger=tmp_path / "spend.json",
        campaign_cap_usd=10,
        python=python,
        script=script,
    )
    assert unit == "nadoc-runpod-watchdog-pod123"
    command = seen["command"]
    assert command[:3] == [
        "systemd-run",
        "--user",
        "--unit=nadoc-runpod-watchdog-pod123",
    ]
    assert command[command.index("--pod-id") + 1] == "pod123"
    assert command[command.index("--owner-pid") + 1] == "77"
    assert command[command.index("--owner-start-ticks") + 1] == "2468"
    assert "--property=Restart=on-failure" in command
    with pytest.raises(ValueError, match="unsafe"):
        watchdog.watchdog_unit_name("pod/id")


class _FakeClient:
    def __init__(self, observations):
        self.observations = iter(observations)
        self.events = []
        self.terminated = []

    async def list_pods(self):
        observation = next(self.observations)
        if isinstance(observation, Exception):
            raise observation
        return observation

    async def terminate_pod(self, pod_id, *, reason):
        self.terminated.append((pod_id, reason))

    def record_lifecycle(self, event, **details):
        self.events.append((event, details))


def _args(tmp_path: Path) -> argparse.Namespace:
    ledger_path = tmp_path / "spend.json"
    ledger = CampaignLedger(ledger_path, cap_usd=10)
    ledger.open_pod("target", 1.0, now=100.0)
    return argparse.Namespace(
        pod_id="target",
        owner_pid=77,
        owner_start_ticks=2468,
        deadline="2026-09-04T18:05:00Z",
        audit_dir=tmp_path,
        campaign_ledger=ledger_path,
        campaign_cap_usd=10.0,
        poll_seconds=0.001,
    )


def test_watchdog_retries_poll_then_kills_only_exact_pod_and_confirms_absence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = SimpleNamespace(id="target")
    unrelated = SimpleNamespace(id="do-not-touch")
    client = _FakeClient(
        [RuntimeError("temporary provider failure"), [target, unrelated], [unrelated]]
    )
    monkeypatch.setattr(SCRIPT_MODULE, "process_identity_alive", lambda *_args: False)

    async def no_sleep(_seconds):
        return None

    report = asyncio.run(
        SCRIPT_MODULE.run_watchdog(
            _args(tmp_path),
            client=client,
            sleep=no_sleep,
            now=lambda: datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc),
        )
    )
    assert client.terminated == [
        ("target", "independent_watchdog:terminate_owner_lost")
    ]
    assert report["status"] == "provider_absent"
    assert report["poll_failures"] == 1
    assert CampaignLedger(tmp_path / "spend.json", cap_usd=10).open_pod_ids() == []
    assert "independent_watchdog_triggered" in [event for event, _ in client.events]


def test_watchdog_does_not_kill_while_owner_and_deadline_are_healthy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = SimpleNamespace(id="target")
    client = _FakeClient([[target], []])
    monkeypatch.setattr(SCRIPT_MODULE, "process_identity_alive", lambda *_args: True)

    async def no_sleep(_seconds):
        return None

    report = asyncio.run(
        SCRIPT_MODULE.run_watchdog(
            _args(tmp_path),
            client=client,
            sleep=no_sleep,
            now=lambda: datetime(2026, 9, 4, 18, 0, tzinfo=timezone.utc),
        )
    )
    assert client.terminated == []
    assert report["trigger"] is None
