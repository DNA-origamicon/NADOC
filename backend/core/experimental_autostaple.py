"""Recorded experimental routing policy; lattice placement rules stay unchanged."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ExperimentalAutostaple(BaseModel):
    model_config = ConfigDict(extra="forbid")

    crossover_repeat_bp: Literal[21, 42] = 42
    pattern: Literal[0, 1] = 0
    min_length: int = Field(default=21, ge=7, le=200)
    max_merged_length: int = Field(default=56, ge=21, le=300)
    folding_order: bool = False
    temperature_gap_c: float = Field(default=2.0, ge=0.1, le=20, allow_inf_nan=False)

    @model_validator(mode="after")
    def ordered_lengths(self):
        if self.min_length > self.max_merged_length:
            raise ValueError("Minimum staple length must not exceed the merge limit.")
        return self


def retain_boundary(lower_bp: int, policy, *, helix_ids=()) -> bool:
    """Select whole crossover pairs by their existing lower nick boundary.

    Both members (e.g. 20/21) use lower_bp=20. Absolute lattice coordinates
    anchor the alternating pattern across regions and repeated placement passes.
    Negative coordinates use floor division, preserving the same 42 bp period.
    """
    if hasattr(policy, 'for_boundary'):
        policy = policy.for_boundary(lower_bp, helix_ids)
    return policy is None or policy.crossover_repeat_bp == 21 or (lower_bp // 21) % 2 == policy.pattern


def length_report(design, kept_ids=frozenset()):
    """Realized distributions for the routed scope, including protected staples."""
    from collections import Counter
    from backend.core.sequences import strand_nucleotide_count, _build_loop_skip_map
    from backend.core.models import StrandType

    staples = [s for s in design.strands if s.strand_type == StrandType.STAPLE
               and not s.is_reference and s.id not in kept_ids]
    loop_skips = _build_loop_skip_map(design)
    return {
        "staple_lengths": dict(sorted(Counter(strand_nucleotide_count(s, design, loop_skip_map=loop_skips) for s in staples).items())),
        "domain_lengths": dict(sorted(Counter(abs(d.end_bp - d.start_bp) + 1 for s in staples for d in s.domains).items())),
    }
