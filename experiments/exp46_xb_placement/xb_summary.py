#!/usr/bin/env python3
"""Summarise an xb_observables trajectory dump: equilibrium (t, bow, axial) per insert,
block-averaged so the drift/convergence is visible, plus the seed/arc offsets."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

KEYS = ["t_c1", "bow_c1", "ax_c1", "t_base", "bow_base", "ax_base", "L",
        "interhelix", "axis_angle_deg", "chord_dot_axis",
        "gly_dot_axis", "gly_dot_bow", "gly_dot_chord",
        "norm_dot_chord", "norm_dot_axis", "norm_dot_bow",
        "stack_d", "stack_ang"]


def arr(samples, key):
    return np.array([s[key] for s in samples], dtype=float)


def block_stats(x, n_blocks=8):
    b = np.array_split(x, n_blocks)
    return np.array([bb.mean() for bb in b])


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=Path)
    ap.add_argument("--burn-ns", type=float, default=20.0,
                   help="discard this much of the head as equilibration")
    ap.add_argument("--dt-ns", type=float, default=0.01, help="ns per DCD frame")
    args = ap.parse_args(argv)

    d = json.loads(args.dump.read_text())
    dt = args.dt_ns * d["stride"]
    print(f"{d['stem']}  {len(d['inserts'])} insert(s)  "
          f"{len(d['inserts'][0]['samples'])} samples x {dt*1000:.0f} ps "
          f"= {len(d['inserts'][0]['samples'])*dt:.0f} ns")
    n_burn = int(round(args.burn_ns / dt))
    print(f"burn-in: first {n_burn} samples ({args.burn_ns} ns) discarded\n")

    for ins in d["inserts"]:
        xid = ins["crossover_id"][:8]
        s = ins["samples"]
        print(f"── crossover {xid}  {ins['base']}  src={tuple(ins['src'])} "
              f"dst={tuple(ins['dst'])}")
        stat = d["static"]
        for tag in ("arc", "built", "seed", "reseed"):
            m = stat.get(tag, {}).get(ins["crossover_id"])
            if m:
                print(f"   {tag:<7s} t={m['t_c1']:+.3f} bow={m['bow_c1']:+.3f} "
                      f"ax={m['ax_c1']:+.3f}  L={m['L']:.2f}  "
                      f"base=({m['t_base']:+.2f},{m['bow_base']:+.2f},{m['ax_base']:+.2f})")
        print(f"   {'MD':<7s} {'mean':>8s} {'sd':>7s} {'p5':>7s} {'p50':>7s} {'p95':>7s} "
              f"{'blocks (8 x 22.5 ns)':>20s}")
        for k in KEYS:
            x = arr(s, k)[n_burn:]
            blk = block_stats(x)
            bs = " ".join(f"{v:+.2f}" for v in blk)
            print(f"   {k:<16s} {x.mean():+8.3f} {x.std():7.3f} "
                  f"{np.percentile(x,5):+7.3f} {np.percentile(x,50):+7.3f} "
                  f"{np.percentile(x,95):+7.3f}   {bs}")
        # sign persistence of the bow coordinate
        bow = arr(s, "bow_c1")[n_burn:]
        print(f"   bow_c1 > 0 in {100*np.mean(bow>0):.1f}% of frames; "
              f"stack_d < 4.5 A in {100*np.mean(arr(s,'stack_d')[n_burn:]<4.5):.1f}%")
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
