#!/usr/bin/env python3
"""Tail the NAMD log and print energy/step summary."""
import sys, re, time
log = sys.argv[1] if len(sys.argv) > 1 else "output/namd.log"
pat = re.compile(r"^ENERGY:\s+(\d+)\s+[\d.+-]+\s+[\d.+-]+\s+[\d.+-]+\s+[\d.+-]+\s+([\d.+-]+)")
seen = 0
while True:
    try:
        with open(log) as f:
            lines = f.readlines()[seen:]
        for ln in lines:
            m = pat.match(ln)
            if m:
                print(f"step {m.group(1):>10s}  Etotal = {float(m.group(2)):12.1f} kcal/mol")
            seen += 1 if ln.strip() else 0
    except FileNotFoundError:
        pass
    time.sleep(2)
