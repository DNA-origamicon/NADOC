"""Wake on whole-cgroup termination, including its in-cgroup completion watcher."""

import argparse
import json
import os
from pathlib import Path
import select
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from experiments.cpd_anti_additive.watch import main

parser = argparse.ArgumentParser()
parser.add_argument("--root", type=Path, required=True)
parser.add_argument("--thread", required=True)
args = parser.parse_args()
state = json.loads((args.root / "status.json").read_text())
try:
    fd = os.pidfd_open(state["pid"])
except ProcessLookupError:
    fd = None
(args.root / "fallback_armed.json").write_text(
    json.dumps(
        {
            "supervisor_pid": state["pid"],
            "watcher_pid": os.getpid(),
            "thread": args.thread,
            "mechanism": "separate systemd service + pidfd",
        }
    )
    + "\n"
)
if fd is not None:
    select.select([fd], [], [])
    os.close(fd)
wake_path = args.root / "completion_wake.json"
wake = json.loads(wake_path.read_text()) if wake_path.exists() else {}
if not any(
    d["returncode"] == 0 and d["event"] != "overdue" for d in wake.get("deliveries", [])
):
    if wake_path.exists():
        (args.root / "completion_wake_before_fallback.json").write_text(
            wake_path.read_text()
        )
    main(args.root, args.thread)
