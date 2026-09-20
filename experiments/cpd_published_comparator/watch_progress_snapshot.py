"""Refresh a saved CPD view on status events, without periodic polling."""

import argparse
import json
from pathlib import Path
import subprocess
import sys
from experiments.cpd_published_comparator.completion_events import CompletionEvents


def main(root):
    events = CompletionEvents(root)
    revision = None
    try:
        while True:
            state = json.loads((root / "status.json").read_text())
            current = (state["state"], len(state["records"]))
            if current != revision:
                subprocess.run(
                    [
                        sys.executable,
                        "experiments/cpd_published_comparator/export_progress.py",
                    ],
                    check=True,
                )
                revision = current
            if state["state"] != "running":
                return
            events.wait()
    finally:
        events.close()


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--root", type=Path, required=True)
    main(p.parse_args().root.resolve())
