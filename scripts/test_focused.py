#!/usr/bin/env python3
"""Run one current-development test file/node, including slow tests, without a session.

An explicit file is required: directories, extra targets, and arbitrary pytest
configuration/plugin options cannot accidentally turn this into a broad sweep.
Relevance to the user's task is an agent responsibility; duration is not a gate.
Scientific campaigns retain their separate authorization and selection mechanism.
"""

from __future__ import annotations

import argparse
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def build_command(argv: list[str] | None = None) -> list[str]:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target", help="tests/test_topic.py[::Class::test_name]")
    parser.add_argument("-k")
    parser.add_argument("-m")
    parser.add_argument("--collect-only", action="store_true")
    parser.add_argument("--durations", type=int, default=10)
    parser.add_argument("--maxfail", type=int)
    parser.add_argument("-x", action="store_true")
    parser.add_argument("-q", action="store_true")
    parser.add_argument("-v", action="store_true")
    args = parser.parse_args(argv)
    path = Path(args.target.split("::", 1)[0]).resolve()
    if (
        not path.is_relative_to(ROOT / "tests")
        or not path.is_file()
        or path.suffix != ".py"
    ):
        parser.error(
            "target must be one existing Python test file/node under tests/, not a directory"
        )
    cmd = ["uv", "run", "pytest", args.target, f"--durations={args.durations}"]
    for flag in ("k", "m", "maxfail"):
        value = getattr(args, flag)
        if value is not None:
            cmd.extend([f"-{flag}" if len(flag) == 1 else f"--{flag}", str(value)])
    for flag in ("collect-only", "x", "q", "v"):
        if getattr(args, flag.replace("-", "_")):
            cmd.append(f"-{flag}" if len(flag) == 1 else f"--{flag}")
    return [
        "bash",
        str(ROOT / "scripts/test_guard.sh"),
        "test-focused",
        "0",
        "focused",
        "--",
        *cmd,
    ]


if __name__ == "__main__":
    raise SystemExit(subprocess.call(build_command()))
