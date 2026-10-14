"""Exact scaffold availability checks, independent of sequence completeness.

A routed prefix does not make a shorter scaffold available. Only the scaffold
library and an explicitly assigned custom source establish available lengths.
This module reads topology; it never adds bases or changes a scaffold route.
"""

from collections import defaultdict

from backend.core.models import Design
from backend.core.sequences import SCAFFOLD_LIBRARY, strand_nucleotide_count
from backend.core.topology_integrity import forced_edge, half_slot, slot


def scaffold_length_checks(design: Design, *, loop_skip_map=None) -> list[dict]:
    """Check each active scaffold, including its authored junction and tail bases.

    Domain counts use the native loop/skip contract. Junction inserts live outside
    ``Strand.sequence`` and count only on their realized backbone transition,
    using the same directed slots as topology integrity. Terminal DNA sequences
    count; non-DNA terminal modifications do not. Reference DNA never contributes.
    """
    junction_lengths = {}
    for crossover in design.crossovers:
        if crossover.extra_bases:
            a, b = half_slot(crossover.half_a), half_slot(crossover.half_b)
            junction_lengths[a, b] = junction_lengths[b, a] = len(crossover.extra_bases)
    for ligation in design.forced_ligations:
        if ligation.extra_bases:
            junction_lengths[forced_edge(ligation)] = len(ligation.extra_bases)
    tails = defaultdict(int)
    for extension in design.extensions:
        tails[extension.strand_id] += len(extension.sequence or "")
    library = {length: name for name, length, _sequence in SCAFFOLD_LIBRARY}
    checks = []
    for strand in design.strands:
        if not strand.is_scaffold or strand.is_reference:
            continue
        domain_nt = strand_nucleotide_count(strand, design, loop_skip_map=loop_skip_map)
        junction_nt = sum(
            junction_lengths.get((
                slot(a.helix_id, a.end_bp, a.direction),
                slot(b.helix_id, b.start_bp, b.direction),
            ), 0)
            for a, b in zip(strand.domains, strand.domains[1:])
        )
        terminal_nt = tails[strand.id]
        actual_nt = domain_nt + junction_nt + terminal_nt
        available = dict(library)
        if strand.custom_scaffold_length is not None:
            available.setdefault(strand.custom_scaffold_length, "declared custom scaffold")
        matched = available.get(actual_nt)
        nearest = min(available, key=lambda length: (abs(length - actual_nt), length))
        difference = actual_nt - nearest
        lengths = ", ".join(str(length) for length in sorted(available))
        label = strand.name or strand.id
        detail = (
            f"{label}: {actual_nt} nt exactly matches {matched}."
            if matched else
            f"{label}: {actual_nt} nt does not exactly match an available scaffold "
            f"({lengths} nt); {abs(difference)} nt "
            f"{'short of' if difference < 0 else 'over'} {nearest} nt."
        )
        if matched is None and strand.custom_scaffold_length is None:
            detail += " For a custom scaffold, assign the original source sequence to declare its full length."
        checks.append({
            "strand_id": strand.id, "name": label,
            "actual_nt": actual_nt, "domain_nt": domain_nt,
            "junction_nt": junction_nt, "terminal_nt": terminal_nt,
            "available_lengths_nt": sorted(available),
            "matched_scaffold": matched, "complete": matched is not None,
            "detail": detail,
        })
    return checks
