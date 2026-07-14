#!/usr/bin/env python3
"""Harvest SNUPI's ssDNA element properties from the REAL binary — the source of
``snupi_material._SS_TABLE`` (SS-1 / gap G9).

SNUPI ships as a compiled MATLAB binary.  Its options file (``~/SNUPI/Default.snp`` lines
88-153) exposes the INPUTS to the ssDNA laws (SS_LCT1_*, SS_LPB_*, SS_EA_*, SS_GJ_*) but not
the closed forms that combine them, and no combination of the obvious WLC forms reproduces its
output.  So rather than guess, we MEASURE: open interior scaffold gaps of many different
lengths in one design, run SNUPI, and read the resulting ssDNA elements' (L, GJ, EI, EA)
straight out of its ``PROP`` array.

Gaps are opened by eroding staple STRAND-TERMINAL domains outward from a site where two staple
ends face each other, so strand continuity and every crossover survive and the design still
converges.  Each ssDNA element is paired with its nucleotide count by sorting both lists: the
SS-0 classifier's BRIDGE runs and SNUPI's isotropic elements are in bijection (EIy == EIz is
the discriminator — every duplex/crossover element is anisotropic), and rest length is monotone
in nt.  That bijection holding at all is itself a cross-validation of the SS-0 classifier
against the real SNUPI.

PROP layout, reverse-engineered: ``[L, 8 node offsets, GJ, EIy, EIz, EA, GAy, GAz, 15 couplings]``.

LOCAL TOOL — needs SNUPI + the MATLAB Runtime installed (this machine only; see
memory/project_snupi_reference_compare.md).  Not part of the test suite.

Usage:
    uv run python scripts/snupi_ssdna_probe.py <run-name> <nt,nt,...> [design-stem]
    uv run python scripts/snupi_ssdna_probe.py ssprobe 1,2,3,4,5 6hbx100_noT
"""
import sys
from pathlib import Path

import numpy as np
import scipy.io as sio

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))

from backend.core.models import Design, Direction, StrandType  # noqa: E402
from backend.core.sequences import domain_bp_range  # noqa: E402
from backend.physics.snupi_ssdna import classify_ssdna_runs  # noqa: E402

import snupi_reference_compare as srx  # noqa: E402

TARGETS = sorted((int(x) for x in sys.argv[2].split(",")), reverse=True)
BASENAME = sys.argv[1]
MIN_KEEP = 2          # never shrink a terminal domain below this many nt


def _bps(dm):
    return list(domain_bp_range(dm))


def _trim_3p(dm, k):
    dm.end_bp += -k if dm.direction == Direction.FORWARD else k


def _trim_5p(dm, k):
    dm.start_bp += k if dm.direction == Direction.FORWARD else -k


def main():
    design = Design.model_validate_json(REPO / "workspace" / ((sys.argv[3] if len(sys.argv) > 3 else "6hbx100_noT") + ".nadoc").read_text())

    staples = [s for s in design.strands
               if s.strand_type == StrandType.STAPLE and not s.is_reference]

    # Every staple nick: a 3'-terminal domain end adjacent to a 5'-terminal domain start
    # on the same helix.  Eroding outward from a nick keeps both strands contiguous.
    ends_3p = {}   # (helix, bp) -> domain (the 3' terminus sits here)
    ends_5p = {}
    for s in staples:
        d0, dn = s.domains[0], s.domains[-1]
        ends_5p[(d0.helix_id, d0.start_bp)] = d0
        ends_3p[(dn.helix_id, dn.end_bp)] = dn

    # A "site" = a 3'-terminal staple end and a 5'-terminal staple end facing each other
    # across `existing` staple-free bp (existing=0 -> a plain nick).  Eroding both ends
    # outward widens that gap to existing + a + b, keeping both strands contiguous.
    covered = {(dm.helix_id, bp) for s in staples for dm in s.domains for bp in _bps(dm)}
    sites = []
    for (h, bp), d3 in ends_3p.items():
        for step in (1, -1):
            for gap in range(0, 41):
                probe = bp + step * (gap + 1)
                if (h, probe) in covered:
                    d5 = ends_5p.get((h, probe))
                    if d5 is not None and d5 is not d3:
                        sites.append((d3, d5, gap))
                    break

    caps = [g + len(_bps(d3)) + len(_bps(d5)) - 2 * MIN_KEEP for d3, d5, g in sites]
    order = sorted(range(len(sites)), key=lambda i: -caps[i])
    print("site capacities:", [caps[i] for i in order])

    used, free = [], order
    for n in TARGETS:                       # biggest gap first -> widest site
        hit = next((i for i in free if caps[i] >= n >= sites[i][2]), None)
        if hit is None:
            print(f"  ! no site left with capacity for n={n}")
            continue
        free.remove(hit)
        d3, d5, existing = sites[hit]
        need = n - existing
        cap3, cap5 = len(_bps(d3)) - MIN_KEEP, len(_bps(d5)) - MIN_KEEP
        a = min(cap3, (need + 1) // 2)
        b = need - a
        if b > cap5:
            b, a = cap5, need - cap5
        _trim_3p(d3, a)
        _trim_5p(d5, b)
        used.append(n)

    runs = classify_ssdna_runs(design)
    bridges = sorted(r.n_nt for r in runs if r.kind == "bridge")
    tails = sorted(r.n_nt for r in runs if r.kind == "tail")
    print("requested gaps :", used)
    print("bridges (n_nt) :", bridges, " count", len(bridges))
    print("tails          :", tails)

    basename = BASENAME
    _, _, lattice = srx.prep_snupi_inputs(design, basename, with_nma=False)
    out = srx.run_snupi(basename, lattice, timeout_s=3600)
    print("output:", out)

    m = sio.loadmat(str(out / f"{basename}_STT_RES.mat"))
    P = m["PROP"]      # (n_el, 30): [L, 8 offsets, GJ, EIy, EIz, EA, GAy, GAz, 15 couplings]
    L, GJ, EIy, EIz, EA = P[:, 0], P[:, 9], P[:, 10], P[:, 11], P[:, 12]
    idx = np.where(np.isclose(EIy, EIz, rtol=1e-9) & (P[:, 13] == 0) & (P[:, 14] == 0))[0]
    print(f"\nSNUPI ssDNA elements: {len(idx)}   classifier bridges: {len(bridges)}")

    ss = sorted((float(L[i]), float(GJ[i]), float(EIy[i]), float(EA[i])) for i in idx)
    print(f"\n{'nt':>4} {'L_rest':>9} {'GJ':>9} {'EI':>9} {'EA':>9}")
    rows = []
    for nt, (l, gj, ei, ea) in zip(bridges, ss):
        print(f"{nt:>4} {l:9.4f} {gj:9.4f} {ei:9.4f} {ea:9.4f}")
        rows.append([nt, l, gj, ei, ea])
    return rows


if __name__ == "__main__":
    main()
