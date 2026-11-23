"""Run explicit frontend test files or Vitest-related source files, with resource guards."""

from __future__ import annotations

import argparse
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parent.parent


def command(paths: list[str], related: bool, root: Path = ROOT, *, watch: bool = False) -> list[str]:
    if not paths:
        raise ValueError("Supply test files or --related source files; use test-frontend-all for a broad sweep.")
    selected = []
    frontend = root / "frontend"
    for value in paths:
        path = (root / value if value.startswith("frontend/") else frontend / value).resolve()
        if not path.is_relative_to(frontend / "src") or not path.is_file():
            raise ValueError(f"Expected an existing file under frontend/src/: {value}")
        if related:
            if path.suffix != ".js":
                raise ValueError("Related selection supports JS imports; select explicit tests for HTML/CSS/wiring changes.")
        elif not path.name.endswith(".test.js"):
            raise ValueError(f"Expected .test.js file, or use --related for source files: {value}")
        selected.append(path.relative_to(frontend).as_posix())
    # No --passWithNoTests: an empty dependency selection must fail visibly.
    mode = (["related"] if watch else ["related", "--run"]) if related else ["watch" if watch else "run"]
    return ["bash", str(root / "scripts/validation_guard.sh"), "node", "node_modules/vitest/vitest.mjs",
            *mode, *sorted(set(selected))]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+")
    parser.add_argument("--related", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--watch", action="store_true", help="Explicit interactive watch; holds the validation lock")
    args = parser.parse_args(argv)
    try:
        cmd = command(args.paths, args.related, watch=args.watch)
    except ValueError as exc:
        parser.error(str(exc))
    print("FOCUSED frontend selection: " + shlex.join(cmd), flush=True)
    return 0 if args.dry_run else subprocess.call(cmd, cwd=ROOT / "frontend")


if __name__ == "__main__":
    raise SystemExit(main())
