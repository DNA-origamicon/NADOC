"""Reliable poll-watch for a BLADE RunPod run. Run under Bash run_in_background (NO
nohup/&) so the harness delivers ONE completion notification carrying the terminal
POLL_RESULT. Polls internally; heartbeats go to the output file (not notifications).

Why this exists: the previous `until ! pgrep -f "<pat>"` waiters matched their OWN
command line, so they never fired. This checks the driver by PID via os.kill(pid, 0)
(no pattern), checks the expected output file, and queries the RunPod API for leaks.

Exits (each is the single notification the harness surfaces):
  POLL_RESULT=SUCCESS      expected npz landed -> done, happy path
  POLL_RESULT=OVERDUE      past --deadline-min, npz still missing -> ESCALATE
  POLL_RESULT=DRIVER_DIED  driver PID gone + npz missing -> ESCALATE (+ pod maybe leaking)
  POLL_RESULT=LEAK         a pod is billing but driver is dead -> ESCALATE (reap NOW)
On any non-SUCCESS result the main loop should spawn a diagnostic agent.

  python blade_poll.py --driver-pid 12345 --expect-npz /path/x.npz \
      --deadline-min 600 --poll-sec 180
"""
import argparse
import os
import sys
import time
from pathlib import Path

REPO = Path("/home/jojo/Work/NADOC")
EXP43 = REPO / "experiments/exp43_runpod_bench"
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(EXP43))


def pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)  # signal 0 = existence check, no pattern matching
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else


def live_pods(key: str):
    try:
        import asyncio
        from backend.core.runpod_api import RunpodClient  # noqa: PLC0415
        async def _q():
            c = RunpodClient(key)
            try:
                return [p.id for p in await c.list_pods() if not p.is_destroyed]
            finally:
                await c.aclose()
        return asyncio.run(_q())
    except Exception as e:
        return f"POD_QUERY_ERR:{e}"


def emit(msg):
    print(msg, flush=True)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--driver-pid", type=int, default=0,
                    help="optional; 0 = skip driver-death check (deadman covers that)")
    ap.add_argument("--expect-npz", required=True)
    ap.add_argument("--deadline-min", type=float, required=True)
    ap.add_argument("--poll-sec", type=float, default=180)
    ap.add_argument("--grace-sec", type=float, default=120,
                    help="after driver PID vanishes, wait this long for the npz before DRIVER_DIED")
    args = ap.parse_args()

    key = (Path.home() / ".runpod_key").read_text().strip()
    npz = Path(args.expect_npz)
    t0 = time.time()
    deadline = t0 + args.deadline_min * 60
    driver_gone_at = None
    last_size = -1  # require the npz size to be STABLE across two polls (fetch complete),
    #               not merely present — a partial download is non-zero but still growing.
    emit(f"POLL start pid={args.driver_pid} npz={npz} deadline={args.deadline_min}min poll={args.poll_sec}s")

    while True:
        now = time.time()
        el = int(now - t0)
        if npz.exists() and npz.stat().st_size > 0:
            sz = npz.stat().st_size
            if sz == last_size:
                emit(f"POLL_RESULT=SUCCESS npz={npz} size={sz} elapsed={el}s")
                return 0
            emit(f"[+{el}s] npz present, size={sz} (was {last_size}) — waiting for stable size")
            last_size = sz
            time.sleep(args.poll_sec)
            continue
        alive = pid_alive(args.driver_pid) if args.driver_pid > 0 else None
        pods = live_pods(key)
        # heartbeat -> output file only (run_in_background doesn't notify on these)
        emit(f"[+{el}s] driver_alive={alive} npz=missing pods={pods}")

        if args.driver_pid > 0 and not alive:
            driver_gone_at = driver_gone_at or now
            if now - driver_gone_at > args.grace_sec:
                if isinstance(pods, list) and pods:
                    emit(f"POLL_RESULT=LEAK driver dead, pods still billing={pods} elapsed={el}s")
                    return 4
                emit(f"POLL_RESULT=DRIVER_DIED npz missing, pods={pods} elapsed={el}s")
                return 3
        else:
            driver_gone_at = None

        if now > deadline:
            emit(f"POLL_RESULT=OVERDUE past {args.deadline_min}min, npz missing, "
                 f"driver_alive={alive}, pods={pods} elapsed={el}s")
            return 2
        time.sleep(args.poll_sec)


if __name__ == "__main__":
    sys.exit(main())
