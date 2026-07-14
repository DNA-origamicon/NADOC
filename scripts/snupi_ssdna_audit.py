#!/usr/bin/env python
"""Audit a design's ssDNA content as the SNUPI FEM sees it (phase SS-0).

    uv run python scripts/snupi_ssdna_audit.py workspace/VoltronCore.nadoc

Reports every single-stranded run, classified bridge / tail / free (see
``backend/physics/snupi_ssdna.py``), plus the duplex beams that currently span a
multi-bp gap — those are unstapled regions being held rigid by a full-stiffness dsDNA
element, which is exactly what phase SS-1 replaces.

Read-only. Loads the .nadoc from disk; never touches the running server.
"""

from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.core.models import Design                       # noqa: E402
from backend.physics.fem_solver import FEM_RISE_PER_BP, build_fem_mesh  # noqa: E402
from backend.physics.snupi_ssdna import ssdna_inventory      # noqa: E402


def _hist(lengths) -> str:
    c = collections.Counter(lengths)
    return ", ".join(f"{n} nt ×{k}" for n, k in sorted(c.items())) or "—"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("design", type=Path, help="path to a .nadoc design")
    ap.add_argument("--runs", action="store_true", help="list every run individually")
    args = ap.parse_args()

    design = Design(**json.loads(args.design.read_text()))
    inv = ssdna_inventory(design)
    mesh = build_fem_mesh(design)

    print(f"\n=== {args.design.name} ===")
    print(f"helices               {inv.n_helices}  ({inv.n_helices - inv.n_meshed_helices} with NO FEM nodes)")
    print(f"strands               {len(design.strands)}")
    print(f"FEM nodes (duplex bp) {inv.n_nodes}")
    print(f"FEM elements          {len(mesh.elements)}")
    print(f"single-stranded nt    {inv.n_ss_nt}"
          f"   ({100.0 * inv.n_ss_nt / max(1, inv.n_ss_nt + inv.n_nodes):.1f}% of nt)")

    interior = inv.bridges("interior")
    hops = inv.bridges("hop")
    oh_tails = inv.tails(overhang=True)
    end_tails = inv.tails(overhang=False)
    free = inv.of_kind("free")

    print("\n-- BRIDGES (load-bearing; SNUPI models these; phase SS-1) --")
    print(f"  interior gaps (same helix)  {len(interior):4d} runs, {sum(r.n_nt for r in interior):5d} nt   [{_hist(r.n_nt for r in interior)}]")
    print(f"  cross-helix hops            {len(hops):4d} runs, {sum(r.n_nt for r in hops):5d} nt   [{_hist(r.n_nt for r in hops)}]")

    print("\n-- TAILS (no load path; SNUPI CANNOT represent; phases SS-2/3/4) --")
    print(f"  overhangs / toeholds        {len(oh_tails):4d} runs, {sum(r.n_nt for r in oh_tails):5d} nt   [{_hist(r.n_nt for r in oh_tails)}]")
    print(f"  dangling scaffold/staple ends {len(end_tails):3d} runs, {sum(r.n_nt for r in end_tails):5d} nt   [{_hist(r.n_nt for r in end_tails)}]")
    by_type = collections.Counter(r.strand_type for r in end_tails)
    if by_type:
        print(f"    by strand type: {dict(by_type)}")

    print("\n-- FREE (no meshed neighbour at all; excluded from the FEM) --")
    print(f"  {len(free):4d} runs, {sum(r.n_nt for r in free):5d} nt   [{_hist(r.n_nt for r in free)}]")

    # Duplex beams spanning >1 bp: an unstapled gap currently held rigid. SS-1 target.
    long_el = [e for e in mesh.elements if e.length > 1.5 * FEM_RISE_PER_BP]
    intra = [e for e in long_el
             if mesh.nodes[e.node_i].helix_id == mesh.nodes[e.node_j].helix_id]
    print("\n-- ARTIFACT: duplex beams spanning a multi-bp gap (SS-1 replaces these) --")
    print(f"  {len(intra)} intra-helix beams > 1 bp")
    for e in sorted(intra, key=lambda e: -e.length)[:10]:
        ni, nj = mesh.nodes[e.node_i], mesh.nodes[e.node_j]
        gap = nj.global_bp - ni.global_bp - 1
        print(f"    {ni.helix_id}  bp {ni.global_bp}→{nj.global_bp}"
              f"   gap {gap} bp   L = {e.length:.2f} nm   family={e.motif_family}")

    if args.runs:
        print("\n-- every run --")
        for r in sorted(inv.runs, key=lambda r: -r.n_nt):
            a = (f"5'{r.anchor_5.helix_id}:{r.anchor_5.bp}" if r.anchor_5 else "5'—") + \
                " " + (f"3'{r.anchor_3.helix_id}:{r.anchor_3.bp}" if r.anchor_3 else "3'—")
            extra = f" bridge={r.bridge_kind}" if r.kind == "bridge" else ""
            oh = f" oh={r.overhang_ids[0]}" if r.overhang_ids else ""
            print(f"  {r.kind:7s} {r.n_nt:4d} nt  {r.strand_type:9s} {a}{extra}{oh}")

    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
