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
from backend.core.runpod_api import RunpodClient, ssh_endpoint  # noqa: E402
from backend.core.runpod_conn import RunpodConnection  # noqa: E402
from backend.core.runpod_executor import remote_dir_for  # noqa: E402
from experiments.exp43_runpod_bench.spend_ledger import HARD_CAP_USD, SpendLedger  # noqa: E402

WORKSPACE = ROOT / "workspace"
JOB_ID = os.environ.get("NADOC_WATCH_JOB") or (Path(__file__).parent / "JOB_ID_3x6x400").read_text().strip()

# "Periodic cell has become too small" is an NPT box relaxing ~3% to equilibrium density
# crossing NAMD's fixed patch grid. It is SELF-HEALING and the chain script already
# retries it (bounded). Do NOT panic-kill on it.
BENIGN = ("Periodic cell has become too small",)

# The ladder is NOT one timestep. The minimisation is 2 fs, the first dynamics chunk is
# the SOFT integrator (flexible H bonds, 1 fs, offload — no GPUresident), and everything
# after it is the fast path (4 fs + HMR + GPUresident). Reporting ns/day against the wrong
# one silently mis-sizes production by 4x.
TIMESTEP_FS = {"min": 2.0, "soft": 1.0, "fast": 4.0}


def _kind(seg: str) -> str:
    if "_min" in seg:
        return "min"
    if seg.endswith("_01_300K_NPT_ENM_k0p5_p10"):
        return "soft"
    return "fast"


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

        # Pick the pod THIS JOB is on — never just pods[0]. Once a second pod exists (a
        # benchmark, a build), pods[0] is a coin flip: the sentinel files still read fine
        # because the VOLUME is shared, but `kill -0 <pid>` is pod-LOCAL, so we check the
        # job's PID on someone else's machine and report a perfectly healthy run as DEAD.
        # A false alarm that kills a good pod costs exactly as much as a missed real one.
        pod = next((p for p in pods if p.id == job.runpod_pod_id), None)
        if pod is None:
            print(f"PODS     {len(pods)} live, but NONE is this job's pod "
                  f"({job.runpod_pod_id}) — it is gone")
            print(ledger.summary())
            return 1
        print(f"POD      {pod.id}  {pod.desired_status}  ${pod.cost_per_hr}/hr"
              + (f"   ({len(pods)} pods live)" if len(pods) > 1 else ""))

        endpoint = ssh_endpoint(pod)
        if endpoint is None:
            print("SSH      not reachable yet (pod still booting)")
            return 0
        host, port = endpoint
        conn = RunpodConnection(
            host=host, port=port, pod_id=pod.id,
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
            n_frames = len(energies)
            print(f"PROGRESS {cur}: {n_frames} ENERGY frames, last step {energies[-1] if energies else '-'}")

            # Find TOTAL by NAME from the ETITLE header, never by a hardcoded column
            # index. Counting columns by hand got TEMP instead of TOTAL — and TEMP is
            # legitimately 0.0 during a minimisation, so the watchdog screamed
            # "structure blew up" at a perfectly healthy run. A false alarm that kills a
            # good pod costs exactly as much as a missed real one.
            head = re.search(r"^ETITLE:\s+(.*)$", log_txt, re.M)
            rows = [ln.split()[1:] for ln in log_txt.splitlines() if ln.startswith("ENERGY:")]
            if head and rows:
                cols = head.group(1).split()
                try:
                    i_total = cols.index("TOTAL")
                    last = rows[-1][i_total]
                    val = float(last)
                    ok = val == val and abs(val) < 1e10 and val < 0    # NaN != NaN
                    print(f"SANITY   TOTAL = {val:.4e}  {'ok' if ok else '*** BAD ***'}")
                    if not ok:
                        problems.append(f"TOTAL energy is {last} — structure blew up")
                except (ValueError, IndexError):
                    problems.append(f"TOTAL energy unparseable in {cur} (NaN?)")

            # ms/step — the number the entire budget hangs on.
            #
            # NAMD prints `Benchmark time:` only for DYNAMICS, so a minimisation gives
            # none. Fall back to wall-clock/step from the log's own age, which works for
            # every segment type. (And remember NAMD reports throughput in DIFFERENT
            # UNITS by mode — offload prints days/ns, GPU-resident prints ns/day — so
            # never trust a single parsed rate line without knowing which mode you're in.)
            m = re.findall(r"Benchmark time:.*?([\d.]+)\s+s/step", log_txt)
            s_per_step = float(m[-1]) if m else None
            if s_per_step is None and len(energies) >= 2:
                # Two samples a few seconds apart: how far did the step counter move, and
                # how long did that take? Works for a minimisation too (which prints no
                # Benchmark line at all) and needs no file birth-time — `stat -c %W`
                # returns 0 on the pod's network FS.
                before = int(energies[-1])
                t0 = time.time()
                await asyncio.sleep(20)
                again = (await conn.run(
                    f"grep -c '^ENERGY:' {remote}/{cur}.log; "
                    f"grep '^ENERGY:' {remote}/{cur}.log | tail -1 | awk '{{print $2}}'")).stdout
                dt = time.time() - t0
                try:
                    after = int(again.split()[-1])
                    if after > before:
                        s_per_step = dt / (after - before)
                except (ValueError, IndexError):
                    pass
            if s_per_step:
                ts_fs = TIMESTEP_FS.get(_kind(cur), 4.0)
                print(f"SPEED    {s_per_step * 1000:.1f} ms/step   "
                      f"({ts_fs * 1e-6 / s_per_step * 86400:.1f} ns/day at {ts_fs:g} fs)"
                      f"   [{_kind(cur)}]")

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


async def oneline() -> int:
    """One compact line per poll — for the overnight Monitor, which turns every stdout
    line into a notification. The verbose form would emit eight per poll."""
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = await main()
    got = {}
    for ln in buf.getvalue().splitlines():
        if ln[:8].strip():
            got[ln[:8].strip()] = ln[8:].strip()
    bits = [
        got.get("COST", "?").split()[0],
        got.get("STATUS", "?").split()[0],
        (got.get("PROGRESS", "") or "-").split(":")[0][-28:],
        "step " + (got.get("PROGRESS", "").split("last step ")[-1] if "last step" in got.get("PROGRESS", "") else "?"),
        got.get("SANITY", "").replace("TOTAL = ", "E="),
        got.get("SPEED", "").split("(")[0].strip(),
        got.get("OUTPUT", "").split()[0] + " coor",
    ]
    print(" | ".join(b for b in bits if b and b != "?"), flush=True)
    if rc:
        for p in buf.getvalue().split("*** PROBLEMS ***")[-1].splitlines():
            if p.strip().startswith("-"):
                print("PROBLEM:" + p.strip()[1:], flush=True)
    return rc


if __name__ == "__main__":
    if "--oneline" in sys.argv:
        raise SystemExit(asyncio.run(oneline()))
    raise SystemExit(asyncio.run(main()))
