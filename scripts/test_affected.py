"""Explicit current-task backend selection; never consumes broad regression debt.

Mappings are reviewed regression starting points, not a claim of complete impact
analysis. Callers must include consumers/contracts affected by their actual diff.
Unmapped sources require explicit tests and a coverage rationale.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parent.parent
MAP = ROOT / "scripts/test_impact.json"


def relative_file(value: str, root: Path = ROOT) -> str:
    path = (root / value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Expected an existing file inside the repository: {value}")
    return path.relative_to(root).as_posix()


def test_target(value: str, root: Path = ROOT) -> str:
    filename, separator, node = value.partition("::")
    relative = relative_file(filename, root)
    if not relative.startswith("tests/test_") or not relative.endswith(".py"):
        raise ValueError(f"Expected a test file/node under tests/: {value}")
    return relative + (separator + node if separator else "")


def select(paths: list[str], explicit: list[str], reason: str, root: Path = ROOT,
           mapping: dict | None = None) -> tuple[list[str], list[str]]:
    if not paths:
        raise ValueError("Supply current-task source files or test files; no broad default.")
    if mapping is None:
        mapping = json.loads(MAP.read_text())
    selected = {test_target(value, root) for value in explicit}
    decisions = []
    unknown = []
    for value in paths:
        filename = value.split("::", 1)[0]
        relative = relative_file(filename, root)
        if relative.startswith("tests/test_") and relative.endswith(".py"):
            selected.add(test_target(value, root))
            decisions.append(f"{value}: explicit test")
        elif relative in mapping:
            targets = mapping[relative]
            if not targets:
                raise ValueError(f"Empty impact mapping: {relative}")
            selected.update(test_target(target, root) for target in targets)
            decisions.append(f"{relative}: {', '.join(targets)}")
        else:
            unknown.append(relative)
    if unknown:
        if not explicit or not reason.strip():
            raise ValueError("Unmapped sources: " + ", ".join(unknown)
                             + ". Add a reviewed mapping or supply --test FILE (repeatable)"
                             " and --reason explaining consumer/contract coverage.")
        decisions.append(f"Reviewed selection for {', '.join(unknown)}: {reason.strip()}")
    if not selected:
        raise ValueError("No tests selected; coverage must be resolved before running.")
    return sorted(selected), decisions


def command(targets: list[str]) -> list[str]:
    return ["bash", str(ROOT / "scripts/validation_guard.sh"),
            "bash", str(ROOT / "scripts/test_guard.sh"), "test-affected", "0", "focused",
            "--", "uv", "run", "pytest", *targets, "--durations=10"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--test", action="append", default=[])
    parser.add_argument("--reason", default="")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    try:
        targets, decisions = select(args.paths, args.test, args.reason)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print("FOCUSED backend selection (including relevant slow tests):", flush=True)
    for decision in decisions:
        print(f"  {decision}", flush=True)
    cmd = command(targets)
    print(shlex.join(cmd), flush=True)
    print("Broad regression debt/watermark unchanged.", flush=True)
    return 0 if args.dry_run else subprocess.call(cmd, cwd=ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
