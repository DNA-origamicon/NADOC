#!/usr/bin/env python3
"""exp36 cutoff replay (v2): offline test of relaxation-stage cutoffs against a
reference bank. Compares two causal stopping rules:

  ENERGY-ONLY : stop when pot(+volume) plateau over a trailing window.
  MULTI       : stop only when pot(+volume) AND WC base-pairing both plateau.

Also reports a within-stage WC GUARD (robust drift, restart-frame-immune) that
flags a stage where structure is still moving after energy flattens -- the
case where ENERGY-ONLY is unsafe. Pure replay; never changes the physics.

Usage:  cutoff_replay.py --bank <bank_dir>
"""
from __future__ import annotations
import argparse, csv, re, statistics as st
from pathlib import Path

# rule params
W = 10            # trailing window (frames), ~9600 steps/frame -> ~96k steps
P = 3             # patience: consecutive passing windows
EPS_POT = 1e-3    # rel drift/fluct threshold for energy (0.1%)
EPS_VOL = 2e-3    # rel threshold for volume (0.2%)
EPS_WC = 0.02     # abs drift/fluct threshold for WC fraction (2 pts)
GUARD_WC = 0.10   # within-stage WC drift above this = structure still relaxing


def load(bank: Path):
    rows = []
    with (bank / "frames.tsv").open() as f:
        for r in csv.DictReader(f, delimiter="\t"):
            for c in ("k", "step_global", "pot_per_atom", "POTENTIAL",
                      "VOLUME", "wc_ref_relative"):
                r[c] = float(r[c]) if r[c] not in ("", None) else None
            rows.append(r)
    return rows


def stages(rows):
    """Group by stage identity = segment name minus the _pNN chunk suffix, so a
    stage's p10/p50/p100 chunks join. Robust across protocols (ENM ladder,
    NVT-heating ramp, production). Ordered by first step."""
    out = {}
    for r in rows:
        base = re.sub(r"_p\d+$", "", r["segment"])
        out.setdefault(base, []).append(r)
    for base in out:
        out[base].sort(key=lambda r: r["step_global"])
    return sorted(out.items(), key=lambda kv: kv[1][0]["step_global"])


def is_production(base):
    return bool(re.search(r"production|qualification", base, re.I))


def rel(a, b):
    m = (abs(a) + abs(b)) / 2 or 1.0
    return abs(a - b) / m


def online_cut(pot, vol, wc, use_wc):
    """causal trailing-window trigger; returns frame index or None."""
    hits = 0
    for i in range(2 * W, len(pot)):
        wp = pot[i - W:i]
        ok = (rel(st.mean(pot[i - W:i - W // 2]), st.mean(pot[i - W // 2:i])) < EPS_POT
              and st.pstdev(wp) / (abs(st.mean(wp)) or 1) < EPS_POT)
        if vol[0] is not None:
            ok = ok and rel(st.mean(vol[i - W:i - W // 2]), st.mean(vol[i - W // 2:i])) < EPS_VOL
        if use_wc and any(w is not None for w in wc):
            ww = [w for w in wc[i - W:i] if w is not None]
            if len(ww) >= 4:
                drift = abs(st.mean(ww[:len(ww) // 2]) - st.mean(ww[len(ww) // 2:]))
                ok = ok and drift < EPS_WC and st.pstdev(ww) < EPS_WC
            else:
                ok = False
        hits = hits + 1 if ok else 0
        if hits >= P:
            return i
    return None


def wc_stage_drift(wc):
    """robust within-stage WC drift: |median(last 20%) - median(first 20%)|.
    Ignores the restart reference frame (=1.0) that spikes early WC."""
    ww = [w for w in wc if w is not None]
    if len(ww) < 5:
        return 0.0
    n = max(1, len(ww) // 5)
    return abs(st.median(ww[-n:]) - st.median(ww[:n]))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--bank", required=True, type=Path)
    a = ap.parse_args()
    rows = load(a.bank)
    design = rows[0]["design"]
    print(f"\n=== {design}  ({a.bank.name}) ===")
    hdr = (f"{'stage':<28} {'k':>5} {'T':>4} {'fr':>4} {'stepsK':>7} "
           f"{'E%':>5} {'M%':>5} {'WCdr':>6} {'guard':>5} {'M-saved':>9}")
    print(hdr)
    tot = e_aggr = e_cons = m_safe = 0
    for base, seg in stages(rows):
        prod = is_production(base)
        k = seg[0]["k"]
        temp = seg[0].get("temp_target_k") or ""
        pot = [(r["pot_per_atom"] if r["pot_per_atom"] is not None else r["POTENTIAL"]) for r in seg]
        vol = [r["VOLUME"] for r in seg]
        wc = [r["wc_ref_relative"] for r in seg]
        steps = [r["step_global"] for r in seg]
        stage_len = steps[-1] - seg[0]["step_global"]
        short = len(seg) < 2 * W + P
        e_i = None if short else online_cut(pot, vol, wc, use_wc=False)
        m_i = None if short else online_cut(pot, vol, wc, use_wc=True)
        e_i = e_i if e_i is not None else len(seg) - 1
        m_i = m_i if m_i is not None else len(seg) - 1
        e_saved = steps[-1] - steps[e_i]
        m_saved = steps[-1] - steps[m_i]
        drift = wc_stage_drift(wc)
        guard = "-" if all(w is None for w in wc) else ("OK" if drift <= GUARD_WC else "WARN")
        tag = "  [PROD/excl]" if prod else ""
        name = re.sub(r"^[^_]+_\d+_", "", base)[:27]
        print(f"{name:<28} {k:>5} {str(temp):>4} {len(seg):>4} {int(stage_len/1000):>7} "
              f"{100*e_i/len(seg):>4.0f}% {100*m_i/len(seg):>4.0f}% "
              f"{drift:>6.3f} {guard:>5} {int(m_saved):>9}{tag}")
        if prod:                         # production is not a relaxation stage
            continue
        tot += stage_len
        e_aggr += e_saved
        if k and k > 0:
            e_cons += e_saved
        m_safe += m_saved
    def line(name, saved):
        pct = 100 * saved / tot
        spd = tot / (tot - saved) if saved < tot else float("inf")
        print(f"  {name:<34} saved {int(saved):>9,} = {pct:4.1f}%  ->  {spd:.2f}x")
    print("-" * 74)
    print(f"  total dynamics steps: {int(tot):,}")
    line("ENERGY-ONLY aggressive (all)", e_aggr)
    line("ENERGY-ONLY conservative (hold k=0)", e_cons)
    line("MULTI-CRITERIA (energy+WC, self-holds)", m_safe)


if __name__ == "__main__":
    main()
