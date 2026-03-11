"""
Topological + geometric layer — design validation.

This module validates crossover geometry (inter-helix distances, phase
register) and strand topology (no unresolved nicks, sequence length
consistency).  It operates on Design objects and may call geometry.py for
position checks, but never modifies any model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List

from backend.core.models import Design


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


def validate_design(design: Design) -> ValidationReport:
    """
    Run all available validation checks on *design*.

    Currently implemented:
    - Unique helix IDs
    - Unique strand IDs
    - Domain helix references exist
    - Scaffold strand count (exactly 1)
    - Sequence length consistency (if sequence provided)
    - Crossover strand references exist

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
    scaffold_count = sum(1 for s in design.strands if s.is_scaffold)
    if scaffold_count == 0:
        report.results.append(ValidationResult(False, "No scaffold strand defined."))
    elif scaffold_count == 1:
        report.results.append(ValidationResult(True, "Scaffold strand present."))
    else:
        report.results.append(
            ValidationResult(True, f"Multi-scaffold design: {scaffold_count} scaffold strands.")
        )

    # ── Sequence length consistency ───────────────────────────────────────
    for strand in design.strands:
        if strand.sequence is None:
            continue
        expected_len = sum(
            abs(d.end_bp - d.start_bp) + 1 for d in strand.domains
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

    # ── Crossover strand references ───────────────────────────────────────
    bad_xo: List[str] = []
    for xo in design.crossovers:
        if xo.strand_a_id not in strand_ids:
            bad_xo.append(f"Crossover {xo.id!r} references unknown strand_a {xo.strand_a_id!r}")
        if xo.strand_b_id not in strand_ids:
            bad_xo.append(f"Crossover {xo.id!r} references unknown strand_b {xo.strand_b_id!r}")
    if bad_xo:
        report.results.append(ValidationResult(False, "; ".join(bad_xo)))
    elif design.crossovers:
        report.results.append(ValidationResult(True, "All crossover strand references are valid."))

    return report
