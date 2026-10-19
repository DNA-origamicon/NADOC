"""Nucleotide occupancy uniqueness: every (helix, bp, direction) slot holds at most one base.

A helix position is ``(helix_id, bp)``; each bp has two strand slots, FORWARD and
REVERSE. A slot may be covered by at most one domain of at most one physical
strand. Anything else is physically impossible (ISSUE-19, ISSUE-126).

Reference strands (``Strand.is_reference``) are non-physical overlays excluded
from export and validation, so they do not occupy slots. Loops and skips change
how many bases sit at a bp, not which strand owns the slot, so they do not affect
this check.
"""

from collections import defaultdict


def occupancy_conflicts(design, *, limit=20):
    """Return up to ``limit`` conflicts as dicts, plus the total conflicting-slot count.

    Each conflict: {"helix_id", "bp", "direction", "strand_ids"} where strand_ids
    lists every claimant (a strand appears twice if it covers the slot twice).
    Runs in O(occupied slots) using per-helix interval sweeps, not per-bp dicts.
    """
    # (helix_id, direction) -> list of (lo, hi, strand_id)
    intervals = defaultdict(list)
    for strand in design.strands:
        if strand.is_reference:
            continue
        for domain in strand.domains:
            lo, hi = sorted((domain.start_bp, domain.end_bp))
            intervals[(domain.helix_id, domain.direction)].append((lo, hi, strand.id))
    conflicts, total = [], 0
    for (helix_id, direction), spans in intervals.items():
        events = sorted(spans)
        active = []  # (hi, strand_id) intervals still covering the sweep point
        for lo, hi, strand_id in events:
            active = [(h, s) for h, s in active if h >= lo]
            for other_hi, other_id in active:
                overlap_hi = min(hi, other_hi)
                total += overlap_hi - lo + 1
                if len(conflicts) < limit:
                    conflicts.append({"helix_id": helix_id, "bp": lo, "bp_end": overlap_hi,
                                      "direction": getattr(direction, "value", direction),
                                      "strand_ids": [other_id, strand_id]})
            active.append((hi, strand_id))
    return conflicts, total
