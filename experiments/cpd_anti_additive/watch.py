"""External, event-driven supervision with durable and retryable wake receipts."""

import argparse
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_published_comparator.completion_events import CompletionEvents
from experiments.cpd_published_comparator.trigger_dna_review import save


def resolve_codex(root):
    config = root / "watcher_config.json"
    path = (
        json.loads(config.read_text()).get("codex_executable")
        if config.exists()
        else shutil.which("codex")
    )
    if not path or not Path(path).is_absolute() or not os.access(path, os.X_OK):
        raise RuntimeError(
            "Pin an executable absolute codex path in watcher_config.json before launching QM"
        )
    return path


def process_identity(pid):
    try:
        return Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()[19]
    except FileNotFoundError:
        return None


def terminal_event(status, alive):
    if status["state"] in ("complete", "failed"):
        return status["state"]
    if not alive:
        return "supervisor_stopped"
    return None


def observed_event(root, pid, expected_identity, process_exited=False):
    status = json.loads((root / "status.json").read_text())
    identity = process_identity(pid)
    alive = not process_exited and identity is not None and identity == expected_identity
    if not alive:
        # The supervisor may have atomically saved its terminal status between
        # our first read and pidfd/process-exit observation. Read it again.
        status = json.loads((root / "status.json").read_text())
    return terminal_event(status, alive)


def overdue_was_delivered(deliveries, deadline_id):
    return any(
        d["returncode"] == 0
        and d["event"] == "overdue"
        and d.get("deadline_id", "initial") == deadline_id
        for d in deliveries
    )


def deliver(codex, thread, message, timeout=30):
    try:
        p = subprocess.run(
            [codex, "queue", "--thread", thread, "--message", message],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return dict(
            returncode=p.returncode, stdout=p.stdout, stderr=p.stderr, at=time.time()
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(returncode=-1, stdout="", stderr=repr(exc), at=time.time())


def main(root, thread):
    codex = resolve_codex(root)
    config = json.loads((root / "watcher_config.json").read_text())
    with (root / "completion_trigger.lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        path = root / "completion_wake.json"
        status = json.loads((root / "status.json").read_text())
        wake = (
            json.loads(path.read_text())
            if path.exists()
            else dict(
                token=str(uuid.uuid4()),
                thread=thread,
                deliveries=[],
                armed_at=time.time(),
                expected_seconds=config.get("expected_seconds", 21600),
                supervisor_pid=status["pid"],
                supervisor_identity=process_identity(status["pid"]),
            )
        )
        if wake["thread"] != thread:
            raise ValueError("Refusing to redirect an existing campaign wake")
        if any(
            d["returncode"] == 0 and d["event"] != "overdue" for d in wake["deliveries"]
        ):
            return
        expected = wake["expected_seconds"]
        wake.update(
            state="armed",
            watcher_pid=os.getpid(),
            codex_executable=codex,
            overdue_seconds=expected + max(300, expected * 0.5),
        )
        deadline_id = config.get("review_deadline_id", "initial")
        deadline = config.get(
            "review_deadline_epoch", wake["armed_at"] + wake["overdue_seconds"]
        )
        wake.update(active_deadline_id=deadline_id, active_deadline_epoch=deadline)
        events = CompletionEvents(root, status["pid"])
        save(path, wake)
        overdue_sent = overdue_was_delivered(wake["deliveries"], deadline_id)
        process_exited = False
        try:
            while True:
                event = observed_event(
                    root, wake["supervisor_pid"], wake["supervisor_identity"], process_exited
                )
                if event is None and not overdue_sent and time.time() >= deadline:
                    event = "overdue"
                if event:
                    if config.get("self_test"):
                        message = (
                            f"CPD_WATCHER_SELF_TEST token={wake['token']} event={event}. "
                            f"Write {root}/completion_wake_ack.json with token, event, received_at; "
                            "this is a delivery test only. Continue the currently authorized CPD work; do not start duplicate jobs."
                        )
                    else:
                        message = (
                            f"CPD_ANTI_QM_WAKE token={wake['token']} event={event}. "
                            f"Review {root}/status.json and native outputs. Write {root}/completion_wake_ack.json with token, event, received_at. "
                            "Continue the user-authorized campaign from docs/cpd_anti_additive_campaign.md. "
                            "Verify actual evidence, preserve failures, and do not confuse optimizer completion with minimum certification. No cloud spending."
                        )
                    receipt = deliver(
                        codex, thread, message, config.get("queue_timeout_seconds", 30)
                    )
                    receipt["event"] = event
                    receipt["deadline_id"] = deadline_id
                    wake["deliveries"].append(receipt)
                    wake["state"] = (
                        "queued" if receipt["returncode"] == 0 else "delivery_failed"
                    )
                    save(path, wake)
                    if receipt["returncode"]:
                        # systemd restarts this independent watcher; token/history survive.
                        raise RuntimeError(
                            "Wake delivery failed; durable receipt saved"
                        )
                    if event != "overdue":
                        return
                    overdue_sent = True
                signals = events.wait(None if overdue_sent else max(0, deadline - time.time()))
                # A readable pidfd proves exit even while /proc still holds a zombie.
                process_exited = process_exited or "process_exit" in signals
        finally:
            events.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    p.add_argument("--thread", required=True)
    args = p.parse_args()
    main(args.root.resolve(), args.thread)
