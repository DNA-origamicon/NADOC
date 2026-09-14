"""Independent local watchdog for one exact RunPod pod.

The controller process is not a safe billing boundary: an editor, terminal, OOM killer,
or hard process termination can prevent its ``finally`` block from running.  RunPod's
``terminateAfter`` field is retained as a provider hint, but was observed not to terminate
an active pod on 2026-09-04.  This module therefore launches a sibling user-systemd service
that owns the same exact pod id and destroys it when either the controller identity is lost
or the local deadline is reached.

The watchdog never matches a name or a prefix and never touches any other account pod.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Literal


WatchdogAction = Literal[
    "wait",
    "complete_provider_absent",
    "terminate_owner_lost",
    "terminate_deadline",
]


@dataclass(frozen=True)
class WatchdogDecision:
    """One pure watchdog decision, separated from API and process I/O for testing."""

    action: WatchdogAction
    reason: str


def parse_utc_deadline(value: str) -> datetime:
    """Parse an offset-aware ISO-8601 deadline and normalize it to UTC."""

    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"invalid watchdog deadline: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("watchdog deadline must include a timezone")
    return parsed.astimezone(timezone.utc)


def decide_watchdog_action(
    *,
    pod_present: bool,
    owner_alive: bool,
    now: datetime,
    deadline: datetime,
) -> WatchdogDecision:
    """Return the safe action for the currently observed state."""

    if not pod_present:
        return WatchdogDecision(
            "complete_provider_absent", "the exact pod is absent from the account"
        )
    instant = now if now.tzinfo is not None else now.replace(tzinfo=timezone.utc)
    cutoff = (
        deadline
        if deadline.tzinfo is not None
        else deadline.replace(tzinfo=timezone.utc)
    )
    if instant.astimezone(timezone.utc) >= cutoff.astimezone(timezone.utc):
        return WatchdogDecision(
            "terminate_deadline", "the independent local deadline was reached"
        )
    if not owner_alive:
        return WatchdogDecision(
            "terminate_owner_lost", "the owning controller process identity was lost"
        )
    return WatchdogDecision("wait", "owner and deadline are healthy")


def process_start_ticks(pid: int, *, proc_root: Path = Path("/proc")) -> int | None:
    """Linux process start time from ``/proc/PID/stat``, or ``None`` when absent.

    PID alone is insufficient because Linux can reuse it.  Field 22 is stable for the
    lifetime of a process and lets a watchdog distinguish the original controller from a
    later process that happens to receive the same PID.
    """

    try:
        raw = (proc_root / str(int(pid)) / "stat").read_text()
        closing_paren = raw.rfind(")")
        if closing_paren < 0:
            return None
        fields_after_comm = raw[closing_paren + 1 :].split()
        return int(fields_after_comm[19])
    except (OSError, ValueError, IndexError):
        return None


def process_identity_alive(
    pid: int, expected_start_ticks: int, *, proc_root: Path = Path("/proc")
) -> bool:
    """Whether the exact process identity (PID plus start time) still exists."""

    return process_start_ticks(pid, proc_root=proc_root) == int(expected_start_ticks)


def watchdog_unit_name(pod_id: str) -> str:
    """Return a systemd-safe unit name bound to one provider-issued pod id."""

    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}", pod_id):
        raise ValueError(f"unsafe RunPod pod id for watchdog unit: {pod_id!r}")
    return f"nadoc-runpod-watchdog-{pod_id}"


def start_watchdog_service(
    *,
    pod_id: str,
    owner_pid: int,
    deadline: str,
    audit_dir: Path,
    campaign_ledger: Path | None,
    campaign_cap_usd: float,
    poll_seconds: float = 30.0,
    python: Path | None = None,
    script: Path | None = None,
) -> str:
    """Start a user-systemd watchdog and fail closed if it cannot be installed.

    A transient user service is intentionally a sibling of the controller, not its child
    cgroup.  It survives terminal and VS Code shutdown.  It does not survive a host reboot;
    provider use remains disallowed for unattended runs without a second off-host guard.
    """

    parsed_deadline = parse_utc_deadline(deadline)
    start_ticks = process_start_ticks(owner_pid)
    if start_ticks is None:
        raise RuntimeError("cannot establish the RunPod controller process identity")
    unit = watchdog_unit_name(pod_id)
    executable = Path(sys.executable) if python is None else Path(python)
    if not executable.is_absolute():
        executable = Path.cwd() / executable
    watchdog_script = (
        Path(__file__).resolve().parents[2] / "scripts" / "runpod_pod_watchdog.py"
        if script is None
        else Path(script)
    )
    if not executable.is_file() or not watchdog_script.is_file():
        raise FileNotFoundError("RunPod watchdog Python or script is missing")
    command = [
        "systemd-run",
        "--user",
        f"--unit={unit}",
        f"--description=NADOC exact-pod watchdog {pod_id}",
        "--collect",
        "--same-dir",
        "--property=KillMode=control-group",
        "--property=Restart=on-failure",
        "--property=RestartSec=15s",
        # Keep a virtual-environment symlink intact. Resolving it selects the system
        # interpreter and silently drops the watchdog's installed dependencies.
        str(executable.absolute()),
        str(watchdog_script.resolve()),
        "--pod-id",
        pod_id,
        "--owner-pid",
        str(int(owner_pid)),
        "--owner-start-ticks",
        str(start_ticks),
        "--deadline",
        parsed_deadline.isoformat(timespec="seconds").replace("+00:00", "Z"),
        "--audit-dir",
        str(Path(audit_dir).resolve()),
        "--campaign-cap-usd",
        str(float(campaign_cap_usd)),
        "--poll-seconds",
        str(float(poll_seconds)),
    ]
    if campaign_ledger is not None:
        command.extend(["--campaign-ledger", str(Path(campaign_ledger).resolve())])
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
    )
    if completed.returncode:
        detail = (completed.stdout + completed.stderr).strip()[-1000:]
        raise RuntimeError(f"could not start independent RunPod watchdog: {detail}")
    return unit


def current_process_identity() -> tuple[int, int]:
    """Convenience helper for controllers that need to install a watchdog."""

    pid = os.getpid()
    ticks = process_start_ticks(pid)
    if ticks is None:
        raise RuntimeError("cannot read current process identity from /proc")
    return pid, ticks
