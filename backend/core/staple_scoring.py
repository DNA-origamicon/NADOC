"""Read-only staple scoring for Aksel-style routing work.

This module is the first bridge between NADOC topology and the
pyOrigamiBreak/Aksel et al. formulation.  It does not choose breakpoints or
modify strands.  Instead it builds the scaffold-position map that an optimizer
needs, then scores each existing staple in its current routed state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Any

import numpy as np

from backend.core.models import Design, Direction, LatticeType, Strand, StrandType
from backend.core.sequences import complement_base, domain_bp_range


# Units follow pyOrigamiBreak: kcal/mol and kcal/(mol K).
R_KCAL = 0.0019872041
DEFAULT_TEMPERATURE_K = 323.15  # 50 C
DEFAULT_SCAF_CONC = 10.0e-9
DEFAULT_STAP_CONC = 100.0e-9
DEFAULT_MG_CONC = 12.5e-3
DEFAULT_TRIS_CONC = 40.0e-3
DEFAULT_BREAK_RULE = "xstap.all3"
DEFAULT_MIN_SEGMENT_NT = 3


def lattice_min_segment_nt(lattice_type: LatticeType) -> int:
    """Minimum dsDNA leg length for lattice-aware Aksel routing."""

    return 7 if lattice_type == LatticeType.HONEYCOMB else 8


NN_DH = {
    "AA": -7.6, "TT": -7.6, "AT": -7.2, "TA": -7.2,
    "CA": -8.5, "TG": -8.5, "GT": -8.4, "AC": -8.4,
    "CT": -7.8, "AG": -7.8, "GA": -8.2, "TC": -8.2,
    "CG": -10.6, "GC": -9.8, "GG": -8.0, "CC": -8.0,
}
NN_DS = {
    "AA": -21.3, "TT": -21.3, "AT": -20.4, "TA": -21.3,
    "CA": -22.7, "TG": -22.7, "GT": -22.4, "AC": -22.4,
    "CT": -21.0, "AG": -21.0, "GA": -22.2, "TC": -22.2,
    "CG": -27.2, "GC": -24.4, "GG": -19.9, "CC": -19.9,
}
INIT_DH = 0.2
INIT_DS = -5.7
TERMINAL_AT_DH = 2.2
TERMINAL_AT_DS = 6.9


@dataclass(frozen=True)
class ScaffoldBase:
    """One scaffold nucleotide mapped onto a helix/bp/direction slot."""

    index: int
    helix_id: str
    bp: int
    direction: Direction
    base: str


@dataclass
class ScaffoldPositionMap:
    """Bidirectional scaffold-position lookup for scoring and future routing."""

    scaffold_id: str
    sequence: str
    index_to_base: list[ScaffoldBase]
    slot_to_bases: dict[tuple[str, int, Direction], list[ScaffoldBase]]
    is_circular: bool = False

    @property
    def length(self) -> int:
        return len(self.index_to_base)


@dataclass
class BoundSegment:
    """A contiguous dsDNA segment of one staple domain."""

    helix_id: str
    direction: Direction
    start_bp: int
    end_bp: int
    staple_sequence: str
    scaffold_sequence: str
    scaffold_positions: list[int]

    @property
    def length(self) -> int:
        return len(self.staple_sequence)

    @property
    def mean_scaffold_position(self) -> float:
        return float(np.mean(self.scaffold_positions)) if self.scaffold_positions else 0.0


@dataclass
class StapleScore:
    strand_id: str
    color: str | None
    length_nt: int
    bound_nt: int
    unpaired_nt: int
    unresolved_nt: int
    segment_count: int
    segments: list[BoundSegment]
    dG_total: float | None
    dG_hyb: float | None
    dG_loop: float | None
    dG_bind: float | None
    dH_total: float | None
    dS_total: float | None
    prob_fold: float | None
    log_prob_fold: float | None
    Tfold_c: float | None
    max_Tm_c: float | None
    violations: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strand_id": self.strand_id,
            "color": self.color,
            "length_nt": self.length_nt,
            "bound_nt": self.bound_nt,
            "unpaired_nt": self.unpaired_nt,
            "unresolved_nt": self.unresolved_nt,
            "segment_count": self.segment_count,
            "segments": [
                {
                    "helix_id": seg.helix_id,
                    "direction": seg.direction.value,
                    "start_bp": seg.start_bp,
                    "end_bp": seg.end_bp,
                    "length": seg.length,
                    "staple_sequence": seg.staple_sequence,
                    "scaffold_sequence": seg.scaffold_sequence,
                    "scaffold_positions": seg.scaffold_positions,
                    "mean_scaffold_position": seg.mean_scaffold_position,
                }
                for seg in self.segments
            ],
            "dG_total": self.dG_total,
            "dG_hyb": self.dG_hyb,
            "dG_loop": self.dG_loop,
            "dG_bind": self.dG_bind,
            "dH_total": self.dH_total,
            "dS_total": self.dS_total,
            "prob_fold": self.prob_fold,
            "log_prob_fold": self.log_prob_fold,
            "Tfold_c": self.Tfold_c,
            "max_Tm_c": self.max_Tm_c,
            "violations": self.violations,
            "warnings": self.warnings,
        }


@dataclass(frozen=True)
class RouteNucleotide:
    """One nucleotide position along a staple precursor, ordered 5' to 3'."""

    offset: int
    helix_id: str
    bp: int
    direction: Direction
    scaffold_base: str | None
    scaffold_index: int | None
    unpaired: bool = False
    unresolved: bool = False


@dataclass(frozen=True)
class BreakpointNode:
    """A phosphate-break position between staple nucleotides."""

    offset: int
    kind: str  # terminus | crossover | internal
    left_helix_id: str | None = None
    left_bp: int | None = None
    left_direction: Direction | None = None
    right_helix_id: str | None = None
    right_bp: int | None = None
    right_direction: Direction | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "offset": self.offset,
            "kind": self.kind,
            "left": None if self.left_helix_id is None else {
                "helix_id": self.left_helix_id,
                "bp": self.left_bp,
                "direction": self.left_direction.value if self.left_direction else None,
            },
            "right": None if self.right_helix_id is None else {
                "helix_id": self.right_helix_id,
                "bp": self.right_bp,
                "direction": self.right_direction.value if self.right_direction else None,
            },
        }


@dataclass(frozen=True)
class BreakRuleConfig:
    """pyOrigamiBreak-style candidate breakpoint rule."""

    rule: str = DEFAULT_BREAK_RULE
    min_segment_nt: int = DEFAULT_MIN_SEGMENT_NT
    allow_crossover_breaks: bool = False

    @classmethod
    def from_rule(
        cls,
        rule: str = DEFAULT_BREAK_RULE,
        *,
        allow_crossover_breaks: bool = False,
        min_segment_nt: int | None = None,
    ) -> "BreakRuleConfig":
        parts = {part.strip().lower() for part in rule.split(".") if part.strip()}
        if "all2" in parts:
            inferred_min_segment_nt = 2
        elif "all3" in parts:
            inferred_min_segment_nt = 3
        else:
            inferred_min_segment_nt = DEFAULT_MIN_SEGMENT_NT
        if min_segment_nt is not None:
            min_segment_nt = max(min_segment_nt, DEFAULT_MIN_SEGMENT_NT)
        else:
            min_segment_nt = inferred_min_segment_nt
        return cls(
            rule=".".join(sorted(parts)) if parts else DEFAULT_BREAK_RULE,
            min_segment_nt=min_segment_nt,
            allow_crossover_breaks=allow_crossover_breaks,
        )


@dataclass
class CandidateRouteEdge:
    """Candidate staple route produced by cutting two breakpoint nodes."""

    start: int
    end: int
    score: StapleScore

    @property
    def length_nt(self) -> int:
        return self.end - self.start

    @property
    def edge_weight(self) -> float:
        # Aksel/pyOrigamiBreak maximize log probability.  Lower-cost shortest
        # path code uses the negative log probability.
        if self.score.log_prob_fold is None or not math.isfinite(self.score.log_prob_fold):
            return math.inf
        return -self.score.log_prob_fold

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "length_nt": self.length_nt,
            "edge_weight": self.edge_weight,
            "score": self.score.to_dict(),
        }


@dataclass
class PrecursorGraph:
    """Read-only weighted breakpoint graph for one staple precursor."""

    strand_id: str
    nucleotide_count: int
    nodes: list[BreakpointNode]
    edges_by_start: dict[int, list[CandidateRouteEdge]]
    break_rule: BreakRuleConfig = field(default_factory=BreakRuleConfig)

    @property
    def edge_count(self) -> int:
        return sum(len(edges) for edges in self.edges_by_start.values())

    def to_dict(self, include_edges: bool = False) -> dict[str, Any]:
        payload = {
            "strand_id": self.strand_id,
            "nucleotide_count": self.nucleotide_count,
            "node_count": len(self.nodes),
            "edge_count": self.edge_count,
            "break_rule": self.break_rule.rule,
            "min_segment_nt": self.break_rule.min_segment_nt,
            "allow_crossover_breaks": self.break_rule.allow_crossover_breaks,
            "nodes": [node.to_dict() for node in self.nodes],
        }
        if include_edges:
            payload["edges_by_start"] = {
                str(start): [edge.to_dict() for edge in edges]
                for start, edges in self.edges_by_start.items()
            }
        return payload


@dataclass
class PrecursorPath:
    """One complete breakpoint route through a precursor graph."""

    strand_id: str
    edges: list[CandidateRouteEdge]
    total_weight: float
    total_log_prob: float
    total_bound_nt: int
    violations: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "strand_id": self.strand_id,
            "breaks": [edge.start for edge in self.edges] + (
                [self.edges[-1].end] if self.edges else []
            ),
            "edge_count": len(self.edges),
            "total_weight": self.total_weight,
            "total_log_prob": self.total_log_prob,
            "total_bound_nt": self.total_bound_nt,
            "violations": self.violations,
            "edges": [edge.to_dict() for edge in self.edges],
        }


def _active_scaffold(design: Design) -> Strand | None:
    for strand in design.scaffolds():
        if not strand.is_reference:
            return strand
    return None


def _loop_skip_map(design: Design) -> dict[tuple[str, int], int]:
    result: dict[tuple[str, int], int] = {}
    for helix in design.helices:
        for loop_skip in helix.loop_skips:
            result[(helix.id, loop_skip.bp_index)] = loop_skip.delta
    return result


def _is_periodic_scaffold(design: Design) -> bool:
    return any(ligation.is_periodic_seam for ligation in design.forced_ligations)


def build_scaffold_position_map(design: Design) -> ScaffoldPositionMap:
    """Map scaffold sequence indices to helix/bp/direction slots and back.

    Raises ValueError when the active scaffold is missing or unsequenced.  Loop
    insertions create multiple scaffold bases at the same slot; skips omit the
    slot.  Extra sequence bases beyond scaffold topology are ignored for the map.
    """

    scaffold = _active_scaffold(design)
    if scaffold is None:
        raise ValueError("No active scaffold strand found.")
    if scaffold.sequence is None:
        raise ValueError("Scaffold has no sequence; assign a scaffold sequence first.")

    ls_map = _loop_skip_map(design)
    index_to_base: list[ScaffoldBase] = []
    slot_to_bases: dict[tuple[str, int, Direction], list[ScaffoldBase]] = {}
    seq_idx = 0

    for domain in scaffold.domains:
        for bp in domain_bp_range(domain):
            delta = ls_map.get((domain.helix_id, bp), 0)
            if delta <= -1:
                continue
            for _ in range(delta + 1):
                if seq_idx >= len(scaffold.sequence):
                    base = "N"
                else:
                    base = scaffold.sequence[seq_idx].upper()
                entry = ScaffoldBase(
                    index=seq_idx,
                    helix_id=domain.helix_id,
                    bp=bp,
                    direction=domain.direction,
                    base=base if base in "ACGTN" else "N",
                )
                index_to_base.append(entry)
                slot_to_bases.setdefault(
                    (domain.helix_id, bp, domain.direction), []
                ).append(entry)
                seq_idx += 1

    return ScaffoldPositionMap(
        scaffold_id=scaffold.id,
        sequence=scaffold.sequence,
        index_to_base=index_to_base,
        slot_to_bases=slot_to_bases,
        is_circular=_is_periodic_scaffold(design),
    )


def _terminal_at_count(seq: str) -> int:
    if not seq:
        return 0
    return int(seq[0] in "AT") + int(len(seq) > 1 and seq[-1] in "AT")


def _hyb_thermo(seq: str, temperature_k: float) -> tuple[float, float, float]:
    """Return dG, dH, dS for duplex hybridization of a scaffold-bound segment."""

    s = seq.upper()
    dH = INIT_DH + _terminal_at_count(s) * TERMINAL_AT_DH
    dS_cal = INIT_DS + _terminal_at_count(s) * TERMINAL_AT_DS
    for i in range(len(s) - 1):
        pair = s[i:i + 2]
        dH += NN_DH.get(pair, -7.0)
        dS_cal += NN_DS.get(pair, -20.0)

    # Dunn 2015 salt correction used by pyOrigamiBreak.
    if len(s) > 1:
        dS_cal += 0.368 * (len(s) - 1) * math.log(
            0.5 * DEFAULT_TRIS_CONC + 3.3 * math.sqrt(DEFAULT_MG_CONC)
        )

    dS = dS_cal / 1000.0
    dG = dH - temperature_k * dS
    return dG, dH, dS


def _tm_mg(seq: str) -> float | None:
    """Approximate Mg-corrected Tm in Celsius following pyOrigamiBreak."""

    s = seq.upper()
    if len(s) == 0:
        return None
    dH = INIT_DH + _terminal_at_count(s) * TERMINAL_AT_DH
    dS_cal = INIT_DS + _terminal_at_count(s) * TERMINAL_AT_DS
    for i in range(len(s) - 1):
        pair = s[i:i + 2]
        dH += NN_DH.get(pair, -7.0)
        dS_cal += NN_DS.get(pair, -20.0)
    ct = DEFAULT_STAP_CONC - 0.5 * DEFAULT_SCAF_CONC
    if ct <= 0:
        return None
    denom = dS_cal + (R_KCAL * 1000.0) * math.log(ct)
    if abs(denom) < 1e-15:
        return None
    tm_1m_c = dH * 1000.0 / denom - 273.15
    if len(s) <= 1:
        return tm_1m_c

    f_gc = sum(base in "GC" for base in s) / len(s)
    ln_mg = math.log(DEFAULT_MG_CONC)
    a = 3.92e-5
    b = -9.11e-6
    c = 6.26e-5
    d = 1.42e-5
    e = -4.82e-4
    f = 5.25e-4
    g = 8.31e-5
    tm_1m_k = tm_1m_c + 273.15
    if tm_1m_k <= 0:
        return None
    tm_mg_inv = (
        1.0 / tm_1m_k
        + a
        + b * ln_mg
        + f_gc * (c + d * ln_mg)
        + 1.0 / (2 * (len(s) - 1)) * (e + f * ln_mg + g * ln_mg**2)
    )
    if abs(tm_mg_inv) < 1e-15:
        return None
    return 1.0 / tm_mg_inv - 273.15


def _end_to_end_distance_sq(num_bases: int) -> float:
    n = max(1, int(num_bases))
    contour = n * 0.6
    persistence = 0.9
    return 2 * persistence * contour * (
        1 - persistence / contour * (1 - math.exp(-contour / persistence))
    )


def _loop_thermo(
    scaffold_length: int,
    start_index: float,
    end_index: float,
    is_circular: bool,
    temperature_k: float,
) -> tuple[float, float]:
    raw = abs(end_index - start_index)
    if is_circular and scaffold_length > 0:
        forward = (end_index - start_index) % scaffold_length
        reverse = scaffold_length - forward
        raw = min(forward, reverse)
    base_distance = max(1, int(round(raw)))
    distance_sq = _end_to_end_distance_sq(base_distance)
    effective_conc = (
        1.0 / 6.02e23
        * (3.0 / (2 * math.pi * distance_sq * 1.0e-18)) ** 1.5
        / 1000.0
    )
    dS_loop = R_KCAL * math.log(effective_conc)
    dG_loop = -temperature_k * dS_loop
    return dG_loop, dS_loop


def _bind_thermo(temperature_k: float, staple_conc: float, scaffold_conc: float) -> tuple[float, float]:
    effective = staple_conc - 0.5 * scaffold_conc
    if effective <= 0:
        return math.inf, -math.inf
    dS_bind = R_KCAL * math.log(effective)
    dG_bind = -temperature_k * dS_bind
    return dG_bind, dS_bind


def _opposite_direction(direction: Direction) -> Direction:
    return Direction.REVERSE if direction == Direction.FORWARD else Direction.FORWARD


def _count_domain_nt(domain, ls_map: dict[tuple[str, int], int]) -> int:
    total = 0
    for bp in domain_bp_range(domain):
        delta = ls_map.get((domain.helix_id, bp), 0)
        if delta <= -1:
            continue
        total += delta + 1
    return total


def _segment_staple_sequence(scaffold_bases: list[str]) -> str:
    return "".join(complement_base(base) for base in scaffold_bases)


def _segments_from_route_nucleotides(nucleotides: list[RouteNucleotide]) -> list[BoundSegment]:
    segments: list[BoundSegment] = []
    cur_helix: str | None = None
    cur_direction: Direction | None = None
    cur_bps: list[int] = []
    cur_scaffold_bases: list[str] = []
    cur_scaffold_positions: list[int] = []

    def flush() -> None:
        nonlocal cur_helix, cur_direction, cur_bps, cur_scaffold_bases, cur_scaffold_positions
        if cur_helix is not None and cur_direction is not None and cur_bps:
            segments.append(
                BoundSegment(
                    helix_id=cur_helix,
                    direction=cur_direction,
                    start_bp=cur_bps[0],
                    end_bp=cur_bps[-1],
                    staple_sequence=_segment_staple_sequence(cur_scaffold_bases),
                    scaffold_sequence="".join(cur_scaffold_bases),
                    scaffold_positions=list(cur_scaffold_positions),
                )
            )
        cur_helix = None
        cur_direction = None
        cur_bps = []
        cur_scaffold_bases = []
        cur_scaffold_positions = []

    for nucleotide in nucleotides:
        if nucleotide.unpaired or nucleotide.unresolved:
            flush()
            continue
        if nucleotide.scaffold_base is None or nucleotide.scaffold_index is None:
            flush()
            continue
        if (
            cur_helix != nucleotide.helix_id
            or cur_direction != nucleotide.direction
            or (
                cur_bps
                and nucleotide.bp != cur_bps[-1]
                and abs(nucleotide.bp - cur_bps[-1]) != 1
            )
        ):
            flush()
            cur_helix = nucleotide.helix_id
            cur_direction = nucleotide.direction
        cur_bps.append(nucleotide.bp)
        cur_scaffold_bases.append(nucleotide.scaffold_base)
        cur_scaffold_positions.append(nucleotide.scaffold_index)

    flush()
    return segments


def _score_segments(
    strand_id: str,
    color: str | None,
    length_nt: int,
    segments: list[BoundSegment],
    scaf_map: ScaffoldPositionMap,
    unpaired_nt: int,
    unresolved_nt: int,
    temperature_k: float,
    staple_conc: float,
    scaffold_conc: float,
    min_staple_nt: int,
    max_staple_nt: int,
    warnings: list[str] | None = None,
) -> StapleScore:
    warnings = list(warnings or [])
    bound_nt = sum(seg.length for seg in segments)
    violations: list[str] = []
    if length_nt < min_staple_nt:
        violations.append("length_below_min")
    if length_nt > max_staple_nt:
        violations.append("length_above_max")
    if unresolved_nt:
        violations.append("unresolved_scaffold_bases")
    if unpaired_nt:
        violations.append("unpaired_bases")

    if not segments:
        warnings.append("No scaffold-bound dsDNA segment resolved for this staple.")
        return StapleScore(
            strand_id=strand_id,
            color=color,
            length_nt=length_nt,
            bound_nt=0,
            unpaired_nt=unpaired_nt,
            unresolved_nt=unresolved_nt,
            segment_count=0,
            segments=[],
            dG_total=None,
            dG_hyb=None,
            dG_loop=None,
            dG_bind=None,
            dH_total=None,
            dS_total=None,
            prob_fold=None,
            log_prob_fold=None,
            Tfold_c=None,
            max_Tm_c=None,
            violations=violations,
            warnings=warnings,
        )

    dG_hyb = 0.0
    dH_total = 0.0
    dS_total = 0.0
    tm_values: list[float] = []
    for seg in segments:
        if "N" in seg.scaffold_sequence:
            warnings.append(
                f"Segment {seg.helix_id}:{seg.start_bp}->{seg.end_bp} contains N bases."
            )
        dG, dH, dS = _hyb_thermo(seg.scaffold_sequence, temperature_k)
        dG_hyb += dG
        dH_total += dH
        dS_total += dS
        tm = _tm_mg(seg.scaffold_sequence)
        if tm is not None and math.isfinite(tm):
            tm_values.append(tm)

    dG_loop = 0.0
    for left, right in zip(segments, segments[1:]):
        dG, dS = _loop_thermo(
            scaf_map.length,
            left.mean_scaffold_position,
            right.mean_scaffold_position,
            scaf_map.is_circular,
            temperature_k,
        )
        dG_loop += dG
        dS_total += dS

    dG_bind, dS_bind = _bind_thermo(temperature_k, staple_conc, scaffold_conc)
    dS_total += dS_bind
    dG_total = dG_hyb + dG_loop + dG_bind
    exponent = -dG_total / (R_KCAL * temperature_k)
    if exponent >= 0:
        log_prob_fold = -math.log1p(math.exp(-exponent))
    else:
        log_prob_fold = exponent - math.log1p(math.exp(exponent))
    prob_fold = math.exp(log_prob_fold) if log_prob_fold > -745 else 0.0
    Tfold_c = dH_total / dS_total - 273.15 if abs(dS_total) > 1e-15 else None

    return StapleScore(
        strand_id=strand_id,
        color=color,
        length_nt=length_nt,
        bound_nt=bound_nt,
        unpaired_nt=unpaired_nt,
        unresolved_nt=unresolved_nt,
        segment_count=len(segments),
        segments=segments,
        dG_total=dG_total,
        dG_hyb=dG_hyb,
        dG_loop=dG_loop,
        dG_bind=dG_bind,
        dH_total=dH_total,
        dS_total=dS_total,
        prob_fold=prob_fold,
        log_prob_fold=log_prob_fold,
        Tfold_c=Tfold_c,
        max_Tm_c=max(tm_values) if tm_values else None,
        violations=violations,
        warnings=warnings,
    )


def _extract_bound_segments(
    strand: Strand,
    scaf_map: ScaffoldPositionMap,
    ls_map: dict[tuple[str, int], int],
) -> tuple[list[BoundSegment], int, int, int, list[str]]:
    segments: list[BoundSegment] = []
    unresolved_nt = 0
    unpaired_nt = 0
    total_nt = 0
    warnings: list[str] = []

    cur_helix: str | None = None
    cur_direction: Direction | None = None
    cur_bps: list[int] = []
    cur_scaffold_bases: list[str] = []
    cur_scaffold_positions: list[int] = []

    def flush() -> None:
        nonlocal cur_helix, cur_direction, cur_bps, cur_scaffold_bases, cur_scaffold_positions
        if cur_helix is None or cur_direction is None or not cur_bps:
            cur_helix = None
            cur_direction = None
            cur_bps = []
            cur_scaffold_bases = []
            cur_scaffold_positions = []
            return
        segments.append(
            BoundSegment(
                helix_id=cur_helix,
                direction=cur_direction,
                start_bp=cur_bps[0],
                end_bp=cur_bps[-1],
                staple_sequence=_segment_staple_sequence(cur_scaffold_bases),
                scaffold_sequence="".join(cur_scaffold_bases),
                scaffold_positions=list(cur_scaffold_positions),
            )
        )
        cur_helix = None
        cur_direction = None
        cur_bps = []
        cur_scaffold_bases = []
        cur_scaffold_positions = []

    for domain in strand.domains:
        domain_nt = _count_domain_nt(domain, ls_map)
        total_nt += domain_nt
        if domain.overhang_id is not None or domain.binds_overhang_id is not None:
            flush()
            unpaired_nt += domain_nt
            continue

        paired_direction = _opposite_direction(domain.direction)
        for bp in domain_bp_range(domain):
            delta = ls_map.get((domain.helix_id, bp), 0)
            if delta <= -1:
                continue
            expected_copies = delta + 1
            entries = scaf_map.slot_to_bases.get((domain.helix_id, bp, paired_direction))
            if not entries:
                flush()
                unresolved_nt += expected_copies
                continue

            if (
                cur_helix != domain.helix_id
                or cur_direction != domain.direction
                or (
                    cur_bps
                    and bp != cur_bps[-1]
                    and abs(bp - cur_bps[-1]) != 1
                )
            ):
                flush()
                cur_helix = domain.helix_id
                cur_direction = domain.direction
            for entry in entries[:expected_copies]:
                cur_bps.append(bp)
                cur_scaffold_bases.append(entry.base)
                cur_scaffold_positions.append(entry.index)
            if len(entries) < expected_copies:
                unresolved_nt += expected_copies - len(entries)
                warnings.append(
                    f"Loop copy mismatch at {domain.helix_id}:{bp}; "
                    f"expected {expected_copies}, found {len(entries)} scaffold base(s)."
                )

    flush()
    return segments, total_nt, unpaired_nt, unresolved_nt, warnings


def score_staple(
    strand: Strand,
    scaf_map: ScaffoldPositionMap,
    ls_map: dict[tuple[str, int], int],
    temperature_k: float = DEFAULT_TEMPERATURE_K,
    staple_conc: float = DEFAULT_STAP_CONC,
    scaffold_conc: float = DEFAULT_SCAF_CONC,
    min_staple_nt: int = 21,
    max_staple_nt: int = 60,
) -> StapleScore:
    segments, length_nt, unpaired_nt, unresolved_nt, warnings = _extract_bound_segments(
        strand, scaf_map, ls_map
    )
    return _score_segments(
        strand_id=strand.id,
        color=strand.color,
        length_nt=length_nt,
        segments=segments,
        scaf_map=scaf_map,
        unpaired_nt=unpaired_nt,
        unresolved_nt=unresolved_nt,
        temperature_k=temperature_k,
        staple_conc=staple_conc,
        scaffold_conc=scaffold_conc,
        min_staple_nt=min_staple_nt,
        max_staple_nt=max_staple_nt,
        warnings=warnings,
    )


def _strand_route_nucleotides(
    strand: Strand,
    scaf_map: ScaffoldPositionMap,
    ls_map: dict[tuple[str, int], int],
) -> list[RouteNucleotide]:
    route: list[RouteNucleotide] = []
    offset = 0

    for domain in strand.domains:
        domain_unpaired = domain.overhang_id is not None or domain.binds_overhang_id is not None
        paired_direction = _opposite_direction(domain.direction)
        for bp in domain_bp_range(domain):
            delta = ls_map.get((domain.helix_id, bp), 0)
            if delta <= -1:
                continue
            expected_copies = delta + 1
            if domain_unpaired:
                for _ in range(expected_copies):
                    route.append(
                        RouteNucleotide(
                            offset=offset,
                            helix_id=domain.helix_id,
                            bp=bp,
                            direction=domain.direction,
                            scaffold_base=None,
                            scaffold_index=None,
                            unpaired=True,
                        )
                    )
                    offset += 1
                continue

            entries = scaf_map.slot_to_bases.get((domain.helix_id, bp, paired_direction), [])
            for entry in entries[:expected_copies]:
                route.append(
                    RouteNucleotide(
                        offset=offset,
                        helix_id=domain.helix_id,
                        bp=bp,
                        direction=domain.direction,
                        scaffold_base=entry.base,
                        scaffold_index=entry.index,
                    )
                )
                offset += 1
            for _ in range(max(0, expected_copies - len(entries))):
                route.append(
                    RouteNucleotide(
                        offset=offset,
                        helix_id=domain.helix_id,
                        bp=bp,
                        direction=domain.direction,
                        scaffold_base=None,
                        scaffold_index=None,
                        unresolved=True,
                    )
                )
                offset += 1

    return route


def _breakpoint_nodes(route: list[RouteNucleotide]) -> list[BreakpointNode]:
    nodes: list[BreakpointNode] = []
    n = len(route)
    for offset in range(n + 1):
        left = route[offset - 1] if offset > 0 else None
        right = route[offset] if offset < n else None
        if left is None or right is None:
            kind = "terminus"
        elif left.helix_id != right.helix_id or left.direction != right.direction:
            kind = "crossover"
        else:
            kind = "internal"
        nodes.append(
            BreakpointNode(
                offset=offset,
                kind=kind,
                left_helix_id=left.helix_id if left else None,
                left_bp=left.bp if left else None,
                left_direction=left.direction if left else None,
                right_helix_id=right.helix_id if right else None,
                right_bp=right.bp if right else None,
                right_direction=right.direction if right else None,
            )
        )
    return nodes


def _candidate_break_offsets(
    nodes: list[BreakpointNode],
    rule: BreakRuleConfig,
) -> set[int]:
    """Return breakpoint offsets allowed by pyOrigamiBreak-like break rules.

    ``all3`` means an internal nick must leave at least three nucleotides to
    each neighboring terminus/crossover boundary.  Exact crossover nicks are
    kept disabled by default in NADOC because they currently require a distinct
    topology operation from ordinary strand nicks.
    """
    if not nodes:
        return set()
    n = nodes[-1].offset
    boundary_offsets = [
        node.offset
        for node in nodes
        if node.kind in ("terminus", "crossover")
    ]
    boundary_offsets = sorted(set(boundary_offsets))
    allowed = {0, n}
    boundary_index = 0
    for node in nodes[1:-1]:
        while (
            boundary_index + 1 < len(boundary_offsets)
            and boundary_offsets[boundary_index + 1] < node.offset
        ):
            boundary_index += 1
        prev_boundary = boundary_offsets[boundary_index]
        next_boundary = next(
            (offset for offset in boundary_offsets[boundary_index + 1:] if offset >= node.offset),
            n,
        )
        if node.kind == "crossover":
            if rule.allow_crossover_breaks:
                allowed.add(node.offset)
            continue
        left_len = node.offset - prev_boundary
        right_len = next_boundary - node.offset
        if left_len >= rule.min_segment_nt and right_len >= rule.min_segment_nt:
            allowed.add(node.offset)
    return allowed


def _score_route_slice(
    strand: Strand,
    route: list[RouteNucleotide],
    start: int,
    end: int,
    scaf_map: ScaffoldPositionMap,
    temperature_k: float,
    staple_conc: float,
    scaffold_conc: float,
    min_staple_nt: int,
    max_staple_nt: int,
) -> StapleScore:
    nts = route[start:end]
    segments = _segments_from_route_nucleotides(nts)
    unpaired_nt = sum(1 for nt in nts if nt.unpaired)
    unresolved_nt = sum(1 for nt in nts if nt.unresolved)
    return _score_segments(
        strand_id=strand.id,
        color=strand.color,
        length_nt=end - start,
        segments=segments,
        scaf_map=scaf_map,
        unpaired_nt=unpaired_nt,
        unresolved_nt=unresolved_nt,
        temperature_k=temperature_k,
        staple_conc=staple_conc,
        scaffold_conc=scaffold_conc,
        min_staple_nt=min_staple_nt,
        max_staple_nt=max_staple_nt,
    )


def interior_scaffold_crossover_positions(
    design: Design, min_segment_nt: int
) -> dict[str, list[int]]:
    """Per-helix bp positions of *interior* scaffold crossovers (not at a cap).

    A scaffold crossover is "interior" when its bp sits more than
    ``min_segment_nt`` inside the scaffold's coverage on that helix — i.e. it is
    a seam/mid-helix junction, not a near/far-end cap crossover (which sit at the
    coverage extremes).  Staple breaks must keep ``min_segment_nt`` clearance
    from these so a nick never lands on top of a scaffold seam crossover.
    """
    cov: dict[str, tuple[int, int]] = {}
    for s in design.strands:
        if not s.is_scaffold or s.is_reference:
            continue
        for dom in s.domains:
            lo = min(dom.start_bp, dom.end_bp)
            hi = max(dom.start_bp, dom.end_bp)
            cur = cov.get(dom.helix_id)
            cov[dom.helix_id] = (min(cur[0], lo), max(cur[1], hi)) if cur else (lo, hi)

    helix_map = {h.id: h for h in design.helices if h.grid_pos is not None}

    def _scaf_dir(hid: str) -> Direction | None:
        h = helix_map.get(hid)
        if h is None:
            return None
        row, col = h.grid_pos
        return Direction.FORWARD if (row + col) % 2 == 0 else Direction.REVERSE

    out: dict[str, set[int]] = {}
    for xo in design.crossovers:
        for half in (xo.half_a, xo.half_b):
            if half.strand != _scaf_dir(half.helix_id):
                continue  # not the scaffold-strand half → not a scaffold crossover
            span = cov.get(half.helix_id)
            if span is None:
                continue
            lo, hi = span
            if lo + min_segment_nt < half.index < hi - min_segment_nt:
                out.setdefault(half.helix_id, set()).add(half.index)
    return {hid: sorted(v) for hid, v in out.items()}


def build_precursor_graph(
    strand: Strand,
    scaf_map: ScaffoldPositionMap,
    ls_map: dict[tuple[str, int], int],
    temperature_k: float = DEFAULT_TEMPERATURE_K,
    staple_conc: float = DEFAULT_STAP_CONC,
    scaffold_conc: float = DEFAULT_SCAF_CONC,
    min_staple_nt: int = 21,
    max_staple_nt: int = 60,
    break_rule: str = DEFAULT_BREAK_RULE,
    allow_crossover_breaks: bool = False,
    min_segment_nt: int | None = None,
    scaffold_block: dict[str, list[int]] | None = None,
) -> PrecursorGraph:
    """Build a weighted candidate-break graph for one staple precursor.

    ``scaffold_block`` maps helix_id → interior scaffold-crossover bp positions;
    internal break offsets within ``rule.min_segment_nt`` of one are dropped so a
    staple nick never lands too close to a scaffold seam crossover.
    """

    route = _strand_route_nucleotides(strand, scaf_map, ls_map)
    nodes = _breakpoint_nodes(route)
    rule = BreakRuleConfig.from_rule(
        break_rule,
        allow_crossover_breaks=allow_crossover_breaks,
        min_segment_nt=min_segment_nt,
    )
    allowed_offsets = _candidate_break_offsets(nodes, rule)
    if scaffold_block:
        n_route = len(route)
        kept: set[int] = set()
        for off in allowed_offsets:
            if off == 0 or off == n_route:
                kept.add(off)  # precursor termini are fixed, not breaker choices
                continue
            nt = route[off - 1]
            if any(
                abs(nt.bp - sx) < rule.min_segment_nt
                for sx in scaffold_block.get(nt.helix_id, ())
            ):
                continue  # too close to an interior scaffold crossover
            kept.add(off)
        allowed_offsets = kept
    edges_by_start: dict[int, list[CandidateRouteEdge]] = {}
    n = len(route)

    for start in sorted(allowed_offsets):
        if start not in (0, n) and nodes[start].kind == "crossover" and not allow_crossover_breaks:
            continue
        max_end = min(n, start + max_staple_nt)
        for end in sorted(offset for offset in allowed_offsets if start + min_staple_nt <= offset <= max_end):
            if end <= start:
                continue
            if end not in (0, n) and nodes[end].kind == "crossover" and not allow_crossover_breaks:
                continue
            score = _score_route_slice(
                strand,
                route,
                start,
                end,
                scaf_map,
                temperature_k,
                staple_conc,
                scaffold_conc,
                min_staple_nt,
                max_staple_nt,
            )
            if score.dG_total is None:
                continue
            if any(segment.length < rule.min_segment_nt for segment in score.segments):
                continue
            edges_by_start.setdefault(start, []).append(
                CandidateRouteEdge(start=start, end=end, score=score)
            )

    return PrecursorGraph(
        strand_id=strand.id,
        nucleotide_count=n,
        nodes=nodes,
        edges_by_start=edges_by_start,
        break_rule=rule,
    )


def _top_k_paths(graph: PrecursorGraph, k: int = 10) -> list[PrecursorPath]:
    """Return up to k lowest-weight complete paths through a DAG precursor graph."""

    n = graph.nucleotide_count
    suffix: list[list[tuple[float, list[CandidateRouteEdge]]]] = [[] for _ in range(n + 1)]
    suffix[n] = [(0.0, [])]
    for start in range(n - 1, -1, -1):
        candidates: list[tuple[float, list[CandidateRouteEdge]]] = []
        for edge in graph.edges_by_start.get(start, []):
            if not math.isfinite(edge.edge_weight):
                continue
            for rest_weight, rest_edges in suffix[edge.end]:
                candidates.append((edge.edge_weight + rest_weight, [edge] + rest_edges))
        candidates.sort(key=lambda item: item[0])
        suffix[start] = candidates[:k]

    paths: list[PrecursorPath] = []
    for total_weight, edges in suffix[0][:k]:
        total_log_prob = sum(
            edge.score.log_prob_fold or 0.0
            for edge in edges
            if edge.score.log_prob_fold is not None
        )
        total_bound_nt = sum(edge.score.bound_nt for edge in edges)
        violations: list[str] = []
        for edge in edges:
            violations.extend(edge.score.violations)
        paths.append(
            PrecursorPath(
                strand_id=graph.strand_id,
                edges=edges,
                total_weight=total_weight,
                total_log_prob=total_log_prob,
                total_bound_nt=total_bound_nt,
                violations=sorted(set(violations)),
            )
        )
    return paths


def _path_crossover_break_signatures(
    graph: PrecursorGraph,
    path: PrecursorPath,
) -> list[tuple[tuple[str, int, str], tuple[str, int, str]]]:
    signatures = []
    for offset in path.to_dict()["breaks"][1:-1]:
        node = graph.nodes[offset]
        if node.kind != "crossover":
            continue
        if (
            node.left_helix_id is None
            or node.left_bp is None
            or node.left_direction is None
            or node.right_helix_id is None
            or node.right_bp is None
            or node.right_direction is None
        ):
            continue
        a = (node.left_helix_id, node.left_bp, node.left_direction.value)
        b = (node.right_helix_id, node.right_bp, node.right_direction.value)
        signatures.append(tuple(sorted((a, b))))
    return signatures


def _crossover_penalty(
    graphs_by_strand: dict[str, PrecursorGraph],
    paths_by_strand: dict[str, PrecursorPath],
) -> int:
    counts: dict[tuple[tuple[str, int, str], tuple[str, int, str]], int] = {}
    for strand_id, path in paths_by_strand.items():
        graph = graphs_by_strand[strand_id]
        for signature in _path_crossover_break_signatures(graph, path):
            counts[signature] = counts.get(signature, 0) + 1
    return sum(max(0, count - 1) for count in counts.values())


def _select_precursor_paths(
    graphs_by_strand: dict[str, PrecursorGraph],
    paths_by_strand: dict[str, list[PrecursorPath]],
    path_index: int,
) -> tuple[dict[str, PrecursorPath], int]:
    """Select one path per precursor, minimizing crossover-neighbor penalties.

    pyOrigamiBreak assembles k local paths into grouped solutions and sorts by
    crossover penalty.  This lightweight equivalent keeps deterministic behavior
    by ranking candidate choices by total penalty, then total thermodynamic
    weight, then by requested path index.
    """
    selected: dict[str, PrecursorPath] = {}
    for strand_id, paths in paths_by_strand.items():
        if not paths:
            continue
        selected[strand_id] = paths[min(path_index, len(paths) - 1)]

    penalty = _crossover_penalty(graphs_by_strand, selected)
    if penalty == 0:
        return selected, penalty

    improved = True
    while improved:
        improved = False
        for strand_id, paths in paths_by_strand.items():
            if not paths:
                continue
            current = selected[strand_id]
            best_path = current
            best_rank = (
                _crossover_penalty(graphs_by_strand, selected),
                sum(path.total_weight for path in selected.values()),
            )
            for candidate in paths:
                selected[strand_id] = candidate
                rank = (
                    _crossover_penalty(graphs_by_strand, selected),
                    sum(path.total_weight for path in selected.values()),
                )
                if rank < best_rank:
                    best_rank = rank
                    best_path = candidate
            selected[strand_id] = best_path
            if best_path is not current:
                improved = True
    return selected, _crossover_penalty(graphs_by_strand, selected)


def build_precursor_graphs(
    design: Design,
    temperature_c: float = 50.0,
    staple_conc: float = DEFAULT_STAP_CONC,
    scaffold_conc: float = DEFAULT_SCAF_CONC,
    min_staple_nt: int = 21,
    max_staple_nt: int = 60,
    k_paths: int = 10,
    include_edges: bool = False,
    break_rule: str = DEFAULT_BREAK_RULE,
    allow_crossover_breaks: bool = False,
    min_segment_nt: int | None = None,
) -> dict[str, Any]:
    """Build read-only weighted precursor graphs and first k shortest paths."""

    temperature_k = temperature_c + 273.15
    scaf_map = build_scaffold_position_map(design)
    ls_map = _loop_skip_map(design)
    effective_min_segment_nt = (
        lattice_min_segment_nt(design.lattice_type)
        if min_segment_nt is None
        else min_segment_nt
    )
    scaffold_block = interior_scaffold_crossover_positions(design, effective_min_segment_nt)
    graphs: list[PrecursorGraph] = []
    paths_by_strand: dict[str, list[PrecursorPath]] = {}

    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE or strand.is_reference:
            continue
        graph = build_precursor_graph(
            strand,
            scaf_map,
            ls_map,
            temperature_k=temperature_k,
            staple_conc=staple_conc,
            scaffold_conc=scaffold_conc,
            min_staple_nt=min_staple_nt,
            max_staple_nt=max_staple_nt,
            break_rule=break_rule,
            allow_crossover_breaks=allow_crossover_breaks,
            min_segment_nt=effective_min_segment_nt,
            scaffold_block=scaffold_block,
        )
        paths = _top_k_paths(graph, k=max(1, k_paths))
        if not paths and scaffold_block:
            # Soft seam-clearance (see apply_precursor_breaks): relax for any
            # precursor the clearance would otherwise leave unbreakable.
            graph = build_precursor_graph(
                strand, scaf_map, ls_map,
                temperature_k=temperature_k, staple_conc=staple_conc,
                scaffold_conc=scaffold_conc, min_staple_nt=min_staple_nt,
                max_staple_nt=max_staple_nt, break_rule=break_rule,
                allow_crossover_breaks=allow_crossover_breaks,
                min_segment_nt=effective_min_segment_nt, scaffold_block=None,
            )
            paths = _top_k_paths(graph, k=max(1, k_paths))
        graphs.append(graph)
        paths_by_strand[strand.id] = paths

    complete_count = sum(1 for paths in paths_by_strand.values() if paths)
    graphs_by_strand = {graph.strand_id: graph for graph in graphs}
    selected_paths, crossover_penalty = _select_precursor_paths(
        graphs_by_strand,
        paths_by_strand,
        path_index=0,
    )
    best_total_log_prob = sum(path.total_log_prob for path in selected_paths.values())
    best_total_bound_nt = sum(path.total_bound_nt for path in selected_paths.values())
    return {
        "temperature_c": temperature_c,
        "staple_conc_m": staple_conc,
        "scaffold_conc_m": scaffold_conc,
        "min_staple_nt": min_staple_nt,
        "max_staple_nt": max_staple_nt,
        "break_rule": break_rule,
        "allow_crossover_breaks": allow_crossover_breaks,
        "min_segment_nt": effective_min_segment_nt,
        "k_paths": k_paths,
        "scaffold": {
            "strand_id": scaf_map.scaffold_id,
            "length_nt": scaf_map.length,
            "is_circular": scaf_map.is_circular,
        },
        "summary": {
            "precursor_count": len(graphs),
            "complete_precursor_count": complete_count,
            "node_count": sum(len(graph.nodes) for graph in graphs),
            "edge_count": sum(graph.edge_count for graph in graphs),
            "best_total_log_prob": best_total_log_prob,
            "best_total_bound_nt": best_total_bound_nt,
            "best_Q_origami": (
                best_total_log_prob / best_total_bound_nt if best_total_bound_nt else None
            ),
            "best_crossover_penalty": crossover_penalty,
        },
        "graphs": [graph.to_dict(include_edges=include_edges) for graph in graphs],
        "paths": {
            strand_id: [path.to_dict() for path in paths]
            for strand_id, paths in paths_by_strand.items()
        },
    }


def apply_precursor_breaks(
    design: Design,
    temperature_c: float = 50.0,
    staple_conc: float = DEFAULT_STAP_CONC,
    scaffold_conc: float = DEFAULT_SCAF_CONC,
    min_staple_nt: int = 21,
    max_staple_nt: int = 60,
    path_index: int = 0,
    k_paths: int = 10,
    reassign_sequences: bool = True,
    break_rule: str = DEFAULT_BREAK_RULE,
    allow_crossover_breaks: bool = False,
    min_segment_nt: int | None = None,
) -> tuple[Design, dict[str, Any]]:
    """Apply optimized precursor breakpoints as real staple nicks.

    This is the first mutating Aksel-style routing phase.  It keeps the current
    crossover/precursor route and only chooses legal staple breakpoints within
    each precursor.  Breaks are applied from high offset to low offset per
    precursor so the original strand retains the lower-offset fragment while
    later nicks stay addressable in NADOC coordinates.
    """

    if path_index < 0:
        raise ValueError("path_index must be non-negative.")
    if k_paths <= path_index:
        k_paths = path_index + 1

    temperature_k = temperature_c + 273.15
    scaf_map = build_scaffold_position_map(design)
    ls_map = _loop_skip_map(design)
    effective_min_segment_nt = (
        lattice_min_segment_nt(design.lattice_type)
        if min_segment_nt is None
        else min_segment_nt
    )
    scaffold_block = interior_scaffold_crossover_positions(design, effective_min_segment_nt)

    plan: list[dict[str, Any]] = []
    total_internal_breaks = 0
    failed_precursors: list[str] = []
    preserved_short_count = 0
    graphs_by_strand: dict[str, PrecursorGraph] = {}
    paths_by_strand: dict[str, list[PrecursorPath]] = {}
    routes_by_strand: dict[str, list[RouteNucleotide]] = {}

    for strand in design.strands:
        if strand.strand_type != StrandType.STAPLE or strand.is_reference:
            continue
        route = _strand_route_nucleotides(strand, scaf_map, ls_map)
        if len(route) < min_staple_nt:
            preserved_short_count += 1
            plan.append(
                {
                    "strand_id": strand.id,
                    "nucleotide_count": len(route),
                    "status": "preserved_below_min_length",
                    "path_index": None,
                    "path_count": 0,
                    "break_offsets": [],
                    "segment_lengths": [len(route)] if route else [],
                    "total_log_prob": None,
                    "nick_targets": [],
                }
            )
            continue
        graph = build_precursor_graph(
            strand,
            scaf_map,
            ls_map,
            temperature_k=temperature_k,
            staple_conc=staple_conc,
            scaffold_conc=scaffold_conc,
            min_staple_nt=min_staple_nt,
            max_staple_nt=max_staple_nt,
            break_rule=break_rule,
            allow_crossover_breaks=allow_crossover_breaks,
            min_segment_nt=effective_min_segment_nt,
            scaffold_block=scaffold_block,
        )
        paths = _top_k_paths(graph, k=max(1, k_paths))
        if not paths and scaffold_block:
            # Soft seam-clearance: keeping breaks clear of seam crossovers is a
            # preference, not a hard rule.  If it left this precursor with no
            # legal mid-arm break, relax it for this precursor (a break near a
            # seam is still far better than no break / a break at a crossover).
            graph = build_precursor_graph(
                strand, scaf_map, ls_map,
                temperature_k=temperature_k, staple_conc=staple_conc,
                scaffold_conc=scaffold_conc, min_staple_nt=min_staple_nt,
                max_staple_nt=max_staple_nt, break_rule=break_rule,
                allow_crossover_breaks=allow_crossover_breaks,
                min_segment_nt=effective_min_segment_nt, scaffold_block=None,
            )
            paths = _top_k_paths(graph, k=max(1, k_paths))
        graphs_by_strand[strand.id] = graph
        paths_by_strand[strand.id] = paths
        routes_by_strand[strand.id] = route
        if not paths:
            failed_precursors.append(strand.id)
            plan.append(
                {
                    "strand_id": strand.id,
                    "nucleotide_count": len(route),
                    "status": "no_complete_path",
                    "break_offsets": [],
                    "path_count": len(paths),
                }
            )
            continue

    selected_paths, crossover_penalty = _select_precursor_paths(
        graphs_by_strand,
        paths_by_strand,
        path_index=path_index,
    )

    for strand_id, selected in selected_paths.items():
        route = routes_by_strand[strand_id]
        paths = paths_by_strand[strand_id]
        breaks = [edge.start for edge in selected.edges[1:]]
        nick_targets = []
        for offset in breaks:
            previous = route[offset - 1]
            nick_targets.append(
                {
                    "offset": offset,
                    "helix_id": previous.helix_id,
                    "bp": previous.bp,
                    "direction": previous.direction,
                }
            )
        total_internal_breaks += len(nick_targets)
        plan.append(
            {
                "strand_id": strand_id,
                "nucleotide_count": len(route),
                "status": "planned",
                "path_index": paths.index(selected),
                "path_count": len(paths),
                "break_offsets": breaks,
                "segment_lengths": [edge.length_nt for edge in selected.edges],
                "total_log_prob": selected.total_log_prob,
                "crossover_break_offsets": [
                    offset for offset in breaks
                    if graphs_by_strand[strand_id].nodes[offset].kind == "crossover"
                ],
                "nick_targets": [
                    {
                        "offset": target["offset"],
                        "helix_id": target["helix_id"],
                        "bp": target["bp"],
                        "direction": target["direction"].value,
                    }
                    for target in nick_targets
                ],
            }
        )

    if failed_precursors:
        raise ValueError(
            "No complete legal breakpoint path for precursor(s): "
            + ", ".join(failed_precursors)
        )

    from backend.core.lattice import make_nick
    from backend.core.sequences import assign_staple_sequences
    from contextlib import redirect_stdout
    import io

    updated = design
    applied_breaks = 0
    # Apply each precursor's offsets from 3' to 5' to avoid shifting the lower
    # fragment that retains the original strand id.
    for entry in plan:
        targets = sorted(
            entry.get("nick_targets", []),
            key=lambda target: target["offset"],
            reverse=True,
        )
        for target in targets:
            with redirect_stdout(io.StringIO()):
                updated = make_nick(
                    updated,
                    target["helix_id"],
                    target["bp"],
                    Direction(target["direction"]),
                )
            applied_breaks += 1

    if reassign_sequences:
        try:
            updated = assign_staple_sequences(updated)
        except ValueError:
            # The scaffold map already succeeded above, so this should only be
            # reachable for unusual future sequence states.  Leave topology done.
            pass

    score_report = score_staples(
        updated,
        temperature_c=temperature_c,
        staple_conc=staple_conc,
        scaffold_conc=scaffold_conc,
        min_staple_nt=min_staple_nt,
        max_staple_nt=max_staple_nt,
    )
    report = {
        "temperature_c": temperature_c,
        "staple_conc_m": staple_conc,
        "scaffold_conc_m": scaffold_conc,
        "min_staple_nt": min_staple_nt,
        "max_staple_nt": max_staple_nt,
        "path_index": path_index,
        "k_paths": k_paths,
        "break_rule": break_rule,
        "allow_crossover_breaks": allow_crossover_breaks,
        "min_segment_nt": effective_min_segment_nt,
        "precursor_count": len(plan),
        "preserved_short_precursor_count": preserved_short_count,
        "planned_break_count": total_internal_breaks,
        "applied_break_count": applied_breaks,
        "crossover_penalty": crossover_penalty,
        "new_staple_count": score_report["summary"]["staple_count"],
        "length_violation_count": score_report["summary"]["length_violation_count"],
        "total_bound_nt": score_report["summary"]["total_bound_nt"],
        "Q_origami": score_report["summary"]["Q_origami"],
        "plan": plan,
        "score_summary": score_report["summary"],
    }
    return updated, report


def score_staples(
    design: Design,
    temperature_c: float = 50.0,
    staple_conc: float = DEFAULT_STAP_CONC,
    scaffold_conc: float = DEFAULT_SCAF_CONC,
    min_staple_nt: int = 21,
    max_staple_nt: int = 60,
) -> dict[str, Any]:
    """Return a read-only Aksel-style score report for current staple routes."""

    temperature_k = temperature_c + 273.15
    scaf_map = build_scaffold_position_map(design)
    ls_map = _loop_skip_map(design)
    scores = [
        score_staple(
            strand,
            scaf_map,
            ls_map,
            temperature_k=temperature_k,
            staple_conc=staple_conc,
            scaffold_conc=scaffold_conc,
            min_staple_nt=min_staple_nt,
            max_staple_nt=max_staple_nt,
        )
        for strand in design.strands
        if strand.strand_type == StrandType.STAPLE and not strand.is_reference
    ]
    total_bound_nt = sum(score.bound_nt for score in scores)
    total_log_prob = sum(
        score.log_prob_fold
        for score in scores
        if score.log_prob_fold is not None and math.isfinite(score.log_prob_fold)
    )
    q_origami = total_log_prob / total_bound_nt if total_bound_nt else None
    return {
        "temperature_c": temperature_c,
        "staple_conc_m": staple_conc,
        "scaffold_conc_m": scaffold_conc,
        "min_staple_nt": min_staple_nt,
        "max_staple_nt": max_staple_nt,
        "scaffold": {
            "strand_id": scaf_map.scaffold_id,
            "length_nt": scaf_map.length,
            "is_circular": scaf_map.is_circular,
        },
        "summary": {
            "staple_count": len(scores),
            "scored_staple_count": sum(1 for score in scores if score.dG_total is not None),
            "total_bound_nt": total_bound_nt,
            "total_log_prob": total_log_prob,
            "Q_origami": q_origami,
            "violation_count": sum(len(score.violations) for score in scores),
            "length_violation_count": sum(
                1
                for score in scores
                if "length_below_min" in score.violations
                or "length_above_max" in score.violations
            ),
            "unresolved_staple_count": sum(
                1 for score in scores if "unresolved_scaffold_bases" in score.violations
            ),
            "warning_count": sum(len(score.warnings) for score in scores),
        },
        "staples": [score.to_dict() for score in scores],
    }
