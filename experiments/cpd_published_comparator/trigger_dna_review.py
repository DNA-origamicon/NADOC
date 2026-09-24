"""Event-driven wake of the originating agent on completion or an overdue deadline."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import subprocess
import time

REPO = Path(__file__).resolve().parents[2]


def save(path, value):
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, indent=2) + "\n")
    temporary.replace(path)


def terminal_reason(status, alive):
    if status["state"] == "complete":
        keys = {(r["system"], r["replica"], r["block"]) for r in status["records"]}
        expected = {
            (s, r, b)
            for s in ["cpd", "control"]
            for r in range(1, 4)
            for b in range(1, 6)
        }
        if "expected_keys" in status:
            expected = {tuple(key) for key in status["expected_keys"]}
        return (
            "complete"
            if keys == expected and len(status["records"]) == len(expected)
            else "incomplete terminal manifest"
        )
    if status["state"] == "failed":
        return "campaign failed"
    if not alive:
        return "supervisor stopped before terminal status"
    return None


def review_succeeded(exit_code, outcome, expected_blocks):
    return (
        exit_code == 0
        and outcome.get("review_completed") is True
        and outcome.get("verified_blocks") == expected_blocks
        and bool(outcome.get("report_markdown", "").strip())
    )


def run(root, codex, thread, expected_seconds, grace_seconds=300):
    from experiments.cpd_published_comparator.completion_events import (
        CompletionEvents,
        deadline_seconds,
    )
    import uuid

    with (root / "completion_trigger.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        target = root / "completion_wake.json"
        if target.exists():
            raise RuntimeError(
                "A wake trigger already exists; inspect it before retrying"
            )
        status = json.loads((root / "status.json").read_text())
        events = CompletionEvents(root, status.get("pid"))
        token = str(uuid.uuid4())
        state = dict(
            state="armed",
            thread=thread,
            token=token,
            pid=os.getpid(),
            armed_at=time.time(),
            expected_seconds=expected_seconds,
            overdue_after_seconds=deadline_seconds(expected_seconds, grace_seconds),
            mechanism="inotify + pidfd; codex queue to originating thread",
            deliveries=[],
        )
        save(target, state)
        deadline = time.monotonic() + state["overdue_after_seconds"]
        overdue_sent = False
        try:
            while True:
                status = json.loads((root / "status.json").read_text())
                alive = (
                    bool(status.get("pid")) and Path(f"/proc/{status['pid']}").exists()
                )
                reason = terminal_reason(status, alive)
                overdue = (
                    not reason and not overdue_sent and time.monotonic() >= deadline
                )
                if reason or overdue:
                    event = reason or "overdue"
                    snapshot = dict(
                        event=event,
                        at=time.time(),
                        state=status["state"],
                        completed_blocks=len(status["records"]),
                        supervisor_alive=alive,
                    )
                    if overdue:
                        # One targeted diagnostic at the deadline, not a repeating poll.
                        current = status.get("current", {})
                        folder = current.get("folder")
                        if folder and (Path(folder) / "run.log").exists():
                            with (Path(folder) / "run.log").open("rb") as log:
                                log.seek(0, 2)
                                log.seek(max(0, log.tell() - 12000))
                                snapshot["log_tail"] = log.read().decode(
                                    errors="replace"
                                )
                    save(root / f"wake_{event.replace(' ', '_')}.json", snapshot)
                    message = (
                        f"CPD_COMPLETION_WAKE token={token} event={event}. "
                        f"User-authorized long-job trigger for {root}. "
                        f"Acknowledge delivery by writing completion_wake_ack.json in that directory "
                        f"with token={token}, event={event}, and received_at. "
                        "Then review the actual evidence and report to the user. "
                        "If overdue, inspect the process/log progress and set a revised explicit deadline if justified; "
                        "do not repeatedly poll. If terminal, verify all blocks and convergence diagnostics. "
                        "Do not launch additional simulations or spend money. Preserve unrelated work."
                    )
                    result = subprocess.run(
                        [codex, "queue", "--thread", thread, "--message", message],
                        capture_output=True,
                        text=True,
                        timeout=30,
                    )
                    delivery = dict(
                        event=event,
                        returncode=result.returncode,
                        stdout=result.stdout,
                        stderr=result.stderr,
                        at=time.time(),
                    )
                    state["deliveries"].append(delivery)
                    state["state"] = (
                        "queued" if result.returncode == 0 else "delivery_failed"
                    )
                    state["note"] = (
                        "Queue acceptance is not acknowledgment; verify completion_wake_ack.json"
                    )
                    save(target, state)
                    if reason or result.returncode != 0:
                        return
                    overdue_sent = True
                events.wait(
                    None if overdue_sent else max(0, deadline - time.monotonic())
                )
        finally:
            events.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--codex", required=True)
    parser.add_argument("--thread", required=True)
    parser.add_argument(
        "--expected-seconds",
        type=float,
        required=True,
        help="Estimated remaining wall time when arming",
    )
    parser.add_argument("--grace-seconds", type=float, default=300)
    args = parser.parse_args()
    run(
        args.root.resolve(),
        args.codex,
        args.thread,
        args.expected_seconds,
        args.grace_seconds,
    )
