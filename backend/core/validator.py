"""
Topological + geometric layer — design validation.

This module validates strand topology (no unresolved nicks, sequence length
consistency).  It operates on Design objects and may call geometry.py for
position checks, but never modifies any model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set, Tuple

from backend.core.models import Design, Strand, StrandType


@dataclass
class ValidationResult:
    """Result of a single validation check."""
    ok: bool
    message: str


@dataclass
class ValidationReport:
    """Aggregated report from validate_design()."""
    results: List[ValidationResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(r.ok for r in self.results)

    def __str__(self) -> str:
        lines = []
        for r in self.results:
            symbol = "✓" if r.ok else "✗"
            lines.append(f"  {symbol} {r.message}")
        return "\n".join(lines)


def _is_loop_strand(strand: Strand) -> bool:
    """Return True if the strand has a self-intersecting topology.

    Checks for **position overlap** — any (helix_id, bp, direction) nucleotide
    position visited by more than one domain in the strand.  This catches
    strands that physically thread through the same helix position twice.

    Note: the NADOC model cannot represent truly circular strands (they are
    linearised on import), so there is no adjacency-based heuristic here.
    Two free ends that happen to sit on neighbouring base positions are *not*
    connected and must not be flagged.
    """
    if len(strand.domains) < 1:
        return False

    seen: Set[Tuple[str, int, str]] = set()
    for domain in strand.domains:
        lo = min(domain.start_bp, domain.end_bp)
        hi = max(domain.start_bp, domain.end_bp)
        dir_val = domain.direction.value if hasattr(domain.direction, "value") else str(domain.direction)
        for bp in range(lo, hi + 1):
            key = (domain.helix_id, bp, dir_val)
            if key in seen:
                return True
            seen.add(key)

    return False


def validate_design(design: Design) -> ValidationReport:
    """
    Run all available validation checks on *design*.

    Currently implemented:
    - Unique helix IDs
    - Unique strand IDs
    - Domain helix references exist
    - Scaffold strand count (exactly 1)
    - Sequence length consistency (if sequence provided)

    Returns a ValidationReport; does not raise on failure.
    """
    report = ValidationReport()
    helix_ids = {h.id for h in design.helices}
    strand_ids = {s.id for s in design.strands}

    # ── Unique helix IDs ──────────────────────────────────────────────────
    if len(helix_ids) == len(design.helices):
        report.results.append(ValidationResult(True, "Helix IDs are unique."))
    else:
        report.results.append(ValidationResult(False, "Duplicate helix IDs detected."))

    # ── Unique strand IDs ─────────────────────────────────────────────────
    if len(strand_ids) == len(design.strands):
        report.results.append(ValidationResult(True, "Strand IDs are unique."))
    else:
        report.results.append(ValidationResult(False, "Duplicate strand IDs detected."))

    # ── Domain helix references ───────────────────────────────────────────
    bad_refs: List[str] = []
    for strand in design.strands:
        if strand.strand_type == StrandType.LINKER:
            continue   # linker strands live on virtual __lnk__ helices; skip
        for domain in strand.domains:
            if domain.helix_id not in helix_ids:
                bad_refs.append(
                    f"Strand {strand.id!r} domain references unknown helix {domain.helix_id!r}"
                )
    if bad_refs:
        report.results.append(ValidationResult(False, "; ".join(bad_refs)))
    else:
        report.results.append(ValidationResult(True, "All domain helix references are valid."))

    # ── Scaffold count ────────────────────────────────────────────────────
    # Multiple scaffold strands are valid for MagicDNA-style multi-scaffold
    # designs and clockwork multi-component assemblies (DTP-0c decision).
    scaffold_count = sum(1 for s in design.strands if s.strand_type == StrandType.SCAFFOLD)
    if scaffold_count == 0:
        report.results.append(ValidationResult(False, "No scaffold strand defined."))
    elif scaffold_count == 1:
        report.results.append(ValidationResult(True, "Scaffold strand present."))
    else:
        report.results.append(
            ValidationResult(True, f"Multi-scaffold design: {scaffold_count} scaffold strands.")
        )

    # ── Sequence length consistency ───────────────────────────────────────
    # Build skip-position sets per helix so deleted bases can be subtracted
    # from the bp-count expected length (scadnano deletions reduce nucleotide
    # count below the raw bp span).
    helix_skips: Dict[str, Set[int]] = {
        h.id: {ls.bp_index for ls in h.loop_skips if ls.delta == -1}
        for h in design.helices
    }
    for strand in design.strands:
        if strand.sequence is None:
            continue
        if strand.strand_type == StrandType.LINKER:
            continue   # linker strand sequences are auto-generated, not user-validated
        expected_len = sum(
            abs(d.end_bp - d.start_bp) + 1
            - sum(1 for bp in helix_skips.get(d.helix_id, set())
                  if min(d.start_bp, d.end_bp) <= bp <= max(d.start_bp, d.end_bp))
            for d in strand.domains
        )
        if len(strand.sequence) != expected_len:
            report.results.append(ValidationResult(
                False,
                f"Strand {strand.id!r} sequence length {len(strand.sequence)} "
                f"!= expected {expected_len}."
            ))
        else:
            report.results.append(ValidationResult(
                True,
                f"Strand {strand.id!r} sequence length is consistent."
            ))

    # ── Loop / circular strand detection ─────────────────────────────────────
    loop_ids: List[str] = [
        s.id for s in design.strands
        if s.strand_type not in (StrandType.SCAFFOLD, StrandType.LINKER)
           and _is_loop_strand(s)
    ]
    if loop_ids:
        report.results.append(ValidationResult(
            False,
            f"Circular staple strand(s) detected (no free 5′/3′ ends): "
            + ", ".join(repr(sid) for sid in loop_ids),
        ))
    # No "pass" entry when there are no loops — avoids noise in the report.

    return report
