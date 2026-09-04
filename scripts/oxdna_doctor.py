#!/usr/bin/env python
"""Diagnose (and optionally fix) NADOC's oxDNA setup for full-speed GPU runs.

This is the command-line counterpart to the in-app "MD Engines" panel: it reuses
the exact same detection (`engines.engines_status`) and build planner
(`engine_install.install_steps`) so the terminal and the UI never disagree.

Run::

    uv run python scripts/oxdna_doctor.py          # diagnose only
    uv run python scripts/oxdna_doctor.py --fix     # also build a CUDA oxDNA

What it checks, in order of what breaks full-speed runs:

* a CUDA GPU + the CUDA toolkit (nvcc) needed to *build* a GPU engine,
* which oxDNA binary NADOC actually resolves, and whether it is CUDA-capable,
* the "degraded" state — a CPU-only binary shadowing the GPU (the classic
  conda/apt ``oxDNA`` on PATH that makes every ``backend = CUDA`` MD stage abort
  with "Backend 'CUDA' not supported").

``--fix`` builds NADOC's pinned upstream oxDNA revision into its managed engine directory,
the path NADOC's CUDA-preferring resolver picks up automatically — no env var
needed afterward.  Idempotent: an existing clone is reused.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Allow running as a bare script (python scripts/oxdna_doctor.py) without -m.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core import engine_install, engines  # noqa: E402
from backend.core.oxdna_runner import (  # noqa: E402
    find_oxdna,
    oxdna_supports_cuda,
)

_OK = "\033[32m✓\033[0m"
_WARN = "\033[33m!\033[0m"
_BAD = "\033[31m✗\033[0m"


def _mark(ok: bool, warn: bool = False) -> str:
    return _WARN if warn else (_OK if ok else _BAD)


def diagnose() -> dict:
    """Print the full diagnosis and return the engines_status() dict."""
    st = engines.engines_status()
    gpu, tools = st["gpu"], st["toolchain"]
    ox = st["engines"]["oxdna"]
    oxpy = st["engines"]["oxpy"]

    print("oxDNA full-speed doctor")
    print("=" * 60)

    names = ", ".join(gpu["names"]) or "none"
    print(f"{_mark(gpu['present'])} CUDA GPU: {names}"
          + (f" (compute {gpu['arch']})" if gpu.get("arch") else ""))
    print(f"{_mark(gpu['toolkit'], warn=not gpu['toolkit'] and gpu['present'])} "
          f"CUDA toolkit (nvcc, needed to build the GPU engine): "
          f"{'present' if gpu['toolkit'] else 'MISSING'}")

    base = ["git", "cmake", "make", "cxx"]
    missing_base = [t for t in base if not tools.get(t)]
    print(f"{_mark(not missing_base)} Build toolchain: "
          + (", ".join(base) if not missing_base
             else f"missing {', '.join(missing_base)}"))

    path = ox["path"] or find_oxdna()
    if not path:
        print(f"{_BAD} oxDNA binary: NOT FOUND on any path NADOC searches")
    else:
        cuda = ox.get("cuda_capable")
        if cuda is None:
            cuda = oxdna_supports_cuda(path)
        print(f"{_mark(bool(cuda), warn=not cuda and gpu['present'])} "
              f"oxDNA binary: {path}")
        print(f"    backend support: {'CUDA + CPU' if cuda else 'CPU only'}")

    print(
        f"{_mark(oxpy['installed'])} oxpy Live bindings: "
        f"{oxpy['path'] if oxpy['installed'] else 'MISSING'}"
    )
    if not oxpy["installed"]:
        print(f"    {oxpy.get('required_note') or 'Build oxDNA with Python bindings enabled.'}")

    print("-" * 60)

    if not oxpy["installed"] and path:
        print(f"{_WARN} DEGRADED — batch oxDNA works, but Live needs patched oxpy.")
        print("    Re-run with --fix to build and install oxpy into NADOC's environment.")
    elif ox.get("degraded"):
        print(f"{_WARN} DEGRADED — installed but not full-speed.")
        print(f"    {ox.get('degraded_note', '')}")
    elif not path:
        print(f"{_BAD} oxDNA is not installed.")
    elif gpu["present"] and ox.get("cuda_capable"):
        print(f"{_OK} Full-speed GPU runs are ready.")
    elif not gpu["present"]:
        print(f"{_OK} No GPU present — CPU oxDNA is the correct engine here.")

    return st


def _fix(st: dict) -> int:
    """Run the auto-build for a CUDA oxDNA, streaming output. Returns exit code."""
    gpu, tools = st["gpu"], st["toolchain"]
    ox = st["engines"]["oxdna"]
    oxpy = st["engines"]["oxpy"]

    if ox.get("cuda_capable") and not ox.get("degraded") and oxpy.get("installed"):
        print(f"\n{_OK} Already CUDA-capable — nothing to fix.")
        return 0

    plan = ox.get("install") or engines._source_build_plan(
        gpu, tools, name="oxDNA", commands_fn=engines._managed_oxdna_commands)
    if not plan.get("can_auto"):
        miss = ", ".join(plan.get("missing_prereqs", [])) or "prerequisites"
        print(f"\n{_BAD} Cannot auto-build: missing {miss}.")
        print("    Install them, then re-run with --fix. Manual commands:")
        for c in plan.get("commands", []):
            print(f"      {c}")
        return 1

    target = "CUDA" if gpu["present"] else "CPU"
    print(f"\nBuilding a {target} oxDNA (this can take several minutes)...\n")
    steps = engine_install.install_steps("oxdna", gpu, tools)
    for step in steps:
        skip = step.get("skip_if_dir")
        if skip and os.path.isdir(skip):
            print(f"  (already present: {skip} — skipping)")
            continue
        print(f"  → {step['label']}")
        os.makedirs(step["cwd"], exist_ok=True)
        rc = subprocess.run(
            step["argv"], cwd=step["cwd"],
            env={**os.environ, **step.get("env", {})}, check=False,
        ).returncode
        if rc != 0:
            print(f"\n{_BAD} Step failed (exit {rc}): {step['label']}")
            return rc

    # Re-verify against fresh detection (the capability cache keys on mtime, so
    # the freshly built binary is re-probed, not served stale).
    new_path = find_oxdna()
    new_status = engines.engines_status()
    if new_path and oxdna_supports_cuda(new_path) and new_status["engines"]["oxpy"]["installed"]:
        print(f"\n{_OK} Done — NADOC now resolves a CUDA oxDNA: {new_path}")
        print("    Restart the NADOC backend (just dev) to pick it up.")
        return 0
    if new_path:
        print(f"\n{_WARN} Built, but the resolved binary ({new_path}) still reads "
              f"as CPU-only. If you have a CPU oxDNA earlier on PATH, set "
              f"OXDNA_BIN to the CUDA build.")
        return 1
    print(f"\n{_BAD} Build finished but no oxDNA binary was detected afterward.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", action="store_true",
                    help="build NADOC's pinned CUDA-enabled upstream oxDNA")
    args = ap.parse_args()
    st = diagnose()
    if args.fix:
        return _fix(st)
    ox = st["engines"]["oxdna"]
    if ox.get("degraded") or not ox["path"] or not st["engines"]["oxpy"]["installed"]:
        print("\nRun with --fix to build the GPU engine and Live bindings automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
