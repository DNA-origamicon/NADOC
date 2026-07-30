#!/usr/bin/env python3
"""Turn the measured ensemble into the numbers NADOC should build with.

Everything is reported in the HOP-REFERENCED frame:

    u        unit(C5'(dst) - C3'(src))                   the chord, 3' exit -> 5' entry
    bow      unit(cross(unit(src->dst), avg_helix_axis))  perpendicular to u
    ax       cross(u, bow)

The builder currently builds ``bow`` from the Crossover record's ``half_a -> half_b``
order instead of the chemical hop, so its sign is arbitrary per crossover.  In the
hop-referenced frame the two crossovers of a reciprocal pair become directly comparable
(the hop runs opposite ways on them by definition), which is what makes a single set of
constants possible.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

ATOMS = ["c1", "C3'", "C5'", "P", "base"]


def mean_rotation(mats):
    M = np.mean(np.asarray(mats), axis=0)
    U, _S, Vt = np.linalg.svd(M)
    d = np.sign(np.linalg.det(U @ Vt))
    return U @ np.diag([1.0, 1.0, d]) @ Vt


def rot_angle(A, B):
    c = (np.trace(np.asarray(A).T @ np.asarray(B)) - 1.0) / 2.0
    return float(np.degrees(np.arccos(np.clip(c, -1.0, 1.0))))


def hop_signs(job: Path):
    """crossover_id -> +1 if the builder's bow already points the hop way, else -1."""
    import sys
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from xb_map import load_design
    design = load_design(job / "design.json")
    ends = set()
    for s in design.strands:
        for d in s.domains:
            ends.add((d.helix_id, d.end_bp, d.direction.value))
    out = {}
    for xo in design.crossovers:
        ka = (xo.half_a.helix_id, xo.half_a.index, xo.half_a.strand.value)
        src_helix = xo.half_a.helix_id if ka in ends else xo.half_b.helix_id
        out[xo.id] = 1 if src_helix == xo.half_a.helix_id else -1
    for fl in design.forced_ligations:
        out[fl.id] = 1 if fl.three_prime_helix_id == fl.three_prime_helix_id else 1
    return out


def col(samples, key):
    return np.array([s[key] for s in samples], dtype=float)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("dump", type=Path)
    ap.add_argument("--burn-ns", type=float, default=20.0)
    ap.add_argument("--dt-ns", type=float, default=0.01)
    ap.add_argument("--json", type=Path, default=None)
    args = ap.parse_args(argv)

    d = json.loads(args.dump.read_text())
    dt = args.dt_ns * d["stride"]
    nb = int(round(args.burn_ns / dt))
    signs = hop_signs(Path(d["job"]))

    print(f"{d['stem']}   {len(d['inserts'])} insert(s)   "
          f"{(len(d['inserts'][0]['samples']) - nb) * dt:.0f} ns after {args.burn_ns} ns "
          f"burn-in   ({dt*1000:.0f} ps sampling)\n")
    print("HOP-REFERENCED frame: t along C3'(src)->C5'(dst), bow = cross(hop, axis), "
          "ax = cross(u, bow); lengths in units of the chord L\n")

    res = {"stem": d["stem"], "job": d["job"], "inserts": [], }
    pool = {a: [] for a in ATOMS}
    Mbars = []

    for ins in d["inserts"]:
        s = ins["samples"][nb:]
        sg = signs.get(ins["crossover_id"], 1)
        L = col(s, "L")
        print(f"── crossover {ins['crossover_id'][:8]} {ins['base']}   "
              f"src={tuple(ins['src'])} -> dst={tuple(ins['dst'])}   "
              f"(builder bow sign vs hop: {sg:+d})")
        print(f"   chord L = {L.mean():.2f} +/- {L.std():.2f} A      "
              f"interhelix = {col(s,'interhelix').mean():.1f} +/- "
              f"{col(s,'interhelix').std():.1f} A      "
              f"axis angle = {col(s,'axis_angle_deg').mean():.0f} deg")
        print(f"   {'atom':<6s} {'t':>16s} {'bow':>16s} {'ax':>16s}      "
              f"{'(bow in A)':>10s}")
        entry = {"crossover_id": ins["crossover_id"], "base": ins["base"],
                 "src": ins["src"], "dst": ins["dst"], "hop_sign": sg,
                 "L": [float(L.mean()), float(L.std())], "atoms": {}}
        for a in ATOMS:
            kt, kb, ka = (f"t_{a}", f"bow_{a}", f"ax_{a}")
            if kt not in s[0]:
                continue
            t = col(s, kt)
            bow = sg * col(s, kb)
            ax = sg * col(s, ka)
            print(f"   {a:<6s} {t.mean():+8.3f}+/-{t.std():.3f} "
                  f"{bow.mean():+8.3f}+/-{bow.std():.3f} "
                  f"{ax.mean():+8.3f}+/-{ax.std():.3f}      "
                  f"{bow.mean()*L.mean():+8.2f}")
            entry["atoms"][a] = {"t": [float(t.mean()), float(t.std())],
                                 "bow": [float(bow.mean()), float(bow.std())],
                                 "ax": [float(ax.mean()), float(ax.std())]}
            pool[a].append(np.column_stack([t, bow, ax]))
        b = sg * col(s, "bow_c1")
        print(f"   C1' bow sign: negative in {100*np.mean(b<0):.1f}% of frames;  "
              f"8 blocks: " + " ".join(f"{v:+.2f}" for v in
                                       (np.mean(x) for x in np.array_split(b, 8))))
        # rigid pose + orientation
        Ms = np.array([q["pose_M"] for q in s]).reshape(-1, 3, 3)
        # flip the bow/ax basis rows to the hop frame
        S = np.diag([1.0, float(sg), float(sg)])
        Ms = np.einsum("ij,njk->nik", S, Ms)
        Mbar = mean_rotation(Ms)
        Mbars.append(Mbar)
        spread = np.array([rot_angle(Mbar, M) for M in Ms])
        print(f"   nucleotide orientation: spread {spread.mean():.0f} deg "
              f"(p90 {np.percentile(spread,90):.0f} deg), "
              f"template-fit rmsd {col(s,'pose_rmsd').mean():.2f} A")
        entry["M_hop"] = Mbar.tolist()
        entry["orientation_spread_deg"] = float(spread.mean())

        for tag in ("arc", "built", "seed"):
            m = d["static"].get(tag, {}).get(ins["crossover_id"])
            if m:
                print(f"   {tag:<6s} C1'  t={m['t_c1']:+.3f} "
                      f"bow={sg*m['bow_c1']:+.3f} ax={sg*m['ax_c1']:+.3f}"
                      + (f"   dR={rot_angle(Mbar, S @ np.array(m['pose_M']).reshape(3,3)):.0f} deg"
                         if "pose_M" in m else ""))
                entry.setdefault("static", {})[tag] = {
                    "t": m["t_c1"], "bow": sg * m["bow_c1"], "ax": sg * m["ax_c1"]}
        print()
        res["inserts"].append(entry)

    print("── POOLED over both inserts (hop-referenced)")
    res["pooled"] = {}
    for a in ATOMS:
        if not pool[a]:
            continue
        P = np.vstack(pool[a])
        print(f"   {a:<6s} t={P[:,0].mean():+.3f}+/-{P[:,0].std():.3f}  "
              f"bow={P[:,1].mean():+.3f}+/-{P[:,1].std():.3f}  "
              f"ax={P[:,2].mean():+.3f}+/-{P[:,2].std():.3f}")
        res["pooled"][a] = {"t": [float(P[:, 0].mean()), float(P[:, 0].std())],
                            "bow": [float(P[:, 1].mean()), float(P[:, 1].std())],
                            "ax": [float(P[:, 2].mean()), float(P[:, 2].std())]}
    if len(Mbars) == 2:
        print(f"   orientation difference between the two inserts: "
              f"{rot_angle(Mbars[0], Mbars[1]):.0f} deg  "
              f"(-> base orientation is NOT a single transferable constant)")
        res["orientation_difference_deg"] = rot_angle(Mbars[0], Mbars[1])

    if args.json:
        args.json.write_text(json.dumps(res, indent=1))
        print("wrote", args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
