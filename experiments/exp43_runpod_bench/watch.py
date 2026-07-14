#!/usr/bin/env python3
"""One poll of the live pod. Prints a single status line; exits non-zero if it is unhappy.

    RUNPOD_API_KEY=$(cat ~/.runpod_key) python experiments/exp43_runpod_bench/watch.py

Checks, in the order that costs money:

  COST     cumulative across EVERY pod this session created (the in-code kill-switch is
           per-POD and has no memory — two pods each get the full budget).
  ALIVE    `kill -0 <pid>`. NEVER `pgrep namd3`: NAMD renames its process to
           "NAMD masterPe", so pgrep matches NOTHING and reports a live job as dead.
  PROGRESS ENERGY frame count in the current segment log must be INCREASING, and the
           .coor count growing. A flat frame count is a wedged run billing at full rate.
  SANITY   latest TOTAL energy finite and negative. NaN or a +-1e11 sentinel = the
           structure blew up; kill it rather than let it burn the night.
  STATUS   the nadoc_status sentinel (running / completed / failed:<seg> / lifetime).

Also derives ms/step from the log, which is the number the whole budget hangs on.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.md_job import MdJob  # noqa: E402
from backend.core.runpod_api import RunpodClient  # noqa: E402
from backend.core.runpod_conn import RunpodConnection  # noqa: E402
from backend.core.runpod_executor import remote_dir_for  # noqa: E402
from experiments.exp43_runpod_bench.spend_ledger import HARD_CAP_USD, SpendLedger  # noqa: E402

WORKSPACE = ROOT / "workspace"
JOB_ID = (Path(__file__).parent / "JOB_ID_3x6x400").read_text().strip()

# "Periodic cell has become too small" is an NPT box relaxing ~3% to equilibrium density
# crossing NAMD's fixed patch grid. It is SELF-HEALING and the chain script already
# retries it (bounded). Do NOT panic-kill on it.
BENIGN = ("Periodic cell has become too small",)


async def main() -> int:
    key = os.environ["RUNPOD_API_KEY"]
    job = MdJob.load(JOB_ID, WORKSPACE)
    ledger = SpendLedger(Path(job.archive_path) / "spend.json")
    client = RunpodClient(key)
    problems: list[str] = []

    try:
        pods = [p for p in await client.list_pods() if not p.is_destroyed]
        spent = ledger.spent()
        print(f"COST     ${spent:.2f} / ${HARD_CAP_USD:.2f}   "
              f"(remaining ${ledger.remaining():.2f})")
        if spent > HARD_CAP_USD:
            problems.append(f"BUDGET EXCEEDED: ${spent:.2f} > ${HARD_CAP_USD}")

        if not pods:
            print("PODS     none live  (nothing billing)")
            print(ledger.summary())
            return 1 if problems else 0

        pod = pods[0]
        print(f"POD      {pod.id}  {pod.desired_status}  ${pod.cost_per_hr}/hr")

        conn = RunpodConnection(
            host=pod.ssh_host, port=pod.ssh_port, pod_id=pod.id,
            client_keys=[str(Path.home() / ".ssh" / "id_ed25519")],
        )
        await conn.connect()
        remote = remote_dir_for(job)

        status = (await conn.run(f"cat {remote}/nadoc_status 2>/dev/null")).stdout.strip()
        cur = (await conn.run(f"cat {remote}/nadoc_current 2>/dev/null")).stdout.strip()
        print(f"STATUS   {status or '(none yet)'}   current: {cur or '-'}")
        if status.startswith("failed"):
            problems.append(f"chain script reports {status}")
        if status == "lifetime":
            problems.append("KILL-SWITCH FIRED — pod outlived its budget")

        # ALIVE — the pid we spawned, never a process-name match.
        if job.runpod_pid:
            r = await conn.run(f"kill -0 {job.runpod_pid} 2>/dev/null && echo up || echo down")
            alive = r.stdout.strip() == "up"
            print(f"ALIVE    chain pid {job.runpod_pid}: {'up' if alive else 'DOWN'}")
            if not alive and status == "running":
                problems.append("chain pid is dead but status still says running")

        # PROGRESS + SANITY + ms/step, from the current segment's log.
        if cur:
            log_txt = (await conn.run(f"tail -c 200000 {remote}/{cur}.log 2>/dev/null")).stdout
            energies = re.findall(r"^ENERGY:\s+(\d+)\s+.*", log_txt, re.M)
            totals = re.findall(r"^ENERGY:\s+\d+(?:\s+\S+){10}\s+(\S+)", log_txt, re.M)
            n_frames = len(energies)
            print(f"PROGRESS {cur}: {n_frames} ENERGY frames, last step {energies[-1] if energies else '-'}")

            if totals:
                last = totals[-1]
                try:
                    val = float(last)
                    ok = val == val and abs(val) < 1e10 and val < 0    # NaN != NaN
                    print(f"SANITY   TOTAL = {val:.3e}  {'ok' if ok else '*** BAD ***'}")
                    if not ok:
                        problems.append(f"TOTAL energy is {last} — structure blew up")
                except ValueError:
                    problems.append(f"TOTAL energy unparseable: {last!r} (NaN?)")

            # ms/step — the number the entire budget hangs on.
            m = re.findall(r"Benchmark time:.*?(\d+\.\d+)\s+s/step", log_txt)
            if m:
                s_per_step = float(m[-1])
                print(f"SPEED    {s_per_step * 1000:.1f} ms/step  "
                      f"({4e-6 / s_per_step * 86400:.1f} ns/day at 4 fs)")

            fatal = re.findall(r"^FATAL ERROR:.*", log_txt, re.M)
            for f in fatal:
                if any(b in f for b in BENIGN):
                    print(f"BENIGN   {f.strip()}  (self-healing; chain retries)")
                else:
                    problems.append(f.strip())

        n_coor = (await conn.run(f"ls {remote}/output/*.coor 2>/dev/null | wc -l")).stdout.strip()
        print(f"OUTPUT   {n_coor} .coor on the volume")
        await conn.close()

    finally:
        await client.aclose()

    if problems:
        print("\n*** PROBLEMS ***")
        for p in problems:
            print("  -", p)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
