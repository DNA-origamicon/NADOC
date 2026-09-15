"""Analyze completed physical-time windows while a retained screening campaign runs."""

import argparse
import json
import time
from pathlib import Path
from experiments.electrode_relax.debye_analysis import analyze


def update(campaign):
    rows = json.loads((campaign / "jobs.json").read_text())
    for series in ("replica_a", "replica_b", "control_2fs"):
        selected = [
            r
            for r in rows
            if r.get("status") in ("completed", "failed")
            and r.get("health", {}).get("confined")
            and (
                r["series"] == series
                or (series == "replica_a" and r["series"] == "pilot")
            )
        ]
        if not selected or (len(selected) == 1 and selected[0]["series"] == "pilot"):
            continue
        out = (
            campaign
            / series
            / f"through_{selected[-1]['start_time_ns'] + selected[-1]['duration_ns']:.2f}ns"
        )
        if (out / "debye_analysis.json").exists():
            continue
        out.mkdir(parents=True, exist_ok=True)
        (out / "jobs.json").write_text(json.dumps(selected, indent=2) + "\n")
        result = analyze(out, out, 0.24)
        print(
            series,
            result.get("end_ns"),
            result.get("center_ionic_strength_mM"),
            result.get("ratio_fits"),
            flush=True,
        )
    return rows


def main():
    p = argparse.ArgumentParser()
    p.add_argument("campaign", type=Path)
    p.add_argument("--watch", action="store_true")
    a = p.parse_args()
    deadline = time.monotonic() + 7200
    while True:
        try:
            rows = update(a.campaign)
        except json.JSONDecodeError:
            time.sleep(1)
            continue
        if (
            not a.watch
            or (len(rows) == 10 and rows[-1].get("status"))
            or time.monotonic() > deadline
        ):
            return
        time.sleep(20)


if __name__ == "__main__":
    main()
