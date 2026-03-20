#!/usr/bin/env python3
"""
Generate four fully-routed example .nadoc designs with scaffold length = 7249
(M13mp18).

Each design includes single-stranded scaffold loops at every helix terminus
(LOOP_SIZE=5 bp per end, 10 bp per junction) to prevent blunt-end aggregation.

Strategy to hit exactly 7249 with ss-DNA loops:
  1. Compute total_loop_nts = 2 × LOOP_SIZE × N  (near + far, all helices).
  2. Build uniform bundle at L_lo = (7249 − total_loop_nts) // N.
  3. Route scaffold (seam-line).
  4. Extrude all helices near-end by LOOP_SIZE (scaffold-only ss-DNA loops).
  5. Extrude all helices far-end by LOOP_SIZE (scaffold-only ss-DNA loops).
  6. scaffold_add_end_crossovers — ligates fragments into one continuous strand.
  7. scaffold_nick → set 5′/3′ position.
  8. remainder = 7249 − (N × L_lo + total_loop_nts)  (= 7249 mod N)
     If remainder > 0: extend path[-1] by remainder bp + push scaffold 5′.
  9. Verify scaffold total == 7249.
 10. Run auto_crossover + autostaple pipeline.

Designs (with LOOP_SIZE=5, total_loop_nts = 2×5×N):
  6HB  honeycomb — 6  helices  L_lo=1198  total_loop=60   rem=1
  18HB honeycomb — 18 helices  L_lo=392   total_loop=180  rem=13
  2×20 square    — 40 helices  L_lo=171   total_loop=400  rem=9
  3×6  square    — 18 helices  L_lo=392   total_loop=180  rem=13

Run from the repo root:
  python scripts/gen_examples.py
"""

import sys
import os
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from backend.core.constants import BDNA_RISE_PER_BP
from backend.core.lattice import (
    make_bundle_design,
    auto_scaffold,
    scaffold_extrude_near,
    scaffold_extrude_far,
    scaffold_add_end_crossovers,
    scaffold_nick,
    make_auto_crossover,
    make_nicks_for_autostaple,
    make_merge_short_staples,
    compute_scaffold_routing,
)
from backend.core.models import Design, Direction, LatticeType, Vec3

TARGET    = 7249
LOOP_SIZE = 5   # bp of ss-DNA scaffold loop at each helix terminus
OUT_DIR   = os.path.join(os.path.dirname(__file__), "..", "Examples")

CELLS_6HB = [
    [0, 0], [0, 1], [1, 0],
    [2, 1], [0, 2], [1, 2],
]

CELLS_18HB = [
    [0, 0], [0, 1], [1, 0],
    [0, 2], [1, 2], [2, 1],
    [3, 1], [3, 0], [4, 0],
    [5, 1], [4, 2], [3, 2],
    [3, 3], [3, 4], [3, 5],
    [2, 5], [1, 4], [2, 3],
]

CELLS_2x20_SQ = [[r, c] for r in range(2) for c in range(20)]
CELLS_3x6_SQ  = [[r, c] for r in range(3) for c in range(6)]


# ── Helpers ──────────────────────────────────────────────────────────────────

def scaffold_total(design: Design) -> int:
    """Sum nucleotides across ALL scaffold strands (seam-line creates multiple)."""
    return sum(
        abs(d.end_bp - d.start_bp) + 1
        for s in design.strands
        if s.strand_type == "scaffold"
        for d in s.domains
    )


def _vec3_to_np(v: Vec3) -> np.ndarray:
    return np.array([v.x, v.y, v.z], dtype=float)


def extend_helix(design: Design, helix_id: str, extra_bp: int) -> Design:
    """Extend helix `helix_id` by `extra_bp` along its current axis direction.

    Only the helix geometry is updated (length_bp + axis_end).  Strand domains
    are unchanged here; call extend_scaffold_5prime afterwards to move the
    scaffold terminus into the new region.
    """
    new_helices = []
    for h in design.helices:
        if h.id != helix_id:
            new_helices.append(h)
            continue
        start = _vec3_to_np(h.axis_start)
        end   = _vec3_to_np(h.axis_end)
        unit  = end - start
        norm  = np.linalg.norm(unit)
        if norm < 1e-12:
            new_helices.append(h)
            continue
        unit /= norm
        new_end_np = end + unit * (extra_bp * BDNA_RISE_PER_BP)
        new_h = h.model_copy(update={
            "length_bp": h.length_bp + extra_bp,
            "axis_end":  Vec3(x=float(new_end_np[0]),
                              y=float(new_end_np[1]),
                              z=float(new_end_np[2])),
        })
        new_helices.append(new_h)
    return design.model_copy(update={"helices": new_helices})


def extend_scaffold_5prime(design: Design, helix_id: str, extra_bp: int) -> Design:
    """Force-extend the scaffold 5′ terminus into the newly extruded region.

    Finds the scaffold strand whose first domain is on `helix_id` and pushes
    its start_bp `extra_bp` further into the extrusion:
      - REVERSE strand: start_bp increases (5′ moves toward higher bp).
      - FORWARD strand: start_bp decreases (5′ moves toward lower bp).

    This creates a single-stranded scaffold extension (scaffold loop) because
    no staple covers the extruded bp range.
    """
    new_strands = []
    modified = False
    for s in design.strands:
        if s.strand_type != "scaffold" or not s.domains:
            new_strands.append(s)
            continue
        first = s.domains[0]
        if first.helix_id != helix_id:
            new_strands.append(s)
            continue
        # Extend 5′ terminus into the extrusion
        if first.direction == Direction.REVERSE:
            new_start = first.start_bp + extra_bp   # REVERSE: 5′ moves to higher bp
        else:
            new_start = first.start_bp - extra_bp   # FORWARD: 5′ moves to lower bp
        new_first = first.model_copy(update={"start_bp": new_start})
        new_domains = [new_first] + list(s.domains[1:])
        new_strands.append(s.model_copy(update={"domains": new_domains}))
        modified = True
        break  # only one scaffold strand should match
    if not modified:
        raise ValueError(f"No scaffold strand with 5′ on helix {helix_id} found.")
    return design.model_copy(update={"strands": new_strands})


# ── Core builder ─────────────────────────────────────────────────────────────

def build_example(
    cells: list,
    name: str,
    plane: str = "XY",
    lattice_type: LatticeType = LatticeType.HONEYCOMB,
) -> Design:
    """Build a fully-routed example design with scaffold length exactly TARGET.

    Scaffold loops of LOOP_SIZE bp are added at every helix terminus (near and
    far) before the end-crossover ligation step.  These loops are scaffold-only
    (strand_filter="scaffold") so the loop bases are single-stranded in the
    final design, preventing blunt-end aggregation in experiments.
    """
    N = len(cells)
    total_loop_nts = 2 * LOOP_SIZE * N          # near + far, every helix
    L_lo      = (TARGET - total_loop_nts) // N  # base extrusion length
    remainder = TARGET - (N * L_lo + total_loop_nts)   # = TARGET % N

    print(f"  [{name}]  N={N}  L_lo={L_lo}  loop_nts={total_loop_nts}  remainder={remainder}")

    # ── Step 1: uniform bundle ───────────────────────────────────────────────
    design = make_bundle_design(cells, L_lo, name, plane, lattice_type=lattice_type)

    # ── Step 2: scaffold routing (seam-line) ─────────────────────────────────
    design = auto_scaffold(design, mode="seam_line")

    # ── Step 2b: scaffold end loops ──────────────────────────────────────────
    # Extend every helix by LOOP_SIZE bp at the near end and at the far end.
    # strand_filter="scaffold" means only scaffold domains are created in the
    # extension region — no staple coverage → single-stranded scaffold loops.
    # These calls must happen BEFORE scaffold_add_end_crossovers because the
    # ligation logic searches for scaffold 5′/3′ ends at bp=0 (near) and
    # bp=L−1 (far), which the loop extension domains provide.
    design = scaffold_extrude_near(design, LOOP_SIZE)
    design = scaffold_extrude_far(design, LOOP_SIZE)

    # ── Step 3: ligate fragments + set nick ─────────────────────────────────
    design = scaffold_add_end_crossovers(design)
    design = scaffold_nick(design, nick_offset=0)

    # ── Step 4: if needed, extrude one helix and extend scaffold 5′ ─────────
    if remainder > 0:
        # Find path to identify the outer-rail helix that holds the scaffold 5′ end.
        path = compute_scaffold_routing(design)
        if path is None or len(path) < 2:
            raise ValueError(f"Cannot compute scaffold path for {name}")

        # After scaffold_add_end_crossovers + scaffold_nick, the scaffold 5′ is
        # at the FAR end (bp = L-1) of path[-1].  Extend that helix.
        outer_rail_hid = path[-1]

        print(f"    Extending outer-rail helix {outer_rail_hid} by {remainder} bp")
        design = extend_helix(design, outer_rail_hid, remainder)
        design = extend_scaffold_5prime(design, outer_rail_hid, remainder)

    # ── Step 5: verify scaffold length ──────────────────────────────────────
    total = scaffold_total(design)
    if total != TARGET:
        raise RuntimeError(f"Scaffold length {total} ≠ {TARGET} for {name}!")
    print(f"    Scaffold verified: {total} nt ✓")

    # ── Step 6: DX crossovers + staple routing ───────────────────────────────
    design = make_auto_crossover(design)
    design = make_nicks_for_autostaple(design)
    design = make_merge_short_staples(design)

    # Final check
    total = scaffold_total(design)
    print(f"    Final scaffold check: {total} nt {'✓' if total == TARGET else '✗'}")
    return design


# ── Main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    os.makedirs(OUT_DIR, exist_ok=True)

    tasks = [
        ("6hb_m13.nadoc",   CELLS_6HB,     "6HB Honeycomb (M13)",   "XY", LatticeType.HONEYCOMB),
        ("18hb_m13.nadoc",  CELLS_18HB,    "18HB Honeycomb (M13)",  "XY", LatticeType.HONEYCOMB),
        ("2x20sq_m13.nadoc",CELLS_2x20_SQ, "2x20 Square (M13)",     "XY", LatticeType.SQUARE),
        ("3x6sq_m13.nadoc", CELLS_3x6_SQ,  "3x6 Square (M13)",      "XY", LatticeType.SQUARE),
    ]

    results: dict[str, int] = {}
    for fname, cells, name, plane, ltype in tasks:
        print(f"\n── {fname} ─────────────────────────────────────")
        try:
            design = build_example(cells, name, plane, ltype)
            path = os.path.join(OUT_DIR, fname)
            with open(path, "w", encoding="utf-8") as f:
                f.write(design.model_dump_json(indent=2))
            sl = scaffold_total(design)
            results[fname] = sl
            print(f"  ✓ Saved {path}  (scaffold={sl})")
        except Exception as exc:
            print(f"  ✗ FAILED: {exc}")
            results[fname] = -1

    print("\n── Summary ──────────────────────────────────────────────")
    all_ok = True
    for fname, sl in results.items():
        ok = sl == TARGET
        if not ok:
            all_ok = False
        mark = "✓" if ok else "✗"
        print(f"  {mark}  {fname:30s}  scaffold={sl}")
    print(f"\nAll OK: {all_ok}")


if __name__ == "__main__":
    main()
