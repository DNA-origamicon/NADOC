#!/usr/bin/env python3
"""Autonomous billing watchdog — the hard safety net for an unattended GPU-bench campaign.

Run it as a persistent background monitor BEFORE renting anything:

    RUNPOD_API_KEY=$(cat ~/.runpod_key) \
        python experiments/exp43_runpod_bench/pod_watchdog.py --budget 5 --max-pod-min 25

Every poll it independently re-queries RunPod and enforces three hard limits, in the order
that costs money:

  1. BUDGET  — if the campaign ledger's cumulative spend >= --budget, DESTROY every campaign
               pod. This is the backstop for the in-driver ledger being wrong or the driver
               being dead.
  2. AGE     — any campaign pod older than --max-pod-min is destroyed. A benchmark is minutes;
               a campaign pod alive for half an hour means a stuck fetch / hung launcher /
               dead driver (the exact orphan-billing failure the runbook catalogues).
  3. ORPHAN  — a campaign-named pod with no live driver still gets aged-out by (2); an
               UNKNOWN pod (not campaign-named) is only WARNed about, never killed — it could
               be an unrelated production pod. reap.py --kill is the human all-pods button.

It only ever DESTROYS pods whose name starts with a campaign prefix, so it cannot nuke a
production run (the mistake that "destroyed EVERY pod on the account" — see git log). Every
kill is verified with confirm_pod_terminated and written to the confirmation log; a kill that
cannot be confirmed lands in the review queue.

Output is the event stream: one line on start, a heartbeat only when state changes or every
--heartbeat-min, and a line for every WARN / KILL. Silence = healthy and unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from backend.core.runpod_api import RunpodClient  # noqa: E402
from experiments.exp43_runpod_bench.runpod_confirm import (  # noqa: E402
    ConfirmationLog, confirm_pod_terminated,
)
from experiments.exp43_runpod_bench.spend_ledger import SpendLedger  # noqa: E402

CAMPAIGN_PREFIXES = ("nadoc-bench", "nadoc-fetch", "nadoc-stage")
# NOT under nadoc_jobs/: SpendLedger.spent() sums every *.spend.json one level below the
# ledger's grandparent, so putting it here (grandparent = /media/jojo/Archive) isolates this
# campaign's spend from the old 3x6x400 / 24hb ledgers — a $5 budget must not inherit $80.
CAMPAIGN_DIR = Path("/media/jojo/Archive/nadoc_bench_campaign")
STATE_FILE = CAMPAIGN_DIR / "watchdog_state.json"


def is_campaign(pod) -> bool:
    return str(pod.raw.get("name", "")).startswith(CAMPAIGN_PREFIXES)


def emit(msg: str) -> None:
    print(f"{time.strftime('%H:%M:%S')} {msg}", flush=True)


def load_state() -> dict:
    if STATE_FILE.exists():
        try:
            return json.loads(STATE_FILE.read_text())
        except Exception:  # noqa: BLE001
            return {}
    return {}


def save_state(state: dict) -> None:
    CAMPAIGN_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state))


async def kill(client, ledger, clog, pod, why: str) -> None:
    emit(f"KILL {pod.id} ({pod.raw.get('name')}) — {why}")
    try:
        await client.terminate_pod(pod.id)
    except Exception as exc:  # noqa: BLE001
        clog.flag("terminate", pod.id, reason=f"watchdog terminate raised: {exc}")
        emit(f"  !! terminate raised: {exc} — reap by hand")
        return
    receipt = await confirm_pod_terminated(client, pod.id)
    clog.record(receipt)
    ledger.close_pod(pod.id)
    if receipt.verified:
        emit(f"  confirmed dead [{receipt.code}]")
    else:
        emit(f"  !! NOT confirmed dead — review queue flagged")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--budget", type=float, default=5.0)
    ap.add_argument("--max-pod-min", type=float, default=25.0)
    ap.add_argument("--poll-sec", type=float, default=90.0)
    ap.add_argument("--heartbeat-min", type=float, default=8.0)
    args = ap.parse_args()

    key = os.environ.get("RUNPOD_API_KEY") or (Path.home() / ".runpod_key").read_text().strip()
    client = RunpodClient(key)
    ledger = SpendLedger(CAMPAIGN_DIR / "spend.json")
    clog = ConfirmationLog(CAMPAIGN_DIR)
    state = load_state()
    first_seen = state.get("first_seen", {})

    emit(f"WATCHDOG up — budget ${args.budget:.2f}, max pod {args.max_pod_min:.0f} min, "
         f"poll {args.poll_sec:.0f}s. Guards campaign pods {CAMPAIGN_PREFIXES}.")
    last_beat = 0.0
    last_sig = None
    warned_unknown: set[str] = set()
    try:
        while True:
            now = time.time()
            try:
                pods = [p for p in await client.list_pods() if not p.is_destroyed]
            except Exception as exc:  # noqa: BLE001
                emit(f"WARN poll failed (transient): {exc}")
                await asyncio.sleep(args.poll_sec)
                continue

            camp = [p for p in pods if is_campaign(p)]
            unknown = [p for p in pods if not is_campaign(p)]
            spent = ledger.spent()

            # track first-seen ages
            for p in camp:
                first_seen.setdefault(p.id, now)
            for pid in list(first_seen):
                if pid not in {p.id for p in camp}:
                    first_seen.pop(pid, None)
            state["first_seen"] = first_seen
            save_state(state)

            # 1. BUDGET — destroy the whole campaign
            if spent >= args.budget and camp:
                emit(f"BUDGET HIT ${spent:.2f} >= ${args.budget:.2f} — destroying "
                     f"{len(camp)} campaign pod(s)")
                for p in camp:
                    await kill(client, ledger, clog, p, f"budget ${spent:.2f}")
                continue

            # 2. AGE — destroy stale campaign pods (stuck driver / hung fetch)
            for p in camp:
                age_min = (now - first_seen.get(p.id, now)) / 60
                if age_min > args.max_pod_min:
                    await kill(client, ledger, clog, p,
                               f"age {age_min:.0f} min > {args.max_pod_min:.0f} (stuck?)")

            # 3. ORPHAN warn (never auto-kill unknowns) — warn ONCE per pod id, not every poll,
            #    so a concurrent production run (e.g. nadoc-24hb_*) doesn't spam the stream.
            for p in unknown:
                if p.id not in warned_unknown:
                    warned_unknown.add(p.id)
                    emit(f"WARN unknown pod {p.id} ({p.raw.get('name')}) ${p.cost_per_hr}/hr — "
                         f"NOT a campaign pod; LEFT ALONE (likely a concurrent production run)")

            sig = (len(camp), round(spent, 2))
            beat_due = (now - last_beat) / 60 >= args.heartbeat_min
            if sig != last_sig or beat_due:
                ages = ",".join(f"{(now-first_seen.get(p.id,now))/60:.0f}m" for p in camp)
                emit(f"ok — {len(camp)} campaign pod(s) [{ages}]  spent ${spent:.2f}/"
                     f"${args.budget:.2f}")
                last_sig, last_beat = sig, now

            await asyncio.sleep(args.poll_sec)
    finally:
        await client.aclose()


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
