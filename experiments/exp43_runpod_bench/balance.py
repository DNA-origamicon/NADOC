#!/usr/bin/env python3
"""The account balance — the ONE number that can kill a run, and the one nothing could see.

RunPod terminates every pod the instant the balance hits zero. A multi-day run that dies at
80% for want of credit wastes everything spent to that point. Yet the whole exp43 toolchain
could not read the balance: `watch.py` reports cost-so-far, `spend_ledger.py` reports
cumulative spend, and neither knows how much money is actually LEFT.

This is the L5 pattern one level up. L5 was "a ledger that under-reports is worse than no
ledger, because it is trusted"; here the safety net did not under-report — it did not exist,
while the runbook implied it did.

    python experiments/exp43_runpod_bench/balance.py
    python experiments/exp43_runpod_bench/balance.py --require 300

WHERE THE BALANCE LIVES. Only on the legacy GraphQL API (`myself { clientBalance }`). The
public REST API (rest.runpod.io/v1 — what the rest of the toolchain uses) exposes no billing
endpoint at all: /billing, /account, /me all 400 as "not in the spec".

⚠️ USE httpx, NEVER urllib. api.runpod.io sits behind Cloudflare, which blocks
`Python-urllib`'s client fingerprint with **HTTP 403, body "error code: 1010"**. That is a
Cloudflare bot-block, NOT an auth failure — but it is indistinguishable from a rejected key
if you look only at the status code. It cost this session an hour chasing a "scoped-key
permissions problem" that never existed; the key was fine all along, and the real balance
($207) was 26x the one we had been told to trust ($7.96). **Read the BODY of a 403 before
believing it.**

FAILS LOUD, NOT SAFE. If the balance cannot be read, `--require` EXITS NON-ZERO. It does not
warn and continue. On a rented GPU "fail-safe" means "fail-expensive" (LESSONS L1): a gate
that shrugs and proceeds when it cannot see the money is not a gate. To launch blind you
must say so out loud, with --allow-unknown.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import httpx

GRAPHQL_URL = "https://api.runpod.io/graphql"
KEY_FILE = Path.home() / ".runpod_key"


class BalanceUnavailable(RuntimeError):
    """The balance could not be read. NEVER swallow this into a 'probably fine'."""


def _read_key() -> str:
    if not KEY_FILE.exists():
        raise BalanceUnavailable(f"no API key at {KEY_FILE}")
    key = KEY_FILE.read_text().strip()
    if not key:
        raise BalanceUnavailable(f"{KEY_FILE} is empty")
    return key


def fetch_balance() -> tuple[float, float]:
    """(balance_usd, current_spend_per_hr). Raises BalanceUnavailable — never guesses."""
    key = _read_key()
    query = "query { myself { clientBalance currentSpendPerHr } }"
    try:
        # httpx, not urllib — see the Cloudflare note in the module docstring.
        resp = httpx.post(f"{GRAPHQL_URL}?api_key={key}", json={"query": query}, timeout=30)
    except httpx.HTTPError as exc:
        raise BalanceUnavailable(f"could not reach the RunPod API: {exc}") from exc

    if resp.status_code in (401, 403):
        raise BalanceUnavailable(
            f"HTTP {resp.status_code} from GraphQL. Body: {resp.text[:120]!r}\n"
            "        If the body says 'error code: 1010' this is CLOUDFLARE blocking the\n"
            "        HTTP client, not a bad key — use httpx, never urllib/requests-raw."
        )
    if resp.status_code != 200:
        raise BalanceUnavailable(f"HTTP {resp.status_code}: {resp.text[:120]}")

    body = resp.json()
    if body.get("errors"):
        raise BalanceUnavailable(f"GraphQL error: {body['errors']}")
    try:
        me = body["data"]["myself"]
        return float(me["clientBalance"]), float(me["currentSpendPerHr"])
    except (KeyError, TypeError, ValueError) as exc:
        raise BalanceUnavailable(f"unexpected GraphQL response: {body}") from exc


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--require", type=float, metavar="USD",
                    help="exit non-zero unless the balance is at least this much")
    ap.add_argument("--allow-unknown", action="store_true",
                    help="with --require: treat an UNREADABLE balance as a pass. The "
                         "fail-expensive escape hatch — only for runs whose total cost you "
                         "are willing to lose outright.")
    args = ap.parse_args()

    try:
        bal, rate = fetch_balance()
    except BalanceUnavailable as exc:
        print(f"BALANCE: UNKNOWN — {exc}", file=sys.stderr)
        if args.require is None:
            return 1
        if args.allow_unknown:
            print("  [WARN] --allow-unknown: launching without seeing the balance.",
                  file=sys.stderr)
            return 0
        print(
            f"\n*** REFUSING: cannot confirm the balance covers ${args.require:.2f}. ***\n"
            "    RunPod kills every pod at zero balance. Launching a multi-day run without\n"
            "    being able to see the money is how you lose the whole run at 80%.",
            file=sys.stderr,
        )
        return 2

    print(f"BALANCE: ${bal:.2f}")
    print(f"  current spend rate: ${rate:.4f}/hr", end="")
    if rate > 0:
        print(f"  -> {bal / rate:.1f} h of runway at the CURRENT rate")
    else:
        print()

    if args.require is not None:
        if bal < args.require:
            print(
                f"\n*** REFUSING: balance ${bal:.2f} < required ${args.require:.2f}. ***\n"
                f"    Top up by at least ${args.require - bal:.2f} before launching.",
                file=sys.stderr,
            )
            return 2
        print(f"  [PASS] covers the required ${args.require:.2f} "
              f"(${bal - args.require:.2f} headroom)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
