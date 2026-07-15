#!/usr/bin/env python3
"""ACTIVE billing safety net for a RunPod run — terminate the pod if its job reaches a
terminal state and the launcher then FAILS to tear the pod down in time.

Why this exists: the launcher (`run_job_on_pod`) tears its own pod down on failed/completed,
but only after `fetch_outputs` — which could hang (the runbook's "stuck fetch bills an idle pod
indefinitely"; now bounded by `FETCH_TIMEOUT_S`, but a dead launcher process or a network
partition still orphans the pod). A passive status logger provides NO protection — the 2026-07-15
run billed idle after `02_p10` failed because the babysitter only logged it. This watchdog ACTS.

SAFE by construction (avoids the L10 trap that once destroyed a healthy run):
  * It kills ONLY after a terminal state (`failed:` / `FATAL` / `completed`) has PERSISTED for
    ``--grace`` seconds — longer than the launcher's own bounded fetch+teardown — so it never
    races a healthy teardown. A transient between-segment blip resets the timer.
  * It terminates ONLY the pod whose name carries THIS job_id (targeted, never all-pods).

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
      python experiments/exp43_runpod_bench/watchdog.py <job_id> [--poll 60] [--grace 1080]
"""
from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import RunpodClient  # noqa: E402

HERE = Path(__file__).parent


def _watch_line(job_id: str) -> str:
    """One `watch.py --oneline` snapshot (its status parse already handles failed:/FATAL)."""
    try:
        r = subprocess.run(
            [sys.executable, str(HERE / "watch.py"), job_id, "--oneline"],
            capture_output=True, text=True, timeout=90, env=os.environ,
        )
        return (r.stdout + r.stderr)
    except subprocess.TimeoutExpired:
        return ""


async def _live_pods(client: RunpodClient, job_id: str):
    return [p for p in await client.list_pods()
            if not p.is_destroyed and job_id in (p.name or "")]


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("job_id")
    ap.add_argument("--poll", type=float, default=60.0, help="seconds between checks")
    ap.add_argument("--grace", type=float, default=1080.0,
                    help="seconds a terminal state must persist before the watchdog kills the "
                         "pod (default 18 min > the launcher's 15 min fetch timeout)")
    args = ap.parse_args()

    if not os.environ.get("RUNPOD_API_KEY"):
        print("RUNPOD_API_KEY not set", file=sys.stderr)
        return 2
    client = RunpodClient(os.environ["RUNPOD_API_KEY"])

    print(f"WATCHDOG guarding {args.job_id}: kills the pod only if failed/completed persists "
          f">{args.grace:.0f}s (launcher teardown gets first chance).", flush=True)

    terminal_since: float | None = None
    elapsed = 0.0
    while True:
        out = _watch_line(args.job_id).lower()
        if "nothing is billing" in out or "nothing on the account" in out:
            print("WATCHDOG: no pod billing — nothing to guard. Done.", flush=True)
            return 0
        is_terminal = ("failed:" in out) or ("fatal" in out) or ("completed" in out)

        if is_terminal:
            terminal_since = elapsed if terminal_since is None else terminal_since
            waited = elapsed - terminal_since
            print(f"WATCHDOG: terminal state seen ({waited:.0f}/{args.grace:.0f}s grace) — "
                  f"letting the launcher tear down first.", flush=True)
            if waited >= args.grace:
                pods = await _live_pods(client, args.job_id)
                if not pods:
                    print("WATCHDOG: launcher already destroyed the pod. Done.", flush=True)
                    return 0
                for p in pods:
                    print(f"WATCHDOG: launcher did NOT tear down in time — terminating {p.id} "
                          f"({p.name})", flush=True)
                    await client.terminate_pod(p.id)
                left = await _live_pods(client, args.job_id)
                print(f"WATCHDOG: {len(left)} pod(s) still live after kill. Done.", flush=True)
                return 0
        else:
            terminal_since = None  # transient blip / still progressing — reset

        await asyncio.sleep(args.poll)
        elapsed += args.poll


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
