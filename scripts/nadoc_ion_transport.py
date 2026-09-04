#!/usr/bin/env python3
"""Headless client for NADOC nanopore relaxation, production, and analysis."""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request


def call(base: str, method: str, path: str, payload=None):
    data = None if payload is None else json.dumps(payload).encode()
    request = urllib.request.Request(
        base.rstrip("/") + path, data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise SystemExit(exc.read().decode() or str(exc)) from exc


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://127.0.0.1:8000/api")
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("oxdna_job_id", nargs="?", help="Completed deposited oxDNA job")
    prep.add_argument("--graphene-only", action="store_true", help="Membrane/electrolyte control with no DNA")
    prep.add_argument("--reservoir-padding-nm", type=float, default=3.0)
    prep.add_argument("--pore-nm", type=float, default=2.1)
    prep.add_argument("--salt-mm", type=float, default=150)
    prep.add_argument("--mg-mm", type=float, default=0)
    prep.add_argument("--budget", type=float, default=5)
    prep.add_argument("--target", choices=("local", "runpod", "alpine"), default="runpod")
    prep.add_argument("--no-start", action="store_true")
    run = sub.add_parser("run")
    run.add_argument("parent_job_id")
    run.add_argument("--ns", type=float, default=10)
    run.add_argument("--mv", type=float, default=100)
    run.add_argument("--stride-ps", type=float, default=10)
    run.add_argument("--budget", type=float, default=5)
    run.add_argument("--target", choices=("local", "runpod", "alpine"), default="runpod")
    run.add_argument("--no-start", action="store_true")
    status = sub.add_parser("status")
    status.add_argument("job_id")
    analyze = sub.add_parser("analyze")
    analyze.add_argument("job_id")
    args = parser.parse_args()
    if args.command == "prepare":
        if not args.graphene_only and not args.oxdna_job_id:
            parser.error("prepare needs oxdna_job_id or --graphene-only")
        result = call(args.api, "POST", "/md/ion-transport/prepare", {
            "oxdna_job_id": args.oxdna_job_id, "pore_diameter_nm": args.pore_nm,
            "graphene_only": args.graphene_only,
            "reservoir_padding_nm": args.reservoir_padding_nm,
            "ion_conc_mM": args.salt_mm, "mg_conc_mM": args.mg_mm,
            "execution_target": args.target, "runpod_budget_usd": args.budget,
            "autostart": not args.no_start,
        })
    elif args.command == "run":
        result = call(args.api, "POST", f"/md/ion-transport/{args.parent_job_id}/run", {
            "length_ns": args.ns, "voltage_mV": args.mv,
            "current_stride_ps": args.stride_ps,
            "runpod_budget_usd": args.budget, "execution_target": args.target,
            "autostart": not args.no_start,
        })
    elif args.command == "status":
        result = call(args.api, "GET", f"/md/jobs/{args.job_id}")
    else:
        result = call(args.api, "GET", f"/md/ion-transport/{args.job_id}/analysis")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
