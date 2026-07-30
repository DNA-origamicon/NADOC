#!/usr/bin/env python3
"""Per-arm outcome: did it survive 2 ns, where did it die, and what did the cell do."""
from __future__ import annotations

import json
import re
from pathlib import Path

import numpy as np

WORK = Path("/media/jojo/Archive/exp47_protocol_delta")
PKG = WORK / "pkg"
STEM = "2hb_1xT"
TARGET = 500_000
V0 = 44.147 * 66.635 * 113.568


def box_trace(arm: str):
    f = PKG / "out" / arm / f"{STEM}.xst"
    if not f.exists():
        return None
    rows = []
    for line in f.read_text().splitlines():
        if line.startswith("#"):
            continue
        t = line.split()
        if len(t) >= 10:
            rows.append((int(float(t[0])), float(t[1]), float(t[5]), float(t[9])))
    return np.array(rows, dtype=float) if rows else None


def main():
    man = json.loads((WORK / "arms.json").read_text())
    print(f"{'arm':<15s} {'status':<7s} {'last step':>10s} {'ns':>6s} "
          f"{'a (A)':>8s} {'vol %':>7s} {'ns/day':>8s}  failure")
    print("-" * 104)
    for arm, rec in man.items():
        log = (PKG / f"{arm}.log").read_text(errors="replace") if (PKG / f"{arm}.log").exists() else ""
        steps = [int(m) for m in re.findall(r"^ENERGY:\s+(\d+)", log, re.M)]
        last = max(steps) if steps else 0
        tr = box_trace(arm)
        a = tr[-1][1] if tr is not None and len(tr) else float("nan")
        vol = (tr[-1][1] * tr[-1][2] * tr[-1][3] / V0 * 100
               if tr is not None and len(tr) else float("nan"))
        fatal = ""
        if "Periodic cell has become too small" in log:
            fatal = "PATCH GRID: periodic cell too small"
        elif "Constraint failure in RATTLE" in log:
            fatal = "RATTLE constraint failure"
        elif "FATAL ERROR" in log:
            fatal = re.search(r"FATAL ERROR:?\s*(.+)", log).group(1)[:44]
        elif rec["status"] == "ok":
            fatal = "-- completed --"
        print(f"{arm:<15s} {rec['status']:<7s} {last:>10d} {last*4e-6:>6.2f} "
              f"{a:>8.2f} {vol:>6.1f}% {str(rec['ns_per_day']):>8s}  {fatal}")
    print(f"\nstart cell 44.147 x 66.635 x 113.568 A = {V0/1000:.1f} nm^3 (carved shell, "
          f"6093 waters -> ~211 nm^3 of content, i.e. 37% vacuum)")
    print("target = 500,000 steps = 2.0 ns at 4 fs")


if __name__ == "__main__":
    main()
