#!/usr/bin/env python3
"""Final numbers: the MD equilibrium insert pose vs every stage of the NADOC build,
in the hop-referenced chord frame, in both L-units and Angstrom.

Window: 20-180 ns.  The head is equilibration; the last 20 ns is dropped because the
designed base-pair fraction falls from 0.96 to 0.905 there (the 7 bp staple arms of this
minimal 2hb construct start to fray), so it is no longer a clean junction ensemble.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from compare_builds_to_md import hop_sign_map  # noqa: E402
from xb_map import load_design  # noqa: E402

DUMP = Path(sys.argv[1]) if len(sys.argv) > 1 else (
    Path(__file__).parent / "2hb_1xT_xb_traj.json")
d = json.loads(DUMP.read_text())
design = load_design(Path(d["job"]) / "design.json")
sg = hop_sign_map(design)
dt = 0.01 * d["stride"]
lo, hi = int(20.0 / dt), int(180.0 / dt)
print(__doc__)
print(f"window {lo*dt:.0f}-{hi*dt:.0f} ns, {hi-lo} samples at {dt*1000:.0f} ps\n")

hdr = f"{'':<10s}{'t':>18s}{'bow':>18s}{'ax':>18s}{'L (A)':>9s}"
for ins in d["inserts"]:
    s = ins["samples"][lo:hi]
    k = sg[ins["crossover_id"]]
    L = np.array([q["L"] for q in s])
    print(f"── {ins['base']} insert on the crossover {tuple(ins['src'])} -> "
          f"{tuple(ins['dst'])}")
    print(hdr)
    for tag in ("arc", "built", "seed", "reseed"):
        m = d["static"].get(tag, {}).get(ins["crossover_id"])
        if not m:
            continue
        t, b, a = m["t_c1"], k * m["bow_c1"], k * m["ax_c1"]
        print(f"  {tag:<8s}{t:>+10.3f}{'':8s}{b:>+10.3f}{'':8s}{a:>+10.3f}{'':8s}"
              f"{m['L']:>7.2f}")
    for nm, key in (("MD C1'", "c1"), ("MD P", "P"), ("MD base", "base")):
        if f"t_{key}" not in s[0]:
            continue
        t = np.array([q[f"t_{key}"] for q in s])
        b = k * np.array([q[f"bow_{key}"] for q in s])
        a = k * np.array([q[f"ax_{key}"] for q in s])
        print(f"  {nm:<8s}{t.mean():>+7.3f}+/-{t.std():.3f}"
              f"{b.mean():>+11.3f}+/-{b.std():.3f}"
              f"{a.mean():>+11.3f}+/-{a.std():.3f}{L.mean():>9.2f}")
    b = k * np.array([q["bow_c1"] for q in s])
    t = np.array([q["t_c1"] for q in s])
    bl = d["static"]["built"][ins["crossover_id"]]
    print(f"  built -> MD shift:  dt {t.mean()-bl['t_c1']:+.3f} L "
          f"({(t.mean()-bl['t_c1'])*L.mean():+.2f} A)   "
          f"dbow {b.mean()-k*bl['bow_c1']:+.3f} L "
          f"({(b.mean()-k*bl['bow_c1'])*L.mean():+.2f} A)")
    print(f"  bow sign stable: {100*np.mean(b<0):.1f}% of frames negative\n")

print("── pooled over the two inserts (C1')")
T, B, A = [], [], []
for ins in d["inserts"]:
    s = ins["samples"][lo:hi]
    k = sg[ins["crossover_id"]]
    T += [q["t_c1"] for q in s]
    B += [k * q["bow_c1"] for q in s]
    A += [k * q["ax_c1"] for q in s]
T, B, A = np.array(T), np.array(B), np.array(A)
print(f"  t   {T.mean():+.3f} +/- {T.std():.3f}")
print(f"  bow {B.mean():+.3f} +/- {B.std():.3f}")
print(f"  |ax| {np.abs(A).mean():.3f} +/- {np.abs(A).std():.3f}  "
      f"(signed mean {A.mean():+.3f} — the SIGN does not transfer between the two)")
pf = np.array(d["paired_fraction"])
print(f"\n  designed base pairs intact: {pf[lo:hi].mean():.3f} in-window, "
      f"{pf[hi:].mean():.3f} in the discarded tail")
