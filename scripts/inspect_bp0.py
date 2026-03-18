"""
Build a 6HB and verify the coverage invariant before and after auto_scaffold:
every helix at every bp position must have exactly one scaffold nucleotide
(FORWARD or REVERSE) and one staple nucleotide (the other direction).

Prints a summary and lists any violations for each stage.
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from collections import defaultdict
from backend.core.lattice import make_bundle_design, auto_scaffold
from backend.core.models import Direction

CELLS_6HB = [(0, 0), (0, 1), (1, 0), (1, 2), (0, 2), (2, 1)]


def check_coverage(design, label):
    coverage = defaultdict(list)
    for strand in design.strands:
        for domain in strand.domains:
            lo = min(domain.start_bp, domain.end_bp)
            hi = max(domain.start_bp, domain.end_bp)
            for bp in range(lo, hi + 1):
                coverage[(domain.helix_id, domain.direction, bp)].append(
                    strand.strand_type.value
                )

    total_positions = 0
    violations = []

    for helix in design.helices:
        for bp in range(helix.length_bp):
            total_positions += 1
            fwd = coverage[(helix.id, Direction.FORWARD, bp)]
            rev = coverage[(helix.id, Direction.REVERSE, bp)]

            if sorted(fwd + rev) != ["scaffold", "staple"]:
                violations.append(
                    f"  {helix.id} bp={bp:3d}  FWD={fwd or ['NONE']}  REV={rev or ['NONE']}"
                )

    n_scaffold = sum(1 for s in design.strands if s.strand_type.value == "scaffold")
    n_staple   = sum(1 for s in design.strands if s.strand_type.value == "staple")

    print(f"── {label} ──")
    print(f"  Strands: {len(design.strands)}  (scaffold: {n_scaffold}, staple: {n_staple})")
    print(f"  BP slots checked: {total_positions}")
    if violations:
        print(f"  FAIL — {len(violations)} violation(s):")
        for v in violations[:40]:
            print(v)
        if len(violations) > 40:
            print(f"  ... and {len(violations) - 40} more")
    else:
        print("  PASS — every bp slot has exactly one scaffold + one staple nucleotide.")
    print()


design = make_bundle_design(CELLS_6HB, length_bp=400)
print(f"Design: {len(design.helices)} helices, {design.helices[0].length_bp} bp each\n")

check_coverage(design, "before auto_scaffold")

for mode in ("seam_line", "end_to_end"):
    result = auto_scaffold(design, mode=mode, scaffold_loops=False)
    check_coverage(result, f"after auto_scaffold  mode={mode}")
