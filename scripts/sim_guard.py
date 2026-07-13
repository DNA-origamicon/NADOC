"""Refuse to run a gate whose results a live simulation would make meaningless.

`just smoke` drives a real browser against real servers. A production NAMD/oxDNA/
ARBD/GROMACS job saturates the box (measured: NAMD `+p6` takes ~5.5 of 12 cores,
load average ~10), and the heavy browser specs then blow their 30 s budget purely
from CPU starvation. That produces a RED gate that says nothing about the code —
and worse, it moves: whichever spec happens to land at a bad moment is the one
that fails, so it reads like a flaky app rather than a busy machine.

So: fail LOUD and early rather than let the gate lie. This deliberately does NOT
skip (the pytest guard's choice) — `just smoke` is a *commit* gate, and a silent
skip would let a change through with no gate at all. Refusing is the safe default;
`NADOC_IGNORE_SIM_GUARD=1` is the explicit override.

Fails OPEN via heavy_sim_running(): a probe glitch never blocks the gate.

Usage:  uv run python scripts/sim_guard.py <gate-name>
Exit 0 = clear to run.  Exit 1 = a sim is running.
"""

from __future__ import annotations

import os
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))

from backend.core.hardware import heavy_sim_running  # noqa: E402


def main() -> int:
    gate = sys.argv[1] if len(sys.argv) > 1 else "this gate"

    if os.environ.get("NADOC_IGNORE_SIM_GUARD"):
        print(f"[sim-guard] NADOC_IGNORE_SIM_GUARD=1 — running {gate} anyway.")
        return 0

    running, reason = heavy_sim_running()
    if not running:
        return 0

    print(
        f"\n[sim-guard] REFUSING to run {gate}: a heavy simulation is running on this machine.\n"
        f"            {reason}\n\n"
        f"  {gate} drives a real browser; a production sim starves it and the specs time out.\n"
        f"  A red result here would be about the CPU, not your code.\n\n"
        f"  Either wait for the job to finish, or override:\n"
        f"      NADOC_IGNORE_SIM_GUARD=1 just {gate}\n",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
