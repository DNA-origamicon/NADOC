#!/usr/bin/env python
"""Diagnose (and optionally build) NADOC's LAMMPS + CG-DNA (parallel oxDNA) setup.

The command-line counterpart to the in-app "MD Engines" panel's LAMMPS row: it
reuses the exact same detection (`engines.engines_status`) and build planner
(`engine_install.install_steps`) so the terminal and the UI never disagree —
the same relationship `oxdna_doctor.py` has for standalone oxDNA.

LAMMPS with the CG-DNA package runs the oxDNA/oxDNA2 force field MPI
domain-decomposed across CPU cores — the only oxDNA that scales to very large
assemblies (single-GPU oxDNA can't fit them). This checks:

* the build toolchain (git/cmake/make/c++) and whether an MPI toolchain is
  present (MPI is what makes it *parallel*),
* whether a LAMMPS binary is on any path NADOC searches,
* the "degraded" state — a LAMMPS built **without** the CG-DNA package, which
  runs but can't do oxDNA (the CG-DNA analog of a CPU-only oxDNA that can't do
  CUDA).

Run::

    uv run python scripts/lammps_doctor.py          # diagnose only
    uv run python scripts/lammps_doctor.py --fix     # also build LAMMPS + CG-DNA

``--fix`` runs the auto-build (clone → cmake -D PKG_CG-DNA=on … → make) into
``~/lammps``, the path NADOC's resolver picks up automatically. Idempotent: an
existing clone is reused.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

# Allow running as a bare script without -m.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core import engine_install, engines  # noqa: E402
from backend.core.oxdna_runner import (  # noqa: E402
    find_lammps,
    lammps_supports_cgdna,
)

_OK = "\033[32m✓\033[0m"
_WARN = "\033[33m!\033[0m"
_BAD = "\033[31m✗\033[0m"


def _mark(ok: bool, warn: bool = False) -> str:
    return _WARN if warn else (_OK if ok else _BAD)


def diagnose() -> dict:
    """Print the full diagnosis and return the engines_status() dict."""
    st = engines.engines_status()
    tools = st["toolchain"]
    lmp = st["engines"]["lammps_oxdna"]

    print("LAMMPS + CG-DNA (parallel oxDNA) doctor")
    print("=" * 60)

    base = ["git", "cmake", "make", "cxx"]
    missing_base = [t for t in base if not tools.get(t)]
    print(f"{_mark(not missing_base)} Build toolchain: "
          + (", ".join(base) if not missing_base
             else f"missing {', '.join(missing_base)}"))
    mpi = bool(tools.get("mpi"))
    print(f"{_mark(mpi, warn=not mpi)} MPI toolchain (the parallel speedup): "
          f"{'present' if mpi else 'MISSING — would build single-core'}")

    path = lmp["path"] or find_lammps()
    if not path:
        print(f"{_BAD} LAMMPS binary: NOT FOUND on any path NADOC searches")
    else:
        cg = lmp.get("cgdna_capable")
        if cg is None:
            cg = lammps_supports_cgdna(path)
        print(f"{_mark(bool(cg), warn=not cg)} LAMMPS binary: {path}")
        print(f"    CG-DNA package (oxDNA styles): {'present' if cg else 'MISSING'}")

    print("-" * 60)

    if lmp.get("degraded"):
        print(f"{_WARN} DEGRADED — installed but can't run oxDNA.")
        print(f"    {lmp.get('degraded_note', '')}")
    elif not path:
        print(f"{_BAD} LAMMPS is not installed.")
    elif lmp.get("cgdna_capable"):
        print(f"{_OK} Ready — LAMMPS can run the oxDNA/oxDNA2 force field"
              + (" in parallel (MPI)." if mpi else " (single-core)."))

    return st


def _fix(st: dict) -> int:
    """Run the auto-build for LAMMPS + CG-DNA, streaming output. Returns exit code."""
    gpu, tools = st["gpu"], st["toolchain"]
    lmp = st["engines"]["lammps_oxdna"]

    if lmp.get("cgdna_capable") and not lmp.get("degraded"):
        print(f"\n{_OK} Already CG-DNA-capable — nothing to fix.")
        return 0

    plan = lmp.get("install") or engines._lammps_plan(gpu, tools)
    if not plan.get("can_auto"):
        miss = ", ".join(plan.get("missing_prereqs", [])) or "prerequisites"
        print(f"\n{_BAD} Cannot auto-build: missing {miss}.")
        print("    Install them, then re-run with --fix. Manual commands:")
        for c in plan.get("commands", []):
            print(f"      {c}")
        return 1

    print(f"\nBuilding LAMMPS + CG-DNA ({plan['target']}) — this can take several "
          f"minutes...\n")
    steps = engine_install.install_steps("lammps_oxdna", gpu, tools)
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

    new_path = find_lammps()
    if new_path and lammps_supports_cgdna(new_path):
        print(f"\n{_OK} Done — NADOC now resolves a CG-DNA LAMMPS: {new_path}")
        print("    Restart the NADOC backend (just dev) to pick it up.")
        return 0
    if new_path:
        print(f"\n{_WARN} Built, but the resolved binary ({new_path}) still reads "
              f"as lacking CG-DNA. If another LAMMPS is earlier on PATH, set "
              f"LAMMPS_BIN to the CG-DNA build.")
        return 1
    print(f"\n{_BAD} Build finished but no LAMMPS binary was detected afterward.")
    return 1


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--fix", action="store_true",
                    help="auto-build a CG-DNA LAMMPS into ~/lammps")
    args = ap.parse_args()
    st = diagnose()
    if args.fix:
        return _fix(st)
    lmp = st["engines"]["lammps_oxdna"]
    if lmp.get("degraded") or not lmp["path"]:
        print("\nRun with --fix to build LAMMPS + CG-DNA automatically.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
