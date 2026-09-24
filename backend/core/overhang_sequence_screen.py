"""Screen Johnson candidates in the actual staple and connected linker context.

Uses the checker's conditions and Tm cutoff. Only self-structures are screened:
complementarity between an overhang and its intended linker is intentional.
Unknown bases and long strands have the same limits as the interactive checker.
"""

from functools import lru_cache

from backend.core.hairpin_dimer import (
    DEFAULT_THRESHOLD_C,
    ORIGAMI_BUFFER,
    dimer,
    hairpin,
    linker_strand_sequence,
)
from backend.core.models import StrandType
from backend.core.overhang_generator import SequenceGenerationError
from backend.core.sequences import (
    _assemble_overhang_5to3,
    _build_loop_skip_map,
    _domain_seq_span,
    build_overhang_bp_bases,
    build_scaffold_base_map,
    complement_base,
    strand_partner_bases,
)


class OverhangSequenceScreen:
    """Reusable, read-only candidate screen; commit exactly the sequences tested."""

    def __init__(
        self, design, spec, *, threshold_c=DEFAULT_THRESHOLD_C, max_candidates=500
    ):
        self.design = design
        self.spec = spec
        self.threshold_c = threshold_c
        self.max_candidates = max_candidates
        self.attempts = 0
        self.last_failure = ""
        self.overhangs = {o.id: o for o in design.overhangs}
        self.bp_bases = build_overhang_bp_bases(design)
        self.loop_skips = _build_loop_skip_map(design)
        self.strands = [
            s
            for s in design.strands
            if not s.is_scaffold
            and not s.is_reference
            and any(
                d.overhang_id == spec.id or d.binds_overhang_id == spec.id
                for d in s.domains
            )
        ]
        self.backing = next(
            d for s in self.strands for d in s.domains if d.overhang_id == spec.id
        )
        scaffold_bases = build_scaffold_base_map(design)
        self.stored = {}
        for strand in self.strands:
            if strand.sequence is not None:
                self.stored[strand.id] = strand.sequence.upper()
            else:
                self.stored[strand.id] = "".join(
                    complement_base(b) if b else "N"
                    for b in strand_partner_bases(
                        design,
                        strand,
                        scaf_map=scaffold_bases,
                        ls_map=self.loop_skips,
                        overhang_bp_bases=self.bp_bases,
                    )
                )
        # Cache repeated fixed sequences within this generation, never globally.
        self._tms = lru_cache(maxsize=2048)(self._sequence_tms)
        # The scaffold-derived body is not editable by Gen. Compare each
        # structure type against its own fixed-body baseline, with the variable
        # overhang masked out; never grandfather the old overhang's structures.
        self.limits = {}
        _, fixed = self.sequences(
            "N" * (abs(self.backing.end_bp - self.backing.start_bp) + 1)
        )
        for strand in self.strands:
            if strand.strand_type != StrandType.LINKER:
                self.limits[strand.id] = tuple(
                    max(self.threshold_c, tm) for tm in self._tms(fixed[strand.id])
                )

    def _sequence_tms(self, sequence):
        return tuple(
            hit["tm"] if hit is not None else float("-inf")
            for hit in (
                hairpin(sequence, ORIGAMI_BUFFER),
                dimer(sequence, sequence, ORIGAMI_BUFFER),
            )
        )

    def sequences(self, candidate):
        spec = self.spec.model_copy(update={"sequence": candidate})
        length = abs(self.backing.end_bp - self.backing.start_bp) + 1
        assembled = "".join(_assemble_overhang_5to3(spec, length))
        step = 1 if self.backing.end_bp >= self.backing.start_bp else -1
        bp_bases = dict(self.bp_bases)
        bp_bases[spec.id] = {
            self.backing.start_bp + i * step: base for i, base in enumerate(assembled)
        }
        sequences = {}
        for strand in self.strands:
            if strand.strand_type == StrandType.LINKER:
                sequences[strand.id] = linker_strand_sequence(
                    self.design, strand, bp_bases
                )
                continue
            bases = []
            offset = 0
            for domain in strand.domains:
                span = _domain_seq_span(domain, self.loop_skips)
                if domain.overhang_id:
                    oh = (
                        spec
                        if domain.overhang_id == spec.id
                        else self.overhangs.get(domain.overhang_id)
                    )
                    bases.extend(_assemble_overhang_5to3(oh, span))
                elif domain.binds_overhang_id:
                    bp_map = bp_bases.get(domain.binds_overhang_id, {})
                    direction = 1 if domain.end_bp >= domain.start_bp else -1
                    bases.extend(
                        complement_base(bp_map[bp]) if bp in bp_map else "N"
                        for bp in range(
                            domain.start_bp, domain.end_bp + direction, direction
                        )
                    )
                else:
                    bases.extend(
                        self.stored[strand.id][offset : offset + span].ljust(span, "N")
                    )
                offset += span
            sequences[strand.id] = "".join(bases)
        return assembled, sequences

    def __call__(self, candidate):
        if self.attempts >= self.max_candidates:
            raise SequenceGenerationError(self.failure_message())
        self.attempts += 1
        overhang, strands = self.sequences(candidate)
        for label, sequence in [
            (f"overhang {self.spec.id}", overhang),
            *strands.items(),
        ]:
            limits = self.limits.get(label, (self.threshold_c, self.threshold_c))
            for kind, tm, limit in zip(
                ("hairpin", "self-dimer"), self._tms(sequence), limits
            ):
                if tm > limit:
                    self.last_failure = (
                        f"{label}: {kind} Tm {tm:.1f} °C (limit {limit:.1f} °C)"
                    )
                    return False
        return True

    def failure_message(self):
        return (
            f"No overhang sequence passed the {self.threshold_c:g} °C hairpin/self-dimer "
            f"screen for the whole staple and connected linkers after {self.attempts} candidates. "
            f"{self.last_failure}. Fixed staple bases, locked sub-domains, the other linker arm "
            "or bridge may prevent a solution; edit those sequences or regenerate the other arm."
        )

    def apply(self, candidate):
        """Return the accepted design without changing unrelated strands or geometry."""
        _, sequences = self.sequences(candidate)
        return self.design.model_copy(
            update={
                "overhangs": [
                    self.spec.model_copy(update={"sequence": candidate})
                    if o.id == self.spec.id
                    else o
                    for o in self.design.overhangs
                ],
                "strands": [
                    s.model_copy(update={"sequence": sequences[s.id]})
                    if s.id in sequences
                    else s
                    for s in self.design.strands
                ],
            }
        )
