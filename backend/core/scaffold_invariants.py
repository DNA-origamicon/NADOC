"""
Scaffold-routing invariants — a reusable contract every autoscaffold entry point
must satisfy, so a new routing path cannot silently regress the established
seamed conventions.

Background (the 2026-06-26 hinge regression).  A new return path was wired into
``auto_scaffold_seamed`` that produced a seamless single-pass raster — no seam
(double) crossovers and no scaffold-end extension — so scaffold crossovers sat
inside staple domains with zero ssDNA margin.  The full suite stayed green because
``validate_design`` does NOT encode these properties and the path-specific router
tests never exercised the new path.  This module makes the properties explicit and
asserted so any routing output (existing or future) is gated on them.

Two invariants:

* **Seam presence** (``require_seams``) — a *seamed* route must contain genuine
  mid-helix seam crossovers (``scaffold_seam_positions`` non-empty).  Seamless /
  zig-zag routes legitimately have none, so callers pass ``require_seams=False``.

* **ssDNA margin at end/turn crossovers** — every scaffold crossover that is NOT
  part of a seam (a single u-turn / near-far end cap) must sit at least
  ``MIN_SSDNA_MARGIN`` bp clear of any staple domain on its helix, i.e. the
  scaffold is single-stranded for ≥3 bases before the crossover (the hard-won
  rule that scaffold crossovers live in extended ssDNA, never buried in a staple).
  Seam crossovers are intentionally mid-duplex and are exempt.  Helices with no
  staple coverage are vacuously clear.

The checker is a pure function returning a list of human-readable violation
strings (empty == compliant), so it can be used both in tests and as a runtime
self-gate inside a router.
"""

from __future__ import annotations

from backend.core.crossover_positions import scaffold_seam_positions
from backend.core.models import Crossover, Design, HalfCrossover, StrandType

# Minimum unpaired-scaffold clearance (bp) between an end/turn scaffold crossover
# and the nearest staple-domain edge on the same helix.
MIN_SSDNA_MARGIN = 3


def _staple_coverage(design: Design) -> dict[str, list[tuple[int, int]]]:
    """helix_id → list of (lo, hi) bp ranges covered by staple domains."""
    cov: dict[str, list[tuple[int, int]]] = {}
    for s in design.strands:
        if s.strand_type != StrandType.STAPLE or s.is_reference:
            continue
        for dom in s.domains:
            lo = min(dom.start_bp, dom.end_bp)
            hi = max(dom.start_bp, dom.end_bp)
            cov.setdefault(dom.helix_id, []).append((lo, hi))
    return cov


def _staple_clearance(bp: int, ranges: list[tuple[int, int]]) -> int:
    """bp distance from ``bp`` to the nearest staple range (0 if inside one)."""
    if not ranges:
        return 1 << 30  # no staples on this helix → vacuously clear
    best = 1 << 30
    for lo, hi in ranges:
        if lo <= bp <= hi:
            return 0
        best = min(best, lo - bp if bp < lo else bp - hi)
    return best


def _scaffold_crossovers(design: Design) -> list[Crossover]:
    """Crossovers both of whose halves run on the scaffold strand direction."""
    helix_map = {h.id: h for h in design.helices if h.grid_pos is not None}

    def _scaffold_half(half: HalfCrossover) -> bool:
        h = helix_map.get(half.helix_id)
        if h is None:
            return False
        row, col = h.grid_pos
        expected = "FORWARD" if (row + col) % 2 == 0 else "REVERSE"
        return half.strand.value == expected

    return [
        xo
        for xo in design.crossovers
        if _scaffold_half(xo.half_a) and _scaffold_half(xo.half_b)
    ]


def scaffold_routing_invariants(
    design: Design,
    *,
    require_seams: bool = True,
    min_margin: int = MIN_SSDNA_MARGIN,
) -> list[str]:
    """Return a list of invariant violations for a routed scaffold (empty == OK).

    ``require_seams`` — assert the route contains mid-helix seam crossovers (set
    False for inherently seamless / zig-zag routes).  ``min_margin`` — required
    ssDNA clearance (bp) between every end/turn scaffold crossover and the nearest
    staple edge on its helix.
    """
    violations: list[str] = []

    seam_positions = scaffold_seam_positions(design)
    if require_seams and not seam_positions:
        violations.append(
            "seamed route has no seam (double) scaffold crossovers — "
            "this is a seamless raster, not a seamed routing."
        )

    seam_keys = {(hid, bp) for hid, bps in seam_positions.items() for bp in bps}
    staples = _staple_coverage(design)

    for xo in _scaffold_crossovers(design):
        for half in (xo.half_a, xo.half_b):
            if (half.helix_id, half.index) in seam_keys:
                continue  # seam crossovers are intentionally mid-duplex
            clr = _staple_clearance(half.index, staples.get(half.helix_id, []))
            if clr < min_margin:
                violations.append(
                    f"end/turn scaffold crossover {half.helix_id}[{half.index}] "
                    f"has only {clr} bp ssDNA clearance to a staple domain "
                    f"(need ≥{min_margin}); crossover is buried in / abuts a staple."
                )

    return violations
