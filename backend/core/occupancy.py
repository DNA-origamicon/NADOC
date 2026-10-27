"""Nucleotide occupancy uniqueness: every (helix, bp, direction) slot holds at most one base.

A helix position is ``(helix_id, bp)``; each bp has two strand slots, FORWARD and
REVERSE. A slot may be covered by at most one domain of at most one physical
strand. Anything else is physically impossible (ISSUE-19, ISSUE-126).

Reference strands (``Strand.is_reference``) are non-physical overlays excluded
from export and validation, so they do not occupy slots. Loops and skips change
how many bases sit at a bp, not which strand owns the slot, so they do not affect
this check.
"""

from collections import Counter, defaultdict

from backend.core.part_command_errors import CommandContractError


def require_unique_occupancy(design):
    """Refuse a native candidate before it can become an accepted replay result.

    This checks ownership, not spatial proximity, and never merges claimants or
    changes their polarity. Reference overlays retain their existing exclusion.
    """
    conflicts, total = occupancy_conflicts(design, limit=1)
    if total:
        conflict = conflicts[0]
        raise CommandContractError(
            "Two bases occupy the same helix, bp and direction: "
            f"{conflict['helix_id']} bp {conflict['bp']}..{conflict['bp_end']} "
            f"{conflict['direction']}; strands {conflict['strand_ids']}. "
            "Choose compatible connection endpoints or repair the conflicting domains.",
            code="nucleotide_double_occupancy",
        )


def occupancy_conflicts(design, *, limit=20):
    """Return up to ``limit`` conflicts as dicts, plus the total conflicting-slot count.

    Each conflict: {"helix_id", "bp", "direction", "strand_ids"} where strand_ids
    lists every claimant (a strand appears twice if it covers the slot twice).
    Counts each conflicting slot once, even when three or more domains claim it.
    Uses interval sweeps rather than allocating a boolean for every bp.
    """
    # End-exclusive events keep inclusive domain endpoints exact in both directions.
    events = defaultdict(lambda: defaultdict(Counter))
    for strand in design.strands:
        if strand.is_reference:
            continue
        for domain in strand.domains:
            lo, hi = sorted((domain.start_bp, domain.end_bp))
            lane = events[(domain.helix_id, domain.direction)]
            lane[lo][strand.id] += 1
            lane[hi + 1][strand.id] -= 1
    conflicts, total = [], 0
    for (helix_id, direction), lane in events.items():
        active = Counter()
        count, previous = 0, None
        for position in sorted(lane):
            if count > 1 and previous is not None:
                total += position - previous
                if len(conflicts) < limit:
                    conflicts.append({"helix_id": helix_id, "bp": previous, "bp_end": position - 1,
                                      "direction": getattr(direction, "value", direction),
                                      "strand_ids": sorted(active.elements())})
            for strand_id, delta in lane[position].items():
                active[strand_id] += delta
                count += delta
                if not active[strand_id]:
                    del active[strand_id]
            previous = position
    return conflicts, total
