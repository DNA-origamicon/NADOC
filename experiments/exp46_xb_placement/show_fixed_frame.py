#!/usr/bin/env python3
"""Print the insert geometry in the FIXED-AXIS hop frame (no chord tangent), which is
the fair test of whether ONE set of constants describes both crossovers of a pair.

e1 = src helix -> dst helix (the chemical hop), e2 = local helix axis, e3 = e1 x e2.
Origin = C3'(src) = the builder's p0.  Lengths in units of the chord L.
"""
import json
import sys

import numpy as np

d = json.loads(open(sys.argv[1]).read())
nb = int(sys.argv[2]) if len(sys.argv) > 2 else 400
print(__doc__)
for ins in d["inserts"]:
    s = ins["samples"][nb:]
    print(f" {ins['crossover_id'][:8]}  src={tuple(ins['src'])} -> dst={tuple(ins['dst'])}")
    for tag in ("c1", "base", "P", "C3'", "C5'", "p1"):
        if f"h1_{tag}" not in s[0]:
            continue
        v = [np.array([q[f"h{i}_{tag}"] for q in s]) for i in (1, 2, 3)]
        print(f"   {tag:<5s} e1 {v[0].mean():+6.3f}+/-{v[0].std():.3f}   "
              f"e2 {v[1].mean():+6.3f}+/-{v[1].std():.3f}   "
              f"e3 {v[2].mean():+6.3f}+/-{v[2].std():.3f}")
    pm = np.array([q.get("partner_min_d", np.nan) for q in s])
    if not np.all(np.isnan(pm)):
        print(f"   partner-crossover backbone min dist: {np.nanmean(pm):.2f} "
              f"+/- {np.nanstd(pm):.2f} A   (p5 {np.nanpercentile(pm,5):.2f})")
    for tag in ("arc", "built", "seed"):
        m = d["static"].get(tag, {}).get(ins["crossover_id"])
        if m and "h1_c1" in m:
            print(f"   {tag:<6s} c1  e1 {m['h1_c1']:+6.3f} e2 {m['h2_c1']:+6.3f} "
                  f"e3 {m['h3_c1']:+6.3f}")
    print()
