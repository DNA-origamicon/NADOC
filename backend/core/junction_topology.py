"""Topology-only crossover connector enumeration.

This module intentionally contains no geometric winding score or seed verdict. It defines
the design-intent connector records shared by Holliday-junction display geometry and CPD
weld-pair selection.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Sequence


@dataclass(frozen=True)
class Connector:
    """One point where a strand leaves one helix and enters another."""

    strand_id: str
    from_helix: str
    from_bp: int
    from_dir: str
    to_helix: str
    to_bp: int
    to_dir: str
    crossover_id: Optional[str] = None
    n_inserts: int = 0

    @property
    def helices(self) -> frozenset:
        return frozenset((self.from_helix, self.to_helix))


def _dir_value(direction) -> str:
    return direction.value if hasattr(direction, "value") else str(direction)


def _junction_index(design) -> dict:
    """Map an unordered pair of crossover halves to its id and inserted bases."""
    index: dict = {}
    for crossover in getattr(design, "crossovers", None) or []:
        half_a = (
            crossover.half_a.helix_id,
            crossover.half_a.index,
            _dir_value(crossover.half_a.strand),
        )
        half_b = (
            crossover.half_b.helix_id,
            crossover.half_b.index,
            _dir_value(crossover.half_b.strand),
        )
        index[frozenset((half_a, half_b))] = (
            crossover.id,
            crossover.extra_bases or "",
        )
    for ligation in getattr(design, "forced_ligations", None) or []:
        half_a = (
            ligation.three_prime_helix_id,
            ligation.three_prime_bp,
            _dir_value(ligation.three_prime_direction),
        )
        half_b = (
            ligation.five_prime_helix_id,
            ligation.five_prime_bp,
            _dir_value(ligation.five_prime_direction),
        )
        index[frozenset((half_a, half_b))] = (
            ligation.id,
            ligation.extra_bases or "",
        )
    return index


def crossover_connectors(design) -> list[Connector]:
    """Return every inter-helix hop, walked in strand 5′→3′ order."""
    junctions = _junction_index(design)
    connectors: list[Connector] = []
    for strand in design.strands:
        for outgoing, incoming in zip(strand.domains, strand.domains[1:]):
            if outgoing.helix_id == incoming.helix_id:
                continue
            half_a = (
                outgoing.helix_id,
                outgoing.end_bp,
                _dir_value(outgoing.direction),
            )
            half_b = (
                incoming.helix_id,
                incoming.start_bp,
                _dir_value(incoming.direction),
            )
            crossover_id, extra_bases = junctions.get(
                frozenset((half_a, half_b)), (None, "")
            )
            connectors.append(
                Connector(
                    strand_id=strand.id,
                    from_helix=outgoing.helix_id,
                    from_bp=outgoing.end_bp,
                    from_dir=_dir_value(outgoing.direction),
                    to_helix=incoming.helix_id,
                    to_bp=incoming.start_bp,
                    to_dir=_dir_value(incoming.direction),
                    crossover_id=crossover_id,
                    n_inserts=len(extra_bases),
                )
            )
    return connectors


def reciprocal_pairs(connectors: Sequence[Connector]) -> list[tuple[int, int]]:
    """Return antiparallel connector pairs sharing an immobile junction."""
    pairs: list[tuple[int, int]] = []
    for index_a, connector_a in enumerate(connectors):
        for index_b in range(index_a + 1, len(connectors)):
            connector_b = connectors[index_b]
            if (
                connector_a.helices != connector_b.helices
                or len(connector_a.helices) != 2
            ):
                continue
            if connector_a.from_helix == connector_b.from_helix:
                continue
            if abs(connector_a.from_bp - connector_b.from_bp) > 1:
                continue
            pairs.append((index_a, index_b))
    return pairs
