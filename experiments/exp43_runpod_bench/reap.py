#!/usr/bin/env python3
"""PANIC BUTTON — destroy every pod on the account, right now.

    python experiments/exp43_runpod_bench/reap.py            # list what is billing
    python experiments/exp43_runpod_bench/reap.py --kill     # destroy it all

Why this exists: the pod's on-pod kill-switch can only stop NAMD — it has no API key, so
it CANNOT stop the billing. Pod destruction lives in the launcher's `finally`. If the
launcher dies (reboot, OOM, closed terminal), the pod keeps billing an idle GPU until a
human notices. This is that human's one command.

Reads the key from ~/.runpod_key so it works with no environment set up.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import RunpodClient  # noqa: E402
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger  # noqa: E402

KEY_FILE = Path.home() / ".runpod_key"

# Where the job ledgers live. Reaping must CLOSE the pod here too, or a destroyed pod
# keeps accruing in `spent()` forever and every later budget decision is wrong.
LEDGER_ROOT = Path("/media/jojo/Archive/nadoc_jobs")


async def main() -> int:
    if not KEY_FILE.exists():
        print(f"no API key at {KEY_FILE}", file=sys.stderr)
        return 2
    kill = "--kill" in sys.argv

    client = RunpodClient(KEY_FILE.read_text().strip())
    try:
        # is_destroyed, NOT is_terminated: an EXITED pod is a stopped container that is
        # still on the account and still billing for its disk.
        pods = [p for p in await client.list_pods() if not p.is_destroyed]
        if not pods:
            print("nothing on the account. Nothing is billing.")
            return 0

        print(f"{len(pods)} pod(s) still on the account:")
        for p in pods:
            print(f"  {p.id}  {p.desired_status}  ${p.cost_per_hr}/hr  {p.raw.get('name')}")

        if not kill:
            print("\nre-run with --kill to destroy them")
            return 1

        ledgers = [SpendLedger(f) for f in sorted(LEDGER_ROOT.glob("*/spend.json"))]
        for p in pods:
            print(f"destroying {p.id} ...", flush=True)
            try:
                await client.terminate_pod(p.id)
            except Exception as exc:  # noqa: BLE001
                print(f"  !! FAILED: {exc} — destroy it by hand in the RunPod console")
                continue
            # The pod is gone; stop it accruing. Skipping this is how a destroyed pod
            # keeps inflating spent() and silently eats the remaining budget.
            for led in ledgers:
                led.close_pod(p.id)

        left = [p for p in await client.list_pods() if not p.is_destroyed]
        print(f"\nstill on the account: {len(left)} "
              f"{'— nothing billing' if not left else [p.id for p in left]}")
        return 0 if not left else 1
    finally:
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
