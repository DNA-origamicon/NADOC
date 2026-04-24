#!/usr/bin/env python3
"""
Generate a minimal 2hb smoke-test design (15 bp arms) by scaling down
the production 2hb_xover_val design.  Output: smoke_design.nadoc.

Production layout (bp_start=7, length=35, bp range 7-41):
  outer_stub_L (7 bp)  | junction_A (bp 13-14) | measurement (20 bp)
  | junction_B (bp 34-35) | outer_stub_R (7 bp)

Smoke layout (bp_start=0, length=15, bp range 0-14):
  stub_L (2 bp) | junction_A (bp 2-3) | measurement (8 bp)
  | junction_B (bp 11-12) | stub_R (3 bp)

Scale function: smoke_bp = round((prod_bp - 7) * 15 / 35)
  7  → 0,  13 → 3,  14 → 3,  27 → 9,  28 → 9,  34 → 11,  35 → 12,  41 → 15→14
"""
from __future__ import annotations
import copy, json, math, pathlib

_PROD = pathlib.Path(__file__).parent.parent.parent / "Examples" / "2hb_xover_val.nadoc"
_OUT  = pathlib.Path(__file__).parent / "smoke_design.nadoc"

_OLD_START = 7
_OLD_LEN   = 35
_NEW_LEN   = 15
_NM_PER_BP = 0.334


def _scale(bp: int) -> int:
    raw = (bp - _OLD_START) * _NEW_LEN / _OLD_LEN
    return max(0, min(_NEW_LEN - 1, round(raw)))


def main() -> None:
    data = json.loads(_PROD.read_text())
    d = copy.deepcopy(data)

    # ── helices ──────────────────────────────────────────────────────────────
    for h in d["helices"]:
        # phase_offset is calibrated for old bp_start.  Roll it back to bp 0
        # so the rotational position of each nucleotide is consistent with
        # the new bp_start=0.  Without this, atoms end up at wrong angles
        # causing overlaps and Fmax=inf in GROMACS EM.
        h["phase_offset"] = h["phase_offset"] - _OLD_START * h["twist_per_bp_rad"]
        h["bp_start"] = 0
        h["length_bp"] = _NEW_LEN
        z0 = h["axis_start"]["z"]
        h["axis_end"]["z"] = z0 + _NEW_LEN * _NM_PER_BP

    # ── strands: rescale all domain start_bp / end_bp ────────────────────────
    for s in d["strands"]:
        for dom in s["domains"]:
            dom["start_bp"] = _scale(dom["start_bp"])
            dom["end_bp"]   = _scale(dom["end_bp"])

    # ── crossovers: rescale index ─────────────────────────────────────────────
    for c in d["crossovers"]:
        c["half_a"]["index"] = _scale(c["half_a"]["index"])
        c["half_b"]["index"] = _scale(c["half_b"]["index"])

    # ── drop overhangs / extensions (not needed for smoke) ───────────────────
    d["overhangs"]   = []
    d["extensions"]  = []

    _OUT.write_text(json.dumps(d, indent=2))
    print(f"Wrote {_OUT}")

    # Sanity print
    for s in d["strands"]:
        print(f"  {s['id']}: " +
              " | ".join(f"{dom['helix_id']} {dom['start_bp']}→{dom['end_bp']} {dom['direction']}"
                         for dom in s["domains"]))
    print("crossovers:")
    for c in d["crossovers"]:
        print(f"  {c['half_a']['helix_id']}[{c['half_a']['index']}] ↔ "
              f"{c['half_b']['helix_id']}[{c['half_b']['index']}]")


if __name__ == "__main__":
    main()
